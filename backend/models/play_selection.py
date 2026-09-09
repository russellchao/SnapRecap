"""
Play Selection layer: this layer's job is picking the plays that matter,
grouped by why they matter.

No DB persistence: this is an in-memory projection of a GameDocument,
consumed directly by whatever builds the recap. The macro-context prompts
fetch and store their own play sets separately.
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


# ------- Configuration -------

# WPA and EPA magnitude above which a play is significant on win-probability terms
# alone, independent of down or drive.
HIGH_LEVERAGE_WPA = 0.05
HIGH_LEVERAGE_EPA = 2.0


# ------- Output Dataclasses -------

@dataclass
class DriveGroup:
    """All plays belonging to one drive, in original order."""
    drive: int
    plays: list[Play]

@dataclass
class PlaySelection:
    """In-memory, prompt-ready projection of a GameDocument.

    Categories overlap by design -- a 4th-and-1 conversion with wpa=0.12
    belongs in both `high_leverage` and `situational`, and every selected
    play also appears in its `drives` entry. Nothing here is a table row;
    downstream consumers read this object directly.
    """
    header: GameHeader
    drives: list[DriveGroup] = field(default_factory=list)
    high_leverage: list[Play] = field(default_factory=list)
    situational: list[Play] = field(default_factory=list)
    decisive: list[Play] = field(default_factory=list)

    @classmethod
    def build(cls, document: GameDocument) -> "PlaySelection":
        """Project a GameDocument into its play selection."""
        return cls(
            header=document.header,
            drives=_drive_groups(document),
            high_leverage=_high_leverage_plays(document),
            situational=_situational_plays(document),
            decisive=_decisive_plays(document),
        )

    def to_dict(self) -> dict:
        """JSON-serializable form for the prompt step."""
        return asdict(self)


# ------- Selection: by drive -------

def _drive_groups(document: GameDocument) -> list[DriveGroup]:
    """Every play, grouped by drive, in drive order.

    Plays with no drive (pre-game/administrative rows) are excluded.
    """
    by_drive: dict[int, list[Play]] = {}
    for p in document.plays:
        if p.drive is not None:
            by_drive.setdefault(p.drive, []).append(p)
    return [DriveGroup(drive=d, plays=plays) for d, plays in sorted(by_drive.items())]


# ------- Selection: by leverage -------

def _high_leverage_plays(document: GameDocument) -> list[Play]:
    """Plays that swung win probability by more than HIGH_LEVERAGE_WPA or
    expected points by more than HIGH_LEVERAGE_EPA, in chronological order."""
    return [
        p for p in document.plays
        if (p.wpa is not None and abs(p.wpa) > HIGH_LEVERAGE_WPA)
        or (p.epa is not None and abs(p.epa) > HIGH_LEVERAGE_EPA)
    ]


# ------- Selection: by down -------

def _situational_plays(document: GameDocument) -> list[Play]:
    """3rd/4th down attempts, converted or failed, in chronological order."""
    return [
        p for p in document.plays
        if p.third_down_converted or p.third_down_failed
        or p.fourth_down_converted or p.fourth_down_failed
    ]


# ------- Selection: decisive plays -------

def _decisive_plays(document: GameDocument) -> list[Play]:
    """Touchdowns, turnovers, and field goal attempts, regardless of wpa or
    down.

    This carries forward the guarantee the old elimination-first model
    enforced: a low-wpa pick-six must never be dropped just because it
    isn't the biggest swing on its drive and isn't a 3rd/4th down play.
    Without this category, the new inclusion criteria (drive/leverage/down)
    would reintroduce the exact Maye's-pick-six gap elimination-first was
    built to close.

    Play carries no made-field-goal flag -- only field_goal_attempt -- so
    every attempt is treated as decisive; that is the conservative
    direction, keeping missed kicks in rather than risking a made one
    being dropped.
    """
    return [
        p for p in document.plays
        if p.touchdown or p.interception or p.fumble_lost or p.field_goal_attempt
    ]




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

    # ------- Step 1: Selection -------
    selection = PlaySelection.build(document)
    print(f"\n{len(selection.drives)} drive(s), "
          f"{len(selection.high_leverage)} high-leverage play(s) "
          f"(|wpa| > {HIGH_LEVERAGE_WPA} or |epa| > {HIGH_LEVERAGE_EPA}), "
          f"{len(selection.situational)} situational (3rd/4th down) play(s), "
          f"{len(selection.decisive)} decisive play(s):\n")

    print("High-leverage plays:")
    for p in selection.high_leverage:
        print(f"  WPA {p.wpa:+.3f}  q{p.qtr} {(p.description or '')[:80]}")

    print("\nSituational plays:")
    for p in selection.situational:
        print(f"  {p.down} & {p.ydstogo}  q{p.qtr} {(p.description or '')[:80]}")

    print("\nDecisive plays:")
    for p in selection.decisive:
        print(f"  WPA {p.wpa if p.wpa is not None else float('nan'):+.3f}  "
              f"q{p.qtr} {(p.description or '')[:80]}")

    # ------- Step 1a: defensive-score survival -------
    # A pick-six or fumble-return TD must show up in `decisive` however
    # little win probability it moved.
    defensive_tds = [p for p in document.plays
                     if p.touchdown and (p.interception or p.fumble_lost)]
    if defensive_tds:
        for p in defensive_tds:
            assert p in selection.decisive, f"defensive TD missing from decisive: {p.description}"
        print(f"\n{len(defensive_tds)} defensive TD(s) in this game, all present in "
              f"`decisive` regardless of WPA:")
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
        assert pick_six in _decisive_plays(GameDocument(header=document.header, plays=[pick_six])), (
            "zero-WPA pick-six was not captured as decisive"
        )
        print("\nNo defensive TD in this game's data. Checked synthetically instead: "
              "a pick-six with wpa=0.0 is captured by `decisive`\nregardless of WPA.")

    # ------- Step 2: Save to a JSON-serializable dict for inspection -------
    selection_dict = selection.to_dict()
    selection_json_filename = "../test_data/play_selection.json"
    with open(selection_json_filename, "w") as f:
        json.dump(selection_dict, f, indent=2)
    print(f"\nPlay selection saved to {selection_json_filename}")