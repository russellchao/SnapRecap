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

--- On reconciliation ---
EPA is already denominated in points, so there is no unit conversion
step. What there IS is a coverage problem: categories can overlap (a
3rd-down explosive pass matches two filters) and most plays don't match
any named category at all. Both are solved the same way — each play is
claimed by exactly one category, in LEDGER_CATEGORIES priority order,
and anything left over falls into "other".

Once every play with a valid posteam is claimed exactly once, summing
category diffs is a real accounting identity, not an approximation: for
any single play, crediting -epa to the defense produces the identical
contribution to (home_ep - away_ep) as leaving the offense's own raw epa
in place. So categorized_diff == total_epa_diff by construction — that
equality isn't something to test for, it's guaranteed by the partition.

What's NOT guaranteed, and never will be, is total_epa_diff == actual
score margin. EPA is a probabilistic model of point value, not a ledger
— special teams variance, garbage time, kneel-downs, and model residual
mean this gap is normal. Report it as a diagnostic (epa_vs_score_gap),
don't chase it to zero.
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
#
# Order in LEDGER_CATEGORIES is claim PRIORITY: a play matching more than
# one filter (e.g. a 3rd-down interception) is claimed by whichever
# category comes first in the list, and excluded from the rest. This
# ordering is a real design choice, not an implementation detail — it
# decides whether that interception reads as a turnover or a third-down
# stop. Reorder if a different priority tells a truer story.

def _is_turnover(play: Play) -> bool:
    return bool(play.interception or play.fumble_lost)

def _is_protection_play(play: Play) -> bool:
    # Matches sack_rate/pressure_rate's population: dropbacks, not all
    # pass plays (a screen with no dropback shouldn't count here).
    return bool(play.qb_dropback and (play.sack or play.was_pressure))

def _is_penalty(play: Play) -> bool:
    # epa already reflects the penalty's net effect on posteam correctly
    # regardless of which team was flagged, so no credit-defense flip
    # is needed here.
    return bool(play.penalty)

def _is_special_teams(play: Play) -> bool:
    return bool(play.is_special)

def _is_third_down(play: Play) -> bool:
    # Matches third_down_conversion's population exactly (not down == 3,
    # which would also catch plays where these flags were never set).
    return bool(play.third_down_converted or play.third_down_failed)

def _is_red_zone(play: Play) -> bool:
    return play.yardline_100 is not None and play.yardline_100 <= 20

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
    CategoryFilter("pass_protection", _is_protection_play, credit_defense=True),
    CategoryFilter("penalties", _is_penalty),
    CategoryFilter("special_teams", _is_special_teams),
    CategoryFilter("red_zone", _is_red_zone),
    CategoryFilter("third_down", _is_third_down),
    CategoryFilter("explosive_plays", _is_explosive),
]


# --- Aggregation ------------------------------------------------------------

@dataclass
class CategoryLedger:
    category: str
    away_ep: float
    home_ep: float
    diff: float     # home_ep - away_ep
    away_plays: int
    home_plays: int

    def to_dict(self) -> Dict:
        return {
            "category": self.category,
            "away_ep": round(self.away_ep, 2),
            "home_ep": round(self.home_ep, 2),
            "diff": round(self.diff, 2),
            "away_plays": self.away_plays,
            "home_plays": self.home_plays,
        }


@dataclass
class GameLedger:
    """DB entity: nflverse game_id as PK, teams/scores, per-category diffs."""
    game_id: str
    away_team: str
    home_team: str
    away_score: Optional[int]
    home_score: Optional[int]
    categories: Dict[str, CategoryLedger]           # includes "other"
    categorized_diff: float                         # sum of category diffs
    total_epa_diff: float                           # raw total, all plays — should equal categorized_diff exactly
    epa_vs_score_gap: Optional[float]               # total_epa_diff - actual margin; diagnostic only, not forced to 0

    def to_dict(self) -> Dict:
        return {
            "game_id": self.game_id,
            "away_team": self.away_team,
            "home_team": self.home_team,
            "away_score": self.away_score,
            "home_score": self.home_score,
            "categories": {k: v.to_dict() for k, v in self.categories.items()},
            "categorized_diff": round(self.categorized_diff, 2),
            "total_epa_diff": round(self.total_epa_diff, 2),
            "epa_vs_score_gap": (
                None if self.epa_vs_score_gap is None
                else round(self.epa_vs_score_gap, 2)
            ),
        }


def _credit(play: Play, credit_defense: bool):
    """Returns (credited_team, credited_epa) for a play under this category's rule."""
    raw_epa = play.epa or 0.0
    if credit_defense:
        return play.defteam, -raw_epa
    return play.posteam, raw_epa


def _sum_plays(plays: List[Play], home_team: str, away_team: str, credit_defense: bool) -> CategoryLedger:
    home_ep = away_ep = 0.0
    home_n = away_n = 0

    for play in plays:
        team, epa = _credit(play, credit_defense)
        if team == home_team:
            home_ep += epa
            home_n += 1
        elif team == away_team:
            away_ep += epa
            away_n += 1
            
    return CategoryLedger(
        category="",  # filled in by caller
        away_ep=away_ep,
        home_ep=home_ep,
        diff=home_ep - away_ep,
        away_plays=away_n,
        home_plays=home_n,
    )


def build_ledger(doc: GameDocument) -> tuple[GameLedger, Dict[int, str]]:
    home = doc.header.home_team
    away = doc.header.away_team
    plays = doc.plays

    claimed: set = set()
    categories: Dict[str, CategoryLedger] = {}
    
    # Ephemeral, request-scoped play_id -> category name lookup. Never
    # persisted (categories/CategoryLedger stay exactly as M1 shipped them);
    # this exists purely so recap.py can attribute an anchor play's category
    # without re-querying or re-deriving from raw plays.
    play_category_map: Dict[int, str] = {}

    for cat in LEDGER_CATEGORIES:
        cat_plays = [p for p in plays if id(p) not in claimed and cat.play_filter(p)]
        claimed.update(id(p) for p in cat_plays)
        play_category_map.update(
            {p.play_id: cat.name for p in cat_plays if p.play_id is not None}
        )
        ledger = _sum_plays(cat_plays, home, away, cat.credit_defense)
        ledger.category = cat.name
        categories[cat.name] = ledger

    # Everything else with a real possession — normal downs, standard
    # completions/runs, whatever no named category claimed. Offense-credited,
    # same as any uncategorized scrimmage play would be.
    other_plays = [
        p for p in plays
        if id(p) not in claimed and p.posteam in (home, away)
    ]
    other_ledger = _sum_plays(other_plays, home, away, credit_defense=False)
    other_ledger.category = "other"
    categories["other"] = other_ledger
    play_category_map.update(
        {p.play_id: "other" for p in other_plays if p.play_id is not None}
    )

    categorized_diff = sum(c.diff for c in categories.values())

    # Independent total, computed without any category logic at all — every
    # play's raw epa, credited to its own posteam. Should equal
    # categorized_diff exactly (see module docstring). Any gap here means a
    # play was double-claimed or dropped, i.e. a real bug, not noise.
    total_home = sum((p.epa or 0.0) for p in plays if p.posteam == home)
    total_away = sum((p.epa or 0.0) for p in plays if p.posteam == away)
    total_epa_diff = total_home - total_away

    epa_vs_score_gap = None
    if doc.header.home_score is not None and doc.header.away_score is not None:
        actual_margin = doc.header.home_score - doc.header.away_score
        epa_vs_score_gap = total_epa_diff - actual_margin

    ledger = GameLedger(
        game_id=doc.header.game_id,
        away_team=away,
        home_team=home,
        away_score=doc.header.away_score,
        home_score=doc.header.home_score,
        categories=categories,
        categorized_diff=categorized_diff,
        total_epa_diff=total_epa_diff,
        epa_vs_score_gap=epa_vs_score_gap,
    )
    return ledger, play_category_map




if __name__ == "__main__":
    # NOTE: For testing purposes only.
    # Build the game ledger from the loaded game document JSON.

    json_file = "../test_data/game_document.json"
    with open(json_file) as f:
        raw = json.load(f)

    plays = [Play(**p) for p in raw["plays"]]
    header = raw["header"]
    home, away = header["home_team"], header["away_team"]

    class _Doc:
        pass
    doc = _Doc()
    doc.plays = plays
    class _Header:
        pass
    h = _Header()
    for k, v in header.items():
        setattr(h, k, v)
    doc.header = h

    ledger, play_category_map = build_ledger(doc)  # type: ignore[arg-type]

    print(f"{away} @ {home}\n")
    for name, c in ledger.categories.items():
        print(
            f"{name:16s}  "
            f"{home} {c.home_ep:+.2f} ({c.home_plays}p)   "
            f"{away} {c.away_ep:+.2f} ({c.away_plays}p)   "
            f"diff {c.diff:+.2f}"
        )

    print(f"\ncategorized_diff:  {ledger.categorized_diff:+.2f}")
    print(f"total_epa_diff:    {ledger.total_epa_diff:+.2f}  (should match categorized_diff exactly)")
    print(f"epa_vs_score_gap:  {ledger.epa_vs_score_gap:+.2f}  (diagnostic only — expected to be nonzero)")
    print(f"actual margin:     {header['home_score'] - header['away_score']:+d}")