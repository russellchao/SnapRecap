'''
After a game has finished, check if the Play-By-Play data for that game is available from nflreadpy.
If so, download the data and return it in a Pandas Dataframe, then clean it
If the data is not available, return an error. 
'''

import nflreadpy as nfl
import pandas as pd
import sys


pbp_cols_to_drop = [
    # Legacy identifier
    "old_game_id",

    # Raw player name columns (clean versions like passer, rusher, receiver are kept)
    "passer_player_name",
    "rusher_player_name",
    "receiver_player_name",

    # Lateral play columns
    "lateral_receiver_player_name", "lateral_receiver_player_id",
    "lateral_rusher_player_name", "lateral_rusher_player_id",
    "lateral_sack_player_id", "lateral_sack_player_name",
    "lateral_interception_player_id", "lateral_interception_player_name",
    "lateral_kickoff_returner_player_id", "lateral_kickoff_returner_player_name",
    "lateral_punt_returner_player_id", "lateral_punt_returner_player_name",

    # Tackle detail columns
    "tackle_with_assist",
    "tackle_with_assist_1_player_id", "tackle_with_assist_1_player_name", "tackle_with_assist_1_team",
    "tackle_with_assist_2_player_id", "tackle_with_assist_2_player_name", "tackle_with_assist_2_team",
    "assist_tackle_1_player_id", "assist_tackle_1_player_name", "assist_tackle_1_team",
    "assist_tackle_2_player_id", "assist_tackle_2_player_name", "assist_tackle_2_team",
    "assist_tackle_3_player_id", "assist_tackle_3_player_name", "assist_tackle_3_team",
    "assist_tackle_4_player_id", "assist_tackle_4_player_name", "assist_tackle_4_team",
    "solo_tackle_1_player_id", "solo_tackle_1_player_name", "solo_tackle_1_team",
    "solo_tackle_2_player_id", "solo_tackle_2_player_name", "solo_tackle_2_team",

    # Sack player details
    "sack_player_id", "sack_player_name",
    "half_sack_1_player_id", "half_sack_1_player_name",
    "half_sack_2_player_id", "half_sack_2_player_name",

    # Pass defense player details
    "pass_defense_1_player_id", "pass_defense_1_player_name",
    "pass_defense_2_player_id", "pass_defense_2_player_name",

    # Fumble detail columns
    "forced_fumble_player_1_player_id", "forced_fumble_player_1_player_name", "forced_fumble_player_1_team",
    "forced_fumble_player_2_player_id", "forced_fumble_player_2_player_name", "forced_fumble_player_2_team",
    "fumbled_1_player_id", "fumbled_1_player_name",
    "fumbled_2_player_id", "fumbled_2_player_name", "fumbled_2_team",
    "fumble_recovery_1_player_id", "fumble_recovery_1_player_name", "fumble_recovery_1_yards",
    "fumble_recovery_2_player_id", "fumble_recovery_2_player_name", "fumble_recovery_2_team", "fumble_recovery_2_yards",

    # Interception player details
    "interception_player_id", "interception_player_name",

    # Blocked kick player details
    "blocked_player_id", "blocked_player_name",

    # Kicking/return player details
    "kicker_player_id", "kicker_player_name",
    "punter_player_id", "punter_player_name",
    "kickoff_returner_player_id", "kickoff_returner_player_name",
    "punt_returner_player_id", "punt_returner_player_name",
    "own_kickoff_recovery_player_id", "own_kickoff_recovery_player_name",

    # Penalty player details
    "penalty_player_id", "penalty_player_name",

    # xyac model internals
    "xyac_epa", "xyac_success", "xyac_fd", "xyac_mean_yardage", "xyac_median_yardage",

    # Redundant WP reformulations
    "home_wp", "away_wp", "home_wp_post", "away_wp_post",
    "vegas_wp", "vegas_home_wp", "vegas_wpa", "vegas_home_wpa",

    # Series tracking
    "series", "series_success", "series_result",

    # Fantasy columns
    "fantasy", "fantasy_id", "fantasy_player_name", "fantasy_player_id",

    # Play sequencing / internal tracking
    "order_sequence", "nfl_api_id", "play_clock", "play_deleted",
    "play_type_nfl", "special_teams_play", "st_play_type",
    "end_clock_time", "end_yard_line",

    # Stadium / game conditions (not relevant to play-level narrative)
    "stadium_id", "game_stadium", "stadium",
]


def get_pbp_data(season, game_id):
    try: 
        pbp = nfl.load_pbp(season).to_pandas()
        filtered_pbp = pbp[(pbp['game_id'] == game_id)]

        if filtered_pbp.empty:
            return {
                f"Error": 
                f"Play-by-play data not available for the game with ID: {game_id}"
            }

        return filtered_pbp
    
    except Exception as e:
        return {
            f"Error": 
            f"An error occurred while fetching play-by-play data for the game with ID: {game_id}. Details: {str(e)}"
        }


def clean(pbp_df: pd.DataFrame) -> pd.DataFrame:
    return pbp_df.drop(columns=pbp_cols_to_drop, errors="ignore")



if __name__ == "__main__":
    #NOTE: For testing purposes only
    # Download and Clean the PBP Data for the game requested in the command line arguments and save the data to a CSV for inspection

    season, week, away_team, home_team = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    season, week = int(season), int(week)
    game_id = f"{season}_{week < 10 and '0' + str(week) or str(week)}_{away_team}_{home_team}"

    pbp_data = get_pbp_data(season, game_id)
    if isinstance(pbp_data, pd.DataFrame):
        cleaned_pbp_data = clean(pbp_data)
        filename = "../test_data/pbp_data.csv"
        cleaned_pbp_data.to_csv(filename, index=False)
        print(f"PBP data successfully saved to {filename}")
    else:
        print(pbp_data) # Prints out the error message