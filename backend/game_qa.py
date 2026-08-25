"""Q&A phrasing layer for game recaps. Replaces recap.py's one-shot recap generation.

Python owns retrieval scope and factual grounding; the LLM owns phrasing only.
"""

import json
import anthropic

MODEL = "claude-sonnet-5"
PROMPT_VERSION = "v1"

VALID_COMPONENTS = {"ledger", "anchor_plays", "team_signals"}

_ROUTER_TOOL = {
    "name": "select_components",
    "description": "Select which game-data components are relevant to answering the user's question.",
    "input_schema": {
        "type": "object",
        "properties": {
            "components": {
                "type": "array",
                "items": {"type": "string", "enum": sorted(VALID_COMPONENTS)},
                "uniqueItems": True,
            }
        },
        "required": ["components"],
    },
}

_ROUTER_SYSTEM_PROMPT = """You route user questions about a single NFL game to the data \
components needed to answer them. Do not answer the question. Do not explain your reasoning.

Components:
- ledger: margin decomposition by category (turnovers, pass_protection, penalties, \
special_teams, red_zone, third_down, explosive_plays, other) — use for "why did the \
margin end up X" or category-specific questions.
- anchor_plays: the handful of individual plays that most shaped the outcome — use for \
questions about specific moments, plays, or players' individual actions.
- team_signals: season-context tendency and efficiency stats per team (rates, EPA, \
personnel/coverage distributions) — use for "how does this compare to their usual" or \
tendency-based questions.

Select every component that could plausibly be relevant. If the question is unrelated to \
this game's plays, situational tendencies, or team stats (e.g. contracts, other weeks, \
opinions), return an empty components list."""


class RoutingValidationError(Exception):
    """Raised when the router's tool-use output fails validation."""


def route_question(question: str, client: anthropic.Anthropic | None = None) -> list[str]:
    """Return the subset of {ledger, anchor_plays, team_signals} relevant to a question.

    Empty list means the question is out of scope; callers should short-circuit to a
    canned response rather than invoking the answer call.
    """
    client = client or anthropic.Anthropic()

    response = client.messages.create(
        model=MODEL,
        max_tokens=200,
        system=_ROUTER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": question}],
        tools=[_ROUTER_TOOL],
        tool_choice={"type": "tool", "name": "select_components"},
    )

    tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
    if len(tool_use_blocks) != 1:
        raise RoutingValidationError(
            f"Expected exactly one tool_use block, got {len(tool_use_blocks)}"
        )

    raw_components = tool_use_blocks[0].input.get("components")
    if raw_components is None:
        raise RoutingValidationError("Router response missing 'components' field")

    invalid = set(raw_components) - VALID_COMPONENTS
    if invalid:
        raise RoutingValidationError(f"Router returned invalid components: {invalid}")

    return list(raw_components)


OUT_OF_SCOPE_RESPONSE = (
    "I can only answer questions about this game's plays, situational tendencies, "
    "and team stats."
)

_ANSWER_SYSTEM_PROMPT = """You answer a user's question about a single NFL game using \
only the structured data provided below. You are a phrasing layer, not an analyst: every \
factual claim you make must be directly traceable to a field in the provided data.

Rules:
- Only cite facts present in the data below. Never introduce outside knowledge about \
players, teams, or the league.
- Do not speculate about causes not evidenced in the data (e.g. motivation, coaching \
intent, injuries) unless a field explicitly states it.
- team_signals rates are this-game tendency stats, each paired with an "attempts" or "n" \
count. Treat any rate with a small attempts/n (roughly single digits) as a weak signal — \
mention the sample size or hedge the claim rather than stating the rate as a strong pattern.
- If the provided data does not contain enough to answer the question, say so plainly \
rather than guessing.
- Write 2-4 sentences in plain, casual language for a fan who did not watch the game \
closely. No headers, no bullet points, no restating the question."""


def answer_question(
    question: str,
    payload: dict,
    client: anthropic.Anthropic | None = None,
) -> str:
    """Phrase an answer to a question using only the Python-fetched, routed payload.

    payload contains only the components route_question() selected, each already
    shaped per the ledger/anchor_plays/team_signals contracts (selection metrics like
    wpa/epa/cpoe/wp excluded upstream).
    """
    client = client or anthropic.Anthropic()

    response = client.messages.create(
        model=MODEL,
        max_tokens=400,
        system=_ANSWER_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Game data:\n{json.dumps(payload, indent=2)}\n\nQuestion: {question}",
            }
        ],
    )

    text_blocks = [b.text for b in response.content if b.type == "text"]
    return "".join(text_blocks).strip()