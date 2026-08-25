"""
Q&A phrasing layer for game recaps.

Python owns retrieval scope and factual grounding; the LLM owns phrasing only.
"""

import anthropic

MODEL = "claude-sonnet-5"
PROMPT_VERSION = "qa-v1"

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