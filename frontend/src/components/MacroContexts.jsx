import SectionHead from './SectionHead'
import './RecapSection.css'
import './MacroContexts.css'

const ABOUT = (
    <p>
        The game's story in plain language: the plays that won it, the ones that cost the losing
        team most, and how each offense moved before and after an injury. The numbers pick what
        mattered here, so nothing is said that didn't happen on the field.
    </p>
);

/*
    The backend keys each macro context by `context_type` (see MACRO_CONTEXT_VERSIONS
    in backend/get_recap.py) and hands back the whole DB row per type, not the bare
    text: { game_id, context_type, content: { text }, version }.

    Rendered in this order. A context type the backend adds later is ignored here
    rather than rendered untitled — unlike Team Signals' chips, a narrative block
    needs a heading and a team to attribute it to, and neither can be guessed from
    the key.
*/
const CONTEXT_ORDER = ["winners_best_plays", "losers_biggest_mistakes", "injury_impact"];

// Pull the prose out of a macro_contexts row. `content` is a jsonb column, so a
// row that made it this far has an object with the text under `text`.
function textOf(row) {
    const text = row?.content?.text;
    return typeof text === "string" && text.trim() ? text : null;
}

// Possessive form of a team name. Five NFL cities end in an s — Dallas, Las
// Vegas, Los Angeles, New Orleans, Indianapolis — and those take a bare
// apostrophe, the way they're written about ("Dallas' best plays").
function possessive(name) {
    return name.endsWith('s') || name.endsWith('S') ? `${name}'` : `${name}'s`;
}

/*
    Title, and which team the block belongs to, per context type.

    `side` picks the accent the card is painted with — "home"/"away" track the two
    teams' brand colors (--rc-home / --rc-away, set per matchup by theme/team_colors.js),
    and null falls back to the page accent for a block that belongs to neither team.
*/
function describeContext(contextType, { winner, loser }) {
    switch (contextType) {
        case "winners_best_plays":
            // A tie has no winner, and the backend writes no row for it — but a stale
            // row from before a score correction could still arrive, so guard anyway.
            return winner && { title: `${possessive(winner.name)} Best Plays`, tag: "Winner", side: winner.side };
        case "losers_biggest_mistakes":
            return loser && { title: `${possessive(loser.name)} Biggest Mistakes`, tag: "Loser", side: loser.side };
        case "injury_impact":
            // Belongs to whichever teams got hurt, which isn't known until the text
            // is read — so no tag, and the neutral page accent.
            return { title: "Injury Impact", tag: null, side: null };
        default:
            return null;
    }
}

function MacroCard({ title, tag, side, text }) {
    return (
        <article className={`macro-card ${side ?? "neutral"}`}>
            <div className="macro-card-head">
                <h3>{title}</h3>
                {tag && <span className="macro-tag">{tag}</span>}
            </div>
            <p className="macro-text">{text}</p>
        </article>
    );
}

export default function MacroContexts({ contexts, awayName, homeName, awayAbbr, homeAbbr, awayScore, homeScore, colors }) {
    // Who won decides which card is whose, and which team color it wears. Scores
    // arrive as strings from the games list, so compare them numerically; a tie
    // leaves both sides null and only the injury block renders.
    const away = { name: awayName || awayAbbr, side: "away" };
    const home = { name: homeName || homeAbbr, side: "home" };
    const decided = Number(awayScore) !== Number(homeScore);
    const awayWon = Number(awayScore) > Number(homeScore);
    const winner = decided ? (awayWon ? away : home) : null;
    const loser = decided ? (awayWon ? home : away) : null;

    const cards = CONTEXT_ORDER
        .map((contextType) => {
            const text = textOf(contexts?.[contextType]);
            if (!text) return null;
            const described = describeContext(contextType, { winner, loser });
            return described && { key: contextType, ...described, text };
        })
        .filter(Boolean);

    // Nothing phrased for this game yet — leave the section out entirely rather
    // than show an empty card, same as the other recap sections.
    if (!cards.length) return null;

    return (
        <section className="recap-section macro-contexts" id="macro-contexts" style={colors}>
            <SectionHead title="Macro Context" about={ABOUT} />

            <div className="macro-grid">
                {cards.map(({ key, ...card }) => <MacroCard key={key} {...card} />)}
            </div>
        </section>
    );
}
