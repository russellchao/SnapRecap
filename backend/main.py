from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import os
from dotenv import load_dotenv
from backend.get_data.get_raw_data import get_pbp_data, get_participation_data


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