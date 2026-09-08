"""
Anchor Play Selection layer: this layer's job is picking the plays that mattered most.
"""

from dataclasses import dataclass, field, asdict, replace
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


VERSION = "v3"


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
            row["version"] = VERSION
            rows.append(row)
        return rows


# ------- Configuration -------

MAX_ANCHORS = 10

# Elimination epsilon: the |wpa| below which a play is treated as having done
# nothing on its own terms. This is NOT a significance threshold and is a
# different kind of number from the inclusion floors it replaces -- those asked
# "was this play important enough to include?", this asks only "did this play do
# anything at all?", so it needs to clear measurement noise and nothing more.
# It is also only ever reached after every consequence test below has passed,
# meaning it can never eliminate a score, turnover, decided down, or explosive
# gain no matter how small the WP swing.
# NOTE: tunable, not settled. Tune it empirically against both ends of the range
# -- a blowout, where much of the game should read as inert, and a close/comeback
# game, where little should -- before treating it as final.
INERT_WPA_EPSILON = 0.02

# Clock-killing plays. nflverse encodes kneel-downs and spikes as `play_type`
# values; there is no qb_kneel/qb_spike field on Play (those raw PBP columns are
# not carried over in Play.from_row), so play_type is the field to read.
INERT_PLAY_TYPES = {"qb_kneel", "qb_spike"}

# Yardage at or above which a gain is explosive enough to be consequential
# on its own, independent of what it did to win probability.
EXPLOSIVE_YARDS = 15

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


# ------- Elimination -------

def _is_inert(play: Play) -> bool:
    """True when a play did nothing worth anchoring on.

    Elimination-first: a play is inert only if it clears *every* consequence
    test -- no score, no turnover, no down decided, no explosive gain -- and is
    then either a clock-killing kneel/spike or moved win probability by less
    than INERT_WPA_EPSILON. Any single consequence keeps the play eligible
    regardless of its WPA, so a pick-six or fumble-return touchdown survives
    even when it lands in a game that was already decided.

    Boolean flags come through as None wherever the PBP feed left them unset;
    that is read as "not flagged" rather than as an unknown that would block
    elimination.
    """
    if play.touchdown:
        return False

    # Play carries no made-field-goal flag -- only field_goal_attempt; nflverse's
    # field_goal_result is not carried over in Play.from_row -- so every attempt
    # is treated as a scoring play. That is the conservative direction: it keeps
    # missed kicks eligible rather than risking the elimination of made ones.
    if play.field_goal_attempt:
        return False

    if play.interception or play.fumble_lost:
        return False

    if (play.third_down_converted or play.third_down_failed
            or play.fourth_down_converted or play.fourth_down_failed):
        return False

    if play.yards_gained is not None and play.yards_gained >= EXPLOSIVE_YARDS:
        return False

    if play.play_type in INERT_PLAY_TYPES:
        return True

    return play.wpa is not None and abs(play.wpa) < INERT_WPA_EPSILON


# ------- Anchor play selection -------

def _drive_candidates(document: GameDocument) -> list[Play]:
    """Each drive's single biggest swing, sorted by composite priority."""
    swings = [p for p in document.plays if p.wpa is not None]

    by_drive: dict[int, Play] = {}
    for p in swings:
        key = p.drive if p.drive is not None else p.play_id
        current = by_drive.get(key)
        if current is None or _priority(p) > _priority(current):
            by_drive[key] = p

    return sorted(by_drive.values(), key=_priority, reverse=True)


def _select_anchors(document: GameDocument, max_anchors: int = MAX_ANCHORS) -> list[AnchorPlay]:
    """Up to `max_anchors` plays by composite priority, one candidate per drive.

    Elimination-first: rather than admitting plays that clear a significance
    bar, this drops the ones _is_inert() proves did nothing and anchors on
    whatever is left. The list is therefore variable-length and may come back
    shorter than `max_anchors` -- that is the intended behavior when a game
    genuinely lacked that many live plays, not a shortfall to pad. Survivors are
    still ranked by the recency-weighted _priority() score. Ungated by garbage
    time, by design.
    """
    candidates = _drive_candidates(document)
    live = [p for p in candidates if not _is_inert(p)]
    top = live[:max_anchors]

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
    candidates = _drive_candidates(document)
    inert = [p for p in candidates if _is_inert(p)]
    anchors = _select_anchors(document)
    print(f"\n{len(candidates)} drive candidate(s): {len(inert)} eliminated as inert, "
          f"{len(anchors)} anchor(s) selected (cap {MAX_ANCHORS}):\n")
    for sp in anchors:
        p = sp.play
        print(f"  WPA {sp.anchor_wpa:+.3f}  priority {_priority(p):.3f}  "
              f"q{p.qtr} {(p.description or '')[:80]}")

    # ------- Step 1a: defensive-score survival -------
    # A pick-six or fumble-return TD must survive elimination on the strength of
    # the score alone, however little win probability it moved.
    defensive_tds = [p for p in document.plays
                     if p.touchdown and (p.interception or p.fumble_lost)]
    if defensive_tds:
        for p in defensive_tds:
            assert not _is_inert(p), f"defensive TD wrongly eliminated: {p.description}"
        print(f"\n{len(defensive_tds)} defensive TD(s) in this game, all surviving "
              f"elimination regardless of WPA:")
        for p in defensive_tds:
            print(f"  WPA {p.wpa:+.3f}  {(p.description or '')[:80]}")
    else:
        # This game's data has none, so the guarantee is demonstrated on a
        # synthetic play instead: a real play rewritten as a zero-WPA pick-six.
        base = next(p for p in document.plays if p.wpa is not None)
        pick_six = replace(
            base, touchdown=True, interception=True, fumble_lost=False, wpa=0.0,
            yards_gained=0, third_down_converted=False, third_down_failed=False,
            fourth_down_converted=False, fourth_down_failed=False,
        )
        assert not _is_inert(pick_six), "zero-WPA pick-six was eliminated as inert"
        print("\nNo defensive TD in this game's data. Checked synthetically instead: "
              "a pick-six with wpa=0.0 survives elimination\n(_is_inert -> False), "
              "so the score alone keeps it eligible.")

    # ------- Step 2: Full build and save to a JSON-serializable dict for inspection -------
    anchor_list = AnchorPlayList.build(document)
    anchor_dict = anchor_list.to_dict()
    anchor_json_filename = "../test_data/anchor_plays.json"
    with open(anchor_json_filename, "w") as f:
        json.dump(anchor_dict, f, indent=2)
    print(f"\nAnchor play list saved to {anchor_json_filename}")