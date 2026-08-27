import './RecapSection.css'
import './GameLedger.css'

// Display labels for the backend's ledger categories, in the order they're shown.
// A category the backend adds later still renders — appended at the bottom under
// a prettified version of its raw key.
const LEDGER_LABELS = {
    explosive_plays: "Explosive Plays",
    third_down: "3rd Down",
    turnovers: "Turnovers",
    red_zone: "Red Zone",
    pass_protection: "Pressure / Sacks",
    special_teams: "Special Teams",
    penalties: "Penalties",
    other: "Other",
};

// Widest a bar may get, as a share of its half of the row. Leaves room for the
// value label sitting just past the bar's end.
const MAX_BAR_PCT = 78;

// Turn a raw backend key ("pass_protection") into a display label.
function prettifyKey(key) {
    return (key ?? "")
        .split('_')
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ');
}

function orderedCategories(categories) {
    const known = Object.keys(LEDGER_LABELS);
    const rank = (name) => (known.indexOf(name) === -1 ? known.length : known.indexOf(name));
    return Object.entries(categories ?? {}).sort(([a], [b]) => rank(a) - rank(b));
}

// diff is home_ep - away_ep, so its sign is the whole point: it's always shown.
// A true minus sign keeps the same width as the "+".
function formatDiff(diff) {
    return `${diff >= 0 ? "+" : "−"}${Math.abs(diff).toFixed(2)}`;
}

function LedgerRow({ name, category, maxAbs }) {
    const diff = Number(category?.diff ?? 0);
    // A positive diff means the home team gained in this category, so its bar
    // grows to the right of the center axis; the away team's grows left.
    const homeSide = diff >= 0;
    const width = maxAbs > 0 ? `${(Math.abs(diff) / maxAbs) * MAX_BAR_PCT}%` : "0%";
    // "Other" is a catch-all rather than a real category, so it stays neutral gray.
    const barClass = name === "other" ? "other" : (homeSide ? "home" : "away");

    const bar = (
        <>
            <div className={`ledger-bar ${barClass}`} style={{ width }} />
            <span className="ledger-value">{formatDiff(diff)}</span>
        </>
    );

    return (
        <div className="ledger-row">
            <div className="ledger-axis" />
            <div className="ledger-bar-track left">{homeSide ? null : bar}</div>
            <div className="ledger-label">{LEDGER_LABELS[name] ?? prettifyKey(name)}</div>
            <div className="ledger-bar-track right">{homeSide ? bar : null}</div>
        </div>
    );
}

export default function GameLedger({ ledger, awayAbbr, homeAbbr }) {
    const categories = orderedCategories(ledger?.categories);
    if (!categories.length) return null;

    // Bars are scaled against the game's largest swing, so their widths read
    // relative to each other rather than against an absolute EP scale.
    const maxAbs = Math.max(...categories.map(([, c]) => Math.abs(Number(c?.diff ?? 0))), 0);

    return (
        <section className="recap-section game-ledger" id="ledger">
            <div className="section-head">
                <h2>Game Margin Ledger</h2>
                <span className="meta">Expected points, by category</span>
            </div>

            <div className="ledger-teams">
                <span className="tag away">{awayAbbr}</span>
                <span className="tag home">{homeAbbr}</span>
            </div>

            {categories.map(([name, category]) => (
                <LedgerRow key={name} name={name} category={category} maxAbs={maxAbs} />
            ))}

            <div className="ledger-foot">
                <span>
                    Total EPA diff:{" "}
                    <span className="reconcile">{formatDiff(Number(ledger.total_epa_diff ?? 0))}</span>
                </span>
                <span>
                    Team with the advantage:{" "}
                    <span className="reconcile">
                        {ledger.total_epa_diff > 0 ? homeAbbr : ledger.total_epa_diff < 0 ? awayAbbr : "Tie"}
                    </span>
                </span>
            </div>
        </section>
    );
}
