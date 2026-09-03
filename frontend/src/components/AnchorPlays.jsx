import SectionHead from './SectionHead'
import './RecapSection.css'
import './AnchorPlays.css'

const ABOUT = (
    <p>
        The handful of plays that swung the game the most, ranked by how much they moved each
        team's chances of winning. Later plays count for more, since a big play in the fourth
        quarter or OT matters more than one in the first.
    </p>
);

const PERIOD_SECONDS = 900;
const DOWN_NAMES = ["1st", "2nd", "3rd", "4th"];

// The game clock as it read on that snap. `game_seconds_remaining` counts down
// 3600 -> 0 across regulation and resets to 900 for each overtime period, so the
// two cases subtract different amounts of elapsed regulation.
function formatClock(qtr, gameSecondsRemaining) {
    if (gameSecondsRemaining == null || qtr == null) return null;
    const inPeriod = qtr >= 5
        ? gameSecondsRemaining
        : gameSecondsRemaining - (4 - qtr) * PERIOD_SECONDS;
    const secs = Math.min(Math.max(Math.round(inPeriod), 0), PERIOD_SECONDS);
    return `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')}`;
}

// Anything past the fourth quarter is overtime, not "Q5"/"Q6".
function formatQuarter(qtr) {
    if (qtr == null) return "";
    return qtr >= 5 ? "OT" : `Q${qtr}`;
}

// yardline_100 is yards to the opponent's end zone, so it has to be flipped back
// into the "TEAM yardline" form a box score uses.
function formatFieldPosition(play) {
    const yl = play?.yardline_100;
    if (yl == null) return null;
    if (yl === 50) return "the 50";
    return yl < 50 ? `${play.defteam ?? ""} ${yl}`.trim() : `${play.posteam ?? ""} ${100 - yl}`.trim();
}

function formatSituation(play) {
    const down = play?.down != null ? DOWN_NAMES[play.down - 1] : null;
    const spot = formatFieldPosition(play);

    if (!down) return spot ? `From ${spot}` : null;
    const distance = play.goal_to_go ? "Goal" : play.ydstogo;
    return spot ? `${down} & ${distance} from ${spot}` : `${down} & ${distance}`;
}

// Rendered ".24" / "−.24" — the leading zero adds nothing at this size, but the
// sign says which way the swing went for the team that had the ball.
function formatWpa(wpa) {
    return `${wpa >= 0 ? "+" : "−"}${Math.abs(wpa).toFixed(2).replace(/^0/, '')}`;
}

export default function AnchorPlays({ plays, homeAbbr, colors }) {
    // The backend ranks anchors by |WPA| x recency, but that composite weight isn't
    // stored on the row, so they're re-sorted here by the magnitude alone.
    const anchors = (plays ?? [])
        .filter((play) => play?.wpa != null)
        .slice()
        .sort((a, b) => Math.abs(b.wpa) - Math.abs(a.wpa));
    if (!anchors.length) return null;

    const maxAbs = Math.max(...anchors.map((play) => Math.abs(play.wpa)));

    return (
        <section className="recap-section anchor-plays" id="anchor-plays" style={colors}>
            <SectionHead title="Anchor Plays" about={ABOUT} />

            <div className="anchor-scroll">
                {anchors.map((play) => {
                    const side = play.posteam === homeAbbr ? "home" : "away";
                    const clock = formatClock(play.qtr, play.game_seconds_remaining);
                    const situation = formatSituation(play);

                    return (
                        <div className={`anchor-card ${side}`} key={play.play_id}>
                            <div className="anchor-meta">
                                <span className="anchor-qtr">
                                    {formatQuarter(play.qtr)}{clock ? ` · ${clock}` : ""}
                                </span>
                                <span className="anchor-team-tag">{play.posteam}</span>
                            </div>

                            {situation && <div className="anchor-situation">{situation}</div>}
                            <div className="anchor-desc">{play.description}</div>

                            <div className="anchor-mag">
                                <div className="anchor-mag-bar">
                                    <div
                                        className="anchor-mag-fill"
                                        style={{ width: `${(Math.abs(play.wpa) / maxAbs) * 100}%` }}
                                    />
                                </div>
                                <span className="anchor-mag-val">WPA {formatWpa(play.wpa)}</span>
                            </div>
                        </div>
                    );
                })}
            </div>
        </section>
    );
}
