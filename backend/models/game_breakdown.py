"""
Game Breakdown layer: the plays that decided the game -- the
losing team's costliest mistakes and the winning team's best plays,
both ranked by EPA.

No DB persistence here, same as play_selection.py -- this is an
in-memory projection of a GameDocument. Precomputing this at ingest
time (rather than live per tap) is a pipeline/ingest-code concern,
not this layer's.
"""

from dataclasses import dataclass, field, asdict
import sys
import os

try:
    from .play import Play
    from .game_document import GameDocument, GameHeader
except ImportError:
    sys.path.insert(0, os.path.dirname(__file__))
    from play import Play
    from game_document import GameDocument, GameHeader


TOP_N = 3


@dataclass
class GameBreakdown:
    """The losing team's `TOP_N` worst-EPA plays and the winning team's
    `TOP_N` best-EPA plays."""
    header: GameHeader
    winner: str
    loser: str
    biggest_mistakes: list[Play] = field(default_factory=list)
    best_plays: list[Play] = field(default_factory=list)

    @classmethod
    def build(cls, document: GameDocument, top_n: int = TOP_N) -> "GameBreakdown | None":
        """Project a GameDocument into its breakdown.

        Returns None on a tie: there's no winner's best plays or loser's
        mistakes to find, since neither role exists. This is a legitimate
        degenerate case (like a blowout coming back short of MAX_ANCHORS
        used to be), not an error -- callers should skip offering this
        macro-context prompt for a tied game rather than treat a None
        return as a failure.
        """
        header = document.header
        if header.home_score == header.away_score:
            return None

        winner = header.home_team if header.home_score > header.away_score else header.away_team
        loser = header.away_team if winner == header.home_team else header.home_team

        return cls(
            header=header,
            winner=winner,
            loser=loser,
            biggest_mistakes=_worst_epa_plays(document, loser, top_n),
            best_plays=_best_epa_plays(document, winner, top_n),
        )

    def to_dict(self) -> dict:
        """JSON-serializable form for the prompt step."""
        return asdict(self)


def _worst_epa_plays(document: GameDocument, team: str, top_n: int) -> list[Play]:
    """`team`'s own offensive plays with the most negative EPA, worst first."""
    plays = [p for p in document.plays if p.posteam == team and p.epa is not None]
    return sorted(plays, key=lambda p: p.epa)[:top_n]


def _best_epa_plays(document: GameDocument, team: str, top_n: int) -> list[Play]:
    """`team`'s own offensive plays with the most positive EPA, best first."""
    plays = [p for p in document.plays if p.posteam == team and p.epa is not None]
    return sorted(plays, key=lambda p: p.epa, reverse=True)[:top_n]




if __name__ == "__main__":
    # NOTE: For testing purposes only

    import json

    def document_from_dict(raw: dict) -> GameDocument:
        """Rebuild a GameDocument from its `to_dict()` / JSON form."""
        return GameDocument(
            header=GameHeader(**raw["header"]),
            plays=[Play(**p) for p in raw["plays"]],
        )

    game_doc_json = "../test_data/game_document.json"
    with open(game_doc_json) as f:
        raw = json.load(f)
    document = document_from_dict(raw)

    breakdown = GameBreakdown.build(document)
    if breakdown is None:
        print(f"{document.header.game_id} ended in a tie -- no breakdown to build.")
    else:
        print(f"{document.header.game_id}: {breakdown.winner} beat {breakdown.loser}\n")

        print(f"{breakdown.loser}'s biggest mistakes:")
        for p in breakdown.biggest_mistakes:
            print(f"  EPA {p.epa:+.2f}  q{p.qtr} {(p.description or '')[:100]}")

        print(f"\n{breakdown.winner}'s best plays:")
        for p in breakdown.best_plays:
            print(f"  EPA {p.epa:+.2f}  q{p.qtr} {(p.description or '')[:100]}")
