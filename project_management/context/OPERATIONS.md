# OPERATIONS — what can go down, how to tell, which button

**Current as of 2026-08-14.** *(P5/S3 added a second Fly app — `fantasy-ai-worker`, a stateful
singleton with a 1 GB volume. It serves no traffic, so it cannot take the site down; its failure
mode is "leagues stop being built", not "the site is off". `fly scale count 0` on the API is still
the meter switch, and it does not touch the worker.)* Not a project artifact and not a session — this is the page you read
**while something is wrong**, so it lives in `context/` beside `SEASON_CALENDAR.md` rather than inside a
project that hasn't run yet. Keep it short enough to read at 2am. Building the guardrails is **P6/S3–S4**.

## The shape of the risk — read this once, calmly

- **There is no runaway-bill path.** **Two** Fly machines (`shared-cpu-1x`, 256mb, both `iad`),
  **no autoscaling configured**, scale-to-zero when idle — so compute is capped by there being nothing to
  scale into. And the Supabase project is on the **free tier, which cannot bill: it pauses instead.**
  Deliberate (Will), not accidental.
  *Measured 2026-08-11 (S2c): `fly scale show` → `app │ 2 │ shared │ 1 │ 256 MB │ iad(2)`.* This page said
  "one machine" and `appendices/auth.md` said "`fly.toml` runs two"; the S1b audit was right that
  **`fly.toml` declares no count** — it is a deploy-time property — and nobody had actually run the
  command. Two is the number. Re-check with `fly scale show` rather than reading it off a doc.
- **So the only real failure is "the site is down," and it comes in two flavours.** One recovers by
  itself. One does not, and that is the one worth knowing about before it happens.

| | what happened | recovers alone? |
|---|---|---|
| **Fly machine saturated** | 256mb / shared CPU under load; slow or unresponsive | **Yes** — when traffic stops |
| **Supabase paused** | free-tier limit crossed; the database stops | **No** — somebody has to turn it back on |

## Telling them apart — the health check is the discriminator

`/health` is **deliberately DB-free** (see `fly.toml`) so it does not flap when Supabase pauses. That
accident of design is the diagnostic:

- **`/health` responds, but the app is broken or empty** → **Supabase**. Fly is fine; the database is not.
- **`/health` does not respond at all** → **Fly**. The machine is saturated, stopped, or the deploy is bad.

It also answers a third question for free (S2c): `{"status":"ok","season":2026,"season_source":"derived"}`
— so "which season is this deploy actually serving, and is an override set?" is one curl, not a log grep.
Adding that kept the DB-free property, which is why the season is derived from the calendar rather than
looked up.

Check it directly: `https://surplusff.com/health`. Do not diagnose from the rendered page — a stale
bundle can survive a deploy (see `PM_SESSION_STARTUP.md`); trust `/api/*` JSON and `/health`.

## The buttons

- **Supabase paused** → un-pause it in the **Supabase dashboard**. No Fly command helps here, and this is
  the failure most likely to catch you out: the instinct is to reach for `fly`, and `fly` is not involved.
- **Stop everything / cut the meter** → `fly scale count 0`. Back up with `fly scale count 1`.
- **Something is deployed and wrong** → `fly deploy` from `application/` (build context is that
  directory). A merged-but-undeployed change has bitten this project before, so confirm the deploy, not
  the merge.
- **A full store reload (`build_db --load`) — how long the site is down.** Measured **2026-08-11**, the
  first planned outage this project has taken: **82s for the load itself, 145s end to end** (load →
  `fly deploy` → serving again), publishing 32 slices across 15 tables. Two things that number teaches:
  the load is the smaller half, and **the window is load → REDEPLOY, not the load** — the deployed code
  is what breaks first if the schema moved under it (that reload renamed a table). At Week 1, with real
  people on the site, budget the round trip and deploy immediately after the load rather than verifying
  first. A *scoped* reload (`--reload-league <id>`) is not an outage at all: it DELETEs and re-COPYs one
  league in a transaction and drops nothing.
- **The worker refuses to refresh: "write_ros_player_band() is refused … STORE_ROLE=worker"** →
  this is the store boundary doing its job, not a fault. The worker read the shared rest-of-season
  band on its volume, recomputed it, and got a **different** answer — so its substrate is stale,
  realistically because the engine constants moved at the annual re-tune. The error names the exact
  command; the short version is **rebuild on the laptop, then re-seed the volume**:
  ```
  application/venv/bin/python -m application.data.transforms.compute_ros_player_band --season <YYYY> --scoring-key <key>
  ```
  then re-run the seed below. Until you do, the worker declines leagues on that scoring key — which
  is the point: a loud stop beats silently serving numbers built from a recipe nobody approved.

- **Onboarding a league the store has never seen (P5/S4a).** One command, on the worker, from its
  own volume. It fetches, joins, computes the spine, writes the catalog row and COMMITs to
  Postgres; `--dry-run` does everything except the last two.
  ```
  fly ssh console -a fantasy-ai-worker -C "python -m application.data.serve.onboard_league --league <ID> --season <YYYY>"
  ```
  It **refuses** rather than guessing: a non-redraft league (V1 scope), a league that is the first
  on its scoring key (no `projection_consensus` — build the substrate first), and any league that
  belongs to the frozen corpus, the demo slate or the generated clone. A re-onboard of the same
  league is a clean no-op, so re-running after a failure is safe.
  **The league is not visible to its owner until `season == the season /health reports`** — that is
  the visibility predicate working, not a fault (`appendices/auth.md`).

- **`build_db --verify` now belongs on the WORKER, not the laptop.** It compares the *local* disk
  against Postgres, and since P5/S4a the worker builds leagues the laptop has never seen — so the
  laptop's copy is a strict subset and it reports a mismatch per table plus `league_catalog`
  32 vs 33. That is the expected reading, not a fault. Measured 2026-08-14: laptop **VERIFY FAILED**
  (10 tables), worker **VERIFY OK** (all 15). Run it where the artifacts are:
  ```
  fly ssh console -a fantasy-ai-worker -C "python -m application.data.serve.build_db --verify"
  ```

- **NEVER run `build_db --reload-manifest` on the worker.** It TRUNCATEs `league_catalog` and
  re-COPYs it from that machine's *local* store, which on the worker is a seeded snapshot — so
  every league catalogued since the last seed would silently vanish from the served catalog. It now
  refuses there (`STORE_ROLE=worker`), and the worker's scoped equivalent is what the onboarder
  already calls. Run it on the laptop.

- **Seeding (or RE-seeding) the worker volume — the recovery procedure, measured.** The volume is a
  **reconstructible cache, not precious data**: lose the host and re-seed. That claim was untested
  until now, so here is the actual command and the actual clock.

  **Measured 2026-08-14: 37s end to end** — 6s tar · 18s upload · 13s extract — for **244 MB**
  (159 MB compressed) landing as **248 MB on the volume, 28% of the 1 GB**. Run from the repo root:
  ```
  COPYFILE_DISABLE=1 tar -czf /tmp/seed.tgz -C application/data/snapshots --exclude ./derived/ledger .
  COPYFILE_DISABLE=1 tar -czf /tmp/seed_cache.tgz -C application/data/cache .
  fly ssh sftp put /tmp/seed.tgz /app/application/data/snapshots/seed.tgz -a fantasy-ai-worker
  fly ssh sftp put /tmp/seed_cache.tgz /app/application/data/snapshots/seed_cache.tgz -a fantasy-ai-worker
  fly ssh console -a fantasy-ai-worker -C "sh -c 'cd /app/application/data/snapshots && tar -xzf seed.tgz && mkdir -p _cache && tar -xzf seed_cache.tgz -C _cache && rm -f seed.tgz seed_cache.tgz'"
  ```
  **`COPYFILE_DISABLE=1` is not optional on macOS.** Without it `tar` ships an AppleDouble `._`
  sidecar for every file — the first seed put **16,089** of them on the volume, inflated it from
  248 MB to 311 MB, and made `*.parquet` globs raise `ComputeError: file must end with PAR1` on
  files that were never parquet.

  **`derived/ledger` is excluded on purpose** (145 MB) — it is laptop-owned and the worker has no
  use for it. `_cache` is the second tarball because `data_layer._CACHE_DIR` is a *sibling* of
  `snapshots/`, so the mount cannot reach it; the image symlinks `data/cache` onto the volume there.

- **Sleeper is down** → nothing to do. **No request path calls Sleeper any more (S2c).** The season is
  derived from the calendar, so a Sleeper outage no longer costs a read anything. This entry used to be a
  button (`CURRENT_SEASON` in `[env]`, to skip the network call); it is kept only so that anyone
  remembering that button knows why it is gone.
- **The visibility rule is misbehaving, or the season is wrong** → `CURRENT_SEASON` and `DEMO_LEAGUE_ID`
  are plain `[env]` values in `fly.toml`, not secrets, and are the two levers over what anyone can see.
  `CURRENT_SEASON` should normally be **absent** — it is the manual override for the derived season
  (the calendar year, or the year before it until August 1). **`https://surplusff.com/health` reports the
  resolved season and its source**, so check there first: `"season_source": "env"` means an override is
  set and probably shouldn't be.

## What actually consumes the free tier — and therefore what prevents the pause

Queries and the bytes they return. Today **every anonymous visitor fires eleven analytical queries** and
gets back data byte-identical to the previous visitor's, because nothing is cached anywhere in the API.
Traffic converts directly into Supabase consumption, and Supabase consumption is the only thing that can
take the site down in a way that needs a human.

That is why the fix is **not** rate limiting — a limit fires after you have already paid for everything
except the last query. The fix is to make the traffic cheap: **precompute the demo** (it is frozen
forever once S2d lands, so it can be computed once instead of once per visitor) and **put Cloudflare in
front** so most requests never reach Fly or Supabase at all. Both are **P6/S4**.

## Known gaps (deliberate, not oversights)

- **No uptime monitoring.** You find out by looking. Worth fixing at go-live, not before — there is
  nobody on the site to be inconvenienced yet. P6/S3.
- **Google Analytics will not warn you.** Bots and scrapers do not execute JavaScript, so GA is close to
  blind to exactly the traffic that would cause a pause. The instruments are Fly's metrics and Supabase's
  usage page, not GA.
