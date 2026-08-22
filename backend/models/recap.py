"""
Recap phrasing layer for Snap Recap.

Owns the boundary between analytical output (selection.py's anchor plays,
game_ledger.py's categorized ledger) and the LLM's phrasing layer. Python
decides everything about *what* matters; the LLM decides only *how to say
it*. The LLM never sees WPA/EPA numbers used for selection or category
priority — it sees a play description, situational context, and the
category name it was attributed to, and returns two short strings.

This module is pure: build payloads, call the LLM, validate, return
captions. MODEL / PROMPT_VERSION are exposed as constants so get_recap.py
can compare them against a cached row's stored values without duplicating
the version strings.

--- Output shape ---
One recap per game: [{play_id, seen, said}, ...], one object per anchor
play, in the same order selection.py produced them.

`seen`  = the surface-level story a casual viewer would take from the
          play on its own (what commentary would say in the moment).
`said`  = the analytically-grounded explanation of why it actually
          mattered, referencing the game_ledger category it was
          attributed to.

--- Validation ---
Python never trusts the LLM's array positionally or blindly. The model
must echo back play_id per object; before captions are returned, the set
of returned play_ids is checked against the set of input play_ids. Any
mismatch (dropped anchor, reordered without matching ids, hallucinated
id) is a hard failure — get_recap.py must not write to recap_cache when
this raises.
"""

from __future__ import annotations

import json
import os
import sys
from functools import lru_cache
from typing import Dict, List
import anthropic

try:
    from .selection import SelectedPlay
except ImportError:
    sys.path.insert(0, os.path.dirname(__file__))
    from selection import SelectedPlay



# --- Cache identity constants -------------------------------------------
# get_recap.py compares a cached row's stored model/prompt_version against
# these before treating it as a hit. Bump PROMPT_VERSION by hand any time
# the prompt template text or output contract below changes — nothing
# enforces this automatically.
MODEL = "claude-sonnet-5"
PROMPT_VERSION = "v1"


class RecapValidationError(Exception):
    """Raised when the LLM's response fails the play_id integrity check.

    get_recap.py must not upsert recap_cache when this is raised.
    """


# --- Payload construction -------------------------------------------------

def _anchor_payload(anchor: SelectedPlay, category: str) -> Dict:
    """Builds the per-anchor JSON object handed to the LLM.

    Deliberately excludes anchor_wpa and any other selection-time metric —
    those drove *which* plays were chosen, not what the LLM should say
    about them. Including them would blur the significance/phrasing
    boundary by tempting the LLM to reason about magnitude itself.
    """
    p = anchor.play
    return {
        "play_id": p.play_id,
        "desc": p.desc,
        "posteam": p.posteam,
        "qtr": p.qtr,
        "game_seconds_remaining": p.game_seconds_remaining,
        "category": category,
    }


def build_payloads(
    anchors: List[SelectedPlay], play_category_map: Dict[int, str]
) -> List[Dict]:
    return [
        _anchor_payload(a, play_category_map.get(a.play.play_id, "other"))
        for a in anchors
    ]


# --- Prompt construction -------------------------------------------------

_SYSTEM_PROMPT = """You are a phrasing layer for an NFL game recap tool. You will \
receive a JSON array of "anchor plays" from a single game, each already \
identified as analytically significant by an upstream system — you are not \
deciding what matters, only how to describe it.

For each anchor play, write two short strings:

- "seen": the surface-level story a casual viewer would take away from this \
play in isolation — what a broadcast announcer might say in the moment. \
Base this only on the play description and situational context given.
- "said": the analytically-grounded explanation of why this play mattered, \
referencing its "category" field explicitly (e.g. "this was part of a \
pass_protection breakdown that swung the game"). Do not invent statistics \
not present in the input.

Do not reorder, drop, merge, or invent anchor plays. Return exactly one \
object per input anchor, echoing its play_id unchanged.

Respond with ONLY a JSON array, no preamble, no markdown fences:
[{"play_id": <int>, "seen": "<string>", "said": "<string>"}, ...]
"""


def _build_user_message(payloads: List[Dict]) -> str:
    return json.dumps(payloads)


# --- LLM call --------------------------------------------------------------

@lru_cache(maxsize=1)
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def _call_llm(payloads: List[Dict]) -> str:
    response = _client().messages.create(
        model=MODEL,
        max_tokens=2000,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_user_message(payloads)}],
        output_config={"effort": "medium"},
    )
    return "".join(
        block.text for block in response.content if block.type == "text"
    )


# --- Validation --------------------------------------------------------------

def _parse_and_validate(raw_text: str, input_play_ids: List[int]) -> List[Dict]:
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise RecapValidationError(f"LLM response was not valid JSON: {e}") from e

    if not isinstance(parsed, list):
        raise RecapValidationError(
            f"Expected a JSON array, got {type(parsed).__name__}"
        )

    returned_ids = []
    for i, obj in enumerate(parsed):
        if not isinstance(obj, dict) or "play_id" not in obj:
            raise RecapValidationError(f"Malformed caption object at index {i}: {obj}")
        returned_ids.append(obj["play_id"])

    if set(returned_ids) != set(input_play_ids):
        raise RecapValidationError(
            "play_id mismatch between input anchors and LLM response — "
            f"input={input_play_ids}, returned={returned_ids}"
        )

    return parsed


# --- Entry point -------------------------------------------

def generate_captions(
    anchors: List[SelectedPlay], play_category_map: Dict[int, str]
) -> List[Dict]:
    """Returns [{play_id, seen, said}, ...] for the given anchor plays.

    Pure function: one LLM call, then validation. Does not touch the DB —
    get_recap.py is responsible for checking recap_cache before calling
    this, and for upserting the result after. Raises RecapValidationError
    on a failed validation; callers must not write to cache in that case.
    """
    input_play_ids = [a.play.play_id for a in anchors]
    payloads = build_payloads(anchors, play_category_map)
    raw_text = _call_llm(payloads)
    return _parse_and_validate(raw_text, input_play_ids)




if __name__ == "__main__":
    # NOTE: For testing purposes only.
    # Build the GameDocument object from "game_document.json" in "../test_data",
    # where it will then build the anchors and play_category_map to test the caption generation for the recap

    from dotenv import load_dotenv
    from pathlib import Path

    from game_document import GameDocument, GameHeader, TeamSignals
    from play import Play
    from selection import RecapSelection
    from game_ledger import build_ledger

    # The API key lives in backend/.env; the module itself stays env-agnostic.
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    # ------- Test Helper Functions -------
    # GameDocument reconstruction from its to_dict()/JSON form. `asdict` flattens
    # every nested dataclass into a plain dict, so loading a saved document means
    # rebuilding those types from the dicts (same helpers as selection.py).

    def _signal_from_dict(value: dict):
        """Rebuild one signal value, recovering the type `asdict` erased."""
        from signals import RateSignal, MeanSignal
        keys = set(value.keys())
        if keys == {"attempts", "successes", "rate"}:
            return RateSignal(**value)
        if keys == {"n", "mean"}:
            return MeanSignal(**value)
        return value  # distribution dict (or empty {})

    def _team_signals_from_dict(value: dict) -> TeamSignals:
        return TeamSignals(
            offense={name: _signal_from_dict(v) for name, v in value["offense"].items()},
            defense={name: _signal_from_dict(v) for name, v in value["defense"].items()},
        )

    def document_from_dict(raw: dict) -> GameDocument:
        """Rebuild a GameDocument from its `to_dict()` / JSON form."""
        return GameDocument(
            header=GameHeader(**raw["header"]),
            signals={team: _team_signals_from_dict(ts) for team, ts in raw["signals"].items()},
            plays=[Play(**p) for p in raw["plays"]],
        )

    # ------- Step 0: Load the saved game document JSON and rebuild it -------
    game_doc_json = "../test_data/game_document.json"
    with open(game_doc_json) as f:
        raw = json.load(f)

    document = document_from_dict(raw)
    print(f"Rebuilt GameDocument for {document.header.game_id}: "
          f"{len(document.plays)} plays, teams {list(document.signals.keys())}")

    # ------- Step 1: Anchors and the play -> category attribution -------
    anchors = RecapSelection.build(document).anchors
    _, play_category_map = build_ledger(document)
    print(f"\n{len(anchors)} anchor(s) to caption:\n")
    for a in anchors:
        p = a.play
        category = play_category_map.get(p.play_id, "other")
        print(f"  [{p.play_id}] q{p.qtr} {p.posteam} ({category})  {(p.desc or '')[:80]}")

    # ------- Step 2: Generate and validate the captions -------
    print(f"\nCalling {MODEL} (prompt {PROMPT_VERSION})...\n")
    try:
        captions = generate_captions(anchors, play_category_map)
    except RecapValidationError as e:
        print(f"Validation failed, no captions returned: {e}")
        sys.exit(1)

    for c in captions:
        print(f"[{c['play_id']}]")
        print(f"  seen: {c.get('seen')}")
        print(f"  said: {c.get('said')}\n")

    # ------- Step 3: Save for inspection -------
    captions_json_filename = "../test_data/recap_captions.json"
    with open(captions_json_filename, "w") as f:
        json.dump(captions, f, indent=2)
    print(f"Captions saved to {captions_json_filename}")
