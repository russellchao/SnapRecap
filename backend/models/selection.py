"""Selection layer: projects a lossless GameDocument into a selected, prompt-ready structure."""

from dataclasses import dataclass, field, asdict
from collections import defaultdict
import json

from signals import RateSignal, MeanSignal
from play import Play
from game_document import GameDocument, GameHeader, TeamSignals


# ------- Output Dataclasses -------

@dataclass
class SelectedPlay:
    """A play chosen for the prompt, tagged with every reason it was selected."""
    play: Play
    reasons: dict[str, float | None]   # reason -> justifying metric (EPA for signals, WPA for anchors; None for scores/turnovers)

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

        # Step 1: sections where one offense diverges from the other (gap >= threshold)
        sections = _diverging_sections(document, thresholds)

        # Step 2: 
        # - rank each fired section's candidates, keep its top-k exemplars
        # - select anchors based on high-WPA swings, the opposite role from exemplars
        # - determine the always-include plays (TDs/TOs) that should be included regardless of section or anchor status
        for section in sections:
            section.plays = _select_exemplars(section, document)
        anchors = _select_anchors(document)
        always_include = _always_include(document)

        # Step 3: dedupe across sources by play_id, accumulating reasons; section is home
        sections, anchors, always_include = _merge_selection(sections, anchors, always_include)

        return cls(header=document.header, sections=sections, anchors=anchors, always_include=always_include)

    def to_dict(self) -> dict:
        """JSON-serializable form for the prompt step and cache."""
        return asdict(self)
    

# ------- Configuration -------

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


# ------- Step 1: opponent-relative divergence -------

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


# ------- Step 2: importance ranking per exemplar -------

# Per-signal exemplar views
#
# Each view takes one team's offensive plays and returns that signal's
# candidate exemplars, mirroring what the reduction actually counted.

def _scrimmage(offense: list[Play]) -> list[Play]:
    return [p for p in offense if p.is_pass or p.is_rush]

def _passes(offense: list[Play]) -> list[Play]:
    return [p for p in offense if p.is_pass]

def _rushes(offense: list[Play]) -> list[Play]:
    return [p for p in offense if p.is_rush]

def _converted_third(offense: list[Play]) -> list[Play]:
    return [p for p in offense if p.third_down_converted]

def _converted_fourth(offense: list[Play]) -> list[Play]:
    return [p for p in offense if p.fourth_down_converted]

def _successful(offense: list[Play]) -> list[Play]:
    return [p for p in _scrimmage(offense) if p.success]

def _explosive(offense: list[Play]) -> list[Play]:
    return [
        p for p in _scrimmage(offense)
        if p.yards_gained is not None
        and ((p.is_pass and p.yards_gained >= 20) or (p.is_rush and p.yards_gained >= 10))
    ]

def _sacks(offense: list[Play]) -> list[Play]:
    return [p for p in offense if p.qb_dropback and p.sack]

def _red_zone_trip_plays(offense: list[Play]) -> list[Play]:
    """Plays inside red-zone trips (drives that reached the 20)."""
    drives: dict[int, list[Play]] = defaultdict(list)
    for p in offense:
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

EXEMPLARS_PER_SECTION = 3
ANCHOR_COUNT = 3

# Contested-game band on pre-play win probability; candidates outside it are garbage time.
CONTESTED_WP = (0.05, 0.95)

# Signals where lower is better: exemplars rank by most-negative EPA (the damage), not most-positive.
NEGATIVE_SIGNALS = {"sack_rate"}

def _select_exemplars(
        section: Section, document: GameDocument, k: int = EXEMPLARS_PER_SECTION, wp_band: tuple[float, float] = CONTESTED_WP
    ) -> list[SelectedPlay]:
    
    """Rank a fired section's candidate plays by EPA, gate garbage time, keep the top k."""
    team = max(section.team_values, key=section.team_values.get)
    offense = [p for p in document.plays if p.posteam == team]
    candidates = SIGNAL_VIEWS[section.signal](offense)

    lo, hi = wp_band
    live = [p for p in candidates if p.wp is not None and lo <= p.wp <= hi]

    descending = section.signal not in NEGATIVE_SIGNALS
    live.sort(key=lambda p: p.epa if p.epa is not None else 0.0, reverse=descending)

    return [SelectedPlay(play=p, reasons={section.signal: p.epa}) for p in live[:k]]

def _select_anchors(document: GameDocument, k: int = ANCHOR_COUNT) -> list[SelectedPlay]:
    """The dramatic plays: top win-probability swings by |WPA|, ungated by design."""
    swings = [p for p in document.plays if p.wpa is not None]
    swings.sort(key=lambda p: abs(p.wpa), reverse=True)
    return [SelectedPlay(play=p, reasons={"anchor": p.wpa}) for p in swings[:k]]

def _always_include(document: GameDocument) -> list[SelectedPlay]:
    """Scores and turnovers — categorical must-includes, carried with a None metric."""
    selected = []
    for p in document.plays:
        reasons: dict[str, float | None] = {}
        if p.interception or p.fumble_lost:
            reasons["turnover"] = None
        elif p.touchdown:                   # elif: defensive-return TDs stay tagged as turnovers, not posteam scores         
            reasons["touchdown"] = None
        if reasons:
            selected.append(SelectedPlay(play=p, reasons=reasons))
    return selected


# ------- Step 3: merge, dedupe, tag -------

def _merge_selection(
    sections: list[Section], anchors: list[SelectedPlay], always_include: list[SelectedPlay],
) -> tuple[list[Section], list[SelectedPlay], list[SelectedPlay]]:
    
    """Dedupe plays across sources by play_id, accumulating reasons.

    Home precedence is section > anchor > always-include: a play homed in a
    section keeps its anchor/score status as extra reasons instead of appearing
    twice. A play may live in multiple sections (evidence-both) — those sections
    share one SelectedPlay, so its reasons are the union.
    """
    registry: dict[int, SelectedPlay] = {}

    def absorb(sp: SelectedPlay) -> SelectedPlay:
        """Fold sp's reasons into the canonical play for its play_id; return the canonical."""
        canonical = registry.get(sp.play.play_id)
        if canonical is None:
            registry[sp.play.play_id] = sp
            return sp
        canonical.reasons.update(sp.reasons)
        return canonical

    # sections first (highest precedence): rewrite each to reference the canonical play
    for section in sections:
        section.plays = [absorb(sp) for sp in section.plays]

    # a non-section source survives in its own list only if it wasn't already homed
    kept_anchors = []
    for sp in anchors:
        if absorb(sp) is sp:
            kept_anchors.append(sp)

    kept_always = []
    for sp in always_include:
        if absorb(sp) is sp:
            kept_always.append(sp)

    return sections, kept_anchors, kept_always





if __name__ == "__main__":
    # NOTE: For testing purposes only
    # Test building the Selection Layer using the Game Document JSON file in the test data

    # ------- Test Helper Functions -------
    # GameDocument reconstruction from its to_dict()/JSON form 
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


    # ------- Step 0: Load the saved game document JSON and rebuild it into a GameDocument -------
    game_doc_json = "../test_data/game_document.json"
    with open(game_doc_json) as f:
        raw = json.load(f)

    document = document_from_dict(raw)
    print(f"Rebuilt GameDocument for {document.header.game_id}: "
          f"{len(document.plays)} plays, teams {list(document.signals.keys())}")

    team_a, team_b = list(document.signals.keys())
    offense_a = [p for p in document.plays if p.posteam == team_a]
    offense_b = [p for p in document.plays if p.posteam == team_b]


    # ------- Step 1: Sections that fired during selection -------
    sections = _diverging_sections(document, DEFAULT_THRESHOLDS)
    print(f"\n{len(sections)} section(s) fired (gap >= threshold), most decisive first:\n")
    for s in sections:
        ratio = s.gap / DEFAULT_THRESHOLDS[s.signal]
        print(f"  {s.signal:<16} "
              f"{team_a} {s.team_values[team_a]:.3f} vs {team_b} {s.team_values[team_b]:.3f}  "
              f"| gap {s.gap:.3f} (>= {DEFAULT_THRESHOLDS[s.signal]}, {ratio:.1f}x)")


    # ------- Step 2: Ranked candidate exemplars per fired section, plus dramatic anchors -------
    print("\nCandidate exemplars per fired section (relevance views):\n")
    for s in sections:
        view = SIGNAL_VIEWS[s.signal]
        print(f"  {s.signal:<16} {team_a}: {len(view(offense_a)):>3}   {team_b}: {len(view(offense_b)):>3}   candidate play(s)")

    print("\nTop exemplars per fired section (EPA-ranked, garbage time gated):\n")
    for s in sections:
        s.plays = _select_exemplars(s, document)
        team = max(s.team_values, key=s.team_values.get)
        print(f"  {s.signal} ({team}):")
        for sp in s.plays:
            p = sp.play
            print(f"      EPA {sp.reasons[s.signal]:+.2f}  q{p.qtr} {(p.desc or '')[:90]}")

    print("\nAnchors (top |WPA| swings):\n")
    for sp in _select_anchors(document):
        p = sp.play
        print(f"  WPA {sp.reasons['anchor']:+.3f}  q{p.qtr} {(p.desc or '')[:90]}")


    # ------- Step 3: Full build — merge/dedupe/tag across all sources and save to a JSON-serializable dict for inspection -------
    selection = RecapSelection.build(document)
    selection_dict = selection.to_dict()
    selection_json_filename = "../test_data/selection.json"
    with open(selection_json_filename, "w") as f:
        json.dump(selection_dict, f, indent=2)
    print(f"\nSelection layer saved to {selection_json_filename}")