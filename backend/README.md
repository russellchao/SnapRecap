# SnapRecap Backend

The backend turns [nflverse](https://github.com/nflverse) play-by-play data into a structured,
prompt-ready selection of a game's most narratively important plays. It is the heart of SnapRecap:
the LLM-written recap is generated from the output of this pipeline (the final LLM generation call
itself is not implemented yet).

There are two entry points:

- A **recap pipeline** (`generate_recap.py` + `get_data/` + `models/`) that builds the selection
  layer by layer.
- A **FastAPI app** (`main.py`) that the frontend calls.

## Layout

```
backend/
├── generate_recap.py        # orchestrates the full pipeline end to end
├── main.py                  # FastAPI app (/health, placeholder /pbp/...)
├── get_data/
│   ├── get_raw_data.py      # download PBP + participation data from nflreadpy
│   └── preprocess_data.py   # drop unused columns, merge, derive personnel
├── models/
│   ├── play.py              # Play dataclass (one per PBP row, raw values only)
│   ├── signals.py           # reductions over plays (rates/means/distributions)
│   ├── game_document.py     # GameDocument: header + per-team signals + plays
│   ├── selection.py         # RecapSelection: pick prompt-relevant plays
│   ├── projection.py        # render_selection(): flatten to LLM-ready record
│   ├── serialization.py     # serialize_projection(): render the record as the prompt body
│   └── prompt.py            # SYSTEM_PROMPT + build_messages(): assemble the message pair
├── test_data/               # per-layer input/output artifacts (see Testing)
└── .env                     # FRONTEND_URL
```

## The recap pipeline

The pipeline is a linear sequence of transforms orchestrated by
[generate_recap.py](generate_recap.py). Each stage has a single responsibility and a locked output
shape, so a downstream stage only ever depends on the previous stage's dataclass.

1. **Download raw data** — [get_data/get_raw_data.py](get_data/get_raw_data.py) downloads
   play-by-play + participation data for one game from `nflreadpy`, filtered by season/week/teams.
   Returns a `DataFrame`, or an `{"Error": ...}` dict when data isn't available yet (callers check
   `isinstance(x, pd.DataFrame)`).
2. **Clean and merge** — [get_data/preprocess_data.py](get_data/preprocess_data.py) drops the long
   lists of unused columns, merges PBP + participation on `play_id`, and derives the normalized
   offensive personnel package (e.g. "11 Personnel"). One merged `DataFrame` out.
3. **Build the GameDocument** — [models/play.py](models/play.py) defines the `Play` dataclass (one
   per row, **raw contextual values only** — every coercion is NaN-safe; situational labels are
   derived downstream, never stored here). [models/signals.py](models/signals.py) defines
   reductions over a list of `Play` (`f(plays) -> value`) returning `RateSignal`/`MeanSignal`
   (which carry `n`/attempts so small samples aren't mistaken for meaningful ones) or distribution
   dicts. [models/game_document.py](models/game_document.py) assembles the `GameDocument` = header
   + per-team signals + all plays. This is the **lossless intermediate** and the handoff boundary:
   it filters nothing; everything downstream works from this object, never the source DataFrame.
4. **Build the RecapSelection** — [models/selection.py](models/selection.py) projects a
   `GameDocument` into selected, prompt-relevant plays in three steps: fire **sections** where two
   offenses diverge on an efficiency signal past a per-signal threshold (`DEFAULT_THRESHOLDS`);
   rank each section's exemplar plays by EPA (gating garbage time via win-probability band) and
   pick dramatic **anchors** by `|WPA|` and **always-include** plays (TDs/turnovers); then dedupe
   across all sources by `play_id`, accumulating reasons (precedence: section > anchor >
   always-include).
5. **Project to LLM-ready record** — [models/projection.py](models/projection.py)'s
   `render_selection()` flattens a `RecapSelection` into the LLM-ready record, separating each play
   into `facts` / `selection` / `annotations` roles and coarsening magnitudes into significance
   tiers. EPA/WPA/`success` are deliberately excluded from the descriptive fields the prompt is
   allowed to narrate.
6. **Serialize to the prompt body** — [models/serialization.py](models/serialization.py)'s
   `serialize_projection()` renders the projected record (a plain dict) into the plain-text body of
   the user prompt. It enforces the model-facing boundary by construction: selection machinery
   (raw `reasons`, `signal` keys, divergence `team_values`) is dropped, leaving only the coarsened
   emphasis tier; each signal is translated into a plain-language theme so metric jargon like
   `cpoe`/`epa_per_pass` never reaches the model; and attached context renders nested under the one
   play it belongs to (the only causal license the prompt is granted).
7. **Assemble the messages** — [models/prompt.py](models/prompt.py) owns the durable, cacheable
   `SYSTEM_PROMPT` (role + boundary rules, identical across every game) and `build_messages()`,
   which pairs it with the serialized body into the system/user message pair for the generation
   call. The final LLM generation call that consumes these messages is TBD (not yet built).

`asdict` flattens the nested dataclasses for JSON serialization, so reloading a saved
`GameDocument`/`RecapSelection` requires rebuilding the dataclass types from dicts — see the
`*_from_dict` helpers in the `__main__` blocks of `selection.py` and `projection.py`.

## FastAPI app

[main.py](main.py) currently exposes:

- `GET /health` — returns `{"status": "ok"}`.
- `GET /pbp/{season}/{week}/{away}/{home}` — placeholder that reports whether PBP data *exists*
  for a game (it does not yet serve generated recaps).

CORS origin comes from the `FRONTEND_URL` env var.

## Running things

The import style differs by entry point — **the working directory matters.**

- **API server** (from the repo root):

  ```
  uvicorn backend.main:app --reload
  ```

  (`main.py` imports `backend.get_data...`, so it must run from the repo root.)

- **Full pipeline** (from `backend/`):

  ```
  python generate_recap.py <season> <week> <away> <home>
  # e.g. python generate_recap.py 2025 19 BUF JAX
  ```

  Teams are nflverse abbreviations.

## Testing each layer

There is no test framework. Each module has an `if __name__ == "__main__"` block that runs that
layer in isolation, reading the previous stage's artifact from `test_data/` and writing its own.
**These blocks use relative paths (`../test_data/...`) and import siblings directly, so they must
be run from inside their own directory:**

- From `backend/get_data/`:

  ```
  python get_raw_data.py <season> <week> <away> <home>   # → pbp_data.csv + participation_data.csv
  python preprocess_data.py                              # → preprocessed_data.csv
  ```

- From `backend/models/`:

  ```
  python play.py            # reads preprocessed_data.csv
  python signals.py         # reads preprocessed_data.csv
  python game_document.py   # → game_document.json
  python selection.py       # → selection.json
  python projection.py      # → projected_selection.json
  python serialization.py   # → serialized_projection.txt
  ```

  (`prompt.py` is imported for message assembly and has no standalone `__main__` block.)

Each stage consumes the artifact the previous one wrote, so regenerate them in order after changing
an upstream layer. The model modules use a dual-import pattern (relative import when imported as a
package, direct import when run as `__main__`).

## Dependencies

The backend depends on `fastapi`, `uvicorn` (ASGI server), `pandas`, `numpy`, `nflreadpy`, and
`python-dotenv`.

## Environment variables

- `FRONTEND_URL` — CORS allowed origin, loaded from a `.env` via `python-dotenv`.
</content>
</invoke>
