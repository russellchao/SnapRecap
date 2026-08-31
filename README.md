# Snap Recap

## Problem Statement

Following an NFL game, fans are stuck choosing between a box score that buries what actually mattered in undifferentiated stats, or a traditional recap that narrates the scoring sequence without explaining why the game unfolded that way. Neither format lets a fan ask the questions they actually have — why a team's offense stalled, what turned the game, which matchup broke down — and get an answer grounded in what happened on the field. Snap Recap fills this gap with an interactive experience that surfaces the game's most significant moments and lets fans query them directly, turning passive recap-reading into an actual investigation of the game.

## Overview

SnapRecap turns an NFL game's play-by-play data into a structured, explorable recap. Pick a game,
and the app breaks it down into three components:

- **Game Ledger** — the game's EPA margin decomposed into fixed categories (turnovers, pass
  protection, penalties, special teams, red zone, third down, explosive plays, other), so you can
  see *where* the margin actually came from.
- **Anchor Plays** — the handful of plays that swung win probability the most, weighted toward late
  in the game, capped at one per drive.
- **Team Signals** — per-team efficiency stats (third/fourth down, red zone TD rate,
  success rate, explosive rate, EPA and yards per play/pass/rush, CPOE, sacks forced), each carrying
  its sample size so a 1-for-1 doesn't read like a trend.

On top of that there's **Q&A**: ask a question about the game and Claude picks which components are
relevant, then Python hands it only those numbers to phrase an answer from. Python owns retrieval
and grounding; the model owns phrasing.

## Stack

- **Backend** — FastAPI, [nflreadpy](https://github.com/nflverse/nflreadpy) play-by-play, pandas,
  Supabase (component cache + player names), Anthropic API (`claude-sonnet-5`) for Q&A.
- **Frontend** — React 19 + Vite + react-router. Game listings come straight from ESPN's public CDN
  API in the browser; only the recap and Q&A calls hit our backend.

## How a recap gets built

```
nflreadpy PBP  →  clean  →  Play records  →  GameDocument  →  ┬→ Game Ledger
 (one season,     (drop      (one per row,   (lossless       ├→ Anchor Plays
  filtered to      unused     names resolved  intermediate)   └→ Team Signals
  one game_id)     columns)   from Supabase)                        ↓
                                                              Supabase cache
```

`get_recap.py` checks Supabase for each of the three components and builds only what's missing. A
single cache miss pays for the full download + preprocess, so the first request for a game is slow
and every one after it is fast.

## API

| Endpoint | What it does |
| --- | --- |
| `GET /health` | `{"status": "ok"}` |
| `GET /get_recap/{season}/{week}/{away_team}/{home_team}/{away_score}/{home_score}/` | Returns `{game_ledger, anchor_plays, team_signals}`. Also builds any missing components. |
| `POST /ask_question` | Body: `{question, game_ledger, anchor_plays, team_signals}`. The frontend passes back the components it already holds instead of making the backend refetch them. |
| `POST /players/refresh` | 202 + background refresh of the `players` table. Requires `Authorization: Bearer $CRON_SECRET`. |

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
CRON_SECRET=...                    # guards /players/refresh
ANTHROPIC_API_KEY=...
```

`frontend/.env`:

```
VITE_API_BASE_URL=http://127.0.0.1:8000
```

Play-by-play data carries only initials + last name, so player display names come from a `players`
table refreshed from `nflreadpy.load_players()` — populate it once with
`python load_players.py` from `backend/get_data/` before building recaps.

## Testing a layer

There is no test framework. Each backend module has a `__main__` block that runs that stage against
the previous stage's artifact in `backend/test_data/`. They use relative paths and sibling imports,
so **run them from inside their own directory**, in order:

```bash
cd backend/get_data
python get_raw_data.py 2025 5 KC JAX     # → test_data/pbp_data.csv
python preprocess_data.py                # → test_data/preprocessed_data.csv

cd ../models
python game_document.py                  # → test_data/game_document.json
python game_ledger.py                    # → test_data/game_ledger.json
python anchor_plays.py                   # → test_data/anchor_plays.json
```

`play.py` resolves names against Supabase, so even these standalone runs need `DATABASE_URL`.

## License

MIT — see [LICENSE](LICENSE).
