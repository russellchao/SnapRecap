import { useState } from 'react'
import './RecapSection.css'
import './AskAboutGame.css'

export default function AskAboutGame() {
    const [question, setQuestion] = useState("");

    return (
        <section className="recap-section ask-about-game" id="ask">
            <div className="section-head">
                <h2>Ask About This Game</h2>
                <span className="meta">Routed &amp; grounded in the data above</span>
            </div>

            <p className="qa-hint">
                Ask about a specific play, a team's tendencies, or why the game swung the way it did.
            </p>

            <div className="qa-input-row">
                <input
                    className="qa-input"
                    type="text"
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                    placeholder="e.g. Why did Buffalo's fourth-quarter drive succeed?"
                />
                {/* TODO: wire this up to the backend's /ask_question endpoint. */}
                <button className="qa-submit" type="button">Ask</button>
            </div>
        </section>
    );
}
