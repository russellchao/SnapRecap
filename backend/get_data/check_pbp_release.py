import requests
from supabase import client
import os
from dotenv import load_dotenv
from pathlib import Path
import nflreadpy as nfl


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

supabase = client.create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

PBP_RELEASE_API_URL = "https://api.github.com/repos/nflverse/nflverse-data/releases/tags/pbp"


def _get_asset_updated_at(season: int) -> str | None:
    response = requests.get(PBP_RELEASE_API_URL, timeout=10)
    response.raise_for_status()
    assets = response.json().get("assets", [])

    asset_name = f"play_by_play_{season}.parquet"
    for asset in assets:
        if asset["name"] == asset_name:
            return asset["updated_at"]

    print(f"Warning: no '{asset_name}' asset found in the pbp release")
    return None


# ------ Main function ------

def check_pbp_release(season: int) -> bool:
    """Check whether the nflverse pbp release asset for `season` has changed
    since the last check. If it has, clear nflreadpy's cache so the next
    load_pbp() call re-downloads rather than serving a stale cached copy,
    and record the new timestamp. Returns True if the release changed.
    """
    updated_at = _get_asset_updated_at(season)
    if updated_at is None:
        return False

    response = (
        supabase.table("pbp_release_state")
        .select("last_updated_at")
        .eq("season", season)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    last_seen = rows[0]["last_updated_at"] if rows else None

    if last_seen == updated_at:
        print(f"No change in pbp release for {season} (still {updated_at})")
        return False

    nfl.clear_cache()
    supabase.table("pbp_release_state").upsert(
        {"season": season, "last_updated_at": updated_at}, on_conflict="season"
    ).execute()
    print(f"pbp release for {season} changed ({last_seen} -> {updated_at}); cache cleared")
    return True
