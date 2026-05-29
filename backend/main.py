from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import os
from dotenv import load_dotenv
from pbp_stats import get_pbp_stats


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
def get_pbp_stats_endpoint(season: int, week: int, away: str, home: str):
    try:
        pbp_stats = get_pbp_stats(season, week, away, home)

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while fetching play-by-play data for the game: {away} vs. {home} in Week {week} of the {season} Season. Details: {str(e)}",
        )

    if isinstance(pbp_stats, pd.DataFrame):
        return {
            "Success":
            f"Play-by-play data exists for the game: {away} vs. {home} in Week {week} of the {season} Season",
        }

    raise HTTPException(
        status_code=404,
        detail=f"Play-by-play data not available for the game: {away} vs. {home} in Week {week} of the {season} Season",
    )