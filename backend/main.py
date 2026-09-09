# Libraries and Frameworks
from fastapi import FastAPI, HTTPException, BackgroundTasks, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pandas as pd
import os
from dotenv import load_dotenv

# Internal Modules
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


# ------ Check Health endpoint ------

@app.get("/health")
def health():
    return {"status": "ok"}


# ------ Get Recap endpoint ------

@app.get("/get_recap/{season}/{week}/{away_team}/{home_team}/{away_score}/{home_score}/")
def get_recap_endpoint(season: str, week: str, away_team: str, home_team: str, away_score: str, home_score: str):

    game_id = f"{season}_{int(week) < 10 and '0' + str(week) or str(week)}_{away_team}_{home_team}"
    _game_ledger, _team_signals = get_recap(
        game_id, season, week, away_team, home_team, int(away_score), int(home_score) 
    )

    return {
        "game_ledger": _game_ledger,
        "team_signals": _team_signals,
    }


# ------ Ask Question endpoint ------

class AskQuestionRequest(BaseModel):
    """Request body for /ask_question.

    The frontend already holds game_ledger and team_signals in memory from
    the /get_recap call that loaded the page, so those are passed straight
    through rather than re-fetched server-side.
    """
    question: str
    game_ledger: dict | None = None
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
        components, body.game_ledger, body.team_signals
    )
    answer = game_qa.answer_question(body.question, payload)

    return {"answer": answer, "components": components}


#NOTE: Run the FastAPI App locally with: uvicorn main:app --reload