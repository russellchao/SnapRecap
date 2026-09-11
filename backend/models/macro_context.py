"""
Macro-Context Phrasing layer: turns precomputed GameBreakdown and
InjuryImpactReport data into fan-facing text at ingest time.

Same Python-owns-significance / LLM-only-phrases boundary as game_qa.py's
live Q&A pipeline, but there's no routing step -- each macro-context
prompt's data is already fixed by what game_breakdown.py / injury_impact.py
selected, so this is phrasing only.

EPA framing differs between the two payloads:
- Game Breakdown (phrase_losers_biggest_mistakes / phrase_winners_best_plays):
  EPA is the internal sort key in game_breakdown.py but is left out of
  the phrasing payload -- WPA is a percentage figure a casual fan can
  read directly, "expected points added" is not. WPA is a per-play stat,
  so it substitutes cleanly here. The two are phrased independently
  rather than in one combined call, since they're separate macro-context
  prompts with no shared narrative.
- Injury Impact: the before/after comparison IS an EPA aggregate across
  many plays. There is no per-play WPA equivalent that measures execution
  quality over a span (WPA reflects game-state leverage, not
  consistency), so the raw epa_per_play numbers stay in this one payload.
"""

import json
import sys
import os

import anthropic

try:
    from .play import Play
    from .play_narrative import synthesize
    from .game_breakdown import GameBreakdown
    from .injury_impact import InjuryImpactReport, InjuryImpact
except ImportError:
    sys.path.insert(0, os.path.dirname(__file__))
    from play import Play
    from play_narrative import synthesize
    from game_breakdown import GameBreakdown
    from injury_impact import InjuryImpactReport, InjuryImpact


MODEL = "claude-sonnet-5"

LOSERS_MISTAKES_PROMPT_VERSION = "v1"
WINNERS_BEST_PLAYS_PROMPT_VERSION = "v1"
INJURY_IMPACT_PROMPT_VERSION = "v1"

NO_INJURIES_RESPONSE = "No notable injuries occurred in this game."


# ------- Game Breakdown -------

_LOSERS_MISTAKES_SYSTEM_PROMPT = """You explain the losing team's costliest mistakes in \
an NFL game using only the structured data provided below. You are a phrasing layer, not \
an analyst: every factual claim you make must be directly traceable to a field in the \
provided data.

Rules:
- Only cite facts present in the data below. Never introduce outside knowledge about \
players, teams, or the league.
- Do not speculate about causes not evidenced in the data (e.g. motivation, coaching \
intent, injuries) unless a field explicitly states it.
- wpa (win probability added) measures how much a play swung the game, not why it \
happened -- use it to describe the size of the swing, never as the cause of the play \
itself.
- Write 2-4 sentences in plain, casual language for a fan who did not watch the game \
closely. No headers, no bullet points, no restating the question."""

_WINNERS_BEST_PLAYS_SYSTEM_PROMPT = """You explain the winning team's best plays in an \
NFL game using only the structured data provided below. You are a phrasing layer, not an \
analyst: every factual claim you make must be directly traceable to a field in the \
provided data.

Rules:
- Only cite facts present in the data below. Never introduce outside knowledge about \
players, teams, or the league.
- Do not speculate about causes not evidenced in the data (e.g. motivation, coaching \
intent, injuries) unless a field explicitly states it.
- wpa (win probability added) measures how much a play swung the game, not why it \
happened -- use it to describe the size of the swing, never as the cause of the play \
itself.
- Write 2-4 sentences in plain, casual language for a fan who did not watch the game \
closely. No headers, no bullet points, no restating the question."""


def _shape_play_for_breakdown(play: Play) -> dict:
    """Shape a play for the Game Breakdown payload: wpa, not epa -- see
    module docstring."""
    return {
        "narrative": synthesize(play, include_epa=False),
        "wpa": play.wpa,
    }


def _shape_losers_biggest_mistakes(breakdown: GameBreakdown) -> dict:
    """Shape the losing team's mistakes into their phrasing payload contract."""
    return {
        "loser": breakdown.loser,
        "biggest_mistakes": [
            _shape_play_for_breakdown(p) for p in breakdown.biggest_mistakes
        ],
    }


def _shape_winners_best_plays(breakdown: GameBreakdown) -> dict:
    """Shape the winning team's best plays into their phrasing payload contract."""
    return {
        "winner": breakdown.winner,
        "best_plays": [
            _shape_play_for_breakdown(p) for p in breakdown.best_plays
        ],
    }


def phrase_losers_biggest_mistakes(
    breakdown: GameBreakdown, client: anthropic.Anthropic | None = None
) -> str:
    """Phrase the losing team's biggest mistakes into fan-facing text,
    independent of the winner's best plays.

    Callers should skip this entirely when GameBreakdown.build() returned
    None (a tie) rather than call this with nothing to phrase.
    """
    payload = _shape_losers_biggest_mistakes(breakdown)
    client = client or anthropic.Anthropic()

    response = client.messages.create(
        model=MODEL,
        max_tokens=500,
        system=_LOSERS_MISTAKES_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": f"Game data:\n{json.dumps(payload, indent=2)}"}
        ],
    )

    text_blocks = [b.text for b in response.content if b.type == "text"]
    return "".join(text_blocks).strip()


def phrase_winners_best_plays(
    breakdown: GameBreakdown, client: anthropic.Anthropic | None = None
) -> str:
    """Phrase the winning team's best plays into fan-facing text,
    independent of the loser's biggest mistakes.

    Callers should skip this entirely when GameBreakdown.build() returned
    None (a tie) rather than call this with nothing to phrase.
    """
    payload = _shape_winners_best_plays(breakdown)
    client = client or anthropic.Anthropic()

    response = client.messages.create(
        model=MODEL,
        max_tokens=500,
        system=_WINNERS_BEST_PLAYS_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": f"Game data:\n{json.dumps(payload, indent=2)}"}
        ],
    )

    text_blocks = [b.text for b in response.content if b.type == "text"]
    return "".join(text_blocks).strip()


# ------- Injury Impact -------

_INJURY_IMPACT_SYSTEM_PROMPT = """You explain how injuries affected an NFL game using \
only the structured data provided below. You are a phrasing layer, not an analyst: every \
factual claim you make must be directly traceable to a field in the provided data.

Rules:
- Only cite facts present in the data below. Never introduce outside knowledge about \
players, teams, or the league, including injury severity, diagnosis, or whether/when a \
player returned to the game -- the data does not track any of that.
- Do not speculate about causes not evidenced in the data.
- epa_per_play measures scoring efficiency across a span of plays. Treat a before/after \
comparison built from a small sample size (roughly single digits) as a weak signal and \
hedge the claim rather than stating it as a strong pattern.
- Write 2-4 sentences in plain, casual language for a fan who did not watch the game \
closely. No headers, no bullet points, no restating the question."""


def _shape_injury_impact(impact: InjuryImpact) -> dict:
    """Shape one InjuryImpact into its phrasing payload contract.

    Raw epa_per_play numbers are included here -- see module docstring
    for why this payload doesn't substitute wpa the way Game Breakdown's
    does.
    """
    return {
        "injured_player": impact.event.player,
        "injured_players_team": impact.event.team,
        "injury_play": synthesize(impact.event.play),
        "affected_team": impact.before.team,
        "epa_per_play_before": impact.before.epa_per_play,
        "sample_size_before": impact.before.plays,
        "epa_per_play_after": impact.after.epa_per_play,
        "sample_size_after": impact.after.plays,
    }


def phrase_injury_impact(
    report: InjuryImpactReport, client: anthropic.Anthropic | None = None
) -> str:
    """Phrase an InjuryImpactReport into fan-facing text.

    Short-circuits to a canned response when there are no injury events,
    rather than asking the LLM to phrase an empty payload.
    """
    if not report.impacts:
        return NO_INJURIES_RESPONSE

    payload = {"injuries": [_shape_injury_impact(i) for i in report.impacts]}
    client = client or anthropic.Anthropic()

    response = client.messages.create(
        model=MODEL,
        max_tokens=500,
        system=_INJURY_IMPACT_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": f"Game data:\n{json.dumps(payload, indent=2)}"}
        ],
    )

    text_blocks = [b.text for b in response.content if b.type == "text"]
    return "".join(text_blocks).strip()




if __name__ == "__main__":
    # NOTE: For testing purposes only

    import json as _json

    try:
        from .game_document import GameDocument, GameHeader
    except ImportError:
        from game_document import GameDocument, GameHeader

    def document_from_dict(raw: dict) -> GameDocument:
        """Rebuild a GameDocument from its `to_dict()` / JSON form."""
        return GameDocument(
            header=GameHeader(**raw["header"]),
            plays=[Play(**p) for p in raw["plays"]],
        )

    game_doc_json = "../test_data/game_document.json"
    with open(game_doc_json) as f:
        raw = _json.load(f)
    document = document_from_dict(raw)

    breakdown = GameBreakdown.build(document)
    if breakdown is None:
        print(f"{document.header.game_id} ended in a tie -- no Game Breakdown to phrase.")
    else:
        print("--- Loser's Biggest Mistakes ---")
        print(phrase_losers_biggest_mistakes(breakdown))
        print("\n--- Winner's Best Plays ---")
        print(phrase_winners_best_plays(breakdown))

    report = InjuryImpactReport.build(document)
    print("\n--- Injury Impact ---")
    print(phrase_injury_impact(report))