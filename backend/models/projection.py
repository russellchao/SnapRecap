from dataclasses import dataclass

from selection import SelectedPlay, Section, NEGATIVE_SIGNALS

# --- Descriptive fields (pre-snap + in-play) ---
# Descriptive only; the prompt forbids evaluating them (no league baseline).
_PRESNAP = (
    "offense_personnel_package", "offense_formation",
    "defenders_in_box", "number_of_pass_rushers",
    "defense_coverage_type", "defense_man_zone_type",
    "shotgun", "no_huddle",
)
_INPLAY = (
    "pass_location", "pass_length", "air_yards", "yards_after_catch",
    "run_location", "run_gap", "route", "time_to_throw", "was_pressure",
)
_ANNOTATIONS = _PRESNAP + _INPLAY

# --- Raw play facts. epa/qb_epa/wpa and `success` deliberately excluded. ---
_FACTS = (
    "qtr", "game_seconds_remaining", "down", "ydstogo", "yardline_100",
    "goal_to_go", "score_differential", "wp",
    "posteam", "defteam", "play_type",
    "yards_gained", "first_down",
    "third_down_converted", "third_down_failed",
    "fourth_down_converted", "fourth_down_failed",
    "touchdown", "sack", "interception", "fumble_lost", "penalty",
    "passer", "rusher", "receiver", "desc",
)

# Outcome flags that only carry meaning when True; omit otherwise.
_POSITIVE_ONLY = {
    "first_down", "third_down_converted", "third_down_failed",
    "fourth_down_converted", "fourth_down_failed",
    "touchdown", "sack", "interception", "fumble_lost", "penalty",
}

ANCHOR_REASON = "anchor"          # reasons-dict key holding an anchor's WPA
ANCHOR_TIER_CUTS = ((0.20, "decisive"), (0.10, "major"))
ANCHOR_TIER_FLOOR = "notable"


def _present(play, fields) -> dict:
    """Pull `fields` off a Play, dropping None (and falsy positive-only flags)."""
    out = {}
    for f in fields:
        v = getattr(play, f)
        if v is None or (f in _POSITIVE_ONLY and not v):
            continue
        out[f] = v
    return out


def _anchor_tier(reasons: dict) -> str | None:
    """Coarsen an anchor's WPA magnitude into a significance tier."""
    wpa = reasons.get(ANCHOR_REASON)
    if wpa is None:
        return None
    swing = abs(wpa)
    for cut, label in ANCHOR_TIER_CUTS:
        if swing >= cut:
            return label
    return ANCHOR_TIER_FLOOR


def render_play(selected: SelectedPlay) -> dict:
    """Project one SelectedPlay into a role-separated record for the LLM."""
    play = selected.play
    record = {
        "facts": _present(play, _FACTS),
        "selection": {"reasons": selected.reasons},
        "annotations": _present(play, _ANNOTATIONS),
    }
    tier = _anchor_tier(selected.reasons)
    if tier is not None:
        record["selection"]["tier"] = tier
    return record


# --- Divergence significance tiers, on the gap/threshold ratio (cross-signal comparable). ---
# Placeholder cuts pending real divergence-distribution analysis, as with DEFAULT_THRESHOLDS.
DIVERGENCE_TIER_CUTS = ((2.5, "decisive"), (1.6, "major"))
DIVERGENCE_TIER_FLOOR = "notable"


def _divergence_tier(gap: float, threshold: float) -> str:
    """Coarsen a section's gap (as multiples of its firing threshold) into a tier."""
    ratio = gap / threshold
    for cut, label in DIVERGENCE_TIER_CUTS:
        if ratio >= cut:
            return label
    return DIVERGENCE_TIER_FLOOR


def _favored(section: Section) -> str:
    """The team that comes out better on this signal (min for lower-is-better signals)."""
    chooser = min if section.signal in NEGATIVE_SIGNALS else max
    return chooser(section.team_values, key=section.team_values.get)


def render_section(section: Section, thresholds: dict[str, float]) -> dict:
    """Project a fired Section: signal identity, divergence significance, ranked exemplar records."""
    return {
        "signal": section.signal,
        "divergence": {
            "team_values": section.team_values,
            "favored": _favored(section),
            "tier": _divergence_tier(section.gap, thresholds[section.signal]),
        },
        "plays": [render_play(sp) for sp in section.plays],
    }