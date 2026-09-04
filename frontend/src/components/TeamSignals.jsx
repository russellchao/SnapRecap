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
    points_per_trip_inside_40: "Pts / Trip Inside 40",
    early_down_success_rate: "Early Down Success",
    success_rate: "Success Rate",
    explosive_rate: "Explosive Rate",
    negative_play_rate: "Negative Play Rate",
    epa_per_pass: "EPA / Pass",
    epa_per_rush: "EPA / Rush",
    yards_per_pass: "Yards / Pass",
    yards_per_rush: "Yards / Rush",
    cpoe: "CPOE",
    sacks_forced: "Sacks Forced",
    tfl_rate: "TFL Rate",
    forced_fumble_rate: "Forced Fumbles",
    takeaway_rate: "Takeaway Rate",
    penalty_rate: "Penalty Rate",
    penalty_yards_per_drive: "Penalty Yds / Drive",
    starting_field_position: "Avg Starting FP",
    seconds_per_play: "Seconds / Play",
};

/*
    The backend record is flat ({signal_name: value}); the grouping lives here.
    Categories and their membership mirror the section headings the reductions
    are written under in backend/models/team_signals.py, and are rendered in
    this order. Any signal the backend adds that isn't listed here still shows,
    under "Other" at the end, so a new signal is never silently dropped.
*/
const SIGNAL_CATEGORIES = [
    {
        label: "Situational Efficiency",
        signals: [
            "third_down",
            "fourth_down",
            "red_zone_td",
            "points_per_trip_inside_40",
            "early_down_success_rate",
        ],
    },
    {
        label: "Overall Play Efficiency",
        signals: ["success_rate", "explosive_rate", "negative_play_rate"],
    },
    {
        label: "Passing / Rushing",
        signals: ["epa_per_pass", "epa_per_rush", "yards_per_pass", "yards_per_rush", "cpoe"],
    },
    {
        label: "Disruption / Havoc",
        signals: ["sacks_forced", "tfl_rate", "forced_fumble_rate", "takeaway_rate"],
    },
    {
        label: "Discipline / Field Position",
        signals: ["penalty_rate", "penalty_yards_per_drive", "starting_field_position"],
    },
    {
        label: "Pace",
        signals: ["seconds_per_play"],
    },
];

const CATEGORIZED_SIGNALS = new Set(SIGNAL_CATEGORIES.flatMap((category) => category.signals));

// Turn a raw backend key ("sacks_forced") into a display label.
function prettifyKey(key) {
    return (key ?? "")
        .split('_')
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ');
}

/*
    Signals arrive in two shapes (see backend/models/team_signals.py):
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

/*
    Field position arrives as yardline_100 — yards from the opponent's end
    zone — so it reads as a yard line rather than a bare number: rounded down
    to a whole yard, then named from the side of the field it falls on
    (69.9 -> "OWN 31", 45.2 -> "OPP 45", midfield -> just "50").
*/
function formatFieldPosition(value) {
    const mean = typeof value === "number" ? value : value?.mean;
    if (mean == null) return null;

    const yardsToOpponentEndZone = Math.floor(mean);
    if (yardsToOpponentEndZone === 50) return "50";
    if (yardsToOpponentEndZone > 50) return `OWN ${100 - yardsToOpponentEndZone}`;
    return `OPP ${yardsToOpponentEndZone}`;
}

// Signals whose chip value doesn't read well as a plain number.
const SIGNAL_FORMATTERS = {
    starting_field_position: formatFieldPosition,
};

// One category: its heading plus a chip per signal that came back with a
// value. Returns null when the record has none of this category's signals
// (an older cached row, say), so no bare heading is left behind.
function SignalGroup({ label, chips }) {
    if (!chips.length) return null;

    return (
        <div className="signal-group">
            <h4 className="signal-group-label">{label}</h4>
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

function SignalChips({ signals }) {
    const record = signals ?? {};
    const chipFor = (name) => [name, (SIGNAL_FORMATTERS[name] ?? formatSignal)(record[name])];
    const shown = ([, text]) => text != null;

    const groups = SIGNAL_CATEGORIES.map((category) => ({
        label: category.label,
        chips: category.signals.filter((name) => name in record).map(chipFor).filter(shown),
    }));

    // Anything the backend sends that this file doesn't know about yet.
    const uncategorized = Object.keys(record)
        .filter((name) => !CATEGORIZED_SIGNALS.has(name))
        .map(chipFor)
        .filter(shown);
    if (uncategorized.length) groups.push({ label: "Other", chips: uncategorized });

    return groups.map((group) => (
        <SignalGroup key={group.label} label={group.label} chips={group.chips} />
    ));
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
                        <SignalChips signals={column.signals.signals} />
                    </div>
                ))}
            </div>
        </section>
    );
}
