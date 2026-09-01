"""
Game document assembly for Snap Recap.

The GameDocument is the lossless intermediate that bundles every Play
record behind a small game header. It is the handoff boundary: once
built, the three recap components (game_ledger, anchor_plays,
team_signals) and the recap cache work from this object alone and never
touch the source DataFrame again.

Selection (surfacing high-leverage plays, per-team signal reduction,
baseline annotation) happens *downstream* of this object. The document
itself filters nothing and aggregates nothing.
"""

from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional
import pandas as pd
import numpy as np
import json
import sys
import os

try: 
    from .play import Play, plays_from_frame, teams_in
except ImportError:
    sys.path.insert(0, os.path.dirname(__file__))
    from play import Play, plays_from_frame, teams_in


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
class GameDocument:
    """Lossless game representation: header + all plays."""
    header: GameHeader
    plays: List[Play]

    @classmethod
    def build(cls, plays: List[Play], header: GameHeader) -> "GameDocument":
        """Assemble the document from prebuilt plays and a header.

        Plays are stored in full and in order — nothing is filtered here.
        """
        return cls(header=header, plays=plays)

    def to_dict(self) -> Dict[str, object]:
        """JSON-serializable form for the component builders and the cache.

        `asdict` recurses through the nested dataclasses (Play).
        """
        return asdict(self)
    






if __name__ == "__main__":
    # NOTE: For testing purposes only
    # Test building the Game Document object from the Preprocessed Data CSV in the test data

    def _json_default(obj):
        """(Test Helper Function) Coerce numpy scalars/arrays (from pandas) into JSON-native types."""
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    # Read the preprocessed CSV into a DataFrame
    csv_file = "../test_data/preprocessed_data.csv"    
    df = pd.read_csv(csv_file)

    # Obtain the GameHeader attributes obtained from the preprocessed CSV
    header_attrs = {f: df[f][0] for f in ("game_id", "season", "week", "away_team", "home_team", "away_score", "home_score")}
    buf_jax_header = GameHeader(
        game_id = f"{header_attrs['game_id']}",
        season = header_attrs['season'],
        week = header_attrs['week'],
        away_team = header_attrs['away_team'],
        home_team = header_attrs['home_team'],
        away_score = header_attrs['away_score'],
        home_score = header_attrs['home_score'],
    )

    # All plays computed from the preprocessed CSV
    plays = plays_from_frame(df)
    teams = teams_in(plays)
    print(f"Teams in game: {teams}\n")

    # Build the game document and save it as a JSON-serializable dict for inspection
    game_doc = GameDocument.build(plays, buf_jax_header)
    game_doc_dict = game_doc.to_dict()
    game_doc_json_filename = "../test_data/game_document.json"
    with open(game_doc_json_filename, "w") as f:
        json.dump(game_doc_dict, f, indent=2, default=_json_default)
    print(f"Game document saved to {game_doc_json_filename}")
