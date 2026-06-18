"""Selection layer: projects a lossless GameDocument into a selected, prompt-ready structure."""

from dataclasses import dataclass, field, asdict
from collections import defaultdict
import json

from signals import RateSignal, MeanSignal
from play import Play
from game_document import GameDocument, GameHeader, TeamSignals


# --- configuration ---

# Offensive efficiency signals eligible to fire a section. `personnel` is excluded (schematic distribution).
EFFICIENCY_SIGNALS = [
    "epa_per_play",
    "epa_per_pass",
    "epa_per_rush",
    "success_rate",
    "explosive_rate",
    "yards_per_play",
    "yards_per_rush",
    "third_down",
    "fourth_down",
    "red_zone_td",
    "sack_rate",
    "cpoe",
]

# Per-signal notable-gap thresholds, in each metric's native units. Eyeball values — tune these.
DEFAULT_THRESHOLDS = {
    "epa_per_play": 0.10,
    "epa_per_pass": 0.15,
    "epa_per_rush": 0.12,
    "success_rate": 0.08,
    "explosive_rate": 0.05,
    "yards_per_play": 1.0,
    "yards_per_rush": 1.0,
    "third_down": 0.15,
    "fourth_down": 0.25,
    "red_zone_td": 0.25,
    "sack_rate": 0.05,
    "cpoe": 0.04,
}


# --- output dataclasses ---

@dataclass
class SelectedPlay:
    """A play chosen for the prompt, tagged with why it was selected."""
    play: Play
    reason: str          # signal name (exemplar), "anchor", or "turnover"/"touchdown" (always-include)
    value: float         # the EPA or WPA that justified selection; meaning depends on reason


@dataclass
class Section:
    """A fired efficiency signal and the plays that exemplify it."""
    signal: str
    team_values: dict[str, float]   # team abbr -> the signal's value for that team
    gap: float                      # opponent-relative divergence magnitude
    plays: list[SelectedPlay] = field(default_factory=list)


@dataclass
class RecapSelection:
    """Selected, prompt-ready projection of a GameDocument."""
    header: GameHeader
    sections: list[Section] = field(default_factory=list)
    anchors: list[SelectedPlay] = field(default_factory=list)
    always_include: list[SelectedPlay] = field(default_factory=list)

    @classmethod
    def build(cls, document: GameDocument, thresholds: dict[str, float] | None = None) -> "RecapSelection":
        """Project a GameDocument into a selection using per-signal divergence thresholds."""
        thresholds = thresholds or DEFAULT_THRESHOLDS

        # step 1: identify sections where the team's performance diverges significantly from the opponent (gap >= threshold)
        sections = _diverging_sections(document, thresholds)

        # step 2: pull exemplar plays per fired section (relevance views below + importance ranking)

        # step 3: anchors (top WPA) + always-include (scores, turnovers)

        # step 4: merge, dedupe, tag

        return cls(header=document.header, sections=sections)

    def to_dict(self) -> dict:
        """JSON-serializable form for the prompt step and cache."""
        return asdict(self)


# --- step 1: opponent-relative divergence ---

def _signal_value(record: dict, name: str) -> float | None:
    """Pull the comparable scalar for `name` from a signals dict; None if undefined."""
    signal = record[name]
    if isinstance(signal, RateSignal):
        return signal.rate
    if isinstance(signal, MeanSignal):
        return signal.mean
    return None


def _diverging_sections(document: GameDocument, thresholds: dict[str, float]) -> list[Section]:
    """Fire a section per efficiency signal whose opponent-relative offensive gap clears its threshold."""
    team_a, team_b = list(document.signals.keys())
    offense_a = document.signals[team_a].offense
    offense_b = document.signals[team_b].offense

    sections = []
    for name in EFFICIENCY_SIGNALS:
        threshold = thresholds.get(name)
        if threshold is None:
            continue
        a = _signal_value(offense_a, name)
        b = _signal_value(offense_b, name)
        if a is None or b is None:
            continue
        gap = abs(a - b)
        if gap >= threshold:
            sections.append(Section(signal=name, team_values={team_a: a, team_b: b}, gap=gap))

    # order by how decisively each cleared its own bar, so heterogeneous metrics stay comparable
    sections.sort(key=lambda s: s.gap / thresholds[s.signal], reverse=True)
    return sections


# --- step 2 (relevance): per-signal exemplar views ---
# Each view takes one team's offensive plays and returns that signal's
# candidate exemplars, mirroring what the reduction actually counted.

def _scrimmage(off: list[Play]) -> list[Play]:
    return [p for p in off if p.is_pass or p.is_rush]

def _passes(off: list[Play]) -> list[Play]:
    return [p for p in off if p.is_pass]

def _rushes(off: list[Play]) -> list[Play]:
    return [p for p in off if p.is_rush]

def _converted_third(off: list[Play]) -> list[Play]:
    return [p for p in off if p.third_down_converted]

def _converted_fourth(off: list[Play]) -> list[Play]:
    return [p for p in off if p.fourth_down_converted]

def _successful(off: list[Play]) -> list[Play]:
    return [p for p in _scrimmage(off) if p.success]

def _explosive(off: list[Play]) -> list[Play]:
    return [
        p for p in _scrimmage(off)
        if p.yards_gained is not None
        and ((p.is_pass and p.yards_gained >= 20) or (p.is_rush and p.yards_gained >= 10))
    ]

def _sacks(off: list[Play]) -> list[Play]:
    return [p for p in off if p.qb_dropback and p.sack]

def _red_zone_trip_plays(off: list[Play]) -> list[Play]:
    """Plays inside red-zone trips (drives that reached the 20)."""
    drives: dict[int, list[Play]] = defaultdict(list)
    for p in off:
        if p.drive is not None:
            drives[p.drive].append(p)
    candidates = []
    for dp in drives.values():
        in_rz = [p for p in dp if p.yardline_100 is not None and p.yardline_100 <= 20]
        if in_rz:
            candidates.extend(in_rz)
    return candidates


SIGNAL_VIEWS = {
    "epa_per_play": _scrimmage,
    "epa_per_pass": _passes,
    "epa_per_rush": _rushes,
    "yards_per_play": _scrimmage,
    "yards_per_rush": _rushes,
    "cpoe": _passes,
    "success_rate": _successful,
    "explosive_rate": _explosive,
    "third_down": _converted_third,
    "fourth_down": _converted_fourth,
    "sack_rate": _sacks,
    "red_zone_td": _red_zone_trip_plays,
}


# --- test-only: GameDocument reconstruction from its to_dict()/JSON form ---
# `asdict` flattens every nested dataclass into a plain dict, so loading a
# saved document means rebuilding those types from the dicts.

def _signal_from_dict(value: dict):
    """Rebuild one signal value, recovering the type `asdict` erased.

    RateSignal, MeanSignal, and distribution dicts (personnel/coverage/
    man_zone, already plain str -> float) are told apart by their keys.
    """
    keys = set(value.keys())
    if keys == {"attempts", "successes", "rate"}:
        return RateSignal(**value)
    if keys == {"n", "mean"}:
        return MeanSignal(**value)
    return value  # distribution dict (or empty {})


def _team_signals_from_dict(value: dict) -> TeamSignals:
    return TeamSignals(
        offense={name: _signal_from_dict(v) for name, v in value["offense"].items()},
        defense={name: _signal_from_dict(v) for name, v in value["defense"].items()},
    )


def document_from_dict(raw: dict) -> GameDocument:
    """Rebuild a GameDocument from its `to_dict()` / JSON form."""
    return GameDocument(
        header=GameHeader(**raw["header"]),
        signals={team: _team_signals_from_dict(ts) for team, ts in raw["signals"].items()},
        plays=[Play(**p) for p in raw["plays"]],
    )


if __name__ == "__main__":
    # NOTE: For testing purposes only
    # Test the selection layer on the BUF-JAX 2025 Wild Card Game

    # Load the saved game document JSON and rebuild it into a GameDocument
    game_doc_json = "../test_data_docs/game_document_buf_jax_wc_2025.json"
    with open(game_doc_json) as f:
        raw = json.load(f)

    document = document_from_dict(raw)
    print(f"Rebuilt GameDocument for {document.header.game_id}: "
          f"{len(document.plays)} plays, teams {list(document.signals.keys())}")

    team_a, team_b = list(document.signals.keys())
    offense_a = [p for p in document.plays if p.posteam == team_a]
    offense_b = [p for p in document.plays if p.posteam == team_b]

    # Step 1: sections that fired during selection
    sections = _diverging_sections(document, DEFAULT_THRESHOLDS)
    print(f"\n{len(sections)} section(s) fired (gap >= threshold), most decisive first:\n")
    for s in sections:
        ratio = s.gap / DEFAULT_THRESHOLDS[s.signal]
        print(f"  {s.signal:<16} "
              f"{team_a} {s.team_values[team_a]:.3f} vs {team_b} {s.team_values[team_b]:.3f}  "
              f"| gap {s.gap:.3f} (>= {DEFAULT_THRESHOLDS[s.signal]}, {ratio:.1f}x)")

    # Step 2 (relevance): candidate exemplars each fired section's view returns, per team
    print("\nCandidate exemplars per fired section (relevance views):\n")
    for s in sections:
        view = SIGNAL_VIEWS[s.signal]
        print(f"  {s.signal:<16} {team_a}: {len(view(offense_a)):>3}   {team_b}: {len(view(offense_b)):>3}   candidate play(s)")