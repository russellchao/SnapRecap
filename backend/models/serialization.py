"""Text serialization of a projected recap record into the user-prompt body.

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
  - Resolved outcome facts (lead change, turnover direction) are phrased by Python
    on the `result` line so the model never derives them from raw flags or score math.
"""

from __future__ import annotations
import json
import re


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

# Leading game clock as printed by nflfastR: "(9:01)", "(:59)", "(14:18)".
_CLOCK_RE = re.compile(r"^\s*\((\d{0,2}):(\d{2})\)\s*")
# A jersey-number + initial + surname token inside a desc: "17-J.Allen", "3-J.Meyers".
# The initial may be two letters when nflfastR disambiguates shared initials ("An.Johnson").
_PLAYER_TOKEN_RE = re.compile(r"\d{1,2}-([A-Z][a-z]?)\.([A-Za-z'\-]+)")


def _split_clock(desc: str) -> tuple[str | None, str]:
    """Pull a leading (M:SS) clock off a desc; return (clock or None, remaining desc)."""
    if not desc:
        return None, desc
    m = _CLOCK_RE.match(desc)
    if not m:
        return None, desc
    return f"{int(m.group(1) or 0)}:{m.group(2)}", desc[m.end():]


def _derived_clock(facts: dict) -> str | None:
    """Fallback quarter clock from game_seconds_remaining (regulation quarters only)."""
    gsr, qtr = facts.get("game_seconds_remaining"), facts.get("qtr")
    if gsr is None or qtr is None or not (1 <= qtr <= 4):
        return None
    secs = gsr - (4 - qtr) * 900
    return f"{secs // 60}:{secs % 60:02d}" if 0 <= secs <= 900 else None


def _resolved_roles(facts: dict) -> list[str]:
    """Full names resolved upstream (passer/rusher/receiver), used to expand desc tokens."""
    return [facts[r] for r in ("passer", "rusher", "receiver") if facts.get(r)]


def _resolve_names(desc: str, facts: dict) -> str:
    """Expand `NN-X.Last` tokens: resolved roles -> full name; everyone else -> surname form `X.Last`."""
    roles = _resolved_roles(facts)

    def full_name(initial: str, surname: str) -> str | None:
        sl = surname.lower()
        for name in roles:
            parts = name.split()
            if parts and parts[0][:1] == initial[:1] and any(p.lower() == sl for p in parts[1:]):
                return name
        return None

    def repl(m: re.Match) -> str:
        initial, surname = m.group(1), m.group(2)
        return full_name(initial, surname) or f"{initial}.{surname}"

    return _PLAYER_TOKEN_RE.sub(repl, desc)


def _leader(diff: int | None, posteam: str | None, defteam: str | None) -> str | None:
    """Team ahead from a posteam-perspective differential; None if tied or unknown."""
    if diff is None:
        return None
    return posteam if diff > 0 else defteam if diff < 0 else None


def _lead_change(facts: dict) -> str:
    """Qualitative lead change from the pre/post differential sign (PAT-robust, no digits)."""
    pos, dfn = facts.get("posteam"), facts.get("defteam")
    pre = _leader(facts.get("score_differential"), pos, dfn)
    post = _leader(facts.get("score_differential_post"), pos, dfn)
    if post is None:
        return "draws even"
    return f"{post} extends the lead" if post == pre else f"{post} takes the lead"


def _conversion_clause(facts: dict) -> str | None:
    """Down-conversion outcome, if this play settled a third or fourth down."""
    if facts.get("fourth_down_converted"):
        return "converted on 4th down"
    if facts.get("fourth_down_failed"):
        return "stopped on 4th down"
    if facts.get("third_down_converted"):
        return "converted on 3rd down"
    if facts.get("third_down_failed"):
        return "stopped on 3rd down"
    return None


def _result_line(facts: dict) -> str | None:
    """Resolved outcome facts, phrased by Python: turnover direction, lead change, conversion."""
    clauses = []
    if facts.get("interception"):
        clauses.append(f"{facts.get('defteam')} takes over on the interception")
    elif facts.get("fumble_lost"):
        rec = facts.get("fumble_recovery_1_team")
        lost = facts.get("fumbled_1_team")
        clauses.append(f"{lost} lost the ball, {rec} recovered" if rec else "ball lost on a fumble")
    if facts.get("sack"):
        clauses.append("quarterback sacked")
    if facts.get("touchdown"):
        clauses.append(f"touchdown — {_lead_change(facts)}")
    conv = _conversion_clause(facts)
    if conv:
        clauses.append(conv)
    return "; ".join(clauses) or None


def _situation_line(facts: dict, clock: str | None) -> str:
    """A compact, human-readable pre-snap game-state line derived from a play's facts."""
    parts = []
    if facts.get("qtr") is not None:
        parts.append(f"Q{facts['qtr']} {clock}" if clock else f"Q{facts['qtr']}")

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
    """Render one projected play: situation, name-resolved description, resolved result, context, emphasis."""
    facts = play.get("facts", {})
    clock, desc = _split_clock(facts.get("desc") or "")
    clock = clock or _derived_clock(facts)

    lines = [f"- {_situation_line(facts, clock)}"]

    if desc:
        lines.append(f"{_INDENT}play: {_resolve_names(desc, facts)}")

    result = _result_line(facts)
    if result:
        lines.append(f"{_INDENT}result: {result}")

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


if __name__ == "__main__":
    # NOTE: For testing purposes only.
    # Render a full projected record into the user prompt body, using the test
    # projected selection JSON file as input.

    filename = "../test_data/projected_selection.json"
    with open(filename) as f:
        projected = json.load(f)

    serialized_projection = serialize_projection(projected)

    with open("../test_data/serialized_projection.txt", "w") as f:
        f.write(serialized_projection)
    print("Serialized projection saved to ../test_data/serialized_projection.txt")