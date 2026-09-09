"""
Team signals model for Snap Recap.

The second recap component, alongside game_ledger: the per-team
efficiency/tendency record for one game, projected out of a
GameDocument the same way the ledger is.

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


VERSION = "v5"


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

def _seconds_from_mmss(value: Optional[str]) -> Optional[int]:
    """Parse nflfastR's 'M:SS' drive_time_of_possession into seconds."""
    if not value:
        return None
    try:
        minutes, seconds = value.split(":")
        return int(minutes) * 60 + int(seconds)
    except (ValueError, AttributeError):
        return None

# Points awarded for a drive ending in the given fixed_drive_result.
# Deliberately coarse (ignores PAT/2pt/defensive-TD nuance) to match the
# existing red_zone_touchdowns treatment of fixed_drive_result as a label.
_DRIVE_RESULT_POINTS = {
    "Touchdown": 7,
    "Field goal": 3,
}


# --- Signal Reductions ---

# --- Situational Efficiency ---

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

def points_per_trip_inside_40(plays: List[Play]) -> MeanSignal:
    """Points scored per drive that reached inside the 40 (yardline_100 <= 40)."""
    points = []
    for drive_plays in _by_drive(plays).values():
        if not any(p.yardline_100 is not None and p.yardline_100 <= 40 for p in drive_plays):
            continue
        result = next((p.fixed_drive_result for p in drive_plays if p.fixed_drive_result), None)
        points.append(_DRIVE_RESULT_POINTS.get(result, 0))
    return MeanSignal.of(points)

def early_down_success_rate(plays: List[Play]) -> RateSignal:
    """Success rate on 1st/2nd down only."""
    attempts = [p for p in plays if p.down in (1, 2) and p.success is not None]
    successes = sum(1 for p in attempts if p.success)
    return RateSignal.from_counts(successes, len(attempts))

# --- Overall Play Efficiency ---

def success_rate(plays: List[Play]) -> RateSignal:
    """Success rate over scrimmage plays (EPA-positive by down/distance)."""
    scr = [p for p in plays if p.success is not None]
    successes = sum(1 for p in scr if p.success)
    return RateSignal.from_counts(successes, len(scr))

def explosive_play_count(plays: List[Play]) -> int:
    """Explosive-play count (rush >= 10, pass >= 20 yards)."""
    scr = [p for p in plays if (p.is_pass or p.is_rush) and p.yards_gained is not None]
    return sum(
        1 for p in scr
        if (p.is_pass and p.yards_gained >= 20) or (p.is_rush and p.yards_gained >= 10)
    )

# --- Passing / Rushing ---

def epa_per_play(plays: List[Play]) -> MeanSignal:
    """Mean EPA over plays where EPA is defined."""
    return MeanSignal.of(p.epa for p in plays if p.epa is not None)

def yards_per_play(plays: List[Play]) -> MeanSignal:
    """Mean yards gained over the given view (pass scrimmage/rush subsets in)."""
    return MeanSignal.of(p.yards_gained for p in plays if p.yards_gained is not None)

def cpoe(plays: List[Play]) -> MeanSignal:
    """Mean completion % over expected (pass attempts only)."""
    return MeanSignal.of(p.cpoe for p in plays if p.cpoe is not None)

# --- Disruption / Havoc ---

def sacks_forced(plays: List[Play]) -> int:
    """Sack count on the given defensive view (too infrequent for a rate to read as meaningful)."""
    return sum(1 for p in plays if p.sack)

def tfl_count(plays: List[Play]) -> int:
    """Tackle-for-loss count on the given defensive view."""
    scr = [p for p in plays if p.is_pass or p.is_rush]
    return sum(1 for p in scr if p.tackled_for_loss)

def forced_fumble_count(plays: List[Play]) -> int:
    """Forced-fumble count on the given defensive view. Special team plays included."""
    return sum(1 for p in plays if p.fumble_forced)

def takeaway_count(plays: List[Play]) -> int:
    """Takeaway count: opponent turnovers forced on the given defensive view. Special team plays included."""
    return sum(1 for p in plays if p.interception or p.fumble_lost)

# --- Discipline / Field Position ---

def penalty_count(plays: List[Play], team: str) -> int:
    """Penalty count: number of penalties charged to `team` on the given view."""
    charged = sum(1 for p in plays if p.penalty and p.penalty_team == team)
    return charged

def penalty_yards_per_drive(plays: List[Play], team: str) -> MeanSignal:
    """Mean penalty yards charged to `team` per drive, either side of the ball.

    `plays` is expected to be the full, unfiltered game play list, so
    drives are the game's actual drives (both teams' possessions) —
    a defensive penalty during the opponent's drive still counts against
    `team` on that drive.
    """
    yards_by_drive = []
    for drive_plays in _by_drive(plays).values():
        drive_yards = sum(
            p.penalty_yards
            for p in drive_plays
            if p.penalty and p.penalty_team == team and p.penalty_yards is not None
        )
        yards_by_drive.append(drive_yards)
    return MeanSignal.of(yards_by_drive)

def starting_field_position(plays: List[Play]) -> MeanSignal:
    """Average starting yardline_100 of drives within this play population.

    Called with an offense-filtered view, this reads as the average field
    position this team's own offense started its drives with — yards from
    the opponent's end zone, so a lower value is better field position.

    The drive's first row is often the kickoff or punt that set it up
    (nflfastR files that play under the receiving team's drive number and
    posteam), whose yardline_100 is the kicking spot, not where the
    offense took over. So the start is read off the first non-special
    play instead; a drive with no scrimmage play at all contributes
    nothing.
    """
    starts = []
    for drive_plays in _by_drive(plays).values():
        first = next((p for p in drive_plays if not p.is_special), None)
        if first is not None and first.yardline_100 is not None:
            starts.append(first.yardline_100)
    return MeanSignal.of(starts)

# --- Pace ---

def seconds_per_play(plays: List[Play]) -> MeanSignal:
    """Mean seconds-per-play, averaged across this team's offensive drives.

    Each drive contributes one value (its time of possession divided by
    its play count); the mean is unweighted across drives, so a 3-play
    drive counts the same as a 12-play drive. drive_time_of_possession
    and drive_play_count are drive-level values repeated on every row of
    the drive, so only the first play of each drive is read.
    """
    per_drive = []
    for drive_plays in _by_drive(plays).values():
        first = drive_plays[0]
        total_seconds = _seconds_from_mmss(first.drive_time_of_possession)
        play_count = first.drive_play_count
        if total_seconds is not None and play_count:
            per_drive.append(total_seconds / play_count)
    return MeanSignal.of(per_drive)


# --- Per-Team Signal Record ---

def team_signal_record(team: str, plays: List[Play]) -> Dict[str, object]:
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
        "points_per_trip_inside_40": points_per_trip_inside_40(scrimmage),
        "early_down_success_rate": early_down_success_rate(scrimmage),

        "success_rate": success_rate(scrimmage),
        "explosive_count": explosive_play_count(scrimmage),

        "epa_per_pass": epa_per_play(passes),
        "epa_per_rush": epa_per_play(rushes),
        "yards_per_pass": yards_per_play(passes),
        "yards_per_rush": yards_per_play(rushes),
        "cpoe": cpoe(passes),

        "sacks_forced": sacks_forced(defense),
        "tfl": tfl_count(defense),
        "forced_fumbles": forced_fumble_count(defense),
        "takeaways": takeaway_count(defense),

        "penalty_rate": penalty_count(plays, team),
        "penalty_yards_per_drive": penalty_yards_per_drive(plays, team),
        "starting_field_position": starting_field_position(off),

        "seconds_per_play": seconds_per_play(scrimmage),
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
            team: team_signal_record(team, document.plays)
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
                "version": VERSION,
            }
            for team in ordered
        ]




if __name__ == "__main__":
    # NOTE: For testing purposes only
    # Test building the team signals from the Game Document JSON file in the test data

    # Build the GameDocument from the JSON file
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

    # Build the team signals using the GameDocument
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