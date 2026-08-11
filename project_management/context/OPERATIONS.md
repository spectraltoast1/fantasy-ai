# OPERATIONS — what can go down, how to tell, which button

**Current as of 2026-08-11.** Not a project artifact and not a session — this is the page you read
**while something is wrong**, so it lives in `context/` beside `SEASON_CALENDAR.md` rather than inside a
project that hasn't run yet. Keep it short enough to read at 2am. Building the guardrails is **P6/S3–S4**.

## The shape of the risk — read this once, calmly

- **There is no runaway-bill path.** One Fly machine (`shared-cpu-1x`, 256mb), **no autoscaling
  configured**, scale-to-zero when idle — so compute is capped by there being nothing to scale into. And
  the Supabase project is on the **free tier, which cannot bill: it pauses instead.** Deliberate (Will),
  not accidental. *Re-verify the machine count with `fly scale show` if this ever feels wrong.*
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

Check it directly: `https://surplusff.com/health`. Do not diagnose from the rendered page — a stale
bundle can survive a deploy (see `PM_SESSION_STARTUP.md`); trust `/api/*` JSON and `/health`.

## The buttons

- **Supabase paused** → un-pause it in the **Supabase dashboard**. No Fly command helps here, and this is
  the failure most likely to catch you out: the instinct is to reach for `fly`, and `fly` is not involved.
- **Stop everything / cut the meter** → `fly scale count 0`. Back up with `fly scale count 1`.
- **Something is deployed and wrong** → `fly deploy` from `application/` (build context is that
  directory). A merged-but-undeployed change has bitten this project before, so confirm the deploy, not
  the merge.
- **The visibility rule is misbehaving** → `CURRENT_SEASON` and `DEMO_LEAGUE_ID` are plain `[env]` values
  in `fly.toml`, not secrets, and are the two levers over what anyone can see. `CURRENT_SEASON` should
  normally be **absent**.

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
