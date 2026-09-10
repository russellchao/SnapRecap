"""
Injury Impact Report layer: finds injury-notice plays and compares each
team's EPA/play before and after that point in the game.

The efficiency comparison is team-agnostic by design -- both teams are
tracked around the injury regardless of who is hurt, since figuring out
which team a hurt player's absence would affect isn't something this
layer needs to resolve. The injured player's own team is still cheap to
capture directly from the injury notice text (nflverse embeds it there),
so it's kept as identifying context.

Before/after is a single season-long split at the injury play, not a
fixed drive window -- simplest option, not yet validated against a
close/late-game injury where a short window might read more clearly.
"""

import re
import sys
import os
from dataclasses import dataclass, field, asdict

try:
    from .play import Play
    from .game_document import GameDocument, GameHeader
except ImportError:
    sys.path.insert(0, os.path.dirname(__file__))
    from play import Play
    from game_document import GameDocument, GameHeader


# nflverse embeds injury notices directly in `description`, e.g.
# "BUF-22-R.Davis was injured during the play." -- team, jersey number,
# and an abbreviated "F.Lastname" form, not a resolved full name.
_INJURY_PATTERN = re.compile(
    r"([A-Z]{2,3})-(\d{1,2})-([A-Za-z.'\-]+) was injured during the play"
)


@dataclass
class InjuryEvent:
    """One injury notice: who, which team, and the play it happened on."""
    play: Play
    team: str
    player: str  # raw "F.Lastname" form as it appears in the feed


@dataclass
class TeamEfficiency:
    """A team's own offensive EPA/play over some slice of the game."""
    team: str
    plays: int
    epa_per_play: float | None


@dataclass
class InjuryImpact:
    """One injury event plus both teams' EPA/play before and after it."""
    event: InjuryEvent
    before: list[TeamEfficiency]
    after: list[TeamEfficiency]


@dataclass
class InjuryImpactReport:
    """Every injury event in the game, each with its before/after split."""
    header: GameHeader
    impacts: list[InjuryImpact] = field(default_factory=list)

    @classmethod
    def build(cls, document: GameDocument) -> "InjuryImpactReport":
        """Project a GameDocument into its injury impact report."""
        events = _injury_events(document)
        impacts = [_impact_for(document, event) for event in events]
        return cls(header=document.header, impacts=impacts)

    def to_dict(self) -> dict:
        """JSON-serializable form for the prompt step."""
        return asdict(self)


def _injury_events(document: GameDocument) -> list[InjuryEvent]:
    """Every injury notice in the game, in play order.

    A single play's description can carry more than one notice (two
    players hurt on the same play), so this checks all matches per play,
    not just the first.
    """
    events = []
    for p in document.plays:
        if not p.description:
            continue
        for match in _INJURY_PATTERN.finditer(p.description):
            team, _jersey, player = match.groups()
            events.append(InjuryEvent(play=p, team=team, player=player))
    return events


def _teams_in(document: GameDocument) -> list[str]:
    """Both team abbreviations in the game, taken from the first play that
    carries both a posteam and a defteam."""
    for p in document.plays:
        if p.posteam and p.defteam:
            return [p.posteam, p.defteam]
    return []


def _epa_per_play(plays: list[Play], team: str) -> TeamEfficiency:
    """`team`'s own offensive EPA/play over the given slice of scrimmage
    plays (passes and rushes only -- special teams excluded, same
    convention as team_signals.py)."""
    team_plays = [
        p for p in plays
        if p.posteam == team and p.epa is not None and (p.is_pass or p.is_rush)
    ]
    if not team_plays:
        return TeamEfficiency(team=team, plays=0, epa_per_play=None)
    total = sum(p.epa for p in team_plays)
    return TeamEfficiency(team=team, plays=len(team_plays), epa_per_play=total / len(team_plays))


def _impact_for(document: GameDocument, event: InjuryEvent) -> InjuryImpact:
    """Both teams' EPA/play on all plays before vs. after the injury play,
    split by the injury play's position in the game."""
    teams = _teams_in(document)
    idx = next(i for i, p in enumerate(document.plays) if p.play_id == event.play.play_id)
    before_plays = document.plays[:idx]
    after_plays = document.plays[idx + 1:]
    return InjuryImpact(
        event=event,
        before=[_epa_per_play(before_plays, t) for t in teams],
        after=[_epa_per_play(after_plays, t) for t in teams],
    )




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

    report = InjuryImpactReport.build(document)
    print(f"{document.header.game_id}: {len(report.impacts)} injury event(s)\n")

    for impact in report.impacts:
        e = impact.event
        print(f"{e.team}-{e.player} injured, q{e.play.qtr}: {(e.play.description or '')[:100]}")
        for b, a in zip(impact.before, impact.after):
            b_str = f"{b.epa_per_play:+.3f}" if b.epa_per_play is not None else "n/a"
            a_str = f"{a.epa_per_play:+.3f}" if a.epa_per_play is not None else "n/a"
            print(f"  {b.team}: {b_str} EPA/play before ({b.plays} plays) "
                  f"-> {a_str} EPA/play after ({a.plays} plays)")
        print()
