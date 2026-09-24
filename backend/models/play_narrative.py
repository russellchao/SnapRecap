"""
Play Narrative layer: wraps each play's raw `description` with the
game-state context (quarter, down/distance, field position, win
probability) and the full names of the players involved that an LLM
needs to read it correctly.

This is formatting, not selection -- no significance judgment happens
here. That decision has already been made by play_selection.py; this
layer only makes the already-selected data legible to the phrasing LLM.
"""

from __future__ import annotations

import sys
import os

try:
    from .play import Play
except ImportError:
    sys.path.insert(0, os.path.dirname(__file__))
    from play import Play


# Quarter number at which regulation ends and overtime periods begin.
OT_QTR_THRESHOLD = 5

_DOWN_SUFFIX = {1: "st", 2: "nd", 3: "rd"}


def _quarter_label(qtr: int | None) -> str | None:
    """'Q1'-'Q4' in regulation, 'OT'/'2OT'/... beyond it."""
    if qtr is None:
        return None
    if qtr < OT_QTR_THRESHOLD:
        return f"Q{qtr}"
    ot_period = qtr - OT_QTR_THRESHOLD + 1
    return "OT" if ot_period == 1 else f"{ot_period}OT"


def _timestamp_label(quarter_seconds_remaining: int | None) -> str | None:
    if quarter_seconds_remaining is None:
        return None
    minutes, seconds = divmod(quarter_seconds_remaining, 60)
    return f"{minutes:02}:{seconds:02}"


def _down_distance_label(down: int | None, ydstogo: int | None) -> str | None:
    """'3rd & 7'; None on downless plays (kickoffs, PATs, etc.)."""
    if down is None:
        return None
    suffix = _DOWN_SUFFIX.get(down, "th")
    distance = ydstogo if ydstogo is not None else "?"
    return f"{down}{suffix} & {distance}"


def _field_position_label(play: Play) -> str | None:
    """'{team} {yard}', reading yardline_100 (posteam's distance to the
    opponent's end zone) into whichever team's territory the ball is
    actually in."""
    if play.yardline_100 is None:
        return None
    if play.yardline_100 <= 50:
        team, yard = play.defteam, play.yardline_100
    else:
        team, yard = play.posteam, 100 - play.yardline_100
    return f"{team} {yard}" if team is not None else f"the {yard}"


def _win_probability_label(play: Play) -> str | None:
    """Posteam's pre-play win probability, as a percentage."""
    if play.wp is None or play.posteam is None:
        return None
    return f"{play.posteam} WP {play.wp:.1%}"


def _epa_label(play: Play) -> str | None:
    """Play-level EPA -- the same metric play_selection.py's HIGH_LEVERAGE_EPA
    threshold checks, shown here so its actual size is visible rather than
    just its presence above/below that bar."""
    if play.epa is None:
        return None
    return f"EPA {play.epa:+.2f}"


def _cpoe_label(play: Play) -> str | None:
    """Completion % over expected, pass attempts only.

    NOTE: nflverse's cpoe column is already in percentage points (e.g. +8.2
    for a throw 8.2 points more likely to be completed than expected) -- it
    is NOT a 0-1 fraction the way wp is, so this does not use the `.1%`
    formatting _win_probability_label does.
    """
    if not play.is_pass or play.cpoe is None:
        return None
    return f"CPOE {play.cpoe:+.1f}"


def _air_yards_label(play: Play) -> str | None:
    """Air yards vs. yards after catch, pass attempts only. YAC is omitted
    on incompletions, since there's no catch to measure it from."""
    if not play.is_pass or play.air_yards is None:
        return None
    if play.yards_after_catch is None:
        return f"{play.air_yards:.0f} air yds"
    return f"{play.air_yards:.0f} air + {play.yards_after_catch:.0f} YAC"


def _score_label(play: Play) -> str | None:
    """Post-play score, shown only when this play changed it (touchdowns,
    field goals, safeties, PATs, ...). Detected by comparing the pre- and
    post-play score differential rather than flagging by play type, so it
    catches every scoring play without needing its own list of them.
    Omitted on every other play so an unchanged score isn't repeated down
    after down.
    """
    if (
        play.posteam_score_post is None
        or play.defteam_score_post is None
        or play.score_differential is None
        or play.score_differential_post is None
        or play.posteam is None
        or play.defteam is None
        or play.score_differential == play.score_differential_post
    ):
        return None
    return f"{play.posteam} {play.posteam_score_post}-{play.defteam} {play.defteam_score_post}"


def _players_label(play: Play) -> str | None:
    """Full display names of the passer, rusher, and receiver involved,
    whichever are present. The raw description only carries initials +
    last name (e.g. 'J.Allen'), so naming them here keeps the phrasing
    LLM from guessing at who that is."""
    roles = [
        ("Passer", play.passer),
        ("Rusher", play.rusher),
        ("Receiver", play.receiver),
    ]
    named = [f"{role}: {name}" for role, name in roles if name is not None]
    return ", ".join(named) if named else None


def synthesize(play: Play, include_epa: bool = True) -> str:
    """Wrap `play.description` with a compact game-state prefix.

    Missing fields drop out of the prefix rather than rendering as a
    placeholder; a play with no description at all just returns the prefix.
    include_epa=False drops the EPA segment for consumers phrasing this
    play for a casual-fan audience (macro_context.py's Game Breakdown
    payload) where WPA substitutes for it; it has no effect on cpoe/air
    yards, which are unrelated to that framing question.
    """
    segments = [
        _quarter_label(play.qtr),
        _timestamp_label(play.quarter_seconds_remaining) if play.quarter_seconds_remaining is not None else None,
        _down_distance_label(play.down, play.ydstogo),
        _field_position_label(play),
        _win_probability_label(play),
        _epa_label(play) if include_epa else None,
        _cpoe_label(play),
        _air_yards_label(play),
        _score_label(play),
        _players_label(play),
    ]
    prefix = " | ".join(s for s in segments if s is not None)
    description = play.description or ""
    if not prefix:
        return description
    return f"{prefix} | {description}" if description else prefix


def narrate_plays(plays: list[Play]) -> list[str]:
    """Synthesize narrative strings for a list of plays, in order."""
    return [synthesize(p) for p in plays]




if __name__ == "__main__":
    # NOTE: For testing purposes only
    # Sanity-check narrative synthesis against the saved game document JSON

    import json

    try:
        from .game_document import GameDocument, GameHeader
    except ImportError:
        sys.path.insert(0, os.path.dirname(__file__))
        from game_document import GameDocument, GameHeader

    def document_from_dict(raw: dict) -> GameDocument:
        """Rebuild a GameDocument from its `to_dict()` / JSON form."""
        return GameDocument(
            header=GameHeader(**raw["header"]),
            plays=[Play(**p) for p in raw["plays"]],
        )

    game_doc_json = "../test_data/game_document.json"
    with open(game_doc_json) as f:
        raw = json.load(f)
    document = document_from_dict(raw)

    print(f"Rebuilt GameDocument for {document.header.game_id}: {len(document.plays)} plays\n")
    for p in document.plays[:100]:
        print(synthesize(p))