"""
This file downloads player data from nflreadpy using its load_player() function and populates the data to the Supabase DB. 

This file gets ran once per day via a CRON job (and, of course, at the discretion of the developer).

This file is necessary because the player data contains each player's display name (current and historic), 
which is essential in preventing player name hallucinations in the recap. The PBP data does not contain players' display names,
just their first initials and last names.
"""

import os
from pathlib import Path
import nflreadpy as nfl
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Load backend/.env regardless of the directory the CRON job runs this from,
# so SUPABASE_URL is available. load_players.py lives in backend/get_data/,
# so parents[1] is backend/.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def load_player_data():
    try:
        # Download player data from nflreadpy
        players = nfl.load_players().to_pandas()
        if players.empty:
            return {
                f"Error": 
                f"No player data available."
            }
        
        # Include only the necessary columns
        cols_to_keep = ["gsis_id", "display_name", "headshot"]
        players = players[cols_to_keep]

        print(f"Downloaded {len(players)} player rows.")
        return players

    except Exception as e:
        return {
            f"Error": 
            f"An error occurred while fetching player data. Details: {str(e)}"
        }
    

def write_to_db(players):
    if not isinstance(players, pd.DataFrame):
        print(players)  # Prints out the error message
        return

    database_url = os.getenv("SUPABASE_URL")
    if not database_url:
        print("Error: SUPABASE_URL environment variable is not set.")
        return

    print("Writing player data to the database...")
    engine = create_engine(database_url)
    try:
        with engine.begin() as conn:
            conn.execute(text('TRUNCATE TABLE players'))
            players.to_sql(
                "players",
                conn,
                if_exists="append",  # daily full refresh of the player list
                index=False,
            )
        print(f"Wrote {len(players)} player rows to the 'players' table.")
    except Exception as e:
        print(f"An error occurred while writing player data to the database. Details: {str(e)}")
    finally:
        engine.dispose()


def refresh_players():
    """Download the latest player data and write it to the DB."""
    player_data = load_player_data()
    write_to_db(player_data)







if __name__ == "__main__":
    refresh_players()