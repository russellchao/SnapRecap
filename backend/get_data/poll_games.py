import requests
from supabase import client
import os
from dotenv import load_dotenv
from pathlib import Path
import sys


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

supabase = client.create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"

# Same full-name -> nflverse-abbreviation mapping the frontend uses (Games.jsx),
# ported here so both consumers agree on team abbreviations independently.
TEAM_ABBR = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL", "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR", "Chicago Bears": "CHI", "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL", "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX", "Kansas City Chiefs": "KC",
    "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC", "Los Angeles Rams": "LA", "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN", "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT", "San Francisco 49ers": "SF",
    "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB", "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}

# ESPN's postseason week.number -> nflverse's raw week (mirrors fetch_games.js's
# forward mapping, inverted). ESPN's week 4 is the Pro Bowl, not a real game week.
POSTSEASON_WEEK = {1: 19, 2: 20, 3: 21, 5: 22}


def _nflverse_week(season_type: int, week_number: int) -> int | None:
    if season_type == 2:
        return week_number
    if season_type == 3:
        return POSTSEASON_WEEK.get(week_number)
    return None  # preseason (1) or anything else -- not tracked


def _build_game_row(event: dict) -> dict | None:
    season_type = event["season"]["type"]
    week = _nflverse_week(season_type, event["week"]["number"])
    if week is None:
        return None

    competition = event["competitions"][0]
    competitors = competition["competitors"]
    away = next(c for c in competitors if c["homeAway"] == "away")
    home = next(c for c in competitors if c["homeAway"] == "home")

    away_abbr = TEAM_ABBR.get(away["team"]["displayName"])
    home_abbr = TEAM_ABBR.get(home["team"]["displayName"])
    if away_abbr is None or home_abbr is None:
        print(f"Skipping {event['id']}: unmapped team name(s) ({away['team']['displayName']} @ {home['team']['displayName']})")
        return None

    season = event["season"]["year"]
    game_id = f"{season}_{week:02d}_{away_abbr}_{home_abbr}"

    return {
        "game_id": game_id,
        "season": season,
        "week": week,
        "away_team": away_abbr,
        "home_team": home_abbr,
        "away_score": int(away.get("score") or 0),
        "home_score": int(home.get("score") or 0),
        "status": "final" if competition["status"]["type"]["completed"] else "in_progress",
    }


# ------ Main function ------

def poll_games() -> int:
    """Fetch ESPN's current scoreboard and upsert each game's status into
    the games table. Never touches recap_generated -- that's owned by the
    recap-generation job, not the poller.
    """
    response = requests.get(ESPN_SCOREBOARD_URL, timeout=10)
    response.raise_for_status()
    events = response.json().get("events", [])

    rows = [row for event in events if (row := _build_game_row(event)) is not None]
    if not rows:
        print("Poll found no trackable games")
        return 0

    supabase.table("games").upsert(rows, on_conflict="game_id").execute()
    print(f"Upserted {len(rows)} games: " + ", ".join(f"{r['game_id']}={r['status']}" for r in rows))
    return len(rows)




if __name__ == "__main__":
    #NOTE: Run this file manually to upload games to the 'games' table with the desired season/week/season type if necessary.
    # This uses ESPN's /nfl/schedule endpoint instead of the /nfl/scoreboard endpoint in ESPN_SCOREBOARD_URL.
    # Its events carry the same season/week/competitions shape as the scoreboard's, so _build_game_row()
    # is reused as-is -- only the fetch and the flattening below differ.
    #
    # Usage (from backend/get_data/): python poll_games.py <season> <week> <season_type>
    # <week> and <season_type> are ESPN's, not nflverse's: season_type 2 is the regular season
    # (weeks 1-18), 3 the postseason (weeks 1/2/3/5 -> nflverse 19/20/21/22, week 4 being the Pro Bowl).

    if len(sys.argv) != 4:
        print("Usage: python poll_games.py <season> <week> <season_type>")
        sys.exit(1)

    season, week, season_type = sys.argv[1], sys.argv[2], sys.argv[3]
    espn_schedule_url = f"https://cdn.espn.com/core/nfl/schedule?xhr=1&year={season}&week={week}&seasontype={season_type}"

    print(f"Polling games for season: {season}, week: {week}, season_type: {season_type}")

    response = requests.get(espn_schedule_url, timeout=10)
    response.raise_for_status()

    # This endpoint groups games by date under content.schedule, e.g.
    # content.schedule["20250904"].games -- flatten them into one event list.
    schedule = response.json().get("content", {}).get("schedule", {})
    events = [game for day in schedule.values() for game in day.get("games", [])]

    rows = [row for event in events if (row := _build_game_row(event)) is not None]
    if not rows:
        print("Found no trackable games")
        sys.exit(0)

    supabase.table("games").upsert(rows, on_conflict="game_id").execute()
    print(f"Upserted {len(rows)} games: " + ", ".join(f"{r['game_id']}={r['status']}" for r in rows))
