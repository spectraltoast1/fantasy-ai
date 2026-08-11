// The data-access seam. Every view imports its loader from here; the loaders keep their
// exact names, params, and return shapes — only the bodies changed. As of Session 5 of the
// store migration they no longer run DuckDB-WASM SQL over parquet in the browser; each is a
// thin client for the FastAPI endpoint that returns the same shape (built in Sessions 3–4,
// backed by Postgres). In dev, Vite proxies `/api` → the local uvicorn (see vite.config.js);
// the deployed cross-origin/CORS story is Session 6.

export const POS = ['QB', 'RB', 'WR', 'TE'];

const API = '/api';

// The active slice (Stage-B B5): { league_id, season, viewer_roster_id }. A module-level value —
// like the old MY_USERNAME constant — that `apiGet` merges into EVERY request, so the view
// components keep calling loadPlayers(asOfWeek) etc. unchanged while the whole app follows the
// selected league/season/viewer. App sets it SYNCHRONOUSLY on a slice switch, before the reloads
// fire. Empty {} until the first slice is set → the server falls back to the is_mine default (parity).
let _slice = {};

// Set the active slice. Pass the fields you have; nulls/undefined are dropped per-request by apiGet.
export function setActiveSlice(slice) {
  _slice = slice || {};
}

// The caller's access token (P5/S1), or null when signed out. Same shape as `_slice` above and
// for the same reason: this is the ONE place a request is assembled, so it is the one place
// auth attaches — no view component learns that auth exists. App publishes it from Supabase's
// onAuthStateChange, which fires on sign-in, sign-out AND token refresh; a token that stops
// being republished on refresh silently starts failing an hour after sign-in.
let _token = null;

// Set (or clear, with null) the bearer token sent on every subsequent request.
export function setAuthToken(token) {
  _token = token || null;
}

// Called when the server REJECTS our token (401), after this module has already dropped it and
// retried anonymously. App wires it to supabase.auth.signOut() — see the retry in `apiGet` for why
// clearing the token here is not enough on its own.
let _onAuthRejected = null;
export function setOnAuthRejected(fn) {
  _onAuthRejected = fn;
}

// GET `${API}${path}` with the active slice + per-call `params` as the query string. `as_of_week`
// (or any null/undefined param) is OMITTED so the server applies its "latest week" default — the
// old `n == null → latest` seam; unset slice fields drop the same way. Per-call params win on a key
// collision. Throws on a non-2xx, mirroring the DuckDB-era `query()` so views' existing
// loading/error states keep working. Returns the parsed JSON (which may be `null` — e.g. an
// unknown roster/matchup — matching the old loaders).
//
// P5/S2b retired the assumption this function was written under. It used to say "every read
// endpoint's error is a developer problem the user never sees", which was true while reads could
// not fail for auth reasons. Now EVERY read is scoped, so a stale token turns all twelve into
// failures at once — and the app-shell loaders only console.error, which means a permanent
// "Loading…" rather than an error.
//
// So: on 401, drop the token and retry ONCE anonymously. That alone does not rescue the app — the
// active slice still names a league the anonymous caller cannot see, so the retry 404s — which is
// why we also tell App, via `setOnAuthRejected`, to sign out properly. That transition clears the
// slice and refetches the catalog, and landing on the public demo is the whole point: strictly less
// access than the user had, never more, and the server still refuses the bad token either way.
//
// 503 is deliberately treated differently: it is retried anonymously (so the demo still renders)
// but the token is KEPT and nobody is signed out. A verifier outage or a Fly cold-start is
// transient, and signing someone out over it would be a worse bug than the one being handled.
async function apiGet(path, params = {}) {
  const qs = Object.entries({ ..._slice, ...params })
    .filter(([, v]) => v != null)
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&');
  const url = `${API}${path}${qs ? `?${qs}` : ''}`;
  // Snapshot the token: a background TOKEN_REFRESHED landing mid-flight must not have its fresh
  // token discarded by our retry, and `retried` (not "is _token null now?") is what bounds this to
  // one extra request.
  const sent = _token;
  let res = await fetch(url, sent ? { headers: { Authorization: `Bearer ${sent}` } } : undefined);

  const rejected = Boolean(sent) && res.status === 401;      // our credential was refused
  const unavailable = Boolean(sent) && res.status === 503;   // the verifier was, transiently
  if (rejected || unavailable) {
    const authStatus = res.status;
    if (rejected && _token === sent) setAuthToken(null);
    res = await fetch(url);
    // Sign out ONLY for a genuine 401, and only once the anonymous retry shows the server is
    // reachable — otherwise an outage would sign everyone out on its way past.
    if (rejected && res.status !== 401 && _onAuthRejected) _onAuthRejected();
    if (!res.ok) {
      // Report the status that actually explains it. Without this the console says "unknown
      // league_id" for a league the user owns, which is the most misleading message available.
      const err = new Error(`GET ${path} → ${authStatus} (anonymous retry → ${res.status})`);
      err.status = authStatus;
      err.retriedAnonymously = true;
      throw err;
    }
    return res.json();
  }

  if (!res.ok) {
    const err = new Error(`GET ${path} → ${res.status}`);
    err.status = res.status;   // `apiPost` has always done this; callers could not branch without it
    throw err;
  }
  return res.json();
}

// POST a JSON body (P5/S1b — the first write from the client). Two things `apiGet` can't do, and
// both matter here rather than being style:
//   1. it merges the active `_slice` into every request, and an auth call has no business
//      carrying a `league_id`;
//   2. it discards the response body on a non-2xx. Every read endpoint's error is a developer
//      problem the user never sees, so throwing the status was enough. Signup is the first
//      endpoint whose message IS the feature — "that access code isn't right" has to reach the
//      person typing it — so this surfaces the server's `detail`.
// Same seam rule as `apiGet`: this is where a request is assembled, so it's where the token
// attaches. Views still never touch fetch.
export async function apiPost(path, body) {
  const res = await fetch(`${API}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(_token ? { Authorization: `Bearer ${_token}` } : {}),
    },
    body: JSON.stringify(body ?? {}),
  });
  let payload = null;
  try {
    payload = await res.json();
  } catch {
    payload = null;   // a proxy error page or an empty body — fall through to the status
  }
  if (!res.ok) {
    const err = new Error(payload?.detail || `POST ${path} → ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return payload;
}

// --- Auth (P5/S1b) -----------------------------------------------------------------------
// Ask the server to email a sign-in link. The access code is checked SERVER-side — the client
// only carries it. Throws with the server's message on refusal, which the sign-in form shows.
export const requestSignInLink = (email, code) => apiPost('/signup', { email, code });

// --- Shared chrome -----------------------------------------------------------------------
export const loadWeeks = () => apiGet('/weeks');
export const loadLeagueMeta = (asOfWeek) => apiGet('/league-meta', { as_of_week: asOfWeek });

// --- Catalog (Stage-B B3) — the lineage→seasons tree the B5 league/season switcher reads.
export const loadLeagues = () => apiGet('/leagues');

// --- Players tab -------------------------------------------------------------------------
export const loadPlayers = (asOfWeek) => apiGet('/players', { as_of_week: asOfWeek });
export const loadPlayerCard = (sleeperId, asOfWeek) =>
  apiGet(`/players/${encodeURIComponent(sleeperId)}`, { as_of_week: asOfWeek });

// --- Teams tab ---------------------------------------------------------------------------
export const loadStandings = (asOfWeek) => apiGet('/standings', { as_of_week: asOfWeek });
export const loadTeamDetail = (rosterId, asOfWeek) =>
  apiGet(`/teams/${rosterId}`, { as_of_week: asOfWeek });
export const loadManagerDossier = (rosterId) => apiGet(`/managers/${rosterId}`);

// --- League tab --------------------------------------------------------------------------
export const loadLeague = (asOfWeek) => apiGet('/league', { as_of_week: asOfWeek });
export const loadPositionalTalent = () => apiGet('/positional-talent');

// --- Matchups tab ------------------------------------------------------------------------
export const loadMatchups = (asOfWeek) => apiGet('/matchups', { as_of_week: asOfWeek });
export const loadMatchupDetail = (matchupId, asOfWeek) =>
  apiGet(`/matchups/${matchupId}`, { as_of_week: asOfWeek });
