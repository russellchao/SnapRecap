import { useState } from 'react'
import { fetchQa } from '../api/fetch_qa'
import './RecapSection.css'
import './AskAboutGame.css'

export default function AskAboutGame({ ledger, signals }) {
    const [question, setQuestion] = useState("");
    const [asking, setAsking] = useState(false);

    // The question the current answer belongs to, kept so the answer stays
    // labeled with what was asked even after the input is edited again.
    const [asked, setAsked] = useState(null);
    const [answer, setAnswer] = useState(null);
    const [error, setError] = useState(null);

    function handleAsk(event) {
        // The row is a form so Enter submits; neither path should reload the page.
        event.preventDefault();

        const trimmed = question.trim();
        if (!trimmed || asking) return;

        setAsking(true);
        setAsked(trimmed);
        setAnswer(null);
        setError(null);

        fetchQa(trimmed, ledger, signals)
            .then(({ status, data }) => {
                if (status === 200 && data?.answer) {
                    console.log("Received answer:", data.answer)
                    setAnswer(data.answer);
                    return;
                }
                // status is 0 when the request never reached the server; otherwise
                // FastAPI puts the reason in `detail`.
                setError(
                    status === 0
                        ? "Couldn't reach the server. Check your connection and try again."
                        : data?.detail ?? "Something went wrong answering that question."
                );
            })
            .finally(() => setAsking(false));
    }

    return (
        <section className="recap-section ask-about-game" id="ask">
            <div className="section-head">
                <h2>Ask About This Game</h2>
            </div>

            <p className="qa-hint">
                Ask about a specific play, a team's tendencies, or why the game swung the way it did.
            </p>

            <form className="qa-input-row" onSubmit={handleAsk}>
                <input
                    className="qa-input"
                    type="text"
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                    placeholder="e.g. Why did Buffalo's fourth-quarter drive succeed?"
                />
                <button className="qa-submit" type="submit" disabled={asking || !question.trim()}>
                    {asking ? "Asking…" : "Ask"}
                </button>
            </form>

            {(asking || answer || error) && (
                <div className="qa-response" role="status" aria-live="polite">
                    {asked && <p className="qa-asked">{asked}</p>}
                    {asking && <p className="qa-thinking">Working through the game data…</p>}
                    {answer && <p className="qa-answer">{answer}</p>}
                    {error && <p className="qa-error">{error}</p>}
                </div>
            )}
        </section>
    );
}
