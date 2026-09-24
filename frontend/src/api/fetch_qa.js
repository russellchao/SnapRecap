import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

/*
    In-flight requests, keyed by question text.

    Answering a question routes through an LLM and then hits the DB, so a double-click
    on "Ask" (or a StrictMode-induced double effect) must not pay for the same answer
    twice. Callers asking the identical question while a request is open share that
    request's promise instead of issuing another one.
*/
const inFlight = new Map();

export function fetchQa(question, game_ledger, team_signals) {
    const url = `${API_BASE_URL}/ask_question`;

    const pending = inFlight.get(question);
    if (pending) return pending;

    console.log(`Asking "${question}" at ${url}`);

    // The recap page already holds these in memory from /get_recap, so they're passed
    // through rather than making the backend rebuild them.
    const body = {
        question,
        game_ledger: game_ledger ?? null,
        team_signals: team_signals ?? {},
    };

    const request = axios.post(url, body)
        .then((response) => ({ status: response.status, data: response.data }))
        .catch((error) => ({
            // axios throws on non-2xx; surface the status so the caller can branch on it.
            // status is 0 when the request never reached the server (network/CORS error).
            status: error.response?.status ?? 0,
            data: error.response?.data ?? null,
        }))
        // Only the in-flight window is shared; once it settles the next call refetches.
        .finally(() => { inFlight.delete(question); });

    inFlight.set(question, request);
    return request;
}
