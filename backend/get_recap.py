import pandas as pd
from supabase import client
import os
from dotenv import load_dotenv
from pathlib import Path

from models import game_document, game_ledger, anchor_plays
from get_data import get_raw_data, preprocess_data


load_dotenv(Path(__file__).resolve().parent / ".env")

supabase = client.create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))


# ------ Helper function to build the GameDocument object ------

def build_game_doc(game_id: str, season: str, week: str, away_team: str, home_team: str, away_score: int, home_score: int):
    # Get the PBP data for the requested game
    pbp_data = get_raw_data.get_pbp_data(int(season), game_id)
    if not isinstance(pbp_data, pd.DataFrame):
        print(f"Error: PBP data for {game_id} is not available.")
        return pbp_data
    print("Successfully downloaded raw PBP Data")

    # Preprocess the data
    cleaned_df = preprocess_data.clean(pbp_data)
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


# ------ Helper function to build the necessary recap components and save to the DB ------

def build_recap(
        game_id: str, season: str, week: str, away_team: str, home_team: str, away_score: int, home_score: int,
        game_ledgers_exist: bool, anchor_plays_exist: bool, team_signals_exist: bool
    ):

    _game_ledger, _anchor_plays, _team_signals = None, None, None

    # Build the GameDocument for the requested game
    game_doc = build_game_doc(game_id, season, week, away_team, home_team, away_score, home_score)
    if not isinstance(game_doc, game_document.GameDocument):
        print(f"Error: Failed to build GameDocument for {game_id}.")
        return None, None, None

    if not game_ledgers_exist:
        _ledger_obj = game_ledger.build_ledger(game_doc)
        _game_ledger = _ledger_obj.to_dict()
        supabase.table("game_ledgers").insert(_game_ledger).execute()
        print(f"Inserted game ledger for {game_id} into the DB")

    if not anchor_plays_exist:
        recap_selection = anchor_plays.AnchorPlayList.build(game_doc)
        _anchor_plays = recap_selection.to_db_item()
        supabase.table("anchor_plays").insert(_anchor_plays).execute()
        print(f"Inserted anchor plays for {game_id} into the DB")

    if not team_signals_exist:
        game_doc_dict = game_doc.to_dict()
        all_signals = game_doc_dict.get("signals", {})
        away_signals_db_row = {
            "game_id": game_id,
            "team": away_team,
            "signals": all_signals.get(away_team, {})
        }
        home_signals_db_row = {
            "game_id": game_id,
            "team": home_team,
            "signals": all_signals.get(home_team, {})
        }
        supabase.table("team_signals").insert(away_signals_db_row).execute()
        supabase.table("team_signals").insert(home_signals_db_row).execute()
        print(f"Inserted home and away team signals for {game_id} into the DB")
        _team_signals = {
            away_team: away_signals_db_row,
            home_team: home_signals_db_row
        }

    return _game_ledger, _anchor_plays, _team_signals


# ------ Main function ------

def get_recap(game_id: str, season: str, week: str, away_team: str, home_team: str, away_score: int, home_score: int): 
    # Get the game ledgers, anchor plays, and team signals for the requested game ID from the DB,
    # and build the components if they don't exist

    game_ledgers_exist, anchor_plays_exist, team_signals_exist = False, False, False
    _game_ledger, _anchor_plays, _team_signals = None, None, None

    # Check if each of the three components exist in the DB
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
            supabase.table("anchor_plays")
            .select("*")
            .eq("game_id", game_id)
            .execute()
        )
        anchor_plays_rows = response.data or []
        if anchor_plays_rows:
            _anchor_plays = anchor_plays_rows
            anchor_plays_exist = True
            print(f"Found cached anchor plays for {game_id}")
        else:
            print(f"No anchor plays found for {game_id}, they will be built")
    except Exception as e:
        print(f"Error: anchor plays lookup for {game_id} failed ({e}), they will be built")

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

    if False in [game_ledgers_exist, anchor_plays_exist, team_signals_exist]:
        built_ledger, built_anchor_plays, built_signals = build_recap(
            game_id, season, week, away_team, home_team, away_score, home_score,
            game_ledgers_exist, anchor_plays_exist, team_signals_exist
        )
        _game_ledger = _game_ledger if game_ledgers_exist else built_ledger
        _anchor_plays = _anchor_plays if anchor_plays_exist else built_anchor_plays
        _team_signals = _team_signals if team_signals_exist else built_signals

    return _game_ledger, _anchor_plays, _team_signals