"""Signal reductions for Snap Recap.

A *signal* is a reduction over a collection of Play records: filter to a
view, then collapse that view to a summary value. Each reduction is a
self-contained function `f(plays) -> value`, so the same function serves
a single game's recap and the league baseline (run over a season's plays
instead of one game's).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional
import pandas as pd

from play import Play, plays_from_frame, teams_in


# --- Output Dataclasses ---

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

def _distribution(keys: Iterable[Optional[str]]) -> Dict[str, float]:
    vals = [k for k in keys if k]
    total = len(vals)
    if not total:
        return {}
    counts: Dict[str, int] = {}
    for k in vals:
        counts[k] = counts.get(k, 0) + 1
    return dict(sorted(((k, n / total) for k, n in counts.items()), key=lambda kv: -kv[1]))


# --- Offensive Signals ---

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
    """Sacks per dropback (protection on offense / pass rush on defense)."""
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

def personnel_distribution(plays: List[Play]) -> Dict[str, float]:
    """Share of scrimmage snaps by offensive personnel package."""
    return _distribution(
        p.offense_personnel_package for p in plays if p.is_pass or p.is_rush
    )


# --- Defensive Signals ---

def pressure_rate(plays: List[Play]) -> RateSignal:
    """Pressures generated per charted dropback."""
    dropbacks = [p for p in plays if p.qb_dropback and p.was_pressure is not None]
    successes = sum(1 for p in dropbacks if p.was_pressure)
    return RateSignal.from_counts(successes, len(dropbacks))

def blitz_rate(plays: List[Play]) -> RateSignal:
    """Dropbacks rushed with 5+ pass rushers."""
    dropbacks = [p for p in plays if p.qb_dropback and p.number_of_pass_rushers is not None]
    successes = sum(1 for p in dropbacks if p.number_of_pass_rushers >= 5)
    return RateSignal.from_counts(successes, len(dropbacks))

def avg_box_defenders(plays: List[Play]) -> MeanSignal:
    """Mean defenders in the box on opponent rush plays."""
    return MeanSignal.of(
        p.defenders_in_box for p in plays
        if p.is_rush and p.defenders_in_box is not None
    )

def coverage_distribution(plays: List[Play]) -> Dict[str, float]:
    """Share of charted dropbacks by coverage shell."""
    return _distribution(p.defense_coverage_type for p in plays if p.is_pass)

def man_zone_distribution(plays: List[Play]) -> Dict[str, float]:
    """Share of charted dropbacks by man vs zone."""
    return _distribution(p.defense_man_zone_type for p in plays if p.is_pass)


# --- Main Signal Functions ---

def offensive_signals(plays: List[Play], team: str) -> Dict[str, object]:
    """Per-team offensive signal record — the locked output shape.

    A flat dict of {signal_name: signal_value}. Each value is its own
    reduction's return type (RateSignal, MeanSignal, or a dict). Extending
    the recap = add one entry; nothing else changes.
    """
    off = [p for p in plays if p.posteam == team]
    scrimmage = [p for p in off if p.is_pass or p.is_rush]
    passes = [p for p in off if p.is_pass]
    rushes = [p for p in off if p.is_rush]
    return {
        "third_down": third_down_conversion(off),
        "fourth_down": fourth_down_conversion(off),
        "red_zone_td": red_zone_touchdowns(off),
        "success_rate": success_rate(scrimmage),
        "explosive_rate": explosive_play_rate(scrimmage),
        "sack_rate": sack_rate(off),
        "epa_per_play": epa_per_play(scrimmage),
        "epa_per_pass": epa_per_play(passes),
        "epa_per_rush": epa_per_play(rushes),
        "yards_per_play": yards_per_play(scrimmage),
        "yards_per_rush": yards_per_play(rushes),
        "cpoe": cpoe(passes),
        "personnel": personnel_distribution(scrimmage),
    }

def defensive_signals(plays: List[Play], team: str) -> Dict[str, object]:
    """Per-team defensive signal record — the locked output shape.

    'Allowed' metrics reuse the offensive reductions on the defteam
    filter (opponent offense vs this defense); the rest are defense-only
    reductions over the participation columns.
    """
    dfp = [p for p in plays if p.defteam == team]
    scrimmage = [p for p in dfp if p.is_pass or p.is_rush]
    passes = [p for p in dfp if p.is_pass]
    rushes = [p for p in dfp if p.is_rush]
    return {
        "third_down_allowed": third_down_conversion(dfp),
        "red_zone_td_allowed": red_zone_touchdowns(dfp),
        "success_rate_allowed": success_rate(scrimmage),
        "explosive_rate_allowed": explosive_play_rate(scrimmage),
        "epa_per_play_allowed": epa_per_play(scrimmage),
        "epa_per_pass_allowed": epa_per_play(passes),
        "epa_per_rush_allowed": epa_per_play(rushes),
        "yards_per_play_allowed": yards_per_play(scrimmage),
        "yards_per_rush_allowed": yards_per_play(rushes),
        "pressure_rate": pressure_rate(dfp),
        "sacks": sack_rate(dfp),
        "blitz_rate": blitz_rate(dfp),
        "avg_box_defenders": avg_box_defenders(dfp),
        "coverage": coverage_distribution(dfp),
        "man_zone": man_zone_distribution(dfp),
    }









if __name__ == "__main__":
    # NOTE: For testing purposes only.
    # Test offensive and defensive signals on the sample preprocessed CSV
    # (BUF-JAX 2025 Wild Card game).

    def _print_record(title: str, record: Dict[str, object]) -> None:
        """Pretty-print a signal record (test helper)."""
        print(title)
        for name, value in record.items():
            if isinstance(value, dict):
                value = {k: f"{v:.1%}" for k, v in value.items()}
            print(f"  {name}: {value}")
        print()

    csv_file = "../test_data/preprocessed_data_buf_jax_wc_2025.csv"
    df = pd.read_csv(csv_file)

    plays = plays_from_frame(df)
    teams = teams_in(plays)

    for team in teams:
        _print_record(f"Offensive signals for {team}:", offensive_signals(plays, team))
        _print_record(f"Defensive signals for {team}:", defensive_signals(plays, team))