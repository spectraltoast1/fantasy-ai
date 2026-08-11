# OPERATIONS — what can go down, how to tell, which button

**Current as of 2026-08-11.** Not a project artifact and not a session — this is the page you read
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
