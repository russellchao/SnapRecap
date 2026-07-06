"""Prompt assembly and text serialization for NFL game recaps.

Consumes the projected record produced by projection.render_selection() — a plain
dict, not a dataclass — and renders it into the plain-text body of the user prompt.

Boundary the serializer enforces by construction:
  - Selection machinery never reaches the model. Raw `reasons` values, `signal`
    keys, and divergence `team_values` are dropped; only the coarsened `tier`
    survives, as an emphasis token.
  - A signal is translated into a plain-language theme here (Python's verdict,
    phrased minimally) so the model never sees "cpoe" / "epa_per_pass" as jargon.
  - Attached context (the annotations dict per play) renders nested under the single play
    it belongs to — that physical subordination is the only causal license.
"""

from __future__ import annotations

import json
import sys


# ---------------------------------------------------------------------------
# System prompt (durable, cacheable — identical across games).
# Only role + boundary rules are locked; format and tone are deferred.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are the writer for an NFL game recap. Your job is to turn a pre-computed \
analysis into clear, engaging prose for a casual fan who wants to understand \
why the game unfolded as it did.

You are not the analyst. Every judgment about what matters in this game — which \
plays, which signals, how much each one mattered — has already been made and is \
given to you as input. You do not evaluate significance, add plays, or introduce \
information. You explain what you are given, in plain language.

Rules:
- Write only about what is in the input. Never mention a play, statistic, player \
action, or cause that is not present in the data given to you. If it isn't there, \
it didn't happen for your purposes.
- You may state that something caused a play's outcome only when the input \
attaches that context to that play. Attached context is the on-field circumstance \
bound to a play — for example, the pressure the quarterback faced, the coverage he \
threw into, or the personnel or matchup on the field. The single legal causal link \
is: a piece of attached context → the outcome of the play it is attached to. Do \
not link one play to another, do not link across sections, and do not supply a \
cause the input does not attach.
- Some items carry selection metrics — the measures used to decide an item earned \
a place in the recap, such as EPA, win-probability (WPA) swing, or a fired \
efficiency signal. These govern how much emphasis and space you give an item, \
nothing more. Never state them as a cause or effect, and never surface them as \
jargon: do not write "high WPA," "the EPA was," "the signal fired," or any metric \
name. The reader feels the emphasis; they never see the machinery.
- Scoring plays and turnovers are also selected for you, but unlike the metrics \
above, they are real on-field events. Report them as outcomes; simply don't narrate \
why they were chosen for inclusion.
- The final score and basic box score are assumed known. Do not deliver the recap \
as a recounting of the scoreboard. Your value is the why underneath the result, \
not a restatement of it.
"""


# ---------------------------------------------------------------------------
# Signal -> plain-language theme. The ONE translation the serializer must do to
# keep metric keys out of the prompt. PLACEHOLDER wording — tune later alongside
# tone. Themes are short noun phrases; the model builds the sentence around them.
# ---------------------------------------------------------------------------

SIGNAL_THEMES = {
    "epa_per_play": "overall offensive efficiency",
    "epa_per_pass": "passing-game efficiency",
    "epa_per_rush": "running-game efficiency",
    "success_rate": "rate of on-schedule, successful plays",
    "explosive_rate": "rate of explosive, big-gain plays",
    "yards_per_play": "yards gained per play",
    "yards_per_rush": "yards per carry on the ground",
    "third_down": "third-down conversions",
    "fourth_down": "fourth-down conversions",
    "red_zone_td": "finishing red-zone trips with touchdowns",
    "sack_rate": "avoiding sacks",  # negative signal: favored = fewer sacks allowed
    "cpoe": "passing accuracy above expectation",
}

def _theme(signal: str) -> str:
    """Translate a signal key into a fan-facing theme, falling back to a prettified key."""
    return SIGNAL_THEMES.get(signal, signal.replace("_", " "))


# ---------------------------------------------------------------------------
# Signal -> family (the phase of play the metric measures). A fixed property of
# the metric, NOT a significance judgment: selection already decided what matters;
# family only labels domain. Sections sharing a family are co-located so the model
# weaves them into one thread instead of restating the same story per signal.
# ---------------------------------------------------------------------------

SIGNAL_FAMILIES = {
    "epa_per_play": "overall",
    "yards_per_play": "overall",
    "success_rate": "overall",
    "explosive_rate": "overall",
    "epa_per_pass": "passing",
    "cpoe": "passing",
    "epa_per_rush": "rushing",
    "yards_per_rush": "rushing",
    "third_down": "situational",
    "fourth_down": "situational",
    "red_zone_td": "situational",
    "sack_rate": "protection",
}

FAMILY_LABELS = {
    "overall": "Overall offense",
    "passing": "Passing game",
    "rushing": "Running game",
    "situational": "Situational efficiency",
    "protection": "Pass protection",
}

# Canonical tiebreak order when families share the same strongest emphasis.
_FAMILY_ORDER = ("passing", "rushing", "overall", "situational", "protection")

# Emphasis rank for ordering — best (most significant) first.
_TIER_RANK = {"decisive": 0, "major": 1, "notable": 2}


def _section_rank(section: dict) -> int:
    """Ordering rank from a section's divergence tier (lower = more significant)."""
    tier = section.get("divergence", {}).get("tier")
    return _TIER_RANK.get(tier, len(_TIER_RANK))


def _family_of(section: dict) -> str:
    """The family a section belongs to, defaulting unknown signals to 'overall'."""
    return SIGNAL_FAMILIES.get(section.get("signal", ""), "overall")


def _grouped_families(sections: list[dict]) -> list[tuple[str, list[dict]]]:
    """Group sections into families, order families by strongest emphasis (then
    canonical), and order sections within a family by emphasis (stable on ties)."""
    families: dict[str, list[dict]] = {}
    for section in sections:
        families.setdefault(_family_of(section), []).append(section)

    def family_key(family: str) -> tuple[int, int]:
        best = min(_section_rank(s) for s in families[family])
        canonical = _FAMILY_ORDER.index(family) if family in _FAMILY_ORDER else len(_FAMILY_ORDER)
        return (best, canonical)

    return [
        (family, sorted(families[family], key=_section_rank))
        for family in sorted(families, key=family_key)
    ]


# ---------------------------------------------------------------------------
# Play-level rendering.
# ---------------------------------------------------------------------------

_ORDINAL = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}
_INDENT = "    "

def _situation_line(facts: dict) -> str:
    """A compact, human-readable game-state line derived from a play's facts."""
    parts = []
    if facts.get("qtr") is not None:
        parts.append(f"Q{facts['qtr']}")

    down = facts.get("down")
    if down is not None:
        dd = f"{_ORDINAL.get(down, str(down))} & {facts.get('ydstogo')}"
        if facts.get("goal_to_go"):
            dd += " (goal-to-go)"
        parts.append(dd)
    elif facts.get("play_type"):
        parts.append(facts["play_type"])

    if facts.get("yardline_100") is not None:
        parts.append(f"{facts['yardline_100']} yds from end zone")

    sd, pos = facts.get("score_differential"), facts.get("posteam")
    if sd is not None and pos is not None:
        if sd > 0:
            parts.append(f"{pos} up {sd}")
        elif sd < 0:
            parts.append(f"{pos} down {abs(sd)}")
        else:
            parts.append("tied")

    return ", ".join(parts)


def _play_block(play: dict) -> str:
    """Render one projected play: situation, authoritative description, context, emphasis."""
    facts = play.get("facts", {})
    lines = [f"- {_situation_line(facts)}"]

    desc = facts.get("desc")
    if desc:
        lines.append(f"{_INDENT}play: {desc}")

    lines.extend(_annotation_lines(play.get("annotations", {})))

    tier = play.get("selection", {}).get("tier")
    if tier is not None:
        lines.append(f"{_INDENT}emphasis: {tier}")

    return "\n".join(lines)


def _annotation_lines(annotations: dict) -> list[str]:
    """Render attached context as play-subordinate lines (the causal-link license)."""
    lines = []
    for key, value in annotations.items():
        if isinstance(value, bool):
            value = "yes" if value else "no"
        lines.append(f"{_INDENT}context — {key.replace('_', ' ')}: {value}")
    return lines


# ---------------------------------------------------------------------------
# Bucket-level rendering.
# ---------------------------------------------------------------------------

def _section_block(section: dict) -> str:
    """Render a fired section: plain theme, favored team, emphasis, ranked exemplars."""
    divergence = section.get("divergence", {})
    header = (
        f"## {_theme(section.get('signal', ''))}\n"
        f"edge: {divergence.get('favored')}\n"
        f"emphasis: {divergence.get('tier')}"
    )
    plays = "\n\n".join(_play_block(p) for p in section.get("plays", []))
    return f"{header}\n\n{plays}" if plays else header


def _family_block(family: str, sections: list[dict]) -> str:
    """Render a family heading over its sections; the model weaves them into one thread."""
    header = f"# {FAMILY_LABELS.get(family, family.title())}"
    body = "\n\n".join(_section_block(s) for s in sections)
    return f"{header}\n\n{body}"


def _flat_bucket(heading: str, plays: list[dict]) -> str:
    """Render a heading over a flat list of plays (anchors, scores/turnovers)."""
    body = "\n\n".join(_play_block(p) for p in plays)
    return f"# {heading}\n\n{body}"


def _context_block(context: dict) -> str:
    """Render the game frame; the score is grounding only, not the recap."""
    f = context.get("facts", {})
    matchup = f"{f.get('away_team')} at {f.get('home_team')}"
    when = f"Week {f.get('week')}, {f.get('season')} season"
    final = f"Final: {f.get('away_team')} {f.get('away_score')}, {f.get('home_team')} {f.get('home_score')}"

    outcome = context.get("outcome")
    if outcome and "winner" in outcome:
        final += f" ({outcome['winner']} won by {outcome['margin']})"
    elif outcome and outcome.get("result") == "tie":
        final += " (tie)"

    return (
        f"game: {matchup} — {when}\n"
        f"{final}\n"
        "(Score and box score are assumed known; explain the why, don't restate them.)"
    )


# ---------------------------------------------------------------------------
# Top-level assembly.
# ---------------------------------------------------------------------------

def serialize_projection(projected: dict) -> str:
    """Render the full projected record dict into the user-prompt body."""
    blocks = [_context_block(projected.get("context", {}))]

    for family, sections in _grouped_families(projected.get("sections", [])):
        blocks.append(_family_block(family, sections))

    anchors = projected.get("anchors", [])
    if anchors:
        blocks.append(_flat_bucket("Biggest swing plays", anchors))

    scores = projected.get("scores_and_turnovers", [])
    if scores:
        blocks.append(_flat_bucket("Scoring plays and turnovers", scores))

    return "\n\n".join(blocks)


def build_messages(projected: dict) -> list[dict]:
    """Assemble the system/user message pair for the generation call."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": serialize_projection(projected)},
    ]





if __name__ == "__main__":
    # NOTE: For testing purposes only
    # Test rendering a full projected record into the user prompt body, using the test projected selectionJSON file as input.

    filename =  "../test_data/projected_selection.json"
    with open(filename) as f:
        projected = json.load(f)

    serialized_projection = serialize_projection(projected)
    print(serialized_projection)

    # Save the user prompt body to a text file for inspection
    with open("../test_data/serialized_projection.txt", "w") as f:
        f.write(serialized_projection)