import { useEffect, useMemo, useState } from 'react'
import { useLocation, useParams, Link } from 'react-router-dom'
import { fetchRecap } from '../api/fetch_recap'
import GameLedger from '../components/GameLedger'
import AnchorPlays from '../components/AnchorPlays'
import TeamSignals from '../components/TeamSignals'
import AskAboutGame from '../components/AskAboutGame'
import { teamPalette } from '../theme/team_colors'
import './Recap.css'

// Eagerly load every team logo. Files are named by full displayName, e.g. "Dallas Cowboys.png",
// keyed here as "../logos/Dallas Cowboys.png".
const logos = import.meta.glob('../logos/*.png', { eager: true, import: 'default' });

// Look up a team's logo by its displayName (e.g. "Dallas Cowboys").
function getLogo(displayName) {
    return logos[`../logos/${displayName}.png`];
}

// Split a full team displayName (e.g. "Dallas Cowboys") into its city
// ("Dallas") and team name ("Cowboys"). NFL team names are always the last word.
function splitTeamName(displayName) {
    const parts = (displayName ?? "").trim().split(' ');
    const team_name = parts.pop() ?? "";
    const city = parts.join(' ');
    return { city, team_name };
}


export default function Recap() {
    const { season, week, away_team, home_team } = useParams();
    const { state } = useLocation();
    const game = state?.game;
    const status = game?.status || "Unknown";

    const [recapStatus, setRecapStatus] = useState(null);
    const [loading, setLoading] = useState(false);

    const [gameLedger, setGameLedger] = useState(null);
    const [anchorPlays, setAnchorPlays] = useState(null);
    const [teamSignals, setTeamSignals] = useState(null);


    useEffect(() => {
        if (!game) return;
        // StrictMode runs effects twice in dev; `stale` keeps the discarded first
        // run from writing state back after the real one has already resolved.
        let stale = false;
        setLoading(true);
        fetchRecap(season, week, away_team, home_team, game.away_score, game.home_score)
            .then(({ status, data }) => {
                if (!stale) {
                    // `data` is null when the request failed or never reached the server.
                    setRecapStatus(status);
                    console.log("Fetched recap data:", data);
                    setGameLedger(data?.game_ledger ?? null);
                    setAnchorPlays(data?.anchor_plays ?? null);
                    setTeamSignals(data?.team_signals ?? null);
                }
            })
            .finally(() => {
                if (!stale) setLoading(false);
            });
        return () => { stale = true; };
    }, [season, week, away_team, home_team]);

    // The two teams' brand colors, as the `--rc-home` / `--rc-away` overrides each
    // recap section paints from. Declared above the early return below so the hook
    // order stays fixed.
    const teamColors = useMemo(() => teamPalette(away_team, home_team), [away_team, home_team]);

    /*
        The game object is passed via router state from the games list.

        If a user lands here directly (e.g. a refresh or bookmarked URL),
        that state is gone, so prompt them back to the games page.
    */
    if (!game) {
        return (
            <div className="recap recap-empty">
                <p>Recap not available for this game.</p>
                <Link className="recap-back" to="/games">← Back to games</Link>
            </div>
        );
    }

    const away = splitTeamName(game.away_team);
    const home = splitTeamName(game.home_team);

    // Highlight the winning team's score. Scores arrive as strings, so compare numerically.
    const awayScore = Number(game.away_score);
    const homeScore = Number(game.home_score);
    const awayWon = awayScore >= homeScore;
    const homeWon = homeScore >= awayScore;

    // Any one component is enough to show the recap body; each section renders
    // only if its own data made it back.
    const hasRecap = [gameLedger, anchorPlays, teamSignals].some((part) => part != null);

    return (
        <div className="recap">
            <header className="recap-header">
                <Link className="recap-back" to="/games">← Back to games</Link>

                {/* Top meta strip: headline banner + date */}
                <div className="recap-meta">
                    {game.game_headline && game.game_headline !== "None" && (
                        <span className="recap-headline">{game.game_headline}</span>
                    )}
                    <span className="recap-date">{game.start_date}</span>
                </div>

                {/* Scoreboard: away team — score — home team, all on one line */}
                <div className="recap-scoreboard">
                    <div className="recap-team recap-team-away">
                        <img className="recap-logo" src={getLogo(game.away_team)} alt={game.away_team} />
                        <div className="recap-team-name">
                            <span className="recap-team-city">{away.city}</span>
                            <span className="recap-team-nick">{away.team_name}</span>
                        </div>
                    </div>

                    <div className="recap-score">
                        <span className="recap-status">{status}</span>
                        {status === "Final" && (
                            <div className="recap-score-row">
                                <span className={`recap-score-num ${awayWon ? "winner" : "loser"}`}>{game.away_score}</span>
                                <span className="recap-score-dash">–</span>
                                <span className={`recap-score-num ${homeWon ? "winner" : "loser"}`}>{game.home_score}</span>
                            </div>
                        )}
                    </div>

                    <div className="recap-team recap-team-home">
                        <div className="recap-team-name">
                            <span className="recap-team-city">{home.city}</span>
                            <span className="recap-team-nick">{home.team_name}</span>
                        </div>
                        <img className="recap-logo" src={getLogo(game.home_team)} alt={game.home_team} />
                    </div>
                </div>
            </header>

            {loading ? (
                <div className="recap-loading" role="status" aria-live="polite">
                    <span className="recap-spinner" aria-hidden="true" />
                    <span>Loading recap…</span>
                </div>
            ) : hasRecap ? (
                <div className="recap-body">
                    {gameLedger && (
                        <GameLedger ledger={gameLedger} awayAbbr={away_team} homeAbbr={home_team} colors={teamColors} />
                    )}
                    {anchorPlays?.length > 0 && (
                        <AnchorPlays plays={anchorPlays} homeAbbr={home_team} colors={teamColors} />
                    )}
                    {teamSignals && (
                        <TeamSignals
                            signals={teamSignals}
                            awayName={away.city}
                            homeName={home.city}
                            awayAbbr={away_team}
                            homeAbbr={home_team}
                            colors={teamColors}
                        />
                    )}
                    <AskAboutGame ledger={gameLedger} plays={anchorPlays} signals={teamSignals} />
                </div>
            ) : (
                <p className="recap-placeholder">Recap not available for this game yet.</p>
            )}
        </div>
    );
}
