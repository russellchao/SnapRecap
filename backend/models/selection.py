"""Selection layer: projects a lossless GameDocument into a selected, prompt-ready structure.

Anchor-only. Category attribution (the margin decomposition ledger) lives in
game_ledger.py; this layer's sole job is picking the plays that mattered most.
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

@dataclass
class RecapSelection:
    """Selected, prompt-ready projection of a GameDocument."""
    header: GameHeader
    anchors: list[SelectedPlay] = field(default_factory=list)

    @classmethod
    def build(cls, document: GameDocument, max_anchors: int | None = None) -> "RecapSelection":
        """Project a GameDocument into its anchor selection."""
        anchors = _select_anchors(
            document, max_anchors=max_anchors if max_anchors is not None else MAX_ANCHORS,
        )
        return cls(header=document.header, anchors=anchors)

    def to_dict(self) -> dict:
        """JSON-serializable form for the prompt step and cache."""
        return asdict(self)

    def to_db_item(self) -> dict:
        return [
            {
                "game_id": self.header.game_id,
                "play_id": sp.play.play_id,
                "wpa": sp.play.wpa,
                "quarter": sp.play.qtr,
                "game_seconds_remaining": sp.play.game_seconds_remaining,
                "description": sp.play.desc,
                "posteam": sp.play.posteam
            }
            for sp in self.anchors
        ]


# ------- Configuration -------

MAX_ANCHORS = 5

# Convex recency weighting: leverage stays compressed for most of the game and
# spikes late. Regulation runs W_MIN -> W_MAX; OT is treated as strictly higher
# leverage than any regulation play and runs W_MAX -> W_OT_MAX.
W_MIN = 0.5
W_MAX = 1.0
W_OT_MAX = 1.3
RECENCY_EXPONENT = 3

REGULATION_SECONDS = 3600
OT_PERIOD_SECONDS = 900


# ------- Recency weighting -------

def _recency_weight(qtr: int, game_seconds_remaining: float) -> float:
    """Convex leverage weight. `game_seconds_remaining` is continuous 3600->0 in
    regulation and resets to 900 each OT period, so the two are weighted separately.
    """
    if qtr >= 5:
        s = min(max(game_seconds_remaining, 0), OT_PERIOD_SECONDS)
        progress = 1 - s / OT_PERIOD_SECONDS
        return W_MAX + (W_OT_MAX - W_MAX) * progress ** RECENCY_EXPONENT

    s = min(max(game_seconds_remaining, 0), REGULATION_SECONDS)
    progress = 1 - s / REGULATION_SECONDS
    return W_MIN + (W_MAX - W_MIN) * progress ** RECENCY_EXPONENT


def _priority(play: Play) -> float:
    """Composite ranking score: raw WP swing scaled by how late it happened."""
    return abs(play.wpa) * _recency_weight(play.qtr, play.game_seconds_remaining)


# ------- Anchor selection -------

def _select_anchors(document: GameDocument, max_anchors: int = MAX_ANCHORS) -> list[SelectedPlay]:
    """Top-`max_anchors` plays by composite priority, one candidate per drive. Ungated by garbage time, by design."""
    swings = [p for p in document.plays if p.wpa is not None]

    by_drive: dict[int, Play] = {}
    for p in swings:
        key = p.drive if p.drive is not None else p.play_id
        current = by_drive.get(key)
        if current is None or _priority(p) > _priority(current):
            by_drive[key] = p

    candidates = sorted(by_drive.values(), key=_priority, reverse=True)
    top = candidates[:max_anchors]

    return [SelectedPlay(play=p, anchor_wpa=p.wpa) for p in top]




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
    print(f"\n{len(anchors)} anchor(s) selected (cap {MAX_ANCHORS}):\n")
    for sp in anchors:
        p = sp.play
        print(f"  WPA {sp.anchor_wpa:+.3f}  priority {_priority(p):.3f}  "
              f"q{p.qtr} {(p.desc or '')[:80]}")

    # ------- Step 2: Full build and save to a JSON-serializable dict for inspection -------
    selection = RecapSelection.build(document)
    selection_dict = selection.to_dict()
    selection_json_filename = "../test_data/selection.json"
    with open(selection_json_filename, "w") as f:
        json.dump(selection_dict, f, indent=2)
    print(f"\nSelection layer saved to {selection_json_filename}")