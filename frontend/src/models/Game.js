export default class Game {
  constructor(
    espn_id, game_headline, start_date, season, week, away_team, home_team, away_score, home_score, status
  ) {
    this.espn_id = espn_id
    this.game_headline = game_headline // e.g. 'Super Bowl', 'International Series', or could be 'None'
    this.start_date = start_date
    this.season = season
    this.week = week
    this.away_team = away_team
    this.home_team = home_team
    this.away_score = away_score
    this.home_score = home_score
    this.status = status
  }
}
