import pandas as pd
from supabase import client
import os
from dotenv import load_dotenv
from pathlib import Path

from models import game_document, game_ledger
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
        game_ledgers_exist: bool, anchor_plays_exist: bool, recap_cache_exist: bool, signals_exist: bool
    ):

    # Build the GameDocument for the requested game
    game_doc = build_game_doc(game_id, season, week, away_team, home_team, away_score, home_score)
    if not isinstance(game_doc, game_document.GameDocument):
        print(f"Error: Failed to build GameDocument for {game_id}.")
        return None, None, None, None

    _game_ledger, _anchor_plays, _recap_cache, _signals = None, None, None, None

    if not game_ledgers_exist:
        _game_ledger = game_ledger.build_ledger(game_doc).to_dict()
        supabase.table("game_ledgers").insert(_game_ledger).execute()
        print(f"Inserted game ledger for {game_id} into the DB")

    if not anchor_plays_exist:
        # TODO: Build anchor plays and write to DB
        pass

    if not recap_cache_exist:
        # TODO: Build recap cache and write to DB
        pass
    
    if not signals_exist:
        # TODO: Build signals and write to DB
        pass

    return _game_ledger, _anchor_plays, _recap_cache, _signals


# ------ Main function ------

def get_recap(game_id: str, season: str, week: str, away_team: str, home_team: str, away_score: int, home_score: int): 
    # Get the game ledgers, anchor plays, recap cache, and signals for the requested game ID from the DB,
    # and build the components if they don't exist

    game_ledgers_exist, anchor_plays_exist, recap_cache_exist, signals_exist = False, False, False, False
    _game_ledger, _anchor_plays, _recap_cache, _signals = None, None, None, None

    # Check if each of the four components exist in the DB
    #NOTE: For now, only the game ledger entity exists in the DB, edit as you add each component
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

    #NOTE: Add each component's flag to this list as you implement it.
    if False in [game_ledgers_exist]:
        built_ledger, built_anchors, built_cache, built_signals = build_recap(
            game_id, season, week, away_team, home_team, away_score, home_score,
            game_ledgers_exist, anchor_plays_exist, recap_cache_exist, signals_exist
        )
        _game_ledger = _game_ledger if game_ledgers_exist else built_ledger
        _anchor_plays = _anchor_plays if anchor_plays_exist else built_anchors
        _recap_cache = _recap_cache if recap_cache_exist else built_cache
        _signals = _signals if signals_exist else built_signals

    return _game_ledger, _anchor_plays, _recap_cache, _signals
