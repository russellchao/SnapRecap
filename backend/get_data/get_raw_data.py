'''
After a game has finished, check if the Play-By-Play and Participation Data for that game are available from nflreadpy.

If so, download the data and return them in a Pandas Dataframe.

If either data is not available, return an error. 
'''


import nflreadpy as nfl
import pandas as pd
import sys


def get_pbp_data(season, game_id):
    try: 
        pbp = nfl.load_pbp(season).to_pandas()
        filtered_pbp = pbp[(pbp['game_id'] == game_id)]

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
        filtered_participation = participation[(participation['nflverse_game_id'] == game_id)]

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
    # Get the PBP and Participation Data for the game requested in the command line arguments and save the data to a CSV for inspection

    season, week, away_team, home_team = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    season, week = int(season), int(week)
    
    game_id = f"{season}_{week < 10 and '0' + str(week) or str(week)}_{away_team}_{home_team}"

    pbp_data = get_pbp_data(season, game_id)
    participation_data = get_participation_data(season, game_id)

    if isinstance(pbp_data, pd.DataFrame):
        filename = "../test_data/pbp_data.csv"
        pbp_data.to_csv(filename, index=False)
        print(f"PBP data successfully saved to {filename}")
    else:
        print(pbp_data) # Prints out the error message

    if isinstance(participation_data, pd.DataFrame):
        filename = "../test_data/participation_data.csv"
        participation_data.to_csv(filename, index=False)
        print(f"Participation data successfully saved to {filename}")
    else:
        print(participation_data) # Prints out the error message