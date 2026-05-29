import axios from 'axios';

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

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

export async function fetchRecap(season, week, away_team, home_team) {
    const away_abbr = TEAM_ABBR[away_team] ?? away_team;
    const home_abbr = TEAM_ABBR[home_team] ?? home_team;
    const url = `${API_BASE_URL}/pbp/${season}/${week}/${away_abbr}/${home_abbr}`;
    console.log(`Fetching recap from ${url}`);

    try {
        const response = await axios.get(url);
        return { status: response.status, data: response.data };
    } catch (error) {
        // axios throws on non-2xx; surface the status so the caller can branch on it.
        // status is 0 when the request never reached the server (network/CORS error).
        return {
            status: error.response?.status ?? 0,
            data: error.response?.data ?? null,
        };
    }
}
