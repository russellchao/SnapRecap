"""
Anchor Play Selection layer: this layer's job is picking the plays that mattered most.
"""

from dataclasses import dataclass, field, asdict
import json
import sys
import os

try:
    from .play import Play
    from .game_document import GameDocument, GameHeader
except ImportError:
    sys.path.insert(0, os.path.dirname(__file__))
    from play import Play
    from game_document import GameDocument, GameHeader


# ------- Output Dataclasses -------

@dataclass
class AnchorPlay:
    """An anchor play chosen for the prompt."""
    play: Play
    anchor_wpa: float

@dataclass
class AnchorPlayList:
    """Selected, prompt-ready projection of a GameDocument."""
    header: GameHeader
    anchors: list[AnchorPlay] = field(default_factory=list)

    @classmethod
    def build(cls, document: GameDocument, max_anchors: int | None = None) -> "AnchorPlayList":
        """Project a GameDocument into its anchor play selection."""
        anchors = _select_anchors(
            document, max_anchors=max_anchors if max_anchors is not None else MAX_ANCHORS,
        )
        return cls(header=document.header, anchors=anchors)

    def to_dict(self) -> dict:
        """JSON-serializable form for the prompt step and cache."""
        return asdict(self)

    # Full on-field descriptive field set for downstream Q&A retrieval, plus
    # wpa (kept for internal/debugging use — never exposed in the Q&A payload,
    # which whitelist-filters it back out at shaping time in game_qa.py).
    # No category field: on-field flags (interception, third_down_converted,
    # is_special, qb_dropback, etc.) already identify play type without one.
    _DB_ITEM_FIELDS = [
        "play_id", "posteam", "defteam", "qtr", "game_seconds_remaining",
        "down", "ydstogo", "yardline_100", "goal_to_go", "score_differential",
        "posteam_timeouts_remaining", "defteam_timeouts_remaining", "drive",
        "fixed_drive_result", "play_type", "is_special", "shotgun", "no_huddle",
        "qb_dropback", "qb_scramble", "pass_location",
        "pass_length", "air_yards", "yards_after_catch", "run_location",
        "run_gap", "yards_gained",
        "success", "first_down", "third_down_converted", "third_down_failed",
        "fourth_down_converted", "fourth_down_failed", "complete_pass",
        "touchdown", "sack", "qb_hit", "interception", "fumble_lost",
        "penalty", "passer", "rusher", "receiver", "description", "wpa",
    ]

    def to_db_item(self) -> list[dict]:
        """DB rows for the anchor_plays table. game_id + play_id form the
        composite key, so game_id is placed first in each row."""
        rows = []
        for sp in self.anchors:
            row = {"game_id": self.header.game_id}
            row.update({field: getattr(sp.play, field, None) for field in self._DB_ITEM_FIELDS})
            rows.append(row)
        return rows


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


# ------- Anchor play selection -------

def _select_anchors(document: GameDocument, max_anchors: int = MAX_ANCHORS) -> list[AnchorPlay]:
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

    return [AnchorPlay(play=p, anchor_wpa=p.wpa) for p in top]




if __name__ == "__main__":
    # NOTE: For testing purposes only
    # Test building the Selection Layer using the Game Document JSON file in the test data

    # ------- Test Helper Functions -------
    # GameDocument reconstruction from its to_dict()/JSON form
    # `asdict` flattens every nested dataclass into a plain dict, so loading a
    # saved document means rebuilding those types from the dicts.

    def document_from_dict(raw: dict) -> GameDocument:
        """Rebuild a GameDocument from its `to_dict()` / JSON form."""
        return GameDocument(
            header=GameHeader(**raw["header"]),
            plays=[Play(**p) for p in raw["plays"]],
        )

    # ------- Step 0: Load the saved game document JSON and rebuild it into a GameDocument -------
    game_doc_json = "../test_data/game_document.json"
    with open(game_doc_json) as f:
        raw = json.load(f)

    document = document_from_dict(raw)
    print(f"Rebuilt GameDocument for {document.header.game_id}: "
          f"{len(document.plays)} plays, {document.header.away_team} @ {document.header.home_team}")

    # ------- Step 1: Anchors -------
    anchors = _select_anchors(document)
    print(f"\n{len(anchors)} anchor play(s) selected (cap {MAX_ANCHORS}):\n")
    for sp in anchors:
        p = sp.play
        print(f"  WPA {sp.anchor_wpa:+.3f}  priority {_priority(p):.3f}  "
              f"q{p.qtr} {(p.description or '')[:80]}")

    # ------- Step 2: Full build and save to a JSON-serializable dict for inspection -------
    anchor_list = AnchorPlayList.build(document)
    anchor_dict = anchor_list.to_dict()
    anchor_json_filename = "../test_data/anchor_plays.json"
    with open(anchor_json_filename, "w") as f:
        json.dump(anchor_dict, f, indent=2)
    print(f"\nAnchor play list saved to {anchor_json_filename}")