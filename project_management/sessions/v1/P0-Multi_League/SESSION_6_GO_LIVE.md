# Session 6 — Parity sign-off + go-live — a brief for Code

**Last reviewed:** 2026-07-25 · **Status:** Ready to run · **Owner:** Code drives; Will approves the deploy + eyeballs the live URL

> **What this session does:** take the app **live**. Sessions 1–5 built and locally-verified the whole
> server-backed stack; the live Fly app is still the Session-1 *skeleton* (`/api/*` 404s). This session deploys
> the **real** API **and** the built frontend to Fly, wires the two so they talk in production, sets the last
> secrets, and does the **parity sign-off against the deployed URL**. This is the **final step of Stage A** —
> after it, the app is a real website and Stage B (multi-league) begins. Single league, no auth, no new formats.
>
> **The one real decision this session:** how the deployed frontend reaches the API. Locally, Vite proxies
> `/api` → uvicorn (same-origin, no CORS); that proxy is dev-only. See "The hosting decision" below — I've
> chosen **same-origin (one Fly app serves both)** and the brief implements it; the alternative is noted.

## Your part, Will (~15 minutes)
Kick off with the brief below. You may need to (a) approve a `fly auth` browser prompt if the Session-1 login
expired, and (b) un-pause the Supabase project if it went idle (free projects sleep after ~a week — Code will
tell you if the DB health check fails). At the end, **open `https://fantasy-ai-api.fly.dev/` yourself** and click
through the tabs — when your dashboard loads from the internet with real numbers, you're live. The
`LEAGUE_ID`/`MY_USERNAME` values Code sets are just your league id + Sleeper handle (already in `config.py`),
not sensitive.

## FIRST — a latent deploy bug to fix (found in this review)
**The `Dockerfile` COPY list is missing `projections.py`.** It currently copies
`__init__.py db.py settings.py calcs.py reads.py routes.py main.py` — but Session 4 added `projections.py`, and
`reads.py` imports it. As written, the image builds fine and then **crashes on startup** (`ModuleNotFoundError:
projections`). Fix it as step 1, and — to kill this whole class of drift — **copy the api package as a directory
(`COPY api/ …`) instead of enumerating files**, so a future new module can never be silently left out of the image.

## The hosting decision (why same-origin)

Two ways to run the deployed frontend + API:

- **A — Same-origin (CHOSEN): one Fly app serves both.** FastAPI serves the built static SPA *and* the `/api`
  routes on one origin, so the frontend's relative `/api/…` calls just work — **no CORS, one URL, one deploy.**
  It mirrors the dev proxy model, and it sets up auth (Stage B) cleanly (same-origin cookies). Cost: a one-time
  multi-stage Dockerfile (node builds the SPA → python serves it) and a slightly larger image.
- **B — Split hosting: static frontend on a CDN/host, API on Fly, cross-origin + CORS.** Keeps the API image
  tiny, but adds a second deploy target, a CORS allow-list on the API, and a build-time absolute API URL in the
  frontend. More moving parts for no benefit at this scale.

**Recommendation: A.** For a single-league, no-auth demo the goal is "live and correct with the fewest moving
parts," and same-origin removes CORS entirely. A doesn't foreclose B — if you later want the frontend on a CDN,
adding CORS + an absolute URL is a small change. *(If you'd rather do B, say so and I'll swap the brief; the only
code deltas are a `CORSMiddleware` in `main.py` and an env-var API base in `queries.js`.)*

## Decisions I made for you (Code: follow unless you hit a reason not to)

1. **Same-origin hosting (Option A)** — one Fly app (`fantasy-ai-api`) serves the built SPA at `/` and the API at
   `/api`. No CORS.
2. **Multi-stage Dockerfile**, build context moved up to `application/` (so both `api/` and `frontend/` are
   available): stage 1 `node` runs `npm ci && npm run build`; stage 2 `python` installs the api deps, copies the
   **api package as a directory**, and copies the built `dist/` in as the static root. Write a tight
   `.dockerignore` for the new context so the heavy runtime never reaches the builder (exclude `data/`, all
   `.venv`/`venv`, `frontend/node_modules`, `frontend/dist`, `config.py`, `.env*`).
3. **`main.py` serves the SPA:** remove the skeleton `/` JSON route; keep `/health`, `/health/db`, and the `/api`
   router; **mount `StaticFiles(directory=…, html=True)` at `/` LAST** (after the router + health routes) so the
   explicit routes win and the catch-all only serves the SPA. (StaticFiles is built into FastAPI — no new
   dependency.)
4. **Set the last Fly secrets:** `LEAGUE_ID` + `MY_USERNAME` (values from `config.py`'s `SLEEPER_LEAGUE_ID` /
   `SLEEPER_USERNAME`), alongside the existing `DATABASE_URL`. Without them the deployed endpoints filter
   `WHERE league_id = NULL` → **empty results, not an error** — so set them *before* declaring success.
5. **Keep the free `fantasy-ai-api.fly.dev` URL** (custom domain stays parked) and **deploy via the `fly` CLI**
   (GitHub auto-deploy stays off). Keep `fly.toml` as-is (scale-to-zero is fine; note the cold-start below).
6. **No Stage-B / null-policy work.** This is go-live for the single-league app.

## What Code does (steps)

1. **Fix the Dockerfile** (add `projections.py` / copy the api dir) — see above.
2. **Multi-stage build + static serving:** rewrite `Dockerfile` (context `application/`), add the new
   `.dockerignore`, update `fly.toml`'s build note, and mount `StaticFiles` in `main.py`. Build the image and run
   it locally (`docker run` or `fly deploy --local-only` dry run) — confirm `/` serves the SPA and `/api/weeks`
   returns data from one origin.
3. **Secrets + deploy:** `fly secrets set LEAGUE_ID=… MY_USERNAME=…`; `fly deploy` from `application/`.
4. **Verify live (the Stage-A parity sign-off):** hit `https://fantasy-ai-api.fly.dev/` — the SPA loads (not the
   skeleton JSON); `/health/db` is 200; `/api/weeks` and a couple of endpoints return real rows; click every tab
   at two weeks and confirm the numbers match the Session-4/5 ground truth (e.g. a Matchups game's win % sums to
   100; the `thisWeek` bar renders); network shows `/api/*` 200 JSON; console clean.

## The brief to paste to Code

```
Goal: Session 6 of the store migration (Stage A go-live, MULTI_LEAGUE_STORE_MIGRATION.md A4 → live). Deploy the
real API AND the built frontend to Fly as ONE same-origin app, set the last secrets, and sign off parity against
the DEPLOYED URL. The live Fly app is still the Session-1 skeleton; this replaces it. Single league, no auth.

STEP 0 — FIX THE DOCKERFILE BUG FIRST: the COPY list is missing projections.py (added in Session 4, imported by
reads.py) — as-is the image crashes on startup. Copy the api package as a directory (COPY api/ …) instead of
listing files, so no module is ever left out again.

Hosting = SAME-ORIGIN (one Fly app serves both), so no CORS:
1. Multi-stage Dockerfile, build context = application/ (both api/ and frontend/ available):
   - stage 1: FROM node:20-slim → COPY frontend/package*.json, npm ci, COPY frontend/, npm run build (→ dist).
   - stage 2: FROM python:3.13-slim → install api/requirements.txt, recreate the application/ + application/api
     package, COPY the api/*.py package dir in, COPY --from=stage1 the built dist → /app/static.
   - CMD unchanged (uvicorn application.api.main:app --host 0.0.0.0 --port ${PORT:-8080}).
2. New .dockerignore for the application/ context: exclude data/, **/.venv, venv/, frontend/node_modules,
   frontend/dist, config.py, .env* (keep .env.example) — the heavy runtime must never reach the builder.
3. main.py: remove the skeleton GET / route; keep /health, /health/db, and the /api router; then mount
   StaticFiles(directory="static", html=True) at "/" LAST (after the router + health routes) so explicit routes
   win and the catch-all only serves the SPA. StaticFiles ships with FastAPI — no new dependency.
4. Build the image and run it locally; confirm one origin serves the SPA at / AND /api/weeks returns data.
5. fly secrets set LEAGUE_ID=<config.SLEEPER_LEAGUE_ID> MY_USERNAME=<config.SLEEPER_USERNAME> (DATABASE_URL is
   already set). Then `fly deploy` from application/.
6. Verify LIVE at https://fantasy-ai-api.fly.dev/ : the SPA loads (not the skeleton JSON); /health/db is 200;
   /api/weeks + a couple endpoints return real rows; click every tab at as_of_week=latest and one earlier week and
   confirm numbers match the Session-4/5 ground truth (a matchup's win% sums to ~100; the thisWeek bar renders);
   network shows /api/* 200 JSON; console clean. Screenshot the live app.

Gotchas: if /health/db 503s, the free Supabase project is paused — I'll un-pause it (tell me). Scale-to-zero means
the first request after idle cold-starts (a few seconds) — expected. If any endpoint returns [] but /health/db is
200, the LEAGUE_ID/MY_USERNAME secrets aren't set. Keep MY_USERNAME semantics and *_ppr as-is (Stage B).

Follow SESSION_GUIDE: fresh worktree, scripts/worktree-setup.sh, 3-commit cap, update STATUS.md, close/merge, push.
Suggested commits: (1) Dockerfile fix + multi-stage build + .dockerignore + main.py StaticFiles; (2) any fly.toml/
config tweaks; (3) verify live + STATUS.md. (Deploy + secrets are actions between commits, not commits.)

Close: update STATUS.md — STAGE A COMPLETE / app is LIVE at the URL; next = Stage B (multi-league/season on the
new store, MULTI_LEAGUE_STORE_MIGRATION.md Stage B). Note the parked items: custom domain, the null policy
(adopt projections._num across the older reads when multi-league data introduces nulls), and CORS-if-we-ever-split-
hosting. Merge/push.
```

## Definition of done
✅ `Dockerfile` includes `projections.py` (copies the api dir) and is a multi-stage build that bundles the built
SPA; `main.py` serves the SPA at `/` (skeleton route gone) with `/health` + `/api/*` intact; `LEAGUE_ID` +
`MY_USERNAME` set as Fly secrets; **`fly deploy` succeeds and `https://fantasy-ai-api.fly.dev/` serves the live
dashboard** with real data, a clean console, and every tab matching the Session-4/5 numbers; `/health/db` 200;
`STATUS.md` records **Stage A complete / live**, next = Stage B. The app is a real website.

## Notes / gotchas
- **The Dockerfile bug is the highest-risk item** — without `projections.py` the deploy builds green and then
  500s on the first request. Fix it first; the copy-the-directory approach prevents recurrence.
- **Secrets-or-empty is the silent failure mode** — `/health/db` can be 200 (DB reachable) while endpoints return
  `[]` because `LEAGUE_ID` isn't set. The `/api/weeks` check catches it; don't sign off on a green health check alone.
- **Free Supabase pauses when idle** — if the DB probe fails weeks from now, un-pause it in the dashboard. For a
  always-available demo, consider the paid tier later (parked).
- **Cold start:** scale-to-zero means the first hit after idle takes a few seconds to boot. Fine for a demo; if you
  want it always-warm, bump `min_machines_running` to 1 (costs a bit more — parked decision).
- **Rollback:** `fly releases` shows history; `fly releases rollback` (or re-`fly deploy` a fixed image) reverts a
  bad deploy. Nothing here touches the database, so a rollback is safe.
- **This is the first thing the outside world can load** — but it's still the single-league app. The first change a
  *user* notices is multi-league, in Stage B.
```
