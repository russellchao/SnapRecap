# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

SnapRecap turns an NFL game's play-by-play data into a structured, explorable recap. A React/Vite
frontend lists games (pulled directly from ESPN's public APIs in the browser) and renders a per-game
recap page; a FastAPI backend converts nflverse play-by-play into three components — a **game
ledger** (EPA margin decomposed by category), **team signals** (per-team efficiency/tendency
stats), and **macro contexts** (three short phrased narratives) — caches them in Supabase, and
serves them. Those components are built two ways: lazily, on the first `/get_recap` request for a
game, and ahead of time by a scheduled tick (`build_pending_recaps.poll_and_recap()`, exposed as
`POST /poll_games`) that tracks finished games and builds their recaps as soon as nflverse
publishes the plays.

An LLM is called in exactly two places, and both keep the same boundary: **Python owns retrieval
and grounding; the LLM owns phrasing only.**

- **Macro contexts** (`models/macro_context.py`) — phrased once at ingest time and cached.
- **Q&A** (`game_qa.py`) — the user asks a question on the recap page, Claude routes it to the
  relevant components, and Claude phrases an answer from Python-supplied data only.

These modules no longer exist; do not resurrect them from stale docs: `selection.py`,
`projection.py`, `serialization.py`, `prompt.py`, `recap.py`, `generate_recap.py`,
`anchor_plays.py`, `signals.py`, and `get_data/get_raw_data.py` + `get_data/preprocess_data.py`
(merged into `get_data/get_pbp_data.py`). The anchor plays component is gone end to end — no
`anchor_plays` module, DB table, API field, router component, or frontend section. There is no
`backend/README.md`; the root [README.md](README.md) is the prose overview.

## Architecture

### Backend components (`backend/`)

Each stage has a single responsibility and a locked output shape, so a downstream stage only ever
depends on the previous stage's dataclass:

1. **`get_data/get_pbp_data.py`** — both halves of ingest in one module. `get_pbp_data(season,
   game_id)` downloads a season of play-by-play from `nflreadpy` and filters to one `game_id`,
   returning a DataFrame or an `{"Error": ...}` dict when data isn't available yet (callers check
   `isinstance(x, pd.DataFrame)`). `clean(df)` then drops the long lists of unused columns.
2. **`models/play.py`** — `Play` dataclass, one per row. Holds **raw contextual values only**;
   every coercion is NaN-safe (`_int`/`_float`/`_bool`/`_str`). Situational labels are derived
   downstream, never stored here. `passer`/`rusher`/`receiver` are resolved from gsis ids to full
   display names via `get_player_full_name()`, which queries the Supabase `players` table over
   SQLAlchemy (`DATABASE_URL`) — cached with `lru_cache`, but note this means building `Play`
   records **requires DB access**.
3. **`models/game_document.py`** — `GameDocument` = `GameHeader` + all plays. This is the
   **lossless intermediate** and the handoff boundary: it filters nothing and aggregates nothing;
   every component below is built from this object, never the source DataFrame.

#### Cached components (each has a `VERSION`, each is a DB table)

4. **`models/game_ledger.py`** (`VERSION`) — `build_ledger(doc)` decomposes the game's EPA margin
   into fixed categories (`turnovers`, `pass_protection`, `penalties`, `special_teams`, `red_zone`,
   `third_down`, `explosive_plays`, `other`). Sign convention is `diff = home_ep - away_ep`. Order
   in `LEDGER_CATEGORIES` is **claim priority**: every play with a valid `posteam` is claimed by
   exactly one category, so `categorized_diff == total_epa_diff` is an accounting identity, not an
   approximation — a mismatch is a real bug. `epa_vs_score_gap` (EPA margin vs actual score margin)
   is a **diagnostic only** and is expected to be nonzero; don't chase it to zero. Turnovers and
   pass-protection plays credit the defense (`credit_defense=True`).
5. **`models/team_signals.py`** (`VERSION`) — holds two layers. Bottom: the signal *reductions* over
   a list of `Play` (`f(plays) -> value`) returning `RateSignal`/`MeanSignal`, which carry
   `attempts`/`n` so small samples aren't mistaken for meaningful ones; the same reduction works on
   one game or a whole season (league baseline). `team_signal_record(plays, team)` collects them
   into one flat record per team — the team's own offense plus `sacks_forced`, the single defensive
   reduction kept. Top: `TeamSignals.build(doc)`, the component, which resolves teams from the plays
   (`teams_in`) rather than the header and gives each one a record. `to_db_item()` emits one row
   per team (`game_id`, `team`, `signals`, `version`), away row first.
6. **`models/macro_context.py`** (three independent prompt versions) — the phrasing layer for the
   three macro contexts, and the only LLM call outside `game_qa.py`. No routing step: what each
   prompt sees is already fixed by the projection that feeds it, so this is phrasing only.
   `phrase_winners_best_plays(breakdown)` and `phrase_losers_biggest_mistakes(breakdown)` are
   phrased in **separate calls** — they're separate contexts with no shared narrative — and
   `phrase_injury_impact(report)` short-circuits to `NO_INJURIES_RESPONSE` rather than asking the
   model to phrase an empty payload. Each context carries its own `*_PROMPT_VERSION`, so changing
   one prompt regenerates only that context.
   **EPA framing differs by payload on purpose**: the breakdown payloads swap EPA (an internal sort
   key) for WPA, a percentage a casual fan can read; the injury payload keeps raw `epa_per_play`,
   because its before/after comparison *is* an EPA aggregate and WPA has no per-span equivalent.

#### In-memory projections (no DB, no version — rebuilt per use)

7. **`models/game_breakdown.py`** — `GameBreakdown.build(doc)` picks the winning team's `TOP_N`
   best-EPA plays and the losing team's `TOP_N` worst-EPA plays, both from that team's own
   offensive snaps. **Returns `None` on a tie** — neither role exists — which is a legitimate
   degenerate case, not an error: callers skip both breakdown contexts and write no row for either.
8. **`models/injury_impact.py`** — `InjuryImpactReport.build(doc)` finds injury notices by regex on
   `description` (nflverse embeds the team abbreviation in the text, e.g.
   `"BUF-22-R.Davis was injured during the play."`, so no player-team lookup is needed) and
   compares the affected offense's EPA/play before vs. after that play. The affected team is always
   `play.posteam` — whether the injured player was on offense (his own team) or defense (EPA only
   measures offense, so the absence shows up in what the opposing offense does). A notice whose team
   matches neither `posteam` nor `defteam` **raises** rather than mis-attributing. Before/after is a
   single split at the injury play over scrimmage plays only, not a fixed drive window.
9. **`models/play_narrative.py`** — `synthesize(play, include_epa=True)` wraps a play's raw
   `description` with the game-state context (quarter, timestamp, down/distance, field position, win
   probability, and optionally EPA) plus the passer/rusher/receiver full names, whichever are
   present, that an LLM needs to read it correctly. Formatting, not selection.
   `macro_context.py` is its only consumer, and passes `include_epa=False` for breakdown plays.
10. **`models/play_selection.py`** — groups a `GameDocument`'s plays by why they matter (drives,
    high-leverage, situational, decisive). **Currently unwired**: nothing imports it, since the
    macro contexts are fed by `game_breakdown`/`injury_impact` instead. Keep it building, but don't
    assume it's on the live path.

#### Orchestration

11. **`get_recap.py`** — the orchestrator and the cache layer. `get_recap(...)` looks each component
    up in Supabase (`game_ledgers`, `team_signals`, `macro_contexts`) and builds only what's
    missing **or stale** — a cached row whose `version` doesn't match the module's current one is
    rebuilt. A lookup *exception* is treated the same as a cache miss (rebuild rather than fail the
    request). `team_signals` is only considered cached when **both** team rows are present. Macro
    contexts are checked per `context_type` against `MACRO_CONTEXT_VERSIONS`, so a version bump on
    one context doesn't invalidate the other two, and the two breakdown contexts share one
    `GameBreakdown` build while being phrased and upserted independently. Building anything requires
    a `GameDocument`, so a single miss pays for the full download + preprocess.
12. **`game_qa.py`** — the live Q&A layer. Two calls, both `claude-sonnet-5`: `route_question()`
    uses forced tool use (`select_components`) to pick a subset of `VALID_COMPONENTS` —
    `{ledger, team_signals}` — validating the result and raising `RoutingValidationError` on
    anything unexpected; an empty list means out of scope and callers short-circuit to
    `OUT_OF_SCOPE_RESPONSE` without a second call. `fetch_qa_payload()` shapes only the routed
    components through their `_shape_*` contracts, and `answer_question()` phrases 2–4 sentences
    from that payload alone. **Macro contexts are not routable** — they're prewritten prose, not
    queryable data, so the router never selects them.
13. **`get_data/load_players.py`** — full refresh of the `players` table (`gsis_id`,
    `display_name`, `headshot`) from `nflreadpy.load_players()`, TRUNCATE + append over
    `DATABASE_URL`. **Run manually only** (`python load_players.py` from `backend/get_data/`),
    typically right before the start of a season — it is not exposed as an endpoint and is not on a
    scheduler. Exists because PBP data carries only initials + last name; display names are
    what keep player names out of hallucination territory.

#### Scheduled ingest (the poll → recap tick)

Three modules that run on a clock rather than on a request. They are the only writers of the
`games` and `pbp_release_state` tables, and the only path that builds a recap nobody asked for yet.

14. **`get_data/poll_games.py`** — `poll_games()` fetches ESPN's **scoreboard** endpoint and upserts
    one `games` row per trackable event (`game_id`, `season`, `week`, teams, scores, `status` of
    `final`/`in_progress`). It **never writes `recap_generated`** — that column belongs to
    `build_pending_recaps.py`, and the split is what keeps a re-poll from un-marking a built recap.
    Two things it owns: its own copy of `TEAM_ABBR` (deliberately duplicated from
    `pages/Games.jsx` so backend and frontend agree on abbreviations without coupling), and
    `POSTSEASON_WEEK`, the inverse of the frontend's mapping — ESPN postseason weeks 1/2/3/5 are
    nflverse 19/20/21/22, and ESPN's week 4 is the Pro Bowl. Preseason and unmapped team names are
    skipped, not guessed at. Its `__main__` block is a **different fetch for the same rows**: it
    takes ESPN's `<season> <week> <season_type>` and reads the `/nfl/schedule` CDN endpoint (grouped
    by date under `content.schedule`, flattened before use) so a past week can be backfilled; both
    paths funnel through `_build_game_row()`, so the rows they write are identical.
15. **`get_data/check_pbp_release.py`** — `check_pbp_release(season)` compares the GitHub
    `updated_at` of nflverse-data's `play_by_play_<season>.parquet` asset against the timestamp in
    `pbp_release_state`, returning whether it moved. This is the gate on the whole tick: a game
    going final does **not** mean its plays are published, so without it the job would burn a
    download per tick and cache a half-empty recap. It is **not a dry run** — on a change it calls
    `nfl.clear_cache()` (otherwise `load_pbp()` serves the stale local parquet) and upserts the new
    timestamp, so a manual run consumes the change and the next tick sees none.
16. **`build_pending_recaps.py`** — `poll_and_recap()` is the one tick: `poll_games()`, then
    `check_pbp_release(nfl.get_current_season())`, and only on a change
    `_build_recaps_for_eligible_games()`, which runs `get_recap()` for every `games` row that is
    `status = 'final'` and `recap_generated = false`, then flips the flag. Failures are isolated per
    game and **left unflagged on purpose**: an exception is caught and logged, and a build that
    returns no game ledger is skipped, so either way the game is retried on the next tick rather
    than failing the batch or being marked done. It imports `get_recap` and `get_data.*` as
    top-level/package paths, so it runs from `backend/`, not from `get_data/`.

### FastAPI app (`backend/main.py`)

- `GET /health` → `{"status": "ok"}`.
- `POST /poll_games` — the scheduled tick's trigger (pg_cron via pg_net, GitHub Actions, etc.), not
  a user-facing route: it requires an `X-Poll-Secret` header matching `POLL_SECRET` and 401s
  otherwise. It hands `poll_and_recap` to FastAPI's `BackgroundTasks` and returns
  `{"status": "polling started"}` immediately — a tick can build many recaps, far longer than a
  request should stay open, so **nothing about the outcome is in the response**; failures surface in
  the logs and in rows that stay `recap_generated = false`.
- `GET /get_recap/{season}/{week}/{away_team}/{home_team}/{away_score}/{home_score}/` — builds the
  nflverse `game_id` from the path parts and returns `{game_ledger, team_signals, macro_contexts}`
  via `get_recap()`. `macro_contexts` is keyed by `context_type` and each value is the **whole DB
  row**, not the bare text. It is `{}` — not null — when nothing is cached or phrased, so the
  frontend checks for emptiness rather than truthiness.
- `POST /ask_question` — body is `{question, game_ledger, team_signals}`. The
  frontend **passes the components it already holds** from the `/get_recap` call rather than having
  the backend refetch them. Routes → shapes → answers; a `RoutingValidationError` becomes a 502.

There is **no** player-refresh endpoint: `load_players.py` is a manual script (see above).

CORS allows the single `FRONTEND_URL` origin.

### Supabase tables

| Table | Key | Written by |
| --- | --- | --- |
| `players` | `gsis_id` | `load_players.py`, via SQLAlchemy / `DATABASE_URL` |
| `game_ledgers` | `game_id` | `GameLedger.to_dict()` |
| `team_signals` | `game_id` + `team` (one row per team) | `TeamSignals.to_db_item()` |
| `macro_contexts` | `game_id` + `context_type` | `_upsert_macro_context()` in `get_recap.py` |
| `games` | `game_id` | `poll_games.py` (every column but `recap_generated`), `build_pending_recaps.py` (`recap_generated` only) |
| `pbp_release_state` | `season` | `check_pbp_release.py` |

A `macro_contexts` row is `{game_id, context_type, content: {"text": ...}, version}`, with
`context_type` one of `winners_best_plays`, `losers_biggest_mistakes`, `injury_impact`. A tied game
legitimately has neither breakdown row. Every table but `players` is written via the `supabase`
client (`SUPABASE_URL`/`SUPABASE_KEY`); the three component caches each carry a `version` column the
cache checks on read.

The two scheduler tables are not caches and carry no `version`. A `games` row is
`{game_id, season, week, away_team, home_team, away_score, home_score, status, recap_generated}` —
`status` is `final` or `in_progress`, and `recap_generated` is the work queue: **final + false** is
the eligibility condition the recap job selects on. `pbp_release_state` is one row per season,
`{season, last_updated_at}`, holding the nflverse release asset's `updated_at` as of the last check.

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
- `pages/Recap.jsx` fetches the three components and renders `GameLedger`, `TeamSignals`,
  `MacroContexts`, and `AskAboutGame`; each section renders only if its own data came back.
- `components/MacroContexts.jsx` renders the three phrased narratives as full-width stacked cards,
  in the order winner's best plays → loser's biggest mistakes → injury impact. It derives
  winner/loser **from the scores**, not from the backend, to title each card and pick its team
  color; the injury card belongs to neither team and uses the neutral page accent. A context type
  the frontend doesn't recognize is skipped rather than rendered untitled — unlike a signal chip, a
  narrative block needs a heading and a team, and neither can be guessed from the key.
- `components/SectionHead.jsx` is the shared heading + collapsible "About" banner for recap sections.
- `theme/team_colors.js` maps nflverse abbreviations to brand colors and returns the
  `--rc-home`/`--rc-away` overrides the sections paint from; it lifts too-dark colors for contrast
  against the near-black surfaces and falls back to a secondary color when both teams share a hue.
- Team logos live in `src/logos/` keyed by full display name and are loaded with `import.meta.glob`.

Signal chips read `signals[abbr].signals` — the backend returns the **DB row** per team
(`{game_id, team, signals, version}`), not the bare signal record. Macro context cards likewise read
`contexts[context_type].content.text`.

## Running things

The import style differs by entry point — **the working directory matters**:

- **API server** (from `backend/`): `uvicorn main:app --reload`
  (`main.py` imports `get_recap` and `game_qa` as top-level modules, so it must run
  from `backend/`, *not* the repo root.)
- **Player refresh** (from `backend/get_data/`): `python load_players.py` — manual, on demand.
- **Poll + recap tick** (from `backend/`): `python build_pending_recaps.py` — runs one full tick by
  hand, the same thing `POST /poll_games` schedules.
- **Game backfill** (from `backend/get_data/`): `python poll_games.py <season> <week> <season_type>`
  — ESPN's week and season type (2 = regular, 3 = postseason), not nflverse's.
- **Release check** (from `backend/get_data/`): `python check_pbp_release.py <season>` — remember it
  records what it sees, so it consumes the change for the next tick.
- **Frontend** (from `frontend/`): `npm install`, then `npm run dev` / `npm run build` /
  `npm run lint`.

Python deps are in [backend/requirements.txt](backend/requirements.txt) (fastapi, uvicorn,
nflreadpy, pandas, pyarrow, anthropic, python-dotenv, sqlalchemy, psycopg2-binary, supabase) —
they moved out of the repo root, so `pip install -r requirements.txt` from the root no longer
resolves. **`requests` is missing from that file** even though `poll_games.py` and
`check_pbp_release.py` import it; it currently arrives transitively.

## Testing each layer

There is no test framework. Each backend module has an `if __name__ == "__main__"` block that runs
that layer in isolation, reading the previous stage's artifact from `backend/test_data/` and writing
its own. **These blocks use relative paths (`../test_data/...`) and import siblings directly, so
they must be run from inside their own directory:**

- From `backend/get_data/`: `python get_pbp_data.py <season> <week> <away> <home>` — downloads
  *and* cleans, writing `pbp_data.csv` in one step.
- From `backend/models/`: `python game_document.py` (reads `pbp_data.csv`) →
  `game_document.json`. Every layer below reads that one file: `python game_ledger.py` →
  `game_ledger.json`, `python team_signals.py` → `team_signals.json`, `python play_selection.py` →
  `play_selection.json`, and `game_breakdown.py` / `injury_impact.py` / `play_narrative.py` /
  `macro_context.py`, which print rather than write.

Regenerate `game_document.json` after changing anything upstream of it. `play.py` hits the `players`
table, so even the standalone blocks need `DATABASE_URL`; `macro_context.py`'s block additionally
spends real Anthropic tokens.

**Known stale block:** `play.py`'s `__main__` still reads `../test_data/preprocessed_data.csv`, an
artifact no module writes any more (it was `preprocess_data.py`'s output before that module was
folded into `get_pbp_data.py`). Run `play.py` standalone only after pointing it at `pbp_data.csv`.

**Imports in `models/`:** every module uses the dual-import pattern (`try: from .play import ...`
/ `except ImportError:` insert `__file__`'s dir on `sys.path`), so each one imports cleanly both as
a package member and as a standalone script, in any order. Keep the guard on any new module here —
the package used to depend on an accidental side effect (`game_document` importing the old
`signals.py`, whose own bare import failed and put `models/` on `sys.path` for everyone else), and
that prop is gone.

`asdict` flattens the nested dataclasses for JSON serialization, so reloading a saved
`GameDocument` requires rebuilding the dataclass types from dicts — see the `document_from_dict`
helper in the `__main__` block of `team_signals.py`.

## Environment variables

- Backend (`backend/.env`, loaded with `python-dotenv`; `play.py`, `get_recap.py`,
  `load_players.py`, `poll_games.py`, `check_pbp_release.py`, and `build_pending_recaps.py` resolve
  the path relative to `__file__` so they work from any working directory):
  `FRONTEND_URL` (CORS origin), `DATABASE_URL` (Postgres/Supabase, for the `players` table),
  `SUPABASE_URL` + `SUPABASE_KEY` (recap component cache plus the `games` and
  `pbp_release_state` tables), `ANTHROPIC_API_KEY` (macro contexts and Q&A), `POLL_SECRET` (the
  shared secret `POST /poll_games` checks against its `X-Poll-Secret` header).
- Frontend (`frontend/.env`): `VITE_API_BASE_URL`.
