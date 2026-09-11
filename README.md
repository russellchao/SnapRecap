# Snap Recap

## Problem Statement

Following an NFL game, fans are stuck choosing between a box score that buries what actually mattered in undifferentiated stats, or a traditional recap that narrates the scoring sequence without explaining why the game unfolded that way. Neither format lets a fan ask the questions they actually have — why a team's offense stalled, what turned the game, which matchup broke down — and get an answer grounded in what happened on the field. Snap Recap fills this gap with an interactive experience that surfaces the game's most significant moments and lets fans query them directly, turning passive recap-reading into an actual investigation of the game.

## Overview

SnapRecap turns an NFL game's play-by-play data into a structured, explorable recap. Pick a game,
and the app breaks it down into three components:

- **Game Ledger** — the game's EPA margin decomposed into fixed categories (turnovers, pass
  protection, penalties, special teams, red zone, third down, explosive plays, other), so you can
  see *where* the margin actually came from.
- **Team Signals** — per-team efficiency stats (third/fourth down, red zone TD rate,
  success rate, explosive rate, EPA and yards per play/pass/rush, CPOE, sacks forced), each carrying
  its sample size so a 1-for-1 doesn't read like a trend.
- **Macro Context** — three short narratives in plain language: the winner's best plays, the
  loser's biggest mistakes, and how injuries moved each offense. Python picks the plays and computes
  the numbers; Claude only puts them into words.

On top of that there's **Q&A**: ask a question about the game and Claude picks which components are
relevant, then Python hands it only those numbers to phrase an answer from.

Both LLM features keep the same boundary: **Python owns retrieval and grounding; the model owns
phrasing.** Nothing is said that isn't traceable to a field in the play-by-play.

## Stack

- **Backend** — FastAPI, [nflreadpy](https://github.com/nflverse/nflreadpy) play-by-play, pandas,
  Supabase (component cache + player names), Anthropic API (`claude-sonnet-5`) for macro contexts
  and Q&A.
- **Frontend** — React 19 + Vite + react-router. Game listings come straight from ESPN's public CDN
  API in the browser; only the recap and Q&A calls hit our backend.

## How a recap gets built

```
nflreadpy PBP  →  clean  →  Play records  →  GameDocument
 (one season,     (drop      (one per row,   (lossless
  filtered to      unused     names resolved  intermediate)
  one game_id)     columns)   from Supabase)

GameDocument ─┬─→ Game Ledger ────────────────────────────────┐
              │                                               │
              ├─→ Team Signals ───────────────────────────────┼─→ Supabase cache
              │                                               │
              └─→ Game Breakdown / Injury Impact              │
                    → Claude phrases → Macro Contexts ────────┘
```

`get_recap.py` checks Supabase for each component and builds only what's missing — or what's
**stale**, since every cached row carries the `VERSION` of the module that wrote it and is rebuilt
when that version moves. Macro contexts are versioned per context, so reworking one prompt
regenerates only that narrative. A single cache miss pays for the full download + preprocess, so the
first request for a game is slow and every one after it is fast.

The two breakdown narratives come from the winning and losing team's best/worst EPA plays, which
means a tied game legitimately has neither — no winner, no loser, no row written.

## API

| Endpoint | What it does |
| --- | --- |
| `GET /health` | `{"status": "ok"}` |
| `GET /get_recap/{season}/{week}/{away_team}/{home_team}/{away_score}/{home_score}/` | Returns `{game_ledger, team_signals, macro_contexts}`. Also builds any missing or stale components. |
| `POST /ask_question` | Body: `{question, game_ledger, team_signals}`. The frontend passes back the components it already holds instead of making the backend refetch them. |

`macro_contexts` is keyed by context type — `winners_best_plays`, `losers_biggest_mistakes`,
`injury_impact` — and each value is the stored row, with the narrative under `content.text`.

## Setup

```bash
# Backend
python -m venv .venv && .venv\Scripts\activate     # or: source .venv/bin/activate
pip install -r requirements.txt
cd backend && uvicorn main:app --reload            # must run from backend/

# Frontend
cd frontend && npm install && npm run dev
```

`backend/.env`:

```
FRONTEND_URL=http://localhost:5173
DATABASE_URL=postgresql://...      # Supabase Postgres, for the players table
SUPABASE_URL=...
SUPABASE_KEY=...
ANTHROPIC_API_KEY=...
```

`frontend/.env`:

```
VITE_API_BASE_URL=http://127.0.0.1:8000
```

Supabase holds four tables: `players` (`gsis_id` → display name), plus the three component caches
`game_ledgers` (keyed by `game_id`), `team_signals` (`game_id` + `team`, one row per team), and
`macro_contexts` (`game_id` + `context_type`).

Play-by-play data carries only initials + last name, so player display names come from the `players`
table, refreshed from `nflreadpy.load_players()`. It is populated by running
`python load_players.py` from `backend/get_data/` **manually** — do it once before building any
recaps, and again as needed (typically right before the start of a season). There is no endpoint or
scheduled job for it.

## Testing a layer

There is no test framework. Each backend module has a `__main__` block that runs that stage against
the previous stage's artifact in `backend/test_data/`. They use relative paths and sibling imports,
so **run them from inside their own directory**, in order:

```bash
cd backend/get_data
python get_pbp_data.py 2025 5 KC JAX     # downloads + cleans → test_data/pbp_data.csv

cd ../models
python game_document.py                  # → test_data/game_document.json
```

Everything below `game_document.py` reads that one JSON file, so any of these can be run next, in
any order:

```bash
python game_ledger.py                    # → test_data/game_ledger.json
python team_signals.py                   # → test_data/team_signals.json
python play_selection.py                 # → test_data/play_selection.json
python game_breakdown.py                 # prints the winner's/loser's key plays
python injury_impact.py                  # prints each injury's before/after EPA split
python macro_context.py                  # prints all three narratives — spends API tokens
```

`play.py` resolves names against Supabase, so even these standalone runs need `DATABASE_URL`, and
`macro_context.py` needs `ANTHROPIC_API_KEY`.

## License

MIT — see [LICENSE](LICENSE).
