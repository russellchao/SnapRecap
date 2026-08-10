import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useEffect } from 'react'
import './Games.css'
import { fetchGamesByTeamOnly, fetchGamesByWeekOnly, fetchGamesByTeamAndWeek } from '../api/fetch_games'
import Gamecard from '../components/Gamecard'


// nflreadpy / nflverse PBP data uses team abbreviations (e.g. "BUF"), but the
// game object carries full display names (e.g. "Buffalo Bills"). Map between them.
const TEAM_ABBR = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL", "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR", "Chicago Bears": "CHI", "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL", "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX", "Kansas City Chiefs": "KC",
    "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC", "Los Angeles Rams": "LA", "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN", "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT", "San Francisco 49ers": "SF",
    "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB", "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
};


export default function Games() {
  const [season, setSeason] = useState("");
  const [week, setWeek] = useState("");
  const [teamId, setTeamId] = useState("");
  const [gamesList, setGamesList] = useState([]);
  const navigate = useNavigate();


  // Navigate to the recap page for a game, keyed by its ESPN ID.
  // The full game object is passed along via router state so the recap
  // page can render without refetching.
  const handleViewRecap = (game) => {
    navigate(
      `/recap/${game.season}/${game.week}/${TEAM_ABBR[game.away_team] ?? game.away_team}/${TEAM_ABBR[game.home_team] ?? game.home_team}`, 
      { state: { game } }
    );
  };


  // If the season is nullified, also nullify the team and week.
  // This effect resets those selections, which in turn empties the games list
  // via the fetching effect below.
  useEffect(() => {
    if (season === "") {
      setWeek("");
      setTeamId("");
    }
  }, [season]);


  // Fetch games whenever the season, week, or team selection changes.
  useEffect(() => {
    // No season selected: nothing to fetch, so empty the games list.
    if (season === "") {
      setGamesList([]);
      return;
    }

    const fetchGames = async () => {
      let games;

      if (teamId !== "" && week !== "") {
        games = await fetchGamesByTeamAndWeek(season, week, teamId); // Both a team and a week are selected.
      } else if (teamId !== "") {
        games = await fetchGamesByTeamOnly(season, teamId); // Only a team is selected.
      } else if (week !== "") {
        games = await fetchGamesByWeekOnly(season, week); // Only a week is selected.
      } else {
        setGamesList([]); // A season is selected, but neither a team nor a week is.
        return;
      }

      setGamesList(games ?? []);
    };

    fetchGames();
  }, [season, week, teamId]);


  return (
    <>
      <section id="header">
          <h1>NFL <span className="highlight">Game Search</span></h1>
          <p>Select a <strong>season</strong>, then <strong>either</strong> a week <strong>or</strong> a team to view games and recaps.</p>
      </section>

      <br /><br />

      <section id="dropdown">
        <div className="field">
          <label htmlFor="season-select">Season</label>
          <select name="seasons" id="season-select" value={season} onChange={(e) => setSeason(e.target.value)}>
            <option value="">-</option>
            <option value="2024">2024</option>
            <option value="2025">2025</option>
            <option value="2026">2026</option>
          </select>
        </div>

        <p></p>

        <div className="field">
          <label htmlFor="week-select">Week</label>
          <select name="weeks" id="week-select" value={week} onChange={(e) => setWeek(e.target.value)}>
            <option value="">-</option>
          <option value="1">1</option>
          <option value="2">2</option>
          <option value="3">3</option>
          <option value="4">4</option>
          <option value="5">5</option>
          <option value="6">6</option>
          <option value="7">7</option>
          <option value="8">8</option>
          <option value="9">9</option>
          <option value="10">10</option>
          <option value="11">11</option>
          <option value="12">12</option>
          <option value="13">13</option>
          <option value="14">14</option>
          <option value="15">15</option>
          <option value="16">16</option>
          <option value="17">17</option>
          <option value="18">18</option>
          <option value="19">Wild Card</option>
          <option value="20">Divisional</option>
          <option value="21">Conference</option>
            <option value="22">Super Bowl</option>
          </select>
        </div>

        <p></p>

        <div className="field">
          <label htmlFor="team-select">Team</label>
          <select name="teams" id="team-select" value={teamId} onChange={(e) => setTeamId(e.target.value)}>
            {/* values for each team are set to their respective ESPN IDs */}
            <option value="">-</option>
          <option value="22">Arizona Cardinals</option>
          <option value="1">Atlanta Falcons</option>
          <option value="33">Baltimore Ravens</option>
          <option value="2">Buffalo Bills</option>
          <option value="29">Carolina Panthers</option>
          <option value="3">Chicago Bears</option>
          <option value="4">Cincinnati Bengals</option>
          <option value="5">Cleveland Browns</option>
          <option value="6">Dallas Cowboys</option>
          <option value="7">Denver Broncos</option>
          <option value="8">Detroit Lions</option>
          <option value="9">Green Bay Packers</option>
          <option value="34">Houston Texans</option>
          <option value="11">Indianapolis Colts</option>
          <option value="30">Jacksonville Jaguars</option>
          <option value="12">Kansas City Chiefs</option>
          <option value="13">Las Vegas Raiders</option>
          <option value="24">Los Angeles Chargers</option>
          <option value="14">Los Angeles Rams</option>
          <option value="15">Miami Dolphins</option>
          <option value="16">Minnesota Vikings</option>
          <option value="17">New England Patriots</option>
          <option value="18">New Orleans Saints</option>
          <option value="19">New York Giants</option>
          <option value="20">New York Jets</option>
          <option value="21">Philadelphia Eagles</option>
          <option value="23">Pittsburgh Steelers</option>
          <option value="25">San Francisco 49ers</option>
          <option value="26">Seattle Seahawks</option>
          <option value="27">Tampa Bay Buccaneers</option>
          <option value="10">Tennessee Titans</option>
            <option value="28">Washington Commanders</option>
          </select>
        </div>
      </section>

      <br /><br /><br />

      <section id="games-list">
        <div>
          {gamesList.length > 0 ? (
            gamesList.map((game) => (
              <div key={game.espn_id}>
                <Gamecard game={game} onViewRecap={handleViewRecap} />
                <br />
              </div>
            ))
          ) : (
            <p>No games to display.</p>
          )}
        </div>
      </section>

      <br /><br /><br /><br /><br /><br />
    </>
  )
}