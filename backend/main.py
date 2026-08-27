# Libraries and Frameworks
from fastapi import FastAPI, HTTPException, BackgroundTasks, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pandas as pd
import os
from dotenv import load_dotenv

# Internal Modules
from get_data.load_players import refresh_players
from get_recap import get_recap
import game_qa


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


# ------ Refresh Players endpoint ------

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


# ------ Get Recap endpoint ------

@app.get("/get_recap/{season}/{week}/{away_team}/{home_team}/{away_score}/{home_score}/")
def get_recap_endpoint(season: str, week: str, away_team: str, home_team: str, away_score: str, home_score: str):

    game_id = f"{season}_{int(week) < 10 and '0' + str(week) or str(week)}_{away_team}_{home_team}"
    _game_ledger, _anchor_plays, _team_signals = get_recap(
        game_id, season, week, away_team, home_team, int(away_score), int(home_score) 
    )

    return {
        "game_ledger": _game_ledger,
        "anchor_plays": _anchor_plays,
        "team_signals": _team_signals,
    }


# ------ Ask Question endpoint ------

class AskQuestionRequest(BaseModel):
    """Request body for /ask_question.

    The frontend already holds game_ledger, anchor_plays, and team_signals
    in memory from the /get_recap call that loaded the page, so those are
    passed straight through rather than re-fetched server-side.
    """
    question: str
    game_ledger: dict | None = None
    anchor_plays: list[dict] = []
    team_signals: dict = {}


@app.post("/ask_question")
def ask_question_endpoint(body: AskQuestionRequest):
    try:
        components = game_qa.route_question(body.question)
    except game_qa.RoutingValidationError as e:
        raise HTTPException(status_code=502, detail=f"Routing failed: {e}")

    if not components:
        return {"answer": game_qa.OUT_OF_SCOPE_RESPONSE, "components": []}

    payload = game_qa.fetch_qa_payload(
        components, body.game_ledger, body.anchor_plays, body.team_signals
    )
    answer = game_qa.answer_question(body.question, payload)

    return {"answer": answer, "components": components}


#NOTE: Run the FastAPI App locally with: uvicorn main:app --reload