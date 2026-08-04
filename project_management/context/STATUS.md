# STATUS

**What this is:** Gridiron — a fantasy-football decision-support dashboard whose unit is the manager's
*decision*, not the player. Live, single-league, on the server stack.
**Live at:** https://fantasy-ai-api.fly.dev/ · **Updated:** 2026-07-31
**Read next:** `ARCHITECTURE.md` (how it's built) · `CODING_BIBLE.md` (rules for coding agents) ·
`ROADMAP.md` (where it's going) · `projects/v1/` (the active build).

---

## What's live today

- A deployed, mobile-responsive React SPA on **FastAPI + Supabase Postgres** (Fly.io, same-origin). Five
  surfaces: **Players, Teams, League, Matchups, Manager Dossier**.
- **Multi-league, no auth.** All **31 demo league-seasons (12 lineages)** are in the production DB and every
  read is parameterized on `league_id`(+`season`+`viewer_roster_id`), defaulting to the owner's league with
  byte-identical parity when omitted. League + season + week selectors re-scope every surface, and the "you"
  highlight follows the selected league. Verified across all 31 slices × sample weeks, 0 bugs.
  → *`sessions/v1/P0-Multi_League/` + `sessions/v1/SESSION_B6_VERIFICATION_REPORT.md`.*
- **The app can now advance week by week (P2/S2).** The loader has a **per-league scoped reload** and a
  **weekly-refresh orchestrator** advances one league to the current week without rebuilding the DB —
  proven on prod by advancing the owner's 2025 league Week 4 → 5 (the un-freeze). Ready for live 2026 at
  kickoff. → *see below + `sessions/v1/P2-Go_Live_2026/`.*
- Fully migrated off in-browser DuckDB-WASM (Stage A complete); the client is now a thin API client.

## The engine

- Built, measured, and deliberately made **honest** — i.e. tuned so its stated confidence is truthful rather
  than flattering (the shipped "8c" change: a lower center + a wider two-sided band). Reads it produces:
  production VOR, projection bands, playoff odds (Monte Carlo), positional depth, true rank, player signal,
  market VOR, the ROS bull/bear/situation outlook, and manager dossiers.
- **Current honesty state:** production VOR ranks rest-of-season value well but runs the *level* high (trust
  the order, not the total); the band was re-tuned to ~0.86 coverage; playoff odds and true rank are honest;
  four reads still carry no confidence signal. → *see appendix: engine-trust, engine-decision-reads.*
- **The thin-data window is honest (P2/S4a).** Every surface keys off **one** depth clock — weeks with real
  RESULTS, not weeks merely loaded, because a projections-only week joins with zero-filled points and would
  otherwise report "1 week of data" for a league that has played nothing. Below three weeks the app states
  the sample and **withholds the claims the sample can't support**: no posture chip, no clinch magic number,
  no posture map, no trend direction — while the numbers themselves (playoff %, VOR, bands) still show,
  flagged. Reachable today: pick Week 1 on the demo. Nothing changes at ≥3 weeks.
- **The honest band is wired end-to-end, and dark until 2026 (P2/S3b).** `ros_player_band` is now a loaded
  table, selected by `load_player_card` (pinned to `production_vor`'s week) and rendered as a **"Rest-of-season
  range"** panel — bear / center / bull in points, with the ±σ spread as the confidence read (no label: the
  width *is* the confidence, and the `ros_cv` that would have supplied one was measured INVERTED in S5 and
  retired in 8c). It sits **beside** the AI `ros_synthesis` panel — a different object, not a replacement.
  **It serves 0 rows today** and renders an honest absent-state: only seasons at or above
  `build_db.FIRST_HONEST_BAND_SEASON` (2026) may be served, and no 2026 league exists yet. It lights up by
  itself when one is onboarded.
- **Why the 2020–2025 band stays stale — a deliberate boundary, not an omission.** That parquet is also the
  frozen-corpus artifact the **immutable L2 ledger** was derived from, so rebuilding it at the honest
  constants would break the ledger's reproducibility; a corpus re-backfill is the **annual pipeline's** job.
  → *ARCHITECTURE, "The honest-band boundary".*
- **Still true of the weekly surfaces:** MatchupDetail's "Score Range · 25–75" is
  `projection_consensus.p25/p50/p75` under `BAND_Z`/`SKEW_GAIN`, which 8c deliberately **held**, and matchup
  μ/`proj` is `Σ center_ppr` straight from consensus, bypassing `CENTER_SHRINK`. Applying the shrink to the
  weekly serve path is an unmeasured engine change, so it stays a tuner question under propose-only.

## What's real vs. proof-of-concept (current caveats)

- **ROS bull/bear/situation shows an explicit "No rest-of-season outlook yet" empty state** — the read runs on
  live in-season news, which isn't wired yet; an honest empty state, not fabricated grades.
- **The market read is gated off everywhere (P2/S3).** `market_vor` prices *today's* market against a *past*
  season's rosters — `is_cross_time=true` — so all four market surfaces (Players MKT, team-detail MKT toggle,
  player-card market trend + BUY/SELL lean, League positional talent) render an honest "not a live read"
  state instead. The gate is the read's own flag, not a season constant: `panels.market` = the manifest's
  structural flag AND `NOT is_cross_time`, so a contemporaneous league (2026 production × 2026 prices) turns
  the panels back on by itself. `compute_market_vor` is proven contemporaneous-ready.
- **Rostered-only** — no free-agent / waiver value yet.
- **Data collection is hosted off-laptop and hardened (P1, ~done).** The two daily collectors run on **GitHub
  Actions → Supabase Storage** (S1, live), with fetch-timestamp sidecars, a same-day **catch-up retry**,
  flush-batched uploads, and a daily **coverage gate that emails on a missed/short day** (S2). The only thing
  left is the **rolling two-week soak proving ≥95%** coverage — **P1 closes when it clears.** → *see appendix:
  data-collection.*

## The active roadmap

**V1** = a working, **invite-gated self-serve** product for **Sleeper PPR / half-PPR redraft** (1QB and
superflex), running on **live 2026 data**, ready for the invited cohort by **Week 1** (Thu 10 Sept 2026).
Seven projects (P0 finish multi-league → P6 launch hardening); critical-path spine P0 → P2 → P5.

**P0–P2 done.** P2 delivered the un-freeze end to end: the 2026 preseason substrate (ppr+half, honest
constants, `check_forward_substrate` green), the per-league scoped loader + weekly-refresh orchestrator,
the honestly-retired cross-time market, the wired-but-dark ROS band, and the honest early-season window.
→ `sessions/v1/P2-Go_Live_2026/`.

**P5 (accounts + invite-gated self-serve onboarding) is the active block** — 7 sessions, S0–S6, the
critical-path long pole. Everything but S6 is buildable against the 2025 replay now, so the preseason
runway is for building and Gate A is for verifying.

**P5/S0 done — the cold-league latency spike, and it reshaped the connect UX.** A cold league is loadable in
a **measured 8.4–10.3s**, but the Manager Dossier's cross-league fan-out adds **80s / 248 Sleeper calls**,
and its own source calls that a once-per-season job. So connect is **staged**: the four fast surfaces on a
spinner, manager profiling as a separate deferred job class. Network-bound, not compute-bound → the S3
worker is **1 GB `shared-cpu-1x` + a 1 GB volume, ~$7/mo flat to 200 leagues** (that's *worker* cost; the
per-league cost that scales is metered per token). Shared-substrate reuse proven.
`serve/bench_cold_league.py` is committed so **S3 re-runs it unchanged on the worker**.
→ `sessions/v1/P5-Self_Serve/SESSION_P5_S0_REPORT.md` + its audit.

**P5/S1 done — the app has a front door, and it is live.** Supabase Auth, **magic link**. The API verifies
access tokens (ES256) against the project's JWKS and exposes **`/api/me`**, the only *authenticated*
endpoint; it 401s on missing/garbage/forged/expired tokens and 503s when the verifier is unreachable
(denied either way, but an outage stays distinguishable from a bad credential). Every read stays open by
design — authentication without scoping is a half-gate, so closing and scoping the reads is **S2**, one
change with one proof. → `sessions/v1/P5-Self_Serve/SESSION_P5_S1_REPORT.md`.

**P5/S1b done — the signup model corrected.** S1 shipped an *invite* gate because the brief read "word of
mouth" as Will provisioning each person; he meant only that he wouldn't promote the site. So signup is now
**self-serve behind a shared access code**, enforced **server-side** at `POST /api/signup` — the API holds
the secret key and does the admin create itself, which is what makes platform-signup-OFF compatible with
zero per-user work. The code is required from everyone on every request, so *no valid code → no email ever
sent*. The rate limiter lives in Postgres, not memory: two Fly machines with scale-to-zero would otherwise
let an attacker reset it by waiting out the idle window. `scripts/invite.py` → `scripts/users.py`
(`--list`/`--ban`/`--unban`) — nobody is invited now, but self-serve creates the need to remove someone.
**Custom SMTP is a hard dependency**: Supabase's built-in sender *refuses* addresses that aren't project
team members, so without it no friend can receive a link at all.
→ `sessions/v1/P5-Self_Serve/SESSION_P5_S1B_REPORT.md` + `SIGNUP_MODEL_ASSESSMENT.md`.

**Next: P5/S2** (ownership + API-layer per-user isolation — the security session; do not let a fast cadence
compress it, since isolation bugs fail silently). Two things still queue behind calendar gates, neither
blocking P5: **loading the first real 2026 league** at Will's draft (~late Aug) — a manual admin load, not
P5 — which data-proves S2's refresh, S3b's band panel and S4a's regimes at once and **must verify the
ROS-range panel against real band data**; and **S4b** (market turn-on) post-launch.
→ `ROADMAP.md` + `projects/v1/BUILD_ORDER.md` + `projects/v1/P5_ACCOUNTS_SELF_SERVE_ONBOARDING.md`.

## Deferred / parked (not blocking; each picked up in its project)

- **The ROS-range panel is unverified against real band data.** Everything around it is proven — the loader
  guard, the parity oracle across 14 tables, the pinned select, the absent-state — but the populated panel was
  only ever rendered from a synthetic payload stubbed into a local process. The session that loads the first
  2026 league should treat verifying it as part of its own DoD.
- **A corpus re-backfill would un-freeze 2020–2025** (annual pipeline, not a session): re-run the band under
  the live constants, re-derive the ledger's band claims as a **new-`code_version` parallel population** (the
  ledger is append-only-of-new and already supports this), then lower `FIRST_HONEST_BAND_SEASON`. Until then
  the replay seasons legitimately show no ROS range. Two known pre-existing reds live in that same corpus
  lane and are unrelated to serving: `check_predictions` (the is_mine **2024** slice is spined for the demo
  but was never backfilled into the ledger) and `backtest_ros_player_band --season 2025` (it grades the
  frozen pre-8c band, coverage 0.468 vs the 0.80 target).
- **`market_vor` has no cadence.** Nothing recomputes it — not the weekly refresh (that rebuilds the spine),
  not the collectors — yet `load_league` re-publishes it on every scoped reload. It currently trails the raw
  series by ~2 weeks and is priced against `as_of_week` 4 while the league sits at 5, so `check_market_vor`'s
  recompute-match verdict is red (it now says why). Fix when the live panel turns on.
- **Three things bite when the live 2026 market panel turns on** (S4/later): `MARKET_PROFILE` is hardcoded to
  `redraft-1qb-12t-ppr1` — deriving it from league shape is the fix for the parked **superflex QB-pool
  latent** (the feed already banks `redraft-2qb-12t-ppr1` and `ppr0_5` daily); the API hardcodes
  `max(snapshot_date)`, so the market won't replay with the week selector (cross-*week* replaces cross-*time*
  as the time-world bug); and LeagueLogs requires **"Powered by LeagueLogs API"** attribution on any UI that
  displays it — absent today, a launch blocker once the panel is ungated for real users.
- **Silent-reads confidence (the ENGINE half — post-V1).** A *native, measured* confidence column on
  `production_vor` / `player_signal` direction / `bracket_odds` wins+seed, proven monotone-honest against
  `CONF_MONO_MARGIN` and moved from `NO_CONFIDENCE_FAMILIES` into `CONF_SIGNALS`. S4a shipped the display
  half instead (state the sample, withhold what it can't support) — deliberately **not** a derived
  confidence tier, because asserting an unmeasured confidence is exactly how `ros_cv` shipped inverted.
  Note `bracket_odds.proj_wins` reaches **no client** today, so "playoff wins" has no surface to carry a
  signal until it does.
- **`ros_player_band` has RLS disabled** while the other 13 served tables have it enabled (found in P5/S1) —
  RLS was turned on by hand, then a later `--emit`/`--load` recreated that table without it. Zero practical
  exposure today (the owner role bypasses RLS and the Data API is off), but it shows the general failure:
  **any out-of-band property on a `schema.sql` table is destroyed by the next full load.** The durable fix is
  to make `--emit` emit the `ALTER TABLE … ENABLE ROW LEVEL SECURITY` lines; **S2 owns it.**
- **`weekly_refresh._resolve_scoring_key` would silently mis-score a stranger's league** (found in P5/S0).
  A league absent from `demo_manifest` falls back to `data_layer._active_league(season)[1]` — *the owner's*
  scoring key. Every user's league is absent from the catalog until the connect flow catalogs it, so this
  sits on P5's live path. Fix = derive from the league's own settings (`_keys.scoring_key_from_settings`,
  which is what the S0 harness does). Harmless today (nothing but demo slices refresh); **P5/S4 owns it.**
- **`_derive_matchup_result` mints a phantom W/L on a tie.** It ranks a matchup by
  `sort_by(roster_total_points, descending).first()` with **no tie branch**, so both a 0-0 unplayed matchup
  and a genuine real-life tie produce a W and an L decided by sort order. `compute_bracket_sim` handles the
  same case correctly (0.5 each), so the served record and `bracket_odds.current_wins` disagree by
  construction. Changes measured data and only takes effect on a re-join → its own bounded session with a
  parity check, worth doing before the season runs deep. (S4a's depth clock reads points, not W/L, so it is
  already immune.)
- **`matchup_win_probs` returns 50/50 whenever both σ are 0**, regardless of μ — a 30-point projected gap
  included. Pinned by `check_projections`, and it disagrees with the sim's own `_win_prob`, which returns
  1.0/0.0 there. Only reachable on a week with no projections at all.
- **`*_ppr` naming wart** — the `center_ppr` / `band_ppr` / … columns hold *league* points, not PPR; the
  rename is coupled to a frontend + schema change. → *see appendix: scoring-mechanism.*
- **Post-V1 features** — other scoring formats, dynasty, other platforms, owner-keyed dossiers, annual
  re-tune → `projects/post-v1/`.
