import './Gamecard.css'

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

export default function Gamecard({ game, onViewRecap }) {
    const isFinal = game.status === "Final";
    const away = splitTeamName(game.away_team);
    const home = splitTeamName(game.home_team);

    // Highlight the winning team's score. Scores arrive as strings, so compare numerically.
    const awayScore = Number(game.away_score);
    const homeScore = Number(game.home_score);
    const awayWon = awayScore >= homeScore;
    const homeWon = homeScore >= awayScore;

    return (
        <div className="gamecard">
            {/* Headline badge (e.g. "NFL Kickoff Game", "Super Bowl"). Hidden when "None". */}
            {game.game_headline && game.game_headline !== "None" && (
                <div className="gamecard-headline">{game.game_headline}</div>
            )}

            <div className="gamecard-matchup">
                {/* Away team */}
                <div className="team team-away">
                    <img className="team-logo" src={getLogo(game.away_team)} alt={game.away_team} />
                    <div className="team-name">
                        <span className="team-city">{away.city}</span>
                        <span className="team-name">{away.team_name}</span>
                    </div>
                </div>

                {/* Score / status */}
                <div className="gamecard-center">
                    {isFinal && (
                        <div className="gamecard-score">
                            <span className={`score ${awayWon ? "winner" : "loser"}`}>{game.away_score}</span>
                            <span className="score-dash">–</span>
                            <span className={`score ${homeWon ? "winner" : "loser"}`}>{game.home_score}</span>
                        </div>
                    )}
                    <div className="gamecard-status">{game.status}</div>
                </div>

                {/* Home team */}
                <div className="team team-home">
                    <div className="team-name">
                        <span className="team-city">{home.city}</span>
                        <span className="team-name">{home.team_name}</span>
                    </div>
                    <img className="team-logo" src={getLogo(game.home_team)} alt={game.home_team} />
                </div>
            </div>

            <div className="gamecard-footer">
                <span className="gamecard-date">{game.start_date}</span>
                <span>
                    <button
                    className={`espn-btn`}
                    onClick={() => window.open(`https://www.espn.com/nfl/game/_/gameId/${game.espn_id}`, '_blank')}
                >
                    ESPN Page →
                </button>
                <> </>
                <button
                    className={`view-recap-btn`}
                    onClick={() => onViewRecap?.(game)}
                >
                    VIEW RECAP →
                </button>
                </span>
                
            </div>
        </div>
    );
}
