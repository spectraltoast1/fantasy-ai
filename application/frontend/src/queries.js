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

// GET `${API}${path}` with the active slice + per-call `params` as the query string. `as_of_week`
// (or any null/undefined param) is OMITTED so the server applies its "latest week" default — the
// old `n == null → latest` seam; unset slice fields drop the same way. Per-call params win on a key
// collision. Throws on a non-2xx, mirroring the DuckDB-era `query()` so views' existing
// loading/error states keep working. Returns the parsed JSON (which may be `null` — e.g. an
// unknown roster/matchup — matching the old loaders).
async function apiGet(path, params = {}) {
  const qs = Object.entries({ ..._slice, ...params })
    .filter(([, v]) => v != null)
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&');
  const res = await fetch(`${API}${path}${qs ? `?${qs}` : ''}`);
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`);
  return res.json();
}

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
