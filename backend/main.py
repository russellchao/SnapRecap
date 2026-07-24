# Libraries and Frameworks
from fastapi import FastAPI, HTTPException, BackgroundTasks, Header
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import os
from dotenv import load_dotenv

# Internal Modules
from get_data.get_raw_data import get_pbp_data, get_participation_data
from get_data.load_players import refresh_players


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


@app.get("/pbp/{season}/{week}/{away}/{home}")
def get_pbp_data_endpoint(season: int, week: int, away: str, home: str):
    #NOTE: Placeholder endpoint. Will eventually replace.

    pbp_stats = get_pbp_data(season, week, away, home)

    if isinstance(pbp_stats, pd.DataFrame):
        return {
            "Success":
            f"Play-by-play data exists for the game: {away} vs. {home} in Week {week} of the {season} Season",
        }

    print(pbp_stats["Error"])
    raise HTTPException(
        status_code=404,
        detail=pbp_stats["Error"],
    )


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


#NOTE: Run the FastAPI App locally with: uvicorn main:app --reload