# After a game has finished, check if its play-by-play stats are available from nflreadpy

import nflreadpy as nfl
import pandas as pd

def get_pbp_stats(season, week, away_team, home_team):
    pbp = nfl.load_pbp(season).to_pandas()
    filtered_pbp = pbp[
        (pbp['week'] == week) & (pbp['home_team'] == home_team) & (pbp['away_team'] == away_team)
    ]

    # Fallback in case the above filtering returns an empty dataframe 
    # (e.g. due to a mismatch in team abbreviations or stats not being available yet).
    if filtered_pbp.empty:
        return {
            f"Error": f"Play-by-play stats not available for the game: {away_team} vs. {home_team} in Week {week} of the {season} Season"
        }

    return filtered_pbp



if __name__ == "__main__":
    # For testing purposes only

    # Get the PBP Stats for the 2025-26 Bills vs. Jaguars Wild Card Playoff Game and save the stats to a CSV for inspection
    pbp_stats = get_pbp_stats(season=2025, week=19, away_team="BUF", home_team="JAX")
    if isinstance(pbp_stats, pd.DataFrame):
        filename = "pbp_stats_buf_jax_wc_2025.csv"
        pbp_stats.to_csv(filename, index=False)
        print(f"PBP stats saved to {filename}")

    # Try to get the PBP Stats for a game that didn't happen, which should result in an error
    nonexistent_pbp_stats = get_pbp_stats(season=2025, week=19, away_team="BUF", home_team="HOU")
    print(nonexistent_pbp_stats)