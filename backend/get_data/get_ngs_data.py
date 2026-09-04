'''
After a game has finished, check if the Next Gen Stats data for that game is available from nflreadpy.
If so, download the data and return it in a Pandas Dataframe, then clean it
If the data is not available, return an error. 
'''

import nflreadpy as nfl
import pandas as pd
import sys


def get_ngs_data(game_id):
    try:
        game_id_parts = game_id.split("_")
        season = game_id_parts[0]
        week = game_id_parts[1]
        away_team = game_id_parts[2]
        home_team = game_id_parts[3]

        ngs = nfl.load_nextgen_stats("passing", int(season)).to_pandas()
        filtered_ngs = ngs[
            (ngs["week"] == int(week)) & ((ngs["team_abbr"] == away_team) | (ngs["team_abbr"] == home_team))
        ]

        if filtered_ngs.empty:
            return {
                f"Error": 
                f"Next gen stats data not available for the game with ID: {game_id}"
            }

        return filtered_ngs

    except Exception as e:
        return {
            f"Error": 
            f"An error occurred while fetching next gen stats data for the game with ID: {game_id}. Details: {str(e)}"
        }




if __name__ == "__main__":
    #NOTE: For testing purposes only
    # Get the NGS Data for the game requested in the command line arguments and save the data to a CSV for inspection

    season, week, away_team, home_team = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    season, week = int(season), int(week)
    game_id = f"{season}_{week < 10 and '0' + str(week) or str(week)}_{away_team}_{home_team}"

    ngs_data = get_ngs_data(game_id)
    if isinstance(ngs_data, pd.DataFrame):
        filename = "../test_data/raw_ngs_data.csv"
        ngs_data.to_csv(filename, index=False)
        print(f"Next gen stats data successfully saved to {filename}")
    else:
        print(ngs_data) # Prints out the error message