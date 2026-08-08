"""
Aggregation layer for Snap Recap.

Converts a GameDocument's plays into the fixed margin-ledger categories.
For each category, plays are summed (not averaged) by EPA per team, then
the two totals are diffed. This is deliberately separate from the
per-team rate signals already on GameDocument (third_down.rate, etc.) —
those answer "how efficient was this team," the ledger answers "how many
points did this category actually contribute to the final margin."

Sign convention: diff = home_ep - away_ep.
  positive -> home team advantage
  negative -> away team advantage
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional
import json
import sys
import os

try:
    from .game_document import GameDocument
    from .play import Play
except ImportError:
    sys.path.insert(0, os.path.dirname(__file__))
    from game_document import GameDocument
    from play import Play


# --- Category definitions -------------------------------------------------
# Each filter answers: "does this play belong to this category?"
# `credit_defense` controls who the play's EPA is attributed to in the
# ledger — most categories credit the possessing team (posteam), but
# turnovers and pass-protection failures are credited to the defense,
# since that's the team the EP swing actually benefits.

def _is_turnover(play: Play) -> bool:
    return bool(play.interception or play.fumble_lost)

def _is_third_down(play: Play) -> bool:
    # Matches third_down_conversion's population exactly (not down == 3,
    # which would also catch plays where these flags were never set).
    return bool(play.third_down_converted or play.third_down_failed)

def _is_red_zone(play: Play) -> bool:
    return play.yardline_100 is not None and play.yardline_100 <= 20

def _is_protection_play(play: Play) -> bool:
    # Matches sack_rate/pressure_rate's population: dropbacks, not all
    # pass plays (a screen with no dropback shouldn't count here).
    return bool(play.qb_dropback and (play.sack or play.was_pressure))

def _is_explosive(play: Play) -> bool:
    if play.yards_gained is None:
        return False
    if play.is_pass:
        return play.yards_gained >= 20
    if play.is_rush:
        return play.yards_gained >= 10
    return False


@dataclass
class CategoryFilter:
    name: str
    play_filter: Callable[[Play], bool]
    credit_defense: bool = False


LEDGER_CATEGORIES: List[CategoryFilter] = [
    CategoryFilter("turnovers", _is_turnover, credit_defense=True),
    CategoryFilter("third_down", _is_third_down),
    CategoryFilter("red_zone", _is_red_zone),
    CategoryFilter("explosive_plays", _is_explosive),
    CategoryFilter("pass_protection", _is_protection_play, credit_defense=True),
]


# --- Aggregation ------------------------------------------------------------

@dataclass
class CategoryLedger:
    category: str
    home_ep: float
    away_ep: float
    diff: float          # home_ep - away_ep
    home_plays: int
    away_plays: int


@dataclass
class GameLedger:
    """DB entity: nflverse game_id as PK, teams/scores, per-category diffs."""
    game_id: str
    home_team: str
    away_team: str
    home_score: Optional[int]
    away_score: Optional[int]
    categories: Dict[str, CategoryLedger]
    reconciliation: float  # sum(category diffs); TODO once EP->points conversion exists


def _credit_team(play: Play, cat: CategoryFilter) -> Optional[str]:
    return play.defteam if cat.credit_defense else play.posteam


def aggregate_category(
    plays: List[Play], home_team: str, away_team: str, cat: CategoryFilter
) -> CategoryLedger:
    home_ep = away_ep = 0.0
    home_n = away_n = 0
    for play in plays:
        if not cat.play_filter(play):
            continue
        team = _credit_team(play, cat)
        raw_epa = play.epa or 0.0
        # epa is signed from posteam's perspective. When crediting the
        # defense, flip the sign — a -5.5 EPA interception is a +5.5 swing
        # for the team that forced it, not a -5.5 one.
        epa = -raw_epa if cat.credit_defense else raw_epa
        if team == home_team:
            home_ep += epa
            home_n += 1
        elif team == away_team:
            away_ep += epa
            away_n += 1
    return CategoryLedger(
        category=cat.name,
        home_ep=home_ep,
        away_ep=away_ep,
        diff=home_ep - away_ep,
        home_plays=home_n,
        away_plays=away_n,
    )


def build_ledger(doc: GameDocument) -> GameLedger:
    home, away = doc.header.home_team, doc.header.away_team
    categories = {
        cat.name: aggregate_category(doc.plays, home, away, cat)
        for cat in LEDGER_CATEGORIES
    }
    reconciliation = sum(c.diff for c in categories.values())
    return GameLedger(
        game_id=doc.header.game_id,
        home_team=home,
        away_team=away,
        home_score=doc.header.home_score,
        away_score=doc.header.away_score,
        categories=categories,
        reconciliation=reconciliation,
    )




if __name__ == "__main__":
    # NOTE: For testing purposes only. Loads plays directly from the
    # sample game_document.json rather than rebuilding via GameDocument.build,
    # since the JSON is already a flattened dict of Play fields.
    json_file = "../test_data/game_document.json"
    with open(json_file) as f:
        raw = json.load(f)

    plays = [Play(**p) for p in raw["plays"]]
    home, away = raw["header"]["home_team"], raw["header"]["away_team"]

    print(f"{away} @ {home}\n")
    for cat in LEDGER_CATEGORIES:
        ledger = aggregate_category(plays, home, away, cat)
        print(
            f"{ledger.category:16s}  "
            f"{home} {ledger.home_ep:+.2f} ({ledger.home_plays}p)   "
            f"{away} {ledger.away_ep:+.2f} ({ledger.away_plays}p)   "
            f"diff {ledger.diff:+.2f}"
        )

    net = sum(aggregate_category(plays, home, away, c).diff for c in LEDGER_CATEGORIES)
    print(f"\nreconciliation (sum of category diffs): {net:+.2f}")
    print(f"actual margin: {raw['header']['home_score'] - raw['header']['away_score']:+d}")