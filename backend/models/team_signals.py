"""
Team signals model for Snap Recap.

The third recap component, alongside game_ledger and anchor_plays: the
per-team efficiency/tendency record for one game, projected out of a
GameDocument the same way the other two are.

Two layers live here, bottom to top:

1. The *reductions*. A signal is a reduction over a collection of Play
   records: filter to a view, then collapse that view to a summary
   value. Each one is a self-contained function `f(plays) -> value`, so
   the same function serves a single game recap and a league baseline
   (run over a season of plays instead of one game).
2. The *component*. `TeamSignals` decides which teams get a record,
   carries the game header those records belong to, and knows the
   `team_signals` table row shape.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, Iterable, List, Optional
import json
import sys
import os

try:
    from .game_document import GameDocument, GameHeader
    from .play import Play, teams_in
except ImportError:
    sys.path.insert(0, os.path.dirname(__file__))
    from game_document import GameDocument, GameHeader
    from play import Play, teams_in


# --- Signal Output Dataclasses ---

@dataclass
class RateSignal:
    """Return shape shared by every conversion-rate signal
    (third down, fourth down, red-zone TD, ...).

    Carries the raw counts alongside the rate so a small-sample rate
    (1-for-1 = 100%) is never mistaken for a meaningful one downstream,
    and so the baseline store can compare on `.rate` while keeping `n`.
    """
    attempts: int
    successes: int
    rate: Optional[float]   # None when attempts == 0

    @classmethod
    def from_counts(cls, successes: int, attempts: int) -> "RateSignal":
        return cls(
            attempts=attempts,
            successes=successes,
            rate=(successes / attempts if attempts else None),
        )

    def __str__(self) -> str:
        if self.rate is None:
            return f"n/a ({self.successes}/{self.attempts})"
        return f"{self.rate:.1%} ({self.successes}/{self.attempts})"

@dataclass
class MeanSignal:
    """Return shape for continuous per-play signals (EPA/play, YPC, CPOE).

    Carries `n` for the same reason RateSignal does: a mean over two
    plays shouldn't read like a mean over fifty.
    """
    n: int
    mean: Optional[float]

    @classmethod
    def of(cls, values: Iterable[float]) -> "MeanSignal":
        vals = list(values)
        return cls(n=len(vals), mean=(sum(vals) / len(vals) if vals else None))

    def __str__(self) -> str:
        if self.mean is None:
            return f"n/a (n={self.n})"
        return f"{self.mean:.3f} (n={self.n})"


# --- Helpers ---

def _by_drive(plays: List[Play]) -> Dict[int, List[Play]]:
    drives: Dict[int, List[Play]] = {}
    for p in plays:
        if p.drive is not None:
            drives.setdefault(p.drive, []).append(p)
    return drives

# --- Signal Reductions ---

def third_down_conversion(plays: List[Play]) -> RateSignal:
    """Third-down conversion rate."""
    attempts = [p for p in plays if p.third_down_converted or p.third_down_failed]
    successes = sum(1 for p in attempts if p.third_down_converted)
    return RateSignal.from_counts(successes, len(attempts))

def fourth_down_conversion(plays: List[Play]) -> RateSignal:
    """Fourth-down conversion rate."""
    attempts = [p for p in plays if p.fourth_down_converted or p.fourth_down_failed]
    successes = sum(1 for p in attempts if p.fourth_down_converted)
    return RateSignal.from_counts(successes, len(attempts))

def red_zone_touchdowns(plays: List[Play]) -> RateSignal:
    """Red-zone TD rate: drives reaching the 20 that ended in an offensive TD."""
    trips = tds = 0
    for drive_plays in _by_drive(plays).values():
        if not any(p.yardline_100 is not None and p.yardline_100 <= 20 for p in drive_plays):
            continue
        trips += 1
        if any(p.fixed_drive_result == "Touchdown" for p in drive_plays):
            tds += 1
    return RateSignal.from_counts(tds, trips)

def success_rate(plays: List[Play]) -> RateSignal:
    """Success rate over scrimmage plays (EPA-positive by down/distance)."""
    scr = [p for p in plays if p.success is not None]
    successes = sum(1 for p in scr if p.success)
    return RateSignal.from_counts(successes, len(scr))

def explosive_play_rate(plays: List[Play]) -> RateSignal:
    """Explosive-play rate (rush >= 10, pass >= 20 yards)."""
    scr = [p for p in plays if (p.is_pass or p.is_rush) and p.yards_gained is not None]
    successes = sum(
        1 for p in scr
        if (p.is_pass and p.yards_gained >= 20) or (p.is_rush and p.yards_gained >= 10)
    )
    return RateSignal.from_counts(successes, len(scr))

def sack_rate(plays: List[Play]) -> RateSignal:
    """Sacks per dropback over the given view (pass rush on a defteam filter)."""
    dropbacks = [p for p in plays if p.qb_dropback]
    sacks = sum(1 for p in dropbacks if p.sack)
    return RateSignal.from_counts(sacks, len(dropbacks))

def epa_per_play(plays: List[Play]) -> MeanSignal:
    """Mean EPA over plays where EPA is defined."""
    return MeanSignal.of(p.epa for p in plays if p.epa is not None)

def yards_per_play(plays: List[Play]) -> MeanSignal:
    """Mean yards gained over the given view (pass scrimmage/rush subsets in)."""
    return MeanSignal.of(p.yards_gained for p in plays if p.yards_gained is not None)

def cpoe(plays: List[Play]) -> MeanSignal:
    """Mean completion % over expected (pass attempts only)."""
    return MeanSignal.of(p.cpoe for p in plays if p.cpoe is not None)


# --- Per-Team Signal Record ---

def team_signal_record(plays: List[Play], team: str) -> Dict[str, object]:
    """Per-team signal record — the locked output shape.

    A flat dict of {signal_name: signal_value}, each value its own
    reduction's return type (RateSignal or MeanSignal). Extending the
    recap = add one entry; nothing else changes.

    Every entry describes this team's own offense except `sacks_forced`,
    which is the one defensive reduction kept: the pass rush this team
    generated on the opponent's dropbacks. There is deliberately no
    sacks-allowed counterpart — in a two-team game it is the same
    population as the opponent's `sacks_forced`, read from the other side.
    """
    off = [p for p in plays if p.posteam == team]
    scrimmage = [p for p in off if p.is_pass or p.is_rush]
    passes = [p for p in off if p.is_pass]
    rushes = [p for p in off if p.is_rush]
    defense = [p for p in plays if p.defteam == team]
    return {
        "third_down": third_down_conversion(off),
        "fourth_down": fourth_down_conversion(off),
        "red_zone_td": red_zone_touchdowns(off),
        "success_rate": success_rate(scrimmage),
        "explosive_rate": explosive_play_rate(scrimmage),
        "epa_per_pass": epa_per_play(passes),
        "epa_per_rush": epa_per_play(rushes),
        "yards_per_pass": yards_per_play(passes),
        "yards_per_rush": yards_per_play(rushes),
        "cpoe": cpoe(passes),
        "sacks_forced": sack_rate(defense),
    }


# --- Component Dataclass ---

@dataclass
class TeamSignals:
    """DB entity: one signal record per team, under the game's header."""
    header: GameHeader
    signals: Dict[str, Dict[str, object]] = field(default_factory=dict)   # {team abbreviation: signal record}

    @classmethod
    def build(cls, document: GameDocument) -> "TeamSignals":
        """Project a GameDocument into a per-team signal record.

        Teams are resolved from the plays rather than the header, so the
        record set matches what actually appears in the play-by-play.
        """
        signals = {
            team: team_signal_record(document.plays, team)
            for team in teams_in(document.plays)
        }
        return cls(header=document.header, signals=signals)

    def to_dict(self) -> dict:
        """JSON-serializable form for the cache.

        `asdict` recurses through the dict values into the nested signal
        dataclasses (RateSignal, MeanSignal).
        """
        return asdict(self)

    def to_db_item(self) -> List[dict]:
        """DB rows for the team_signals table. game_id + team form the
        composite key, so game_id is placed first in each row. Away team
        first, then home, matching the header's reading order."""
        records = self.to_dict()["signals"]

        ordered = [t for t in (self.header.away_team, self.header.home_team) if t in records]
        ordered += [t for t in records if t not in ordered]

        return [
            {
                "game_id": self.header.game_id,
                "team": team,
                "signals": records[team],
            }
            for team in ordered
        ]




if __name__ == "__main__":
    # NOTE: For testing purposes only
    # Test building the team signals from the Game Document JSON file in the test data

    def document_from_dict(raw: dict) -> GameDocument:
        """(Test Helper Function) Rebuild a GameDocument from its `to_dict()` / JSON form."""
        return GameDocument(
            header=GameHeader(**raw["header"]),
            plays=[Play(**p) for p in raw["plays"]],
        )

    game_doc_json = "../test_data/game_document.json"
    with open(game_doc_json) as f:
        raw = json.load(f)

    document = document_from_dict(raw)
    print(f"Rebuilt GameDocument for {document.header.game_id}: {len(document.plays)} plays")

    team_signals = TeamSignals.build(document)
    print(f"\nSignal records built for: {list(team_signals.signals.keys())}\n")
    for team, record in team_signals.signals.items():
        print(f"Signals for {team}:")
        for name, value in record.items():
            print(f"  {name}: {value}")
        print()

    # Save to a JSON-serializable dict for inspection
    team_signals_json_filename = "../test_data/team_signals.json"
    with open(team_signals_json_filename, "w") as f:
        json.dump(team_signals.to_dict(), f, indent=2)
    print(f"Team signals saved to {team_signals_json_filename}")
