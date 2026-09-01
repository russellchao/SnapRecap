# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

SnapRecap turns an NFL game's play-by-play data into a structured, explorable recap. A React/Vite
frontend lists games (pulled directly from ESPN's public APIs in the browser) and renders a per-game
recap page; a FastAPI backend converts nflverse play-by-play into three components — a **game
ledger** (EPA margin decomposed by category), **anchor plays** (the handful of biggest swings), and
**team signals** (per-team efficiency/tendency stats) — caches them in Supabase, and serves them.

The LLM feature is **Q&A**: the user asks a question on the recap page, Claude routes it to the
relevant components, and Claude phrases an answer from Python-supplied data only.

`selection.py`, `projection.py`, `serialization.py`, `prompt.py`, `recap.py`, and
`generate_recap.py` no longer exist; do not resurrect them from stale docs.

`backend/README.md` is **out of date** (it still describes the removed prompt pipeline and
`generate_recap.py`). Trust this file over it.

## Architecture

### Backend components (`backend/`)

Each stage has a single responsibility and a locked output shape, so a downstream stage only ever
depends on the previous stage's dataclass:

1. **`get_data/get_raw_data.py`** — `get_pbp_data(season, game_id)` downloads a season of
   play-by-play from `nflreadpy` and filters to one `game_id`. Returns a DataFrame, or an
   `{"Error": ...}` dict when data isn't available yet (callers check `isinstance(x, pd.DataFrame)`).
2. **`get_data/preprocess_data.py`** — `clean(df)` drops the long lists of unused columns. One
   cleaned DataFrame out.
3. **`models/play.py`** — `Play` dataclass, one per row. Holds **raw contextual values only**;
   every coercion is NaN-safe (`_int`/`_float`/`_bool`/`_str`). Situational labels are derived
   downstream, never stored here. `passer`/`rusher`/`receiver` are resolved from gsis ids to full
   display names via `get_player_full_name()`, which queries the Supabase `players` table over
   SQLAlchemy (`DATABASE_URL`) — cached with `lru_cache`, but note this means building `Play`
   records **requires DB access**.
4. **`models/game_document.py`** — `GameDocument` = `GameHeader` + all plays. This is the
   **lossless intermediate** and the handoff boundary: it filters nothing and aggregates nothing;
   all three components are built from this object, never the source DataFrame.
5. **`models/game_ledger.py`** — `build_ledger(doc)` decomposes the game's EPA margin into fixed
   categories (`turnovers`, `pass_protection`, `penalties`, `special_teams`, `red_zone`,
   `third_down`, `explosive_plays`, `other`). Sign convention is `diff = home_ep - away_ep`. Order
   in `LEDGER_CATEGORIES` is **claim priority**: every play with a valid `posteam` is claimed by
   exactly one category, so `categorized_diff == total_epa_diff` is an accounting identity, not an
   approximation — a mismatch is a real bug. `epa_vs_score_gap` (EPA margin vs actual score margin)
   is a **diagnostic only** and is expected to be nonzero; don't chase it to zero. Turnovers and
   pass-protection plays credit the defense (`credit_defense=True`).
6. **`models/team_signals.py`** — holds two layers. Bottom: the signal *reductions* over a list of
   `Play` (`f(plays) -> value`) returning `RateSignal`/`MeanSignal`, which carry `attempts`/`n` so
   small samples aren't mistaken for meaningful ones; the same reduction works on one game or a
   whole season (league baseline). `team_signal_record(plays, team)` collects them into one flat
   record per team — the team's own offense plus `sacks_forced`, the single defensive reduction
   kept. Top: `TeamSignals.build(doc)`, the component, which resolves teams from the plays
   (`teams_in`) rather than the header and gives each one a record. `to_db_item()` emits one row
   per team (`game_id`, `team`, `signals`), away row first. (There is no separate `signals.py` —
   it was folded into this module; don't resurrect it from stale docs.)
7. **`models/anchor_plays.py`** — `AnchorPlayList.build(doc)` ranks plays by `|wpa|` scaled by a
   convex recency weight (`_recency_weight`: regulation runs 0.5→1.0, OT 1.0→1.3, exponent 3), keeps
   at most one candidate per drive, and takes the top `MAX_ANCHORS` (5). Deliberately **not** gated
   by garbage time. `to_db_item()` emits DB rows whitelisted to on-field descriptive fields plus
   `wpa` (kept for debugging; filtered back out before it reaches the model).
8. **`get_recap.py`** — the orchestrator and the cache layer. `get_recap(...)` looks each of the
   three components up in Supabase (`game_ledgers`, `anchor_plays`, `team_signals`) and builds only
   what's missing, inserting it as it goes. A lookup *exception* is treated the same as a cache miss
   (rebuild rather than fail the request). `team_signals` is only considered cached when **both**
   team rows are present. Building anything requires a `GameDocument`, so a single miss pays for the
   full download + preprocess.
9. **`game_qa.py`** — the Q&A layer, and the only place an LLM is called. Two calls, both
   `claude-sonnet-5`: `route_question()` uses forced tool use (`select_components`) to pick a subset
   of `{ledger, anchor_plays, team_signals}`, validating the result and raising
   `RoutingValidationError` on anything unexpected — an empty list means out of scope and callers
   short-circuit to `OUT_OF_SCOPE_RESPONSE` without a second call. `fetch_qa_payload()` shapes only
   the routed components through their `_shape_*` contracts, and `answer_question()` phrases 2–4
   sentences from that payload alone. **Python owns retrieval and grounding; the LLM owns phrasing
   only** — selection/value metrics (`wpa`, `epa`, `qb_epa`, `cpoe`, `wp`) are whitelisted out of
   the payload by `ANCHOR_PLAY_FIELDS` and never reach the model.
10. **`get_data/load_players.py`** — full refresh of the `players` table (`gsis_id`,
    `display_name`, `headshot`) from `nflreadpy.load_players()`, TRUNCATE + append over
    `DATABASE_URL`. **Run manually only** (`python load_players.py` from `backend/get_data/`),
    typically right before the start of a season — it is not exposed as an endpoint and is not on a
    scheduler. Exists because PBP data carries only initials + last name; display names are
    what keep player names out of hallucination territory.

### FastAPI app (`backend/main.py`)

- `GET /health` → `{"status": "ok"}`.
- `GET /get_recap/{season}/{week}/{away_team}/{home_team}/{away_score}/{home_score}/` — builds the
  nflverse `game_id` from the path parts and returns `{game_ledger, anchor_plays, team_signals}` via
  `get_recap()`.
- `POST /ask_question` — body is `{question, game_ledger, anchor_plays, team_signals}`. The
  frontend **passes the components it already holds** from the `/get_recap` call rather than having
  the backend refetch them. Routes → shapes → answers; a `RoutingValidationError` becomes a 502.

There is **no** player-refresh endpoint: `load_players.py` is a manual script (see above).

CORS allows the single `FRONTEND_URL` origin.

### Supabase tables

`players` (`gsis_id`, `display_name`, `headshot`), `game_ledgers` (keyed by `game_id`),
`anchor_plays` (composite `game_id` + `play_id`), `team_signals` (composite `game_id` + `team`,
one row per team, written from `TeamSignals.to_db_item()`). `players` is written via SQLAlchemy/`DATABASE_URL`; the three recap
tables via the `supabase` client (`SUPABASE_URL`/`SUPABASE_KEY`).

### Frontend (`frontend/`)

React 19 + Vite + react-router. Routes in [App.jsx](frontend/src/App.jsx): `/games`,
`/recap/:season/:week/:away_team/:home_team`, `/about` (everything else redirects to `/games`).

- `src/api/fetch_games.js` calls **ESPN's CDN API directly from the browser** — the backend is not
  involved in listing games. Only `fetchGamesByWeekOnly` is implemented; `fetchGamesByTeamOnly` and
  `fetchGamesByTeamAndWeek` are stubs.
- `src/api/fetch_recap.js` and `src/api/fetch_qa.js` are the only calls to our backend, both against
  `VITE_API_BASE_URL`. Each keeps an **in-flight map** (keyed by URL / question text) so StrictMode's
  double effects and double-clicks can't pay twice for an expensive build or LLM call. Both resolve
  to `{status, data}` instead of throwing; `status: 0` means the request never reached the server.
- `pages/Games.jsx` owns `TEAM_ABBR` (full display name → nflverse abbreviation) and navigates to
  the recap route, passing the whole `Game` object via **router state**. A hard refresh on a recap
  URL loses that state, and the page falls back to a "back to games" prompt.
- `pages/Recap.jsx` fetches the three components and renders `GameLedger`, `AnchorPlays`,
  `TeamSignals`, and `AskAboutGame`; each section renders only if its own data came back.
- `components/SectionHead.jsx` is the shared heading + collapsible "About" banner for recap sections.
- `theme/team_colors.js` maps nflverse abbreviations to brand colors and returns the
  `--rc-home`/`--rc-away` overrides the sections paint from; it lifts too-dark colors for contrast
  against the near-black surfaces and falls back to a secondary color when both teams share a hue.
- Team logos live in `src/logos/` keyed by full display name and are loaded with `import.meta.glob`.

Signal chips read `signals[abbr].signals` — the backend returns the **DB row** per team
(`{game_id, team, signals}`), not the bare signal record.

## Running things

The import style differs by entry point — **the working directory matters**:

- **API server** (from `backend/`): `uvicorn main:app --reload`
  (`main.py` imports `get_recap` and `game_qa` as top-level modules, so it must run
  from `backend/`, *not* the repo root.)
- **Player refresh** (from `backend/get_data/`): `python load_players.py` — manual, on demand.
- **Frontend** (from `frontend/`): `npm install`, then `npm run dev` / `npm run build` /
  `npm run lint`.

Python deps are in the repo-root [requirements.txt](requirements.txt) (fastapi, uvicorn, nflreadpy,
pandas, pyarrow, anthropic, python-dotenv, sqlalchemy, psycopg2-binary, supabase).

## Testing each layer

There is no test framework. Each backend module has an `if __name__ == "__main__"` block that runs
that layer in isolation, reading the previous stage's artifact from `backend/test_data/` and writing
its own. **These blocks use relative paths (`../test_data/...`) and import siblings directly, so
they must be run from inside their own directory:**

- From `backend/get_data/`: `python get_raw_data.py <season> <week> <away> <home>` → writes
  `pbp_data.csv`; then `python preprocess_data.py` → `preprocessed_data.csv`.
- From `backend/models/`: `python play.py` (reads `preprocessed_data.csv`),
  `python game_document.py` → `game_document.json`, then the three component builders, which each
  read `game_document.json`: `python game_ledger.py` → `game_ledger.json`,
  `python anchor_plays.py` → `anchor_plays.json`, `python team_signals.py` → `team_signals.json`.

Each stage consumes the artifact the previous one wrote, so regenerate them in order after changing
an upstream layer. `play.py` hits the `players` table, so even the standalone blocks need
`DATABASE_URL`.

**Imports in `models/`:** every module uses the dual-import pattern (`try: from .play import ...`
/ `except ImportError:` insert `__file__`'s dir on `sys.path`), so each one imports cleanly both as
a package member and as a standalone script, in any order. Keep the guard on any new module here —
the package used to depend on an accidental side effect (`game_document` importing the old
`signals.py`, whose own bare import failed and put `models/` on `sys.path` for everyone else), and
that prop is gone.

`asdict` flattens the nested dataclasses for JSON serialization, so reloading a saved
`GameDocument` requires rebuilding the dataclass types from dicts — see the `document_from_dict`
helper in the `__main__` blocks of `anchor_plays.py` and `team_signals.py`.

## Environment variables

- Backend (`backend/.env`, loaded with `python-dotenv`; `play.py` and `load_players.py` resolve the
  path relative to `__file__` so they work from any working directory):
  `FRONTEND_URL` (CORS origin), `DATABASE_URL` (Postgres/Supabase, for the `players` table),
  `SUPABASE_URL` + `SUPABASE_KEY` (recap component cache), `ANTHROPIC_API_KEY` (Q&A).
- Frontend (`frontend/.env`): `VITE_API_BASE_URL`.
