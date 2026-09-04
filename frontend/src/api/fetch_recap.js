import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

/*
    In-flight requests, keyed by URL.

    Recaps are expensive to build on the backend (a cache miss downloads a season of
    play-by-play and writes to the DB), so the same game must never be requested twice
    concurrently. StrictMode runs effects twice in dev, and a remount is enough to do it
    in prod, so guarding inside the component isn't sufficient — callers that ask for the
    same URL while a request is open share that request's promise instead of issuing
    another one.
*/
const inFlight = new Map();

export function fetchRecap(season, week, away_team, home_team, away_score, home_score) {
    const url = `${API_BASE_URL}/get_recap/${season}/${week}/${away_team}/${home_team}/${away_score}/${home_score}/`;

    const pending = inFlight.get(url);
    if (pending) return pending;

    console.log(`Fetching recap for ${away_team} at ${home_team}, week ${week}, season ${season}...`);

    const request = axios.get(url)
        .then((response) => ({ status: response.status, data: response.data }))
        .catch((error) => ({
            // axios throws on non-2xx; surface the status so the caller can branch on it.
            // status is 0 when the request never reached the server (network/CORS error).
            status: error.response?.status ?? 0,
            data: error.response?.data ?? null,
        }))
        // Only the in-flight window is shared; once it settles the next call refetches.
        .finally(() => { inFlight.delete(url); });

    inFlight.set(url, request);
    return request;
}
