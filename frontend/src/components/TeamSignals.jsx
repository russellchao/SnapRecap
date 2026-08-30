import SectionHead from './SectionHead'
import './RecapSection.css'
import './TeamSignals.css'

const ABOUT = (
    <p>
        A side-by-side look at how each team actually played — third-down conversions, red zone
        trips, turnovers, and other tendencies — beyond what the box score shows.
    </p>
);

const SIGNAL_LABELS = {
    third_down: "3rd Down",
    fourth_down: "4th Down",
    red_zone_td: "Red Zone TD",
    success_rate: "Success Rate",
    explosive_rate: "Explosive Rate",
    epa_per_play: "EPA / Play",
    epa_per_pass: "EPA / Pass",
    epa_per_rush: "EPA / Rush",
    yards_per_play: "Yards / Play",
    yards_per_rush: "Yards / Rush",
    cpoe: "CPOE",
    sacks_forced: "Sacks Forced",
};

// Turn a raw backend key ("sacks_forced") into a display label.
function prettifyKey(key) {
    return (key ?? "")
        .split('_')
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ');
}

/*
    Signals arrive in two shapes (see backend/models/signals.py):
      RateSignal -> { attempts, successes, rate }
      MeanSignal -> { n, mean }

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

    return null;
}

function SignalChips({ signals }) {
    const chips = Object.entries(signals ?? {})
        .map(([name, value]) => [name, formatSignal(value)])
        .filter(([, text]) => text != null);
    if (!chips.length) return null;

    return (
        <div className="signal-group">
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

export default function TeamSignals({ signals, awayName, homeName, awayAbbr, homeAbbr, colors }) {
    const columns = [
        { side: "away", name: awayName || awayAbbr, signals: signals?.[awayAbbr] },
        { side: "home", name: homeName || homeAbbr, signals: signals?.[homeAbbr] },
    ].filter((column) => column.signals);
    if (!columns.length) return null;

    return (
        <section className="recap-section team-signals" id="team-signals" style={colors}>
            <SectionHead title="Team Signals" about={ABOUT} />

            <div className="signals-grid">
                {columns.map((column) => (
                    <div className={`signals-col ${column.side}`} key={column.side}>
                        <div className="signals-col-head">
                            <span className="signals-dot" />
                            <h3>{column.name}</h3>
                        </div>
                        <SignalChips signals={column.signals} />
                    </div>
                ))}
            </div>
        </section>
    );
}
