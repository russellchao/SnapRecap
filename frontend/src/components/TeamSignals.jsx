import './RecapSection.css'
import './TeamSignals.css'

const SIGNAL_LABELS = {
    // Offense
    third_down: "3rd Down",
    fourth_down: "4th Down",
    red_zone_td: "Red Zone TD",
    success_rate: "Success Rate",
    explosive_rate: "Explosive Rate",
    sack_rate: "Sacks Allowed",
    epa_per_play: "EPA / Play",
    epa_per_pass: "EPA / Pass",
    epa_per_rush: "EPA / Rush",
    yards_per_play: "Yards / Play",
    yards_per_rush: "Yards / Rush",
    cpoe: "CPOE",
    personnel: "Personnel",
    // Defense
    third_down_allowed: "3rd Down Allowed",
    red_zone_td_allowed: "Red Zone TD Allowed",
    success_rate_allowed: "Success Rate Allowed",
    explosive_rate_allowed: "Explosive Rate Allowed",
    epa_per_play_allowed: "EPA / Play Allowed",
    epa_per_pass_allowed: "EPA / Pass Allowed",
    epa_per_rush_allowed: "EPA / Rush Allowed",
    yards_per_play_allowed: "Yards / Play Allowed",
    yards_per_rush_allowed: "Yards / Rush Allowed",
    pressure_rate: "Pressure Rate",
    sacks: "Sack Rate",
    blitz_rate: "Blitz Rate",
    avg_box_defenders: "Box Defenders",
    coverage: "Coverage",
    man_zone: "Man / Zone",
};

// Turn a raw backend key ("blitz_rate") into a display label.
function prettifyKey(key) {
    return (key ?? "")
        .split('_')
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ');
}

/*
    Signals arrive in three shapes (see backend/models/signals.py):
      RateSignal   -> { attempts, successes, rate }
      MeanSignal   -> { n, mean }
      distribution -> { label: share, ... }

    Each collapses into one short chip value. A null rate/mean means the signal
    had no qualifying plays, so the chip is dropped entirely rather than shown
    as an empty stat.
*/
function formatSignal(value) {
    if (value == null) return null;
    if (typeof value === "number") return value.toFixed(2);
    if (typeof value !== "object") return String(value);

    if ("rate" in value) {
        if (value.rate == null) return null;
        return `${value.successes}/${value.attempts} · ${(value.rate * 100).toFixed(0)}%`;
    }
    if ("mean" in value) {
        if (value.mean == null) return null;
        return value.mean.toFixed(2);
    }

    // Distribution: only the most-used option is worth a chip.
    const entries = Object.entries(value);
    if (!entries.length) return null;
    const [label, share] = entries.reduce((best, entry) => (entry[1] > best[1] ? entry : best));
    return `${label} · ${(share * 100).toFixed(0)}%`;
}

function SignalGroup({ label, signals }) {
    const chips = Object.entries(signals ?? {})
        .map(([name, value]) => [name, formatSignal(value)])
        .filter(([, text]) => text != null);
    if (!chips.length) return null;

    return (
        <div className="signal-group">
            <div className="signal-group-label">{label}</div>
            <div className="signal-chips">
                {chips.map(([name, text]) => (
                    <span className="chip" key={name}>
                        <span className="chip-label">{SIGNAL_LABELS[name] ?? prettifyKey(name)}</span>
                        <span className="chip-value">{text}</span>
                    </span>
                ))}
            </div>
        </div>
    );
}

export default function TeamSignals({ signals, awayName, homeName, awayAbbr, homeAbbr }) {
    const columns = [
        { side: "away", name: awayName || awayAbbr, signals: signals?.[awayAbbr] },
        { side: "home", name: homeName || homeAbbr, signals: signals?.[homeAbbr] },
    ].filter((column) => column.signals);
    if (!columns.length) return null;

    return (
        <section className="recap-section team-signals" id="team-signals">
            <div className="section-head">
                <h2>Team Signals</h2>
                <span className="meta">Situational tendencies, both sides</span>
            </div>

            <div className="signals-grid">
                {columns.map((column) => (
                    <div className={`signals-col ${column.side}`} key={column.side}>
                        <div className="signals-col-head">
                            <span className="signals-dot" />
                            <h3>{column.name}</h3>
                        </div>
                        <SignalGroup label="Offense" signals={column.signals.offense} />
                        <SignalGroup label="Defense" signals={column.signals.defense} />
                    </div>
                ))}
            </div>
        </section>
    );
}
