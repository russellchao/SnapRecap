import pandas as pd
from supabase import client
import os
from dotenv import load_dotenv
from pathlib import Path

from models import game_document, game_ledger, team_signals, game_breakdown, injury_impact, macro_context
from get_data import get_pbp_data


load_dotenv(Path(__file__).resolve().parent / ".env")

supabase = client.create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

# Per-context prompt version, keyed by the same context_type values stored
# in macro_contexts.context_type -- each context regenerates independently
# when its own prompt version changes, not when either of the other two do.
MACRO_CONTEXT_VERSIONS = {
    "losers_biggest_mistakes": macro_context.LOSERS_MISTAKES_PROMPT_VERSION,
    "winners_best_plays": macro_context.WINNERS_BEST_PLAYS_PROMPT_VERSION,
    "injury_impact": macro_context.INJURY_IMPACT_PROMPT_VERSION,
}


# ------ Helper function to build the GameDocument object ------

def build_game_doc(game_id: str, season: str, week: str, away_team: str, home_team: str, away_score: int, home_score: int):
    # Download and clean the PBP data for the requested game
    pbp_data = get_pbp_data.get_pbp_data(int(season), game_id)
    if not isinstance(pbp_data, pd.DataFrame):
        print(f"Error: PBP data for {game_id} is not available.")
        return pbp_data
    print("Successfully downloaded raw PBP Data")
    cleaned_df = get_pbp_data.clean(pbp_data)
    print("Successfully cleaned PBP Data")

    # Build the GameDocument object
    header = game_document.GameHeader(
        game_id=game_id,
        season=season,
        week=week,
        away_team=away_team,
        home_team=home_team,
        away_score=away_score,
        home_score=home_score,
    )
    plays = game_document.plays_from_frame(cleaned_df)
    game_doc = game_document.GameDocument.build(plays, header)
    print("Successfully built GameDocument")

    return game_doc


# ------ Helper function to upsert one macro_contexts row ------

def _upsert_macro_context(game_id: str, context_type: str, text: str) -> dict:
    row = {
        "game_id": game_id,
        "context_type": context_type,
        "content": {"text": text},
        "version": MACRO_CONTEXT_VERSIONS[context_type],
    }
    supabase.table("macro_contexts").upsert(row).execute()
    print(f"Upserted {context_type} for {game_id} into the DB")
    return row


# ------ Helper function to build whichever macro contexts are missing/stale ------

def build_macro_contexts(game_doc: game_document.GameDocument, macro_contexts_exist: dict) -> dict:
    """Build and upsert whichever macro contexts aren't already cached with
    an up-to-date version, keyed by context_type.

    losers_biggest_mistakes and winners_best_plays share one GameBreakdown
    build, but are phrased and upserted independently. A tied game has
    neither: GameBreakdown.build() returns None, and no row is written for
    either context type -- that's expected, not an error.
    """
    game_id = game_doc.header.game_id
    built = {}

    need_breakdown = not macro_contexts_exist.get("losers_biggest_mistakes") \
        or not macro_contexts_exist.get("winners_best_plays")
    if need_breakdown:
        breakdown = game_breakdown.GameBreakdown.build(game_doc)
        if breakdown is None:
            print(f"{game_id} ended in a tie, skipping Game Breakdown macro contexts")
        else:
            if not macro_contexts_exist.get("losers_biggest_mistakes"):
                text = macro_context.phrase_losers_biggest_mistakes(breakdown)
                built["losers_biggest_mistakes"] = _upsert_macro_context(
                    game_id, "losers_biggest_mistakes", text
                )
            if not macro_contexts_exist.get("winners_best_plays"):
                text = macro_context.phrase_winners_best_plays(breakdown)
                built["winners_best_plays"] = _upsert_macro_context(
                    game_id, "winners_best_plays", text
                )

    if not macro_contexts_exist.get("injury_impact"):
        report = injury_impact.InjuryImpactReport.build(game_doc)
        text = macro_context.phrase_injury_impact(report)
        built["injury_impact"] = _upsert_macro_context(game_id, "injury_impact", text)

    return built


# ------ Helper function to build the necessary recap components and save to the DB ------

def build_recap(
        game_id: str, season: str, week: str, away_team: str, home_team: str, away_score: int, home_score: int,
        game_ledgers_exist: bool, team_signals_exist: bool, macro_contexts_exist: dict
    ):

    _game_ledger, _team_signals, _macro_contexts = None, None, None

    # Build the GameDocument for the requested game
    game_doc = build_game_doc(game_id, season, week, away_team, home_team, away_score, home_score)
    if not isinstance(game_doc, game_document.GameDocument):
        print(f"Error: Failed to build GameDocument for {game_id}.")
        return None, None, None

    if not game_ledgers_exist:
        _ledger_obj = game_ledger.build_ledger(game_doc)
        _game_ledger = _ledger_obj.to_dict()
        supabase.table("game_ledgers").upsert(_game_ledger).execute()
        print(f"Upserted game ledger for {game_id} into the DB")

    if not team_signals_exist:
        signals_obj = team_signals.TeamSignals.build(game_doc)
        signals_db_rows = signals_obj.to_db_item()
        supabase.table("team_signals").upsert(signals_db_rows).execute()
        print(f"Upserted home and away team signals for {game_id} into the DB")
        # Keyed by team, matching the shape the cache-hit path returns.
        _team_signals = {row["team"]: row for row in signals_db_rows}

    if False in macro_contexts_exist.values():
        _macro_contexts = build_macro_contexts(game_doc, macro_contexts_exist)

    return _game_ledger, _team_signals, _macro_contexts


# ------ Main function ------

def get_recap(game_id: str, season: str, week: str, away_team: str, home_team: str, away_score: int, home_score: int):
    # Get the game ledgers, team signals, and macro contexts for the requested
    # game ID from the DB, and build whichever components don't exist

    game_ledgers_exist, team_signals_exist = False, False
    macro_contexts_exist = {context_type: False for context_type in MACRO_CONTEXT_VERSIONS}
    _game_ledger, _team_signals = None, None
    _macro_contexts = {}

    # Check if each of the two singular components exist in the DB
    try:
        response = (
            supabase.table("game_ledgers")
            .select("*")
            .eq("game_id", game_id)
            .limit(1)
            .execute()
        )
        game_ledger_rows = response.data or []
        if game_ledger_rows:
            _game_ledger = game_ledger_rows[0]
            if _game_ledger["version"] != game_ledger.VERSION:
                print(f"Version mismatch for cached game ledger for {game_id}, it will be rebuilt")
            else:
                game_ledgers_exist = True
                print(f"Found cached game ledger for {game_id} with updated version {game_ledger.VERSION}")
        else:
            print(f"No game ledger found for {game_id}, it will be built")
    except Exception as e:
        # Fall back to rebuilding rather than failing the whole request — a lookup failure is indistinguishable from a cache miss here.
        print(f"Error: game ledger lookup for {game_id} failed ({e}), it will be built")

    try:
        response = (
            supabase.table("team_signals")
            .select("*")
            .eq("game_id", game_id)
            .execute()
        )
        team_signals_rows = response.data or []
        # One row per team, so both the away and home rows have to be present to count as cached.
        if len(team_signals_rows) >= 2:
            _team_signals = {row["team"]: row for row in team_signals_rows}
            if False in [row["version"] == team_signals.VERSION for row in team_signals_rows]:
                print(f"Version mismatch for cached team signals for {game_id}, they will be rebuilt")
            else:
                team_signals_exist = True
                print(f"Found cached team signals for {game_id} with updated version {team_signals.VERSION}")
        else:
            print(f"No team signals found for {game_id}, they will be built")
    except Exception as e:
        print(f"Error: team signals lookup for {game_id} failed ({e}), they will be built")

    # Check each macro context individually — one row per context_type, each
    # with its own version, so a version mismatch on one doesn't affect the
    # cache status of the other two.
    try:
        response = (
            supabase.table("macro_contexts")
            .select("*")
            .eq("game_id", game_id)
            .execute()
        )
        macro_context_rows = response.data or []
        rows_by_type = {row["context_type"]: row for row in macro_context_rows}
        for context_type, expected_version in MACRO_CONTEXT_VERSIONS.items():
            row = rows_by_type.get(context_type)
            if row is None:
                print(f"No {context_type} found for {game_id}, it will be built")
                continue
            _macro_contexts[context_type] = row
            if row["version"] != expected_version:
                print(f"Version mismatch for cached {context_type} for {game_id}, it will be rebuilt")
            else:
                macro_contexts_exist[context_type] = True
                print(f"Found cached {context_type} for {game_id} with updated version {expected_version}")
    except Exception as e:
        print(f"Error: macro contexts lookup for {game_id} failed ({e}), they will be built")

    if False in [game_ledgers_exist, team_signals_exist] or False in macro_contexts_exist.values():
        built_ledger, built_signals, built_macro_contexts = build_recap(
            game_id, season, week, away_team, home_team, away_score, home_score,
            game_ledgers_exist, team_signals_exist, macro_contexts_exist
        )
        _game_ledger = _game_ledger if game_ledgers_exist else built_ledger
        _team_signals = _team_signals if team_signals_exist else built_signals
        if built_macro_contexts:
            _macro_contexts.update(built_macro_contexts)

    return _game_ledger, _team_signals, _macro_contexts