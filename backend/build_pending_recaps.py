from supabase import client
import os
from dotenv import load_dotenv
from pathlib import Path
import nflreadpy as nfl

from get_recap import get_recap
from get_data.poll_games import poll_games
from get_data.check_pbp_release import check_pbp_release


load_dotenv(Path(__file__).resolve().parent / ".env")

supabase = client.create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))


# ------ Helper function to build recaps for games newly eligible after a release change ------

def _build_recaps_for_eligible_games():
    response = (
        supabase.table("games")
        .select("*")
        .eq("status", "final")
        .eq("recap_generated", False)
        .execute()
    )
    eligible_games = response.data or []

    if not eligible_games:
        print("No final, un-recapped games found")
        return

    for game in eligible_games:
        game_id = game["game_id"]
        try:
            _game_ledger, _team_signals, _macro_contexts = get_recap(
                game_id,
                str(game["season"]),
                str(game["week"]),
                game["away_team"],
                game["home_team"],
                game["away_score"],
                game["home_score"],
            )
        except Exception as e:
            # Isolate per-game failures -- one bad game shouldn't block the rest of the batch.
            # It's left with recap_generated = False, so it's retried on the next tick.
            print(f"Error: recap generation for {game_id} raised an exception ({e}); will retry next tick")
            continue

        if _game_ledger is None:
            print(f"Recap generation for {game_id} did not produce a game ledger; will retry next tick")
            continue

        supabase.table("games").update({"recap_generated": True}).eq("game_id", game_id).execute()
        print(f"Marked {game_id} as recap_generated")


# ------ Main function ------

def poll_and_recap():
    """Single cron-tick entry point: refresh game statuses from ESPN, check
    whether the nflverse pbp release has changed, and if so build recaps for
    every final game that doesn't have one yet.
    """
    poll_games()

    season = nfl.get_current_season()
    if check_pbp_release(season):
        _build_recaps_for_eligible_games()
    else:
        print("No pbp release change detected; skipping recap generation")



if __name__ == "__main__":
    #NOTE: Manually triggers recap generation for eligible games at the discretion of the developer.
    poll_and_recap()