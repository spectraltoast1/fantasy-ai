# Store-Migration Audit — Session 5 (frontend becomes an API client)

**Reviewed:** 2026-07-25 · **By:** PM (independent, against the live git repo)
**Scope:** the frontend swap — `queries.js` → thin API client, `db.js`/DuckDB-WASM deleted, Vite proxy + dev
runner, and the "no view touched" guarantee.

**Bottom line: complete, correct, and textbook — the cleanest possible version of this session.** No findings of
substance. Every one of the eleven loaders maps to the right endpoint, the "views untouched" rule held (git-proven),
DuckDB is fully gone, and Code's own in-browser verification cites numbers that **match my independent Session-4
reconstruction from the raw parquet** — so parity is cross-validated, not just asserted.

---

## How this was verified

Audited the **live git HEAD** via `device_bash` (the file-sync bridge served stale copies in the Session-4 audit,
so I go to git directly now). Working tree is clean at HEAD; Session 5 is the merge `00ee572` plus commits
`4b708c9` (queries.js API client), `e94eba7` (delete db.js/posture.js + drop the dep), `08e74bb` (STATUS), and a
`build_db.py` comment cleanup.

- **`git diff --stat` since Session 4:** only `queries.js` (−1079/+~30), `db.js` (−81, deleted), `posture.js`
  (−43, deleted), `package.json`/`package-lock.json` (duckdb removed), `vite.config.js`, `STATUS.md`, and a
  6-line `build_db.py` comment. **Zero `*.jsx` files changed** — I ran the diff scoped to the views and it came
  back empty. The seam held.
- **Read the actual new files** (queries.js, vite.config.js, package.json, .claude/launch.json) and checked each
  loader against the routes shipped in Sessions 3–4.
- **Confirmed the deletions:** `db.js` and `posture.js` no longer exist; `@duckdb/duckdb-wasm` is gone from
  `package.json`, the lockfile, and `vite.config.js`.

---

## What Code got right

- **`queries.js` is a faithful ~49-line client.** `POS` is still exported (the only non-loader thing any view
  imports); `apiGet(path, params)` builds the query string, **omits `as_of_week` when null** (preserving the
  "n == null → latest" seam), **throws on `!res.ok`** (so the views' existing loading/error states keep working),
  and returns `res.json()` (including a `null` body for an unknown roster/matchup — matching the old loaders).
- **All 11 loaders map to the correct endpoint, params, and path encoding** — including the details that were
  easy to get wrong: `loadPlayerCard` `encodeURIComponent`s the string `sleeperId`; `loadManagerDossier` and
  `loadPositionalTalent` send **no** `as_of_week` (they aren't week-scoped); the loader names/params are
  unchanged, so the views call them exactly as before.
- **Views are untouched** (git-proven) — the whole safety model of this session, honored exactly.
- **DuckDB fully removed** — `db.js` deleted, dep uninstalled (lockfile updated), and the dead
  `optimizeDeps`/`esnext` bits stripped from `vite.config.js`. `posture.js` deleted too (posture is now the
  server's `t.posture` field).
- **Dev wiring is right:** `vite.config.js` proxies `/api` → `http://localhost:8000` (same-origin in dev, no
  CORS); `package.json` adds `api` + `dev:full` scripts (via `concurrently`) and `.claude/launch.json` runs the
  full stack in one action. Local uvicorn reads `config.py`, so it runs without the Fly secrets.
- **Real verification, and it checks out.** STATUS records a green in-browser pass (every tab at two weeks;
  `/api/*` 200 JSON with no `.parquet`/DuckDB worker; clean console; week selector re-scopes). The cited
  Matchups figures (**128.5/57%**, **124.4/43%**) are the exact μ/win-prob values I computed independently from
  the parquet in the Session-4 audit — strong evidence the render is genuinely correct end-to-end.
- **Closedown discipline held for the third straight session** — STATUS updated (and it even retired a now-stale
  `db.js` reference in `build_db.py`'s comment; good hygiene since `db.js` no longer exists).
- **Correctly deferred what belongs to Session 6** — the code comments explicitly flag that the dev proxy is
  dev-only and the deployed cross-origin/CORS story is Session 6.

## Findings register — nothing of substance

| # | Severity | Finding |
|---|---|---|
| 1 | Low (env) | The `api` npm script and `.claude/launch.json` assume `application/api/.venv` exists and hardcode the Homebrew npm path (`/opt/homebrew/bin/npm`). Fine on your Mac (the venv is set up per SESSION_GUIDE); would need adjusting on another machine. Not a code defect — a local-dev convenience. |

That's the entire list. Nothing blocks Session 6.

## Context worth knowing (not a defect)

- **A greenlit "deprecation inventory" was also produced this session** (parquet artifacts / the pipeline that
  builds them / other now-unused bits). Code correctly **removed nothing** — several items are traps because the
  loader still `COPY`s the same parquet into Postgres — and the `git diff` confirms no backend file was deleted.
  Worth reading that report before any cleanup, but it introduced no risk here. If you want, I can review that
  inventory separately.

## Carry-forward → Session 6 (parity sign-off + go-live)

Unchanged by this session, and now the whole remaining Stage-A scope:

- **Deploy + Fly secrets.** The live Fly app is still the Session-1 skeleton (`/api/*` 404s); Session 6 deploys
  the real API and must set `LEAGUE_ID` + `MY_USERNAME` as Fly secrets alongside `DATABASE_URL`, or the deployed
  endpoints return empty.
- **Frontend hosting + CORS.** The dev Vite proxy is dev-only. Deployed, the static frontend calls `/api`
  relative to its own origin — which only works if it's served same-origin with the API (or via a rewrite);
  otherwise it needs an absolute API URL + CORS on the Fly side. This is *the* decision to make in Session 6.
- **Parity sign-off on the deployed app** — repeat the click-through against the live URL, not just localhost.
- **Null policy stays a Stage-B prerequisite** — adopt `projections._num` across the older reads when
  multi-league/historical data actually introduces nulls.

## Recommendation
Ship it. Session 5 is done and correct; the app is now server-backed while looking identical to before. Session 6
is the last Stage-A step (deploy, secrets, CORS/hosting, deployed-parity), then Stage B (multi-league) begins.
