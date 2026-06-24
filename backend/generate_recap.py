"""
This file creates a recap for a given NFL game if one doesn't already exist.

Steps in generating a recap for a game: 
    1. Download raw play-by-play and participation data from nflreadpy
    2. Clean and merge the two aforementioned datasets
    3. Create a GameDocument object with the preprocessed data
    4. Create a RecapSelection object using the created GameDocument object
    5. (Text Serialization TBD)
"""

import sys
import pandas as pd

from get_data import get_raw_data, preprocess_data
from models import game_document, selection


def generate_recap(season, week, away_team, home_team):
    """Build a RecapSelection for one game, or return an error dict if its data isn't available.

    `season` and `week` are coerced to int so they match the numeric columns in
    the nflreadpy data (and the GameHeader schema), regardless of whether they
    arrive as strings (e.g. from the command line).
    """

    season, week = int(season), int(week)
    game_id = f"{season}_{week < 10 and '0' + str(week) or str(week)}_{away_team}_{home_team}"

    # Step 1
    pbp_data = get_raw_data.get_pbp_data(season, week, away_team, home_team)
    if not isinstance(pbp_data, pd.DataFrame):
        print(f"Error: PBP data for {game_id} is not available.")
        return pbp_data
    
    participation_data = get_raw_data.get_participation_data(season, game_id)
    if not isinstance(participation_data, pd.DataFrame):
        print(f"Error: Participation data for {game_id} is not available.")
        return participation_data
    
    print("Step 1 Complete: Successfully downloaded raw PBP and Participation Data")


    # Step 2
    merged_df = preprocess_data.clean_and_merge(pbp_data, participation_data)
    print("Step 2 Complete: Successfully cleaned and merged PBP and Participation Data")


    # Step 3
    header = game_document.GameHeader(
        game_id=game_id,
        season=season,
        week=week,
        away_team=away_team,
        home_team=home_team,
    )
    plays = game_document.plays_from_frame(merged_df)
    document = game_document.GameDocument.build(plays, header)
    print("Step 3 Complete: Successfully built GameDocument")


    # Step 4
    recap_selection = selection.RecapSelection.build(document)
    print("Step 4 Complete: Successfully built RecapSelection")











if __name__ == "__main__":
    #NOTE: For testing purposes only
    # Generate a recap for a game based on the command line arguments

    season, week, away_team, home_team = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    print(f"Generating recap for: {away_team} at {home_team}, Week: {week}, Season: {season}")
    generate_recap(season, week, away_team, home_team)
