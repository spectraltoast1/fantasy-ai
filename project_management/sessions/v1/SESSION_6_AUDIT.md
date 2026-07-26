# Store-Migration Audit — Session 6 (parity sign-off + go-live)

**Reviewed:** 2026-07-25 · **By:** PM (independent, against live git + the deployed URL)
**Scope:** the go-live — same-origin deploy (Option A), the Dockerfile fix, secrets, and whether the app is
actually live.

**Bottom line: complete, correct, and LIVE. Stage A is done.** The app serves from `https://fantasy-ai-api.fly.dev/`
— the SPA at `/` and real data at `/api/*`, one origin, no CORS. No findings of substance.

## Verified

- **Live, for real.** `/` returns the **"Gridiron" SPA** (HTML, not the old skeleton JSON); `/api/league?as_of_week=4`
  returns the 10-team standings; `/api/standings?as_of_week=3` returns the full standings array. Real rows (not
  empty) means the **`LEAGUE_ID`/`MY_USERNAME` secrets are set** — the silent-empty failure mode didn't happen.
  *(Caveat on my own process: a first probe showed the Session-1 skeleton — that was WebFetch's 15-min cache from
  an earlier audit; fresh/cache-busted URLs confirm the live app. Verified, not assumed.)*
- **The pre-flagged Dockerfile bug is fixed — proven by the app booting.** `reads.py` imports `projections` at
  top level, so a missing `projections.py` in the image would crash startup and every endpoint would 500. The
  endpoints serve real data → the app imported cleanly → `projections.py` is in the image. Session 6 rebuilt the
  Dockerfile (now `application/Dockerfile`, multi-stage) with the api package copied wholesale, killing that
  drift class.
- **Same-origin serving is wired correctly.** `main.py` imports `StaticFiles`, keeps `/health` + `/health/db` +
  the `/api` router, and mounts `StaticFiles(html=True)` at `/` **last** (so the explicit routes win and the
  catch-all only serves the SPA), with a guard for when the static build is absent (local API runs still work).
- **Clean structural change** (git diff vs Session 5): new `application/Dockerfile` (multi-stage) + `.dockerignore`;
  old api-scoped Dockerfile/.dockerignore deleted; `fly.toml` moved up to `application/`; `main.py` StaticFiles;
  STATUS + ARCHITECTURE updated to "Stage A COMPLETE — LIVE." **Zero `*.jsx` changed.** Working tree clean.
- **Docs current** — third-plus session running with closedown discipline intact.

## Findings — none of substance

The one thing worth a note for later, not a defect: the app is on Fly **scale-to-zero**, so the first hit after
idle cold-starts (a few seconds). Fine for a demo; if you want it always-warm for a live audience, bump
`min_machines_running` to 1 (a few $/mo). Parked.

## Carry-forward (now Stage B / parked)
- **Custom domain** (free `.fly.dev` URL fine for now).
- **CORS + absolute API URL** only if you ever split the frontend onto a CDN (same-origin means neither is needed
  today; the switch stays a small, additive change).
- **Null policy** — adopt `projections._num` across the older reads when Stage-B multi-league/historical data
  introduces nulls.

**Stage A (Sessions 1–6) is complete: the app moved from in-browser DuckDB to a live, server-backed website with
zero change to what a user sees. Next: Stage B — multi-league.**
