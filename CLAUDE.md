# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

SnapRecap generates LLM-written recaps of NFL games. A React/Vite frontend lists games (pulled
directly from ESPN's public APIs in the browser) and links to per-game recap pages; a FastAPI
backend turns nflverse play-by-play data into a structured, prompt-ready selection of the game's
most narratively important plays. The recap-generation pipeline is the heart of the project and is
built layer by layer (the LLM prompt step itself is not implemented yet).

## Architecture

### Backend recap pipeline (`backend/`)

The pipeline is a linear sequence of transforms, orchestrated by
[generate_recap.py](backend/generate_recap.py). Each stage has a single responsibility and a
locked output shape, so a downstream stage only ever depends on the previous stage's dataclass:

1. **`get_data/get_raw_data.py`** — downloads play-by-play data for one game from
   `nflreadpy`, filtered by season/week/teams. Returns a DataFrame, or an `{"Error": ...}` dict
   when data isn't available yet (callers check `isinstance(x, pd.DataFrame)`).
2. **`get_data/preprocess_data.py`** — drops the long lists of unused columns. One cleaned
   DataFrame out.
3. **`models/play.py`** — `Play` dataclass, one per row. Holds **raw contextual values only**;
   every coercion is NaN-safe (`_int`/`_float`/`_bool`/`_str`). Situational labels are derived
   downstream, never stored here.
4. **`models/signals.py`** — reductions over a list of `Play` (`f(plays) -> value`). Returns
   `RateSignal`/`MeanSignal` (which carry `n`/attempts so small samples aren't mistaken for
   meaningful ones). `team_signals` produces one flat record per team — the team's own offense
   plus `sacks_forced`, the single defensive reduction kept. The same reduction works on one game
   or a whole season (league baseline).
5. **`models/game_document.py`** — `GameDocument` = header + per-team signals + all plays. This is
   the **lossless intermediate** and the handoff boundary: it filters nothing; everything
   downstream works from this object, never the source DataFrame.
6. **`models/selection.py`** — `RecapSelection.build()` projects a `GameDocument` into selected,
   prompt-relevant plays via three steps: fire **sections** where two offenses diverge on an
   efficiency signal past a per-signal threshold (`DEFAULT_THRESHOLDS`); rank each section's
   exemplar plays by EPA (gating garbage time via win-probability band) and pick dramatic
   **anchors** by |WPA| and **always-include** plays (TDs/turnovers); then dedupe across all
   sources by `play_id`, accumulating reasons (precedence: section > anchor > always-include).
7. **`models/projection.py`** — `render_selection()` flattens a `RecapSelection` into the
   LLM-ready record, separating each play into `facts` / `selection` / `annotations` roles and
   coarsening magnitudes into significance tiers. EPA/WPA/`success` are deliberately excluded from
   the descriptive fields the prompt is allowed to narrate.
8. **Prompt step** — TBD (step 6 in `generate_recap.py`, not yet built).

`asdict` flattens the nested dataclasses for JSON serialization, so reloading a saved
`GameDocument`/`RecapSelection` requires rebuilding the dataclass types from dicts — see the
`*_from_dict` helpers in the `__main__` blocks of `selection.py` and `projection.py`.

### FastAPI app (`backend/main.py`)

Currently only `/health` and a placeholder `/pbp/...` endpoint that reports whether PBP data
*exists* for a game (it does not yet serve generated recaps). CORS origin comes from the
`FRONTEND_URL` env var.

### Frontend (`frontend/`)

React 19 + Vite + react-router. Routes in [App.jsx](frontend/src/App.jsx): `/games`,
`/recap/:gameId`, `/about`. The games list (`src/api/fetch_games.js`) calls **ESPN's CDN API
directly from the browser** — the backend is not involved in listing games. `src/api/fetch_recap.js`
is the only call to our backend; it maps full team display names → nflverse abbreviations
(`TEAM_ABBR`) and hits `VITE_API_BASE_URL`. The `Game` object is passed to the recap page via
router state, so a hard refresh on `/recap/:gameId` loses it (handled gracefully).

## Running things

The import style differs by entry point — **the working directory matters**:

- **API server** (from repo root): `uvicorn backend.main:app --reload`
  (`main.py` imports `backend.get_data...`, so it must run from the repo root.)
- **Full pipeline** (from `backend/`): `python generate_recap.py <season> <week> <away> <home>`
  e.g. `python generate_recap.py 2024 19 BUF JAX` — teams are nflverse abbreviations.
- **Frontend** (from `frontend/`): `npm install`, then `npm run dev` / `npm run build` /
  `npm run lint`.

## Testing each layer

There is no test framework. Each backend module has an `if __name__ == "__main__"` block that runs
that layer in isolation, reading the previous stage's artifact from `backend/test_data/` and
writing its own. **These blocks use relative paths (`../test_data/...`) and import siblings
directly, so they must be run from inside their own directory:**

- From `backend/get_data/`: `python get_raw_data.py <season> <week> <away> <home>` → writes
  `pbp_data.csv`; then `python preprocess_data.py` → `preprocessed_data.csv`.
- From `backend/models/`: `python play.py` / `python signals.py` (read `preprocessed_data.csv`),
  `python game_document.py` → `game_document.json`, `python selection.py` → `selection.json`,
  `python projection.py` → `projected_selection.json`.

Each stage consumes the artifact the previous one wrote, so regenerate them in order after changing
an upstream layer. The model modules use a dual-import pattern (relative import when imported as a
package, direct import when run as `__main__`).

## Environment variables

- Backend: `FRONTEND_URL` (CORS allowed origin), loaded from a `.env` via `python-dotenv`.
- Frontend: `VITE_API_BASE_URL` (backend base URL).
