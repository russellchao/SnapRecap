from dataclasses import dataclass
import json

from selection import SelectedPlay, Section, RecapSelection, NEGATIVE_SIGNALS
from game_document import GameHeader
from play import Play

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


# ------- Game context -------

_HEADER_FACTS = ("season", "week", "away_team", "home_team", "away_score", "home_score")

def _outcome(header: GameHeader) -> dict | None:
    """Winner and margin from final scores; None until scores are sourced."""
    away, home = header.away_score, header.home_score
    if away is None or home is None:
        return None
    if away == home:
        return {"result": "tie", "margin": 0}
    winner = header.home_team if home > away else header.away_team
    return {"winner": winner, "margin": abs(home - away)}

def render_context(header: GameHeader) -> dict:
    """Project the game header: identity, final score, and derived outcome."""
    record = {"facts": {f: getattr(header, f) for f in _HEADER_FACTS if getattr(header, f) is not None}}
    outcome = _outcome(header)
    if outcome is not None:
        record["outcome"] = outcome
    return record


# ------- Assembly -------

def render_selection(selection: RecapSelection) -> dict:
    """Project a full RecapSelection into the LLM-ready record, preserving each bucket's order."""
    return {
        "context": render_context(selection.header),
        "sections": [render_section(s, selection.thresholds) for s in selection.sections],
        "anchors": [render_play(sp) for sp in selection.anchors],
        "scores_and_turnovers": [render_play(sp) for sp in selection.always_include],
    }





if __name__ == "__main__":
    #NOTE: For testing purposes only
    # Test projecting a full RecapSelection into the LLM-ready record


    # ------- Test Helper Functions -------
    # RecapSelection reconstruction from its to_dict()/JSON form.
    # `asdict` flattens every nested dataclass into a plain dict, so loading a
    # saved selection means rebuilding those types from the dicts.

    def _selected_play_from_dict(raw: dict) -> SelectedPlay:
        return SelectedPlay(play=Play(**raw["play"]), reasons=raw["reasons"])

    def _section_from_dict(raw: dict) -> Section:
        return Section(
            signal=raw["signal"],
            team_values=raw["team_values"],
            gap=raw["gap"],
            plays=[_selected_play_from_dict(sp) for sp in raw["plays"]],
        )

    def selection_from_dict(raw: dict) -> RecapSelection:
        """Rebuild a RecapSelection from its `to_dict()` / JSON form."""
        return RecapSelection(
            header=GameHeader(**raw["header"]),
            thresholds=raw["thresholds"],
            sections=[_section_from_dict(s) for s in raw["sections"]],
            anchors=[_selected_play_from_dict(sp) for sp in raw["anchors"]],
            always_include=[_selected_play_from_dict(sp) for sp in raw["always_include"]],
        )


    # ------- Load the saved selection JSON and rebuild it into a RecapSelection -------
    selection_json = "../test_data/selection.json"
    with open(selection_json) as f:
        raw = json.load(f)

    selection = selection_from_dict(raw)
    print(f"Rebuilt RecapSelection for {selection.header.game_id}: "
          f"{len(selection.sections)} section(s), {len(selection.anchors)} anchor(s), "
          f"{len(selection.always_include)} score(s)/turnover(s)")


    # ------- Project the selection into the LLM-ready record and save it to JSON -------
    projected = render_selection(selection)
    projected_json_filename = "../test_data/projected_selection.json"
    with open(projected_json_filename, "w") as f:
        json.dump(projected, f, indent=2)
    print(f"Projected selection saved to {projected_json_filename}")
    