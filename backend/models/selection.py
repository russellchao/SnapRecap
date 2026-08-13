"""Selection layer: projects a lossless GameDocument into a selected, prompt-ready structure.

Anchor-only. Category attribution (the margin decomposition ledger) lives in
aggregation.py; this layer's sole job is picking the dramatic WPA-swing plays.
"""

from dataclasses import dataclass, field, asdict
import json

from play import Play
from game_document import GameDocument, GameHeader, TeamSignals


# ------- Output Dataclasses -------

@dataclass
class SelectedPlay:
    """An anchor play chosen for the prompt."""
    play: Play
    anchor_wpa: float
    go_ahead_score: bool = False   # placeholder; real go-ahead/game-tying detection is deferred

@dataclass
class RecapSelection:
    """Selected, prompt-ready projection of a GameDocument."""
    header: GameHeader
    anchors: list[SelectedPlay] = field(default_factory=list)

    @classmethod
    def build(
        cls, document: GameDocument, threshold: float | None = None,
        min_anchors: int | None = None, max_anchors: int | None = None,
    ) -> "RecapSelection":
        """Project a GameDocument into its anchor selection."""
        anchors = _select_anchors(
            document,
            threshold=threshold if threshold is not None else ANCHOR_WPA_THRESHOLD,
            min_anchors=min_anchors if min_anchors is not None else MIN_ANCHORS,
            max_anchors=max_anchors if max_anchors is not None else MAX_ANCHORS,
        )
        return cls(header=document.header, anchors=anchors)

    def to_dict(self) -> dict:
        """JSON-serializable form for the prompt step and cache."""
        return asdict(self)


# ------- Configuration -------

MIN_ANCHORS = 1
MAX_ANCHORS = 5
ANCHOR_WPA_THRESHOLD = 0.08   # eyeball value, tune against test games


# ------- Anchor selection -------

def _select_anchors(
        document: GameDocument, threshold: float = ANCHOR_WPA_THRESHOLD,
        min_anchors: int = MIN_ANCHORS, max_anchors: int = MAX_ANCHORS,
    ) -> list[SelectedPlay]:
    """The dramatic plays: one |WPA| swing per drive, threshold-gated with a floor/ceiling. Ungated by garbage time, by design."""
    swings = [p for p in document.plays if p.wpa is not None]

    by_drive: dict[int, Play] = {}
    for p in swings:
        key = p.drive if p.drive is not None else p.play_id
        current = by_drive.get(key)
        if current is None or abs(p.wpa) > abs(current.wpa):
            by_drive[key] = p

    candidates = sorted(by_drive.values(), key=lambda p: abs(p.wpa), reverse=True)

    cleared = [p for p in candidates if abs(p.wpa) >= threshold]
    if len(cleared) < min_anchors:
        cleared = candidates[:min_anchors]
    elif len(cleared) > max_anchors:
        cleared = cleared[:max_anchors]

    return [SelectedPlay(play=p, anchor_wpa=p.wpa) for p in cleared]




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
        from signals import RateSignal, MeanSignal
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

    # ------- Step 1: Anchors -------
    anchors = _select_anchors(document)
    print(f"\n{len(anchors)} anchor(s) selected (threshold {ANCHOR_WPA_THRESHOLD}, "
          f"bounds {MIN_ANCHORS}-{MAX_ANCHORS}):\n")
    for sp in anchors:
        p = sp.play
        print(f"  WPA {sp.anchor_wpa:+.3f}  q{p.qtr} {(p.desc or '')[:90]}")

    # ------- Step 2: Full build and save to a JSON-serializable dict for inspection -------
    selection = RecapSelection.build(document)
    selection_dict = selection.to_dict()
    selection_json_filename = "../test_data/selection.json"
    with open(selection_json_filename, "w") as f:
        json.dump(selection_dict, f, indent=2)
    print(f"\nSelection layer saved to {selection_json_filename}")