import axios from 'axios';
import Game from '../models/Game';

export async function fetchGamesByWeekOnly(season, week) {
    console.log(`Fetching all games from week ${week} of the ${season} season.`);

    let season_type = 2; // Regular season by default.
    let adjusted_week = week;
    if (['19', '20', '21', '22'].includes(week)) {
        season_type = 3; // Playoffs
        switch (week) {
            case '19': adjusted_week = 1; break;    // Wild Card
            case '20': adjusted_week = 2; break;    // Divisional
            case '21': adjusted_week = 3; break;    // Conference
            case '22': adjusted_week = 5; break;    // Super Bowl
        }
    }

    const espn_api_url = `https://cdn.espn.com/core/nfl/schedule?xhr=1&year=${season}&week=${adjusted_week}&seasontype=${season_type}`;
    try {
        const { data } = await axios.get(espn_api_url);

        // The ESPN response groups games by date under content.schedule,
        // e.g. content.schedule["20250904"].games. Flatten them into one list.
        const schedule = data?.content?.schedule ?? {};
        const events = Object.values(schedule).flatMap(day => day.games ?? []);

        const games = events.map(event => {
            const competitors = event.competitions[0].competitors;
            const game_headline = event.competitions[0].notes[0]?.headline ?? "None";

            const game = new Game(
                event.id,
                game_headline,
                new Date(event.date).toLocaleString('en-US', {
                    timeZone: 'America/New_York',
                    weekday: 'short',
                    month: 'short',
                    day: 'numeric',
                    year: 'numeric',
                    hour: 'numeric',
                    minute: '2-digit',
                    timeZoneName: 'short',
                }),
                season,
                week,
                competitors.find(c => c.homeAway === 'away').team.displayName,
                competitors.find(c => c.homeAway === 'home').team.displayName,
                competitors.find(c => c.homeAway === 'away').score,
                competitors.find(c => c.homeAway === 'home').score,
                event.status.type.description
            );

            return game;
        });

        // Filter out matchups whose teams are TBD (i.e. playoff matchups before the regular season ends)
        const filteredGames = games.filter(game => game.away_team !== "TBD" && game.home_team !== "TBD");

        console.log(`List of games fetched for week ${week} of the ${season} season:`, filteredGames); 
        return filteredGames || [];

    } catch (error) {
        console.error('Error fetching games:', error);
        return [];
    }
}


export async function fetchGamesByTeamOnly(season, team_id) {
    console.log(`Fetching all games with team ID ${team_id} from the ${season} season.`);
}


export async function fetchGamesByTeamAndWeek(season, week, team_id) {
    console.log(`Fetching all games from with team ID ${team_id} from week ${week} of the ${season} season.`);
}