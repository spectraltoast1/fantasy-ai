# Session 5 — Frontend becomes an API client — a brief for Code

**Last reviewed:** 2026-07-25 · **Status:** Ready to run · **Owner:** Code (Will operates + eyeballs)

> **What this session does:** flip the frontend off in-browser DuckDB-WASM and onto the FastAPI endpoints built
> in Sessions 3–4. `queries.js` stops running SQL and becomes a thin **API client** — each loader does
> `fetch('/api/…')` and returns the JSON. `db.js` (DuckDB-WASM) and the `@duckdb/duckdb-wasm` dependency are
> **deleted**. This is the first *visible* milestone of the migration: the app looks and behaves identically,
> but every number now comes from Postgres over HTTP instead of parquet in the browser. Stage A of
> `MULTI_LEAGUE_STORE_MIGRATION.md` (A4). Still single-league, no auth, no multi-league selectors.
>
> **Why this is low-risk:** the endpoints already return the **exact shapes** the loaders return today (proven
> in the Session 3 & 4 audits), and **every view imports only the loaders** — so the loaders keep their names,
> params, and return shapes, only their bodies change, and **no view is touched.** `queries.js` goes from ~1000
> lines to ~30.

## Your part, Will (~15 minutes)
Kick off with the brief below. At the end Code will run the app for real (API + frontend together) and click
through every tab. Your "looks right" is: the dashboard renders exactly as it does today, the browser's network
tab shows `/api/*` JSON calls (no more `.parquet` fetches, no DuckDB worker), and the console is clean.

## The seam facts (already confirmed against the live repo)

- **Views import only loaders** (+ the `POS` constant): `App.jsx`→`loadWeeks`/`loadLeagueMeta`;
  `Players.jsx`→`loadPlayers`,`POS`; `PlayerCard.jsx`→`loadPlayerCard`; `Teams.jsx`→`loadStandings`;
  `TeamDetail.jsx`→`loadTeamDetail`; `Dossier.jsx`→`loadManagerDossier`; `League.jsx`→`loadLeague`,
  `loadPositionalTalent`,`POS`; `Matchups.jsx`→`loadMatchups`; `MatchupDetail.jsx`→`loadMatchupDetail`.
- **`db.js` is imported only by `queries.js`** (`import { query } from './db.js'`). **`posture.js` is imported
  only by `queries.js`** (`derivePosture` — now computed server-side in `load_standings`, so it's dead).
  **`MY_USERNAME` is used only inside `queries.js`.** All three are safe to remove without touching a view.
- **`POS` must stay exported** from `queries.js` (`Players.jsx`/`League.jsx` import it) — it's a pure constant.
- Current `vite.config.js` has DuckDB-specific bits (`optimizeDeps.exclude: ['@duckdb/duckdb-wasm']`, `esnext`
  targets) and `server: { host: true, port: 5173 }`. `package.json` deps: `@duckdb/duckdb-wasm ^1.29.0`, react,
  react-dom. Dev script is just `vite`. Dev runner is `.claude/launch.json`.

## Decisions I made for you (Code: follow unless you hit a reason not to)

1. **Loaders keep their exact names, params, and return shapes** — only the body changes to `fetch`. The views
   import them by name; a changed signature or shape is the one thing that breaks a view.
2. **A tiny shared `apiGet(path, params)` helper** builds the query string (**omit `as_of_week` when it's
   null/undefined** so the server defaults to latest — that's the existing "n == null → latest" seam),
   `fetch`es, throws on `!res.ok` (mirroring today's `query()` which throws, so existing loading/error states
   keep working), and returns `res.json()`. Path params (`sleeperId`/`rosterId`/`matchupId`) interpolate into
   the path.
3. **Vite dev proxy, not a hardcoded URL.** Add `server.proxy` so `/api` → `http://localhost:8000` (uvicorn).
   The frontend calls relative `/api/…`; the proxy forwards it. (Same-origin in dev → no CORS. The *deployed*
   app's cross-origin/CORS story is **Session 6**, not now.)
4. **Delete `db.js` and the `@duckdb/duckdb-wasm` dep** (`npm uninstall @duckdb/duckdb-wasm` so the lockfile
   updates), and drop the now-dead DuckDB bits from `vite.config.js`. `posture.js` is now dead — deleting it is
   fine (the server owns posture), but leaving it is harmless; your call.
5. **Views are UNTOUCHED.** If you find yourself needing to edit a view to make it render, **stop** — that means
   an endpoint's shape diverged from the loader contract, and the fix belongs in the *endpoint*, not the view.
6. **No null-policy work this session.** The current data has **zero nulls** in every rendered column (verified
   in the S4 audit), so parity holds as-is. The null-safe policy (adopt `projections._num` across the older
   reads) is a **Stage-B prerequisite** — it only matters once multi-league/historical data introduces nulls.
   Don't pull it into the swap.
7. **No Stage-B work.** Keep `MY_USERNAME` semantics as they are server-side (don't refactor to
   `viewer_roster_id`); no league/season selectors. Local uvicorn reads `config.py`, so it runs without the Fly
   secrets (those are a Session-6 deploy item).

## The loader rewrite (the whole of `queries.js` after this session)

Keep `export const POS = ['QB','RB','WR','TE'];` and the `apiGet` helper; replace all 11 loaders with thin
calls; delete everything else (the SQL, `MY_USERNAME`, `seriesRead`/`num`/`round1`/`asOfSlice`/`weekCutoff`,
`teamProjections`/`teamMatchupSummary`/`expandSlots`/`optimalLineup`/`normalCdf`/`erf`/`matchupWinProbs`/
`recordsByRoster`/`targetWeekFor`/`SQL_STANDINGS_WEEKS`/`matchupPlayerView`/`attachSpectrumPos`/`cv`/
`SHAPE_LABEL`, and the `db.js`/`posture.js` imports).

| Loader (unchanged signature) | Becomes |
|---|---|
| `loadWeeks()` | `apiGet('/weeks')` |
| `loadLeagueMeta(asOfWeek)` | `apiGet('/league-meta', { as_of_week: asOfWeek })` |
| `loadPlayers(asOfWeek)` | `apiGet('/players', { as_of_week: asOfWeek })` |
| `loadPlayerCard(sleeperId, asOfWeek)` | `apiGet('/players/${encodeURIComponent(sleeperId)}', { as_of_week: asOfWeek })` |
| `loadStandings(asOfWeek)` | `apiGet('/standings', { as_of_week: asOfWeek })` |
| `loadTeamDetail(rosterId, asOfWeek)` | `apiGet('/teams/${rosterId}', { as_of_week: asOfWeek })` |
| `loadManagerDossier(rosterId)` | `apiGet('/managers/${rosterId}')` |
| `loadLeague(asOfWeek)` | `apiGet('/league', { as_of_week: asOfWeek })` |
| `loadPositionalTalent()` | `apiGet('/positional-talent')` |
| `loadMatchups(asOfWeek)` | `apiGet('/matchups', { as_of_week: asOfWeek })` |
| `loadMatchupDetail(matchupId, asOfWeek)` | `apiGet('/matchups/${matchupId}', { as_of_week: asOfWeek })` |

Reference `apiGet` (adapt as you see fit — the null-omit and throw-on-error behaviors are the load-bearing parts):

```js
const API = '/api';
async function apiGet(path, params = {}) {
  const qs = Object.entries(params)
    .filter(([, v]) => v != null)               // omit as_of_week when null → server defaults to latest
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&');
  const res = await fetch(`${API}${path}${qs ? `?${qs}` : ''}`);
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`);   // matches today's query() throwing
  return res.json();
}
```

## The brief to paste to Code

```
Goal: Session 5 of the store migration (Stage A, MULTI_LEAGUE_STORE_MIGRATION.md A4). Flip the frontend from
in-browser DuckDB-WASM to the FastAPI endpoints built in Sessions 3-4. Rewrite application/frontend/src/queries.js
as a thin API client, delete db.js + the @duckdb/duckdb-wasm dependency, add a Vite dev proxy, and run the app
end-to-end. Do NOT touch any view component, and do NOT start multi-league/selector/auth work (Stage B).

Confirmed seam facts (verify with a quick grep, then rely on them): every view imports ONLY loaders from
'./queries.js' (plus the POS constant in Players.jsx/League.jsx). db.js and posture.js are imported ONLY by
queries.js. MY_USERNAME is used ONLY inside queries.js. So the loaders must keep their exact names/params/return
shapes; everything else in queries.js is deletable; no view changes.

Do:
1. Rewrite queries.js: keep `export const POS`, add a small apiGet(path, params) helper (build query string,
   OMIT as_of_week when null so the server defaults to latest, throw on !res.ok like today's query(), return
   res.json()), and replace all 11 loaders with thin fetch calls (see the mapping in this session's runbook:
   /weeks, /league-meta, /players, /players/{sleeperId}, /standings, /teams/{rosterId}, /managers/{rosterId},
   /league, /positional-talent, /matchups, /matchups/{matchupId}). Delete the DuckDB SQL, MY_USERNAME, all the
   JS calc/engine helpers, and the db.js/posture.js imports.
2. Add a Vite dev proxy in vite.config.js: server.proxy so '/api' → 'http://localhost:8000'. Drop the now-dead
   @duckdb/duckdb-wasm optimizeDeps/esnext bits. Keep server host:true port:5173.
3. Delete src/db.js; `npm uninstall @duckdb/duckdb-wasm` (updates package-lock). posture.js is now dead — delete
   or leave, your call. Remove any now-unused imports so the build is clean.
4. Update .claude/launch.json so it runs BOTH the API (uvicorn application.api.main:app --port 8000, from repo
   root) AND the Vite dev server together, so a single preview brings up the full stack. The API reads config.py
   locally (DATABASE_URL + SLEEPER_LEAGUE_ID/SLEEPER_USERNAME), so no Fly secrets needed to run locally.

Views are UNTOUCHED. If a view would need editing to render, STOP — an endpoint shape diverged from the loader
contract; fix it in the endpoint (reads.py/projections.py), not the view.

Follow SESSION_GUIDE: fresh worktree, scripts/worktree-setup.sh, 3-commit cap, update STATUS.md, close/merge,
push. Suggested commits: (1) queries.js → API client + vite proxy + launch.json; (2) delete db.js + drop the
duckdb dep + config cleanup; (3) verify + STATUS.md.

Verify (this is the real payoff — RUN it, don't eyeball code): start the API + frontend together and open the
app in the browser preview. Click through every tab — Players, a player card, Teams standings, a team detail
(incl. the thisWeek bar), League, Matchups, a matchup detail — at the latest week and one earlier week. Confirm:
(a) every surface renders the same as today (spot-check a few numbers against the endpoint JSON via curl — e.g.
/api/players top row, /api/standings all-play %, a /api/matchups game's win % summing to ~100); (b)
read_network_requests shows /api/* returning 200 JSON and NO .parquet fetches / no DuckDB worker; (c)
read_console_messages is clean; (d) the week selector still re-scopes every surface. Screenshot two contrasting
surfaces (e.g. Matchups and a team detail) as proof.

Close: update STATUS.md (shipped + next move = Session 6: full parity sign-off + go-live — deploy the app,
set LEAGUE_ID + MY_USERNAME as Fly secrets, decide the frontend hosting/CORS story). Merge/push.
```

## Definition of done
✅ `queries.js` is a thin API client (~30 lines: `POS` + `apiGet` + 11 fetch loaders), same export names/shapes;
`db.js` deleted and `@duckdb/duckdb-wasm` removed from `package.json`/lockfile; Vite proxies `/api`→uvicorn;
`.claude/launch.json` runs API + frontend together; the app renders every surface correctly from `/api/*` with
a clean console and no parquet/DuckDB in the network tab; **no view file changed**; `STATUS.md` updated with
Session 6 as the next move. The app is now server-backed while looking identical to today.

## Notes / gotchas
- **The API must be running for the app to work now.** That's the point of the `launch.json` update — one
  action starts both, and the proxy port (8000) must match uvicorn's.
- **The risk here is wiring, not numbers.** The endpoints' numeric parity was Sessions 3–4's job (already
  verified). Session 5 can only break on the *plumbing*: a wrong proxy, a mis-encoded path param, or forgetting
  to omit `as_of_week` when null. The click-through catches all three.
- **`as_of_week` null-omit is load-bearing** — if the helper always sends `as_of_week=`, the server won't get
  its "latest" default and early/late weeks misbehave. Omit the param when the loader's arg is null.
- **Views untouched is the tripwire, not just a preference** — needing to touch a view means a shape mismatch
  slipped through the earlier audits; treat it as an endpoint bug.
- **Deleting `posture.js`/`db.js` is safe** — grep confirms only `queries.js` imported them. Remove the imports
  first, then the files, so the dev server never sees a dangling import.
- **This is the first visible change** — but it should be *invisible* to a user: identical app, new plumbing.
  The first thing a user actually *sees* differently is multi-league in Stage B.
```
