# Libraries and Frameworks
from fastapi import FastAPI, HTTPException, BackgroundTasks, Header
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import os
from dotenv import load_dotenv

# Internal Modules
from get_data.load_players import refresh_players
from get_recap import get_recap


load_dotenv()


app = FastAPI(title="SnapRecap API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_URL")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/players/refresh", status_code=202)
def refresh_players_endpoint(
    background_tasks: BackgroundTasks, authorization: str = Header(None),
):
    #TODO: Enable the pg_net extension in Supabase to run the CRON scheduler on this endpoint

    # Triggered by an external scheduler (i.e. Supabase pg_cron via pg_net).
    # Protected by a shared secret so it can't be invoked publicly.
    expected = os.getenv("CRON_SECRET")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="CRON_SECRET is not configured on the server.",
        )
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Run in the background so the request returns immediately; the download +
    # DB write takes several seconds and the caller doesn't need to wait.
    background_tasks.add_task(refresh_players)
    return {"status": "accepted", "detail": "Player data refresh started."}


@app.get("/get_recap/{season}/{week}/{away_team}/{home_team}/{away_score}/{home_score}/")
def get_recap_endpoint(season: str, week: str, away_team: str, home_team: str, away_score: str, home_score: str):

    game_id = f"{season}_{int(week) < 10 and '0' + str(week) or str(week)}_{away_team}_{home_team}"
    _game_ledger, _selected_plays, _team_signals = get_recap(
        game_id, season, week, away_team, home_team, int(away_score), int(home_score) 
    )

    return {
        "game_ledger": _game_ledger,
        "selected_plays": _selected_plays,
        "team_signals": _team_signals,
    }


#NOTE: Run the FastAPI App locally with: uvicorn main:app --reload