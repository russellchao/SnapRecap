"""System prompt and generation call for NFL game recaps.

Owns the durable system prompt and the seam where it meets the per-game user body
(built by serialization.serialize_projection). The prompt/serialization split is
deliberate: the system prompt is the locked instruction contract — role + boundary
rules, identical across every game and therefore cacheable — while serialization
renders the per-game body.
"""

from __future__ import annotations
from pathlib import Path
import anthropic
from dotenv import load_dotenv

# Load backend/.env (ANTHROPIC_API_KEY) regardless of the working directory the
# script is run from. anthropic.Anthropic() then picks the key up from the env.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")


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
- Some players are identified only by an initial and surname, like "C.Bishop" or \
"T.White." That is not a full name — it is the only identification you have for that \
player. Refer to that player by surname alone ("Bishop"), and never turn the initial \
into a first name or guess what the first name might be. Players given to you with a \
full name are written with that name as given; do not reshape one player's name to \
match the fuller or shorter form of another.
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

Format:
- The input is organized for you, not as a template to copy. Headings group \
related findings; don't reproduce them as headings or labels — write flowing prose \
meant to be read start to finish.
- Findings grouped under one heading are facets of the same part of the game: \
weave them into one thread rather than covering each in turn, while giving each its \
own distinct point. A single grouping can hold contrasting stories for both teams, \
so don't assume a heading speaks for one side.
- You may choose the order you tell the game in and open wherever it's strongest, \
but cover every thread, and don't stitch separate parts of the game into a \
cause-and-effect chain the input doesn't support.
- Each play belongs in one place. When a play illustrates more than one thread, or \
also appears among the biggest swing plays or the scoring-and-turnover list, cover \
it once where it fits best and refer back briefly elsewhere instead of describing \
it again. Plays that appear only in those lists are the factual backbone — work \
them in as what happened.
- Let each finding's marked emphasis set its weight: the strongest gets the most \
room and the earliest place; the slightest earns a sentence, not a paragraph. \
Never state the emphasis itself.
- Lead with the game's defining dynamic, not the final score.

Tone:
- Write like a knowledgeable friend explaining, after the fact, why the game went \
the way it did — plain, direct, and conversational, never breathless or \
promotional.
- Prefer plain description over technical labels: say what a coverage or alignment \
did to the play rather than naming the scheme.
- Ground what you say in the concrete facts given — down, distance, field \
position, yardage, result — and use natural player and team names.
- Keep it tight. The recap should read in a couple of minutes; cut anything that \
doesn't earn its place, and add no color, emotion, or detail the input doesn't \
support.
"""


# ---------------------------------------------------------------------------
# Generation defaults (Sonnet 5). Swap the model to "claude-opus-4-8" to A/B.
#
# Sonnet 5 rejects sampling params (temperature/top_p/top_k); output tendency is
# steered by the system prompt and by `effort` instead. effort=medium steps down
# from Sonnet 5's high default — this is a phrasing layer, not a reasoning task —
# and is a real cost lever (it caps text + thinking spend, not just thinking depth).
# max_tokens is a hard ceiling over thinking PLUS output, not a per-request charge;
# set generously so adaptive thinking can't crowd out the recap and truncate it.
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_MAX_TOKENS = 6000
DEFAULT_EFFORT = "medium"


def build_messages(serialization: str) -> list[dict]:
    """Wrap the serialized user body as the single user turn (system is passed separately)."""
    return [{"role": "user", "content": serialization}]


def call_llm(
    messages: list[dict],
    *,
    system: str = SYSTEM_PROMPT,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    effort: str = DEFAULT_EFFORT,
    stream: bool = True,
) -> str:
    """Call the Anthropic API and return the full recap text (API key read from env)."""
    client = anthropic.Anthropic()
    params = dict(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
        extra_body={"output_config": {"effort": effort}},
    )

    if not stream:
        response = client.messages.create(**params)
        return "".join(b.text for b in response.content if b.type == "text")

    chunks: list[str] = []
    with client.messages.stream(**params) as response:
        for text in response.text_stream:
            print(text, end="", flush=True)
            chunks.append(text)
    print()
    return "".join(chunks)


def generate_recap(serialization: str, **kwargs) -> str:
    """Build the message payload from a serialized body and generate the recap."""
    return call_llm(build_messages(serialization), **kwargs)






if __name__ == "__main__":
    # NOTE: For testing purposes only.
    # Take the test serialized projection, generate the recap, and save it locally.

    serialized_projection = "../test_data/serialized_projection.txt"
    with open(serialized_projection) as f:
        serialization = f.read()

    recap = generate_recap(serialization)

    with open("../test_data/recap.txt", "w") as f:
        f.write(recap)
    print("\n\nRecap saved to ../test_data/recap.txt")