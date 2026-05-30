'''
After a game has finished, check if the Play-By-Play and Participation Data for that game are available from nflreadpy.

If so, download the data and return them in a Pandas Dataframe.

If either data is not available, return an error. 
'''


import nflreadpy as nfl
import pandas as pd


def get_pbp_data(season, week, away_team, home_team):
    try: 
        pbp = nfl.load_pbp(season).to_pandas()
        filtered_pbp = pbp[
            (pbp['week'] == week) & (pbp['home_team'] == home_team) & (pbp['away_team'] == away_team)
        ]

        if filtered_pbp.empty:
            return {
                f"Error": 
                f"Play-by-play data not available for the game: {away_team} vs. {home_team} in Week {week} of the {season} Season"
            }

        return filtered_pbp
    
    except Exception as e:
        return {
            f"Error": 
            f"An error occurred while fetching play-by-play data for the game: {away_team} vs. {home_team} in Week {week} of the {season} Season. Details: {str(e)}"
        }


def get_participation_data(season, game_id):
    try:
        participation = nfl.load_participation(season).to_pandas()
        filtered_participation = participation[
            (participation['nflverse_game_id'] == game_id)
        ]

        if filtered_participation.empty:
            return {
                f"Error": 
                f"Participation data not available for the game with ID: {game_id}"
            }

        return filtered_participation
    
    except Exception as e:
        return {
            f"Error": 
            f"An error occurred while fetching participation data for the game with ID: {game_id}. Details: {str(e)}"
        }
    




if __name__ == "__main__":
    #NOTE: For testing purposes only

    # Get the PBP and Participation Data for the 2025-26 Bills vs. Jaguars Wild Card Playoff Game 
    # and save the data to a CSV for inspection
    pbp_data = get_pbp_data(season=2025, week=19, away_team="BUF", home_team="JAX")
    participation_data = get_participation_data(season=2025, game_id="2025_19_BUF_JAX")

    if isinstance(pbp_data, pd.DataFrame):
        filename = "pbp_data_buf_jax_wc_2025.csv"
        pbp_data.to_csv(filename, index=False)
        print(f"PBP data saved to {filename}")

    if isinstance(participation_data, pd.DataFrame):
        filename = "participation_data_buf_jax_wc_2025.csv"
        participation_data.to_csv(filename, index=False)
        print(f"Participation data saved to {filename}")
    

    # Try to get the PBP and Participation Data for a game that didn't happen, which should result in an error
    nonexistent_pbp_data = get_pbp_data(season=2025, week=19, away_team="BUF", home_team="HOU")
    print(nonexistent_pbp_data)
    nonexistent_participation_data = get_participation_data(season=2025, game_id="2025_19_BUF_HOU")
    print(nonexistent_participation_data)