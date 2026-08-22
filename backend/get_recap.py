import pandas as pd
from supabase import client
import os
from dotenv import load_dotenv
from pathlib import Path

from models import game_document, game_ledger, selection, recap
from get_data import get_raw_data, preprocess_data


load_dotenv(Path(__file__).resolve().parent / ".env")

supabase = client.create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))


# ------ Helper function to build the GameDocument object ------

def build_game_doc(game_id: str, season: str, week: str, away_team: str, home_team: str, away_score: int, home_score: int):
    # Get the PBP and Participation data for the requested game
    pbp_data = get_raw_data.get_pbp_data(int(season), game_id)
    if not isinstance(pbp_data, pd.DataFrame):
        print(f"Error: PBP data for {game_id} is not available.")
        return pbp_data
    participation_data = get_raw_data.get_participation_data(int(season), game_id)
    if not isinstance(participation_data, pd.DataFrame):
        print(f"Error: Participation data for {game_id} is not available.")
        return participation_data
    print("Successfully downloaded raw PBP and Participation Data")

    # Preprocess the data
    merged_df = preprocess_data.clean_and_merge(pbp_data, participation_data)
    print("Successfully cleaned and merged PBP and Participation Data")

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
    plays = game_document.plays_from_frame(merged_df)
    game_doc = game_document.GameDocument.build(plays, header)
    print("Successfully built GameDocument")

    return game_doc


# ------ Helper function to build the necessary recap components and save to the DB ------

def build_recap(
        game_id: str, season: str, week: str, away_team: str, home_team: str, away_score: int, home_score: int,
        game_ledgers_exist: bool, selected_plays_exist: bool, team_signals_exist: bool, recap_cache_exist: bool
    ):

    _game_ledger, _selected_plays, _team_signals, _recap_cache = None, None, None, None

    # Build the GameDocument for the requested game
    game_doc = build_game_doc(game_id, season, week, away_team, home_team, away_score, home_score)
    if not isinstance(game_doc, game_document.GameDocument):
        print(f"Error: Failed to build GameDocument for {game_id}.")
        return None, None, None, None

    # Build the GameLedger object, where it returns the main object and the play category map
    # Occurs outside of the cehcks since both game_ledgers_exist and recap_cache_exist rely on it.
    _ledger_obj, _play_category_map = game_ledger.build_ledger(game_doc)

    if not game_ledgers_exist:
        _game_ledger = _ledger_obj.to_dict()
        supabase.table("game_ledgers").insert(_game_ledger).execute()
        print(f"Inserted game ledger for {game_id} into the DB")

    if not selected_plays_exist:
        recap_selection = selection.RecapSelection.build(game_doc)
        _selected_plays = recap_selection.to_db_item()
        supabase.table("selected_plays").insert(_selected_plays).execute()
        print(f"Inserted selected plays for {game_id} into the DB")

    if not team_signals_exist:
        game_doc_dict = game_doc.to_dict()
        away_team_signals = game_doc_dict.get("signals", {}).get(away_team, {})
        home_team_signals = game_doc_dict.get("signals", {}).get(home_team, {})
        away_signals_db_row = {
            "game_id": game_id,
            "team": away_team,
            "offense": away_team_signals.get("offense"),
            "defense": away_team_signals.get("defense")
        }
        home_signals_db_row = {
            "game_id": game_id,
            "team": home_team,
            "offense": home_team_signals.get("offense"),
            "defense": home_team_signals.get("defense")
        }
        supabase.table("team_signals").insert(away_signals_db_row).execute()
        supabase.table("team_signals").insert(home_signals_db_row).execute()
        print(f"Inserted home and away team signals for {game_id} into the DB")
        _team_signals = {
            away_team: away_signals_db_row,
            home_team: home_signals_db_row
        }

    if not recap_cache_exist:
        _recap_selection = selection.RecapSelection.build(game_doc)

        try:
            _captions = recap.generate_captions(
                _recap_selection.anchors, _play_category_map
            )
        except recap.RecapValidationError as e:
            print(f"Error: recap generation for {game_id} failed validation ({e}), cache not written")
        else:
            _recap_cache = {
                "game_id": game_id,
                "captions": _captions,
                "model": recap.MODEL,
                "prompt_version": recap.PROMPT_VERSION,
            }
            supabase.table("recap_caches").upsert(_recap_cache, on_conflict="game_id").execute()
            print(f"Inserted recap cache for {game_id} into the DB")

    return _game_ledger, _selected_plays, _team_signals, _recap_cache


# ------ Main function ------

def get_recap(game_id: str, season: str, week: str, away_team: str, home_team: str, away_score: int, home_score: int): 
    # Get the game ledgers, anchor plays, team signals, and recap cache for the requested game ID from the DB,
    # and build the components if they don't exist

    # NOTE: Set recap_cache_exist back to False when finished testing locally
    game_ledgers_exist, selected_plays_exist, team_signals_exist, recap_cache_exist = False, False, False, True
    _game_ledger, _selected_plays, _team_signals, _recap_cache = None, None, None, None

    # Check if each of the four components exist in the DB
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
            game_ledgers_exist = True
            print(f"Found cached game ledger for {game_id}")
        else:
            print(f"No game ledger found for {game_id}, it will be built")
    except Exception as e:
        # Fall back to rebuilding rather than failing the whole request — a lookup failure is indistinguishable from a cache miss here.
        print(f"Error: game ledger lookup for {game_id} failed ({e}), it will be built")

    try:
        response = (
            supabase.table("selected_plays")
            .select("*")
            .eq("game_id", game_id)
            .execute()
        )
        selected_plays_rows = response.data or []
        if selected_plays_rows:
            _selected_plays = selected_plays_rows
            selected_plays_exist = True
            print(f"Found cached selected plays for {game_id}")
        else:
            print(f"No selected plays found for {game_id}, they will be built")
    except Exception as e:
        print(f"Error: selected plays lookup for {game_id} failed ({e}), they will be built")

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
            team_signals_exist = True
            print(f"Found cached team signals for {game_id}")
        else:
            print(f"No team signals found for {game_id}, they will be built")
    except Exception as e:
        print(f"Error: team signals lookup for {game_id} failed ({e}), they will be built")

    try:
        response = (
            supabase.table("recap_caches")
            .select("*")
            .eq("game_id", game_id)
            .limit(1)
            .execute()
        )
        recap_cache_rows = response.data or []
        if recap_cache_rows:
            row = recap_cache_rows[0]
            if row.get("model") == recap.MODEL and row.get("prompt_version") == recap.PROMPT_VERSION:
                _recap_cache = row
                recap_cache_exist = True
                print(f"Found current cached recap for {game_id}")
            else:
                print(f"Cached recap for {game_id} is stale (model/prompt_version mismatch), it will be rebuilt")
        else:
            print(f"No recap cache found for {game_id}, it will be built")
    except Exception as e:
        print(f"Error: recap cache lookup for {game_id} failed ({e}), it will be built")

    if False in [game_ledgers_exist, selected_plays_exist, team_signals_exist, recap_cache_exist]:
        built_ledger, built_selected_plays, built_signals, built_cache = build_recap(
            game_id, season, week, away_team, home_team, away_score, home_score,
            game_ledgers_exist, selected_plays_exist, team_signals_exist, recap_cache_exist
        )
        _game_ledger = _game_ledger if game_ledgers_exist else built_ledger
        _selected_plays = _selected_plays if selected_plays_exist else built_selected_plays
        _team_signals = _team_signals if team_signals_exist else built_signals
        _recap_cache = _recap_cache if recap_cache_exist else built_cache

    return _game_ledger, _selected_plays, _team_signals, _recap_cache