"""Play record schema for Snap Recap.

One `Play` instance per play in a cleaned PBP game file.
Records hold *raw contextual values only* — situational labels
(high-leverage, percentile bands, "explosive", etc.) are derived
downstream so the records stay reusable.

Aggregate signals are reductions over a collection of these, e.g.:
    third_downs = [p for p in plays if p.down == 3]
    conv_rate   = mean(p.third_down_converted for p in third_downs)
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional
import pandas as pd
from dotenv import load_dotenv
from pathlib import Path
from sqlalchemy import create_engine, text


load_dotenv(Path(__file__).resolve().parents[1] / ".env")


# --- NaN-safe coercion helpers (pandas leaves missing values as float NaN) ---

def _na(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def _int(v) -> Optional[int]:
    return None if _na(v) else int(v)


def _float(v) -> Optional[float]:
    return None if _na(v) else float(v)


def _bool(v) -> Optional[bool]:
    return None if _na(v) else bool(v)


def _str(v) -> Optional[str]:
    return None if _na(v) else str(v)


def _player_name(gsis_id: Optional[str], fallback: Optional[str]) -> Optional[str]:
    """Full display name for a gsis id, falling back to the PBP short name.

    PBP carries only initials + last name, so the DB lookup is preferred; the
    short name is used when the id is missing or has no matching row.
    """
    return get_player_full_name(gsis_id) or fallback


@dataclass
class Play:
    # --- Identity / sequencing ---
    play_id: Optional[int]
    posteam: Optional[str]              # offense
    defteam: Optional[str]              # defense

    # --- Game state (the leverage context) ---
    qtr: Optional[int]
    game_seconds_remaining: Optional[int]
    down: Optional[int]                 # None on kickoffs / no-down plays
    ydstogo: Optional[int]
    yardline_100: Optional[int]         # distance to opponent end zone
    goal_to_go: Optional[bool]
    score_differential: Optional[int]   # posteam perspective
    wp: Optional[float]                 # posteam pre-play win probability
    posteam_timeouts_remaining: Optional[int]
    defteam_timeouts_remaining: Optional[int]
    drive: Optional[int]
    fixed_drive_result: Optional[str]

    # --- Play classification ---
    play_type: Optional[str]
    is_pass: Optional[bool]
    is_rush: Optional[bool]
    is_special: Optional[bool]
    extra_point_attempt: Optional[bool]
    two_point_attempt: Optional[bool]
    field_goal_attempt: Optional[bool]
    shotgun: Optional[bool]
    no_huddle: Optional[bool]
    qb_dropback: Optional[bool]
    qb_scramble: Optional[bool]

    # --- Execution detail ---
    pass_location: Optional[str]
    pass_length: Optional[str]
    air_yards: Optional[float]
    yards_after_catch: Optional[float]
    run_location: Optional[str]
    run_gap: Optional[str]

    # --- Outcome ---
    yards_gained: Optional[int]
    epa: Optional[float]
    qb_epa: Optional[float]
    wpa: Optional[float]                # win probability added (posteam perspective)
    success: Optional[bool]
    cpoe: Optional[float]
    first_down: Optional[bool]
    third_down_converted: Optional[bool]
    third_down_failed: Optional[bool]
    fourth_down_converted: Optional[bool]
    fourth_down_failed: Optional[bool]
    complete_pass: Optional[bool]
    touchdown: Optional[bool]
    sack: Optional[bool]
    qb_hit: Optional[bool]
    interception: Optional[bool]
    fumble_lost: Optional[bool]
    penalty: Optional[bool]

    # --- Outcome (post-play score state) ---
    posteam_score_post: Optional[int]      # posteam score at end of play
    defteam_score_post: Optional[int]      # defteam score at end of play
    score_differential_post: Optional[int] # posteam perspective, end of play

    # --- Outcome (fumble) ---
    fumbled_1_team: Optional[str]          # team whose player lost the ball
    fumble_recovery_1_team: Optional[str]  # team that came up with it

    # --- Players + raw text (for narrative / fallback) ---
    passer: Optional[str]
    rusher: Optional[str]
    receiver: Optional[str]
    description: Optional[str]

    @classmethod
    def from_row(cls, row) -> "Play":
        """Build a Play from one row (pandas Series) of the merged frame."""
        g = row.get  # Series.get(key, default=None)
        return cls(
            play_id=_int(g("play_id")),
            posteam=_str(g("posteam")),
            defteam=_str(g("defteam")),

            qtr=_int(g("qtr")),
            game_seconds_remaining=_int(g("game_seconds_remaining")),
            down=_int(g("down")),
            ydstogo=_int(g("ydstogo")),
            yardline_100=_int(g("yardline_100")),
            goal_to_go=_bool(g("goal_to_go")),
            score_differential=_int(g("score_differential")),
            wp=_float(g("wp")),
            posteam_timeouts_remaining=_int(g("posteam_timeouts_remaining")),
            defteam_timeouts_remaining=_int(g("defteam_timeouts_remaining")),
            drive=_int(g("drive")),
            fixed_drive_result=_str(g("fixed_drive_result")),

            play_type=_str(g("play_type")),
            is_pass=_bool(g("pass")),
            is_rush=_bool(g("rush")),
            is_special=_bool(g("special")),
            extra_point_attempt=_bool(g("extra_point_attempt")),
            two_point_attempt=_bool(g("two_point_attempt")),
            field_goal_attempt=_bool(g("field_goal_attempt")),
            shotgun=_bool(g("shotgun")),
            no_huddle=_bool(g("no_huddle")),
            qb_dropback=_bool(g("qb_dropback")),
            qb_scramble=_bool(g("qb_scramble")),

            pass_location=_str(g("pass_location")),
            pass_length=_str(g("pass_length")),
            air_yards=_float(g("air_yards")),
            yards_after_catch=_float(g("yards_after_catch")),
            run_location=_str(g("run_location")),
            run_gap=_str(g("run_gap")),

            yards_gained=_int(g("yards_gained")),
            epa=_float(g("epa")),
            qb_epa=_float(g("qb_epa")),
            wpa=_float(g("wpa")),
            success=_bool(g("success")),
            cpoe=_float(g("cpoe")),
            first_down=_bool(g("first_down")),
            third_down_converted=_bool(g("third_down_converted")),
            third_down_failed=_bool(g("third_down_failed")),
            fourth_down_converted=_bool(g("fourth_down_converted")),
            fourth_down_failed=_bool(g("fourth_down_failed")),
            complete_pass=_bool(g("complete_pass")),
            touchdown=_bool(g("touchdown")),
            sack=_bool(g("sack")),
            qb_hit=_bool(g("qb_hit")),
            interception=_bool(g("interception")),
            fumble_lost=_bool(g("fumble_lost")),
            penalty=_bool(g("penalty")),

            posteam_score_post=_int(g("posteam_score_post")),
            defteam_score_post=_int(g("defteam_score_post")),
            score_differential_post=_int(g("score_differential_post")),

            fumbled_1_team=_str(g("fumbled_1_team")),
            fumble_recovery_1_team=_str(g("fumble_recovery_1_team")),

            passer=_player_name(_str(g("passer_player_id")), _str(g("passer"))),
            rusher=_player_name(_str(g("rusher_player_id")), _str(g("rusher"))),
            receiver=_player_name(_str(g("receiver_player_id")), _str(g("receiver"))),

            description=_str(g("desc")),
        )


def plays_from_frame(df) -> list["Play"]:
    """Build all Play records from a merged, game-filtered DataFrame."""
    return [Play.from_row(row) for _, row in df.iterrows()]


def teams_in(plays: list["Play"]) -> set[str]:
    """Returns a set of distinct offensive teams in a single-game play list (exactly two)."""
    teams = {p.posteam for p in plays if p.posteam}
    assert len(teams) == 2, f"expected 2 teams, got {teams}"
    return teams


@lru_cache(maxsize=1)
def _players_engine():
    """Lazily create (and cache) the SQLAlchemy engine for the players DB.

    Cached so the ~3 lookups per play don't each spin up a new connection pool.
    """
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is not set.")
    return create_engine(database_url)


@lru_cache(maxsize=None)
def get_player_full_name(gsis_id: Optional[str]) -> Optional[str]:
    """Returns a player's full name based on their nflreadr gsis_id.

    Queries the 'players' table in the Supabase DB and returns the
    'display_name' associated with the 'gsis_id'. Returns None when the id is
    missing or has no matching row. Results are cached per gsis_id since the
    same players recur across many plays in a game.
    """

    if not gsis_id:
        return None

    with _players_engine().connect() as conn:
        row = conn.execute(
            text("SELECT display_name FROM players WHERE gsis_id = :gsis_id"),
            {"gsis_id": gsis_id},
        ).first()

    return row[0] if row else None






if __name__ == "__main__":
    #NOTE: For testing purposes only.
    # Test building the Play records on the Preprocessed CSV file in the test data

    def _summarize(p: "Play") -> str:
        """One compact, readable line per play for verification. (Test Helper)"""
        dd = f"{p.down}&{p.ydstogo}" if p.down is not None else "-"
        clock = f"Q{p.qtr}" if p.qtr is not None else "?"
        return (
            f"[{p.play_id}] {clock} {p.posteam or '?'} vs {p.defteam or '?'} "
            f"{dd:>5} @{p.yardline_100 if p.yardline_100 is not None else '?'} "
            f"{(p.play_type or '?'):<10} {p.yards_gained if p.yards_gained is not None else '?':>3} yds "
            f"| {p.description or ''}"
        )

    csv_file = "../test_data/preprocessed_data.csv"
    df = pd.read_csv(csv_file)
    plays = plays_from_frame(df)

    teams = teams_in(plays)
    print(f"Teams in game: {teams}\n")

    for p in plays:
        print(_summarize(p))

    print(f"\nBuilt {len(plays)} Play records from {csv_file} "
          f"({len(df)} rows in CSV)")
