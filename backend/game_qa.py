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
- team_signals: season-context tendency and efficiency stats per team (conversion \
rates, EPA, yards per play) — use for "how does this compare to their usual" or \
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
    print(f"Routing question: {question}")

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


# On-field descriptive fields only. Excludes selection/value metrics (wpa, epa, qb_epa,
# cpoe, wp) and redundant post-play score bookkeeping, per the anchor_plays contract.
ANCHOR_PLAY_FIELDS = [
    "play_id",
    "posteam",
    "defteam",
    "qtr",
    "game_seconds_remaining",
    "down",
    "ydstogo",
    "yardline_100",
    "goal_to_go",
    "score_differential",
    "posteam_timeouts_remaining",
    "defteam_timeouts_remaining",
    "drive",
    "fixed_drive_result",
    "play_type",
    "is_special",
    "shotgun",
    "no_huddle",
    "qb_dropback",
    "qb_scramble",
    "pass_location",
    "pass_length",
    "air_yards",
    "yards_after_catch",
    "run_location",
    "run_gap",
    "yards_gained",
    "success",
    "first_down",
    "third_down_converted",
    "third_down_failed",
    "fourth_down_converted",
    "fourth_down_failed",
    "complete_pass",
    "touchdown",
    "sack",
    "qb_hit",
    "interception",
    "fumble_lost",
    "penalty",
    "passer",
    "rusher",
    "receiver",
    "description",
]


def _shape_ledger(ledger_row: dict) -> dict:
    """Shape a game_ledgers DB row into the ledger payload contract.

    Derives a friendlier point_margin/favors_team framing from the raw
    away_ep/home_ep/diff fields the DB actually stores (categorized_diff
    and total_epa_diff are reconciliation fields for Python's own use,
    not part of the phrasing payload — excluded here).
    """
    home_team = ledger_row["home_team"]
    away_team = ledger_row["away_team"]
    categories = []
    for cat in ledger_row["categories"].values():
        diff = cat["diff"]
        favors_team = None
        if diff > 0:
            favors_team = home_team
        elif diff < 0:
            favors_team = away_team
        categories.append(
            {
                "category": cat["category"],
                "category_point_margin": round(abs(diff), 2),
                "category_play_count": cat["away_plays"] + cat["home_plays"],
                "category_favors_team": favors_team,
            }
        )
    return {"categories": categories}


def _shape_anchor_plays(anchor_play_rows: list[dict]) -> dict:
    """Whitelist-filter anchor_plays DB rows into the payload contract.

    Rows come back with extra fields the DB stores for internal use
    (wpa, game_id) — this filters down to on-field descriptive fields
    only, per the locked contract. No category label: on-field flags
    (interception, third_down_converted, is_special, qb_dropback, etc.)
    already identify what kind of play this was without one.
    """
    return {
        "anchor_plays": [
            {field: row.get(field) for field in ANCHOR_PLAY_FIELDS}
            for row in anchor_play_rows
        ]
    }


def _shape_team_signals(team_signal_rows: dict) -> dict:
    """Shape {team: db_row} into {team: signal_record}, dropping the
    game_id/team columns that don't belong in the phrasing payload.
    """
    return {
        "team_signals": {
            team: row["signals"] for team, row in team_signal_rows.items()
        }
    }


def fetch_qa_payload(
        components: list[str], ledger_row: dict, anchor_play_rows: list[dict], team_signal_rows: dict
    ) -> dict:
    """
    Fetch and shape only the routed components into their payload contracts.
    """
    payload: dict = {}

    if "ledger" in components:
        if ledger_row is not None:
            payload.update(_shape_ledger(ledger_row))

    if "anchor_plays" in components:
        if anchor_play_rows:
            payload.update(_shape_anchor_plays(anchor_play_rows))

    if "team_signals" in components:
        if team_signal_rows:
            payload.update(_shape_team_signals(team_signal_rows))

    return payload


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
    print(f"Answering question: {question}")

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

    print(f"Answer stop reason: {response.stop_reason}")

    text_blocks = [b.text for b in response.content if b.type == "text"]
    return "".join(text_blocks).strip()