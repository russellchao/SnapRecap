"""
Game document assembly for Snap Recap.

The GameDocument is the lossless intermediate that bundles the two layers
— every Play record plus each team's offensive and defensive signal
records — behind a small game header. It is the handoff boundary: once
built, the prompt builder and the recap cache work from this object alone
and never touch the source DataFrame again.

Selection (surfacing high-leverage plays, baseline annotation) happens
*downstream* of this object. The document itself filters nothing.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, List, Optional
import pandas as pd
import json
import sys
import os

try: 
    from .play import Play, plays_from_frame, teams_in
    from .signals import defensive_signals, offensive_signals
except ImportError:
    sys.path.insert(0, os.path.dirname(__file__))
    from play import Play, plays_from_frame, teams_in
    from signals import defensive_signals, offensive_signals


@dataclass
class GameHeader:
    """Game identity and outcome.

    Sourced from ESPN metadata (the same feed used for the games list);
    `game_id` is the key recaps are persisted under. Fields are optional
    so a document can be assembled before header sourcing is wired in.
    """
    game_id: Optional[str] = None
    season: Optional[int] = None
    week: Optional[int] = None
    away_team: Optional[str] = None
    home_team: Optional[str] = None
    away_score: Optional[int] = None
    home_score: Optional[int] = None
    

@dataclass
class TeamSignals:
    """A single team's two signal records (offense + defense)."""
    offense: Dict[str, object]
    defense: Dict[str, object]


@dataclass
class GameDocument:
    """Lossless game representation: header + per-team signals + all plays."""
    header: GameHeader
    signals: Dict[str, TeamSignals]   # keyed by team abbreviation
    plays: List[Play]

    @classmethod
    def build(cls, plays: List[Play], header: GameHeader) -> "GameDocument":
        """Assemble the document from prebuilt plays and a header.

        Resolves the two teams, computes each team's offensive and
        defensive signal records, and packages everything. Plays are
        stored in full and in order — nothing is filtered here.
        """
        signals = {
            team: TeamSignals(
                offense=offensive_signals(plays, team),
                defense=defensive_signals(plays, team),
            )
            for team in teams_in(plays)
        }
        return cls(header=header, signals=signals, plays=plays)

    def to_dict(self) -> Dict[str, object]:
        """JSON-serializable form for the prompt step and the cache.

        `asdict` recurses through the nested dataclasses (Play, RateSignal,
        MeanSignal) and leaves the distribution dicts untouched.
        """
        return asdict(self)
    






if __name__ == "__main__":
    # NOTE: For testing purposes only
    # Test building the game document on the BUF-JAX 2025 Wild Card Game

    # Game header 
    # (sourced from ESPN metadata for the same game, but hardcoded here for testing)
    buf_jax_header = GameHeader(
        game_id = "2025_19_BUF_JAX",
        season = 2025,
        week = 19,
        away_team = "BUF",
        home_team = "JAX",
        away_score = 27,
        home_score = 24,
    )

    # All plays (computed from the preprocessed CSV)
    csv_file = "../test_data/preprocessed_data_buf_jax_wc_2025.csv"    
    df = pd.read_csv(csv_file)
    plays = plays_from_frame(df)
    teams = teams_in(plays)
    print(f"Teams in game: {teams}\n")

    # Signals for both teams (computed from the plays)
    signals = {
        team: TeamSignals(
            offense=offensive_signals(plays, team),
            defense=defensive_signals(plays, team),
        )
        for team in teams
    }

    # Build the game document and save it as a JSON-serializable dict for inspection
    game_doc = GameDocument(header=buf_jax_header, signals=signals, plays=plays)
    game_doc_dict = game_doc.to_dict()
    game_doc_json_filename = "../test_data/game_document_buf_jax_wc_2025.json"
    with open(game_doc_json_filename, "w") as f:
        json.dump(game_doc_dict, f, indent=2)
    print(f"Game document saved to {game_doc_json_filename}")
