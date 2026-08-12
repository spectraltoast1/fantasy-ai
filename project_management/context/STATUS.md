# STATUS

**What this is:** SurplusFF — a fantasy-football decision-support dashboard whose unit is the manager's
*decision*, not the player. Live, single-league, on the server stack.
**Live at:** https://surplusff.com/ (also https://fantasy-ai-api.fly.dev/) · **Updated:** 2026-08-12
**Name + domain:** the official name is **SurplusFF**, commonly shortened to **Surplus** (Will,
2026-08-05); "Gridiron" was a working name — retire it. **surplusff.com** is registered (SSL live), serves
the app (Fly cert + DNS), and is the **Resend sending domain** for auth email — Supabase's custom SMTP
sender, which is what makes a magic link reach anyone who is not a project team member. It is the
**canonical origin**: S1b removed S1's `emailRedirectTo`, so a magic link goes wherever Supabase's **Site
URL** points regardless of where the person signed up, and that is surplusff.com — so a sign-in started on
either host returns there (round trip observed 2026-08-04 →
`sessions/v1/P5-Self_Serve/SESSION_P5_S1B_AUDIT.md`). The UI still says **Gridiron**; moving it is an
undecided, cosmetic-but-broad change (SPA copy plus Supabase's redirect allow-list), not a launch
dependency.
**Read next:** `ARCHITECTURE.md` (how it's built) · `CODING_BIBLE.md` (rules for coding agents) ·
`ROADMAP.md` (where it's going) · `projects/v1/` (the active build).

---

## What's live today

- A deployed, mobile-responsive React SPA on **FastAPI + Supabase Postgres** (Fly.io, same-origin). Five
  surfaces: **Players, Teams, League, Matchups, Manager Dossier**.
- **Multi-league, and leagues now have owners.** All **31 demo league-seasons (12 lineages)** are still in
  the production DB — they are engineering fixtures — but the **public catalog is one league**: the demo,
  plus whatever the signed-in caller owns. Every read is parameterized on
  `league_id`(+`season`+`viewer_roster_id`) and now defaults to `DEMO_LEAGUE_ID` explicitly. League + week
  selectors re-scope every surface, and the "you" highlight follows the selected league.
  → *`sessions/v1/P0-Multi_League/` + `sessions/v1/SESSION_B6_VERIFICATION_REPORT.md`.*
- **The app can now advance week by week (P2/S2).** The loader has a **per-league scoped reload** and a
  **weekly-refresh orchestrator** advances one league to the current week without rebuilding the DB —
  proven on prod by advancing the owner's 2025 league Week 4 → 5 (the un-freeze). Ready for live 2026 at
  kickoff. → *see below + `sessions/v1/P2-Go_Live_2026/`.*
- Fully migrated off in-browser DuckDB-WASM (Stage A complete); the client is now a thin API client.
- **Web analytics — GA4, installed 2026-08-10.** The gtag tag sits in the SPA's one `index.html` shell
  with `send_page_view:false`; `src/analytics.js` sends the virtual pageviews (no router → GA can't
  otherwise tell one surface from another) and five sign-in-funnel events. All eight surfaces proven,
  no hit for `/`, and no GA request carries an `@` or any id. Measurement only: no read, number or
  pixel changes. `signed_in` is the one event awaiting a real prod sign-in. → *see appendix: analytics.*

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
**Gate A's one blocker is cleared (2026-08-05):** `transforms/_matchup` is now the single rule the join
and the sim share — *a matchup is gradeable iff it has a `matchup_id`, exactly two rosters, and somebody
scored; else null, never fabricated.* A freshly drafted league had minted a full W/L slate by roster-id
sort order before a game was played; it now reads `0-0`. A genuine tie became a real outcome (`'T'` →
`2-1-1`), and the null-`matchup_id` playoff case was **not** merely latent — `weekly_refresh` joins
without `harvest`'s `playoff_week_start - 1` clamp. Nothing was re-joined or reloaded: only a *future*
join changes, reaching Postgres via `weekly_refresh`'s existing `reload_league`. Parity is exact — 80
read payloads byte-identical to main, and across all 271 corpus league-seasons exactly **4** groups
change verdict, all genuine ties outside the demo slate.
→ `sessions/v1/P2-Go_Live_2026/` (+ `SESSION_P2_MATCHUP_TIE_REPORT.md`).

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

**P5/S2a + S2b done — per-user isolation is closed, discovery *and* access.** S2a gave leagues owners
(`public.user_leagues`) and scoped the **catalog**, so you cannot *find* someone else's league; S2b scoped
the **eleven per-panel reads**, so knowing a `league_id` is no longer enough to *read* one. Visibility is one
predicate in one function at one seam (`slice_params` → `reads.authorize_slice`), and an unowned league
returns bytes identical to a nonexistent one while a broken deploy raises 503 — mechanism in ARCHITECTURE.
Two fixture-driven gates with prove-it-bites blocks: `check_ownership.py` (8/8 fail pre-S2a) and
`check_isolation.py` (**82 assertions fail against the real pre-S2b binary**). Proven with two real accounts
over 165 live requests, 19/19 demo payloads value-identical. Honest caveat carried forward: `slice_params`
defaulting to the demo is **unobservable today** because `DEMO_LEAGUE_ID` *is* the is_mine league — S2a
proved it by temporarily repointing the config at Trap 2025.
→ `sessions/v1/P5-Self_Serve/SESSION_P5_S2A_REPORT.md` + `SESSION_P5_S2B_REPORT.md`.

**P5/S2c done — the punch list, and audit F6 with it.** Nine loop-closers; no open security hole among
them. **The current season is now derived locally** (calendar year, or the year before it until **August 1**,
a boundary that deliberately *leads* Sleeper's flip). `nfl_state.py`, `nfl_state_cache`, the 5s timeout and
both fallback branches are **deleted** — they existed only to survive a Sleeper outage, which S2b had made
eleven endpoints wide, and removing the failure beat handling it. Sleeper is now an assertion in
`check_ownership`, not a dependency; **`/health` publishes the season + its source** (F7), still DB-free.
The rest — the signup limiter counting only valid-code requests, cascade/orphan assertions, a rejected
token that *says* the session was lost, a catalog error instead of a permanent "Loading…", and a tab
refocus that no longer resets league/week/drill-down — are in the report.
→ `sessions/v1/P5-Self_Serve/SESSION_P5_S2C_REPORT.md` + *appendix: auth*.

**P5/S2d done — the demo is no longer Will's league.** It is now **`DEMO-2025` / "DEMO League"**: a
GENERATED, anonymised clone of LoRP 2025 at week 5 — invented names, no `is_mine`, no viewer seat, so no
"you" highlight and none of the ten real Sleeper handles that were on the landing page until today (swept:
**0 hits across 51.5KB of live payload**). Generated, not inserted, so `--load` re-materialises it rather
than it surviving only to the next schema change — the failure that cost `ros_player_band` its RLS; proven
by regenerate + re-publish, **14/14 tables value-identical**. `--emit` now emits RLS for all **15** served
tables and `--verify` asserts it. The catalog TABLE is now **`league_catalog`**; the parquet keeps its name
and its 31 frozen rows.
→ `sessions/v1/P5-Self_Serve/SESSION_P5_S2D_REPORT.md`.

**P5/S2e built and merged — the honesty pass on the League screen, and the season selector is gone.**
**NOT YET DEPLOYED as of 2026-08-12** — `main` is correct but production still serves the pre-S2e
payloads (`posture` present, catalog nested); verified on four cache-busted probes against a
baseline captured before the merge. **Run `fly deploy`, re-check, then delete these three lines.**
→ `sessions/v1/P5-Self_Serve/SESSION_P5_S2E_AUDIT.md`. Four defects in
one shape: *the UI asserting more certainty than the model has*, stacked on one row of the landing page
(rank 9 read "0%, no path"; the truth is "0.3%, needs help"). Playoff odds are hedged at both ends —
**`<1%` / `>99%`** — because a sim 0 means "did not occur in 10,000 tries", not eliminated; there were
**five** render sites, not the three the brief named. A null magic number now says **"Needs help to
clinch"** — the producer's only way of saying *no win total guarantees a spot* — instead of rendering blank
on one panel and `—` on another. **"Clinched a spot" is retired**: `MAGIC_ODDS` is 0.90 and the engine
calls the value a *proxy*; Clinched/Eliminated may come only from real bracket math, which is deferred.
`check_league_copy.mjs` gates it — 39 checks, dependency-free, **26 fail against the pre-S2e code**. The
**season selector is removed and the catalog is flat** (one entry per visible league, season on the row):
the nesting only ever fed that selector, and `visible` already admitted at most one season per lineage.
League + week switchers stay. Also fixed: `TeamDetail`/`MatchupDetail` spun for ever on a legitimate
`200 null` (filed in S2b) — `null` was both the in-flight sentinel and the "no such thing" payload.
**Parity: 40 of 43 demo payloads byte-identical**, the other three identical once `posture` is stripped and
the baseline hand-flattened. → `sessions/v1/P5-Self_Serve/SESSION_P5_S2E_REPORT.md`.

**`posture` is WITHHELD from the API — the metric is wrong, and that is the next session.** `gap =
all_play_pct - playoff_odds_pct` subtracts two quantities that are not the same unit: odds saturate toward
0 and 100 while all-play compresses toward 50, so the gap tracks the shape of the odds curve rather than
luck. Measured 2026-08-12: with `BAND = 9` and the smallest |gap| in the league at 12.0, **every** team read
*Riding luck* or *Unlucky*, three of the five labels were unreachable, and the highest all-play team was
told to sell. It is inverted for **every** league, not just the demo — `derive_posture` runs on every
standings row served. A correctness defect, not a calibration one, so retuning `BAND` cannot fix it. One
server line withholds it (`reads.load_standings` is the only caller, feeding both `/api/standings` and
`/api/league`); `calcs.derive_posture` stays for the fix. The map **kept its scatter and lost its
interpretation** — dot positions are true, the diagonal and buy/sell quadrants were not. **The fix is its
own measured session:** compare like with like (**all-play % vs actual win %** — same unit, so the gap
*is* luck; rank-vs-rank is the fallback), then **re-measure `BAND`/`LEVEL_CUT` on the new scale**. Note
`derive_posture` now lives in exactly **one** place (`api/calcs.py`) — the `frontend/src/posture.js` mirror
that older notes refer to went with the DuckDB-WASM client, so the fix is cheaper than it was sized.

Two things still queue behind calendar gates, neither blocking P5: **loading the first real 2026 league**
at Will's draft (~late Aug) — a manual admin load, not P5 — which data-proves S2's refresh, S3b's band
panel and S4a's regimes at once and **must verify the ROS-range panel against real band data**; and
**S4b** (market turn-on) post-launch.
→ `ROADMAP.md` + `projects/v1/BUILD_ORDER.md` + `projects/v1/P5_ACCOUNTS_SELF_SERVE_ONBOARDING.md`.

## The demo, visibility, and what a signed-in user sees (decided 2026-08-05; **built in S2a + S2b**)

The model is now code — the mechanism lives in `ARCHITECTURE.md` and `appendices/auth.md`, not here.
Nothing from that decision is outstanding: the season selector was the last piece and went in S2e.

- **The 31 corpus slices stay in the database** — engineering fixtures for `compute_demo_slices`,
  `build_demo_manifest`, B6's 31/31 and `check_scoped_reload`'s parity oracle. Only the public catalog
  shrank. Nothing was deleted.

**The demo clone shipped in S2d** — real computed data everywhere it exists, identities fictional, and
`is_synthetic()` keeps it invisible to every producer (the concrete hazard being `weekly_refresh` trying to
fetch a league that does not exist on Sleeper). **Two pieces of the original clone brief did NOT ship and
are deliberate:** the rest-of-season band (the clone is season 2025, below `FIRST_HONEST_BAND_SEASON`, so
that panel is dark exactly as it was for the old demo) and the **synthetic AI outlook** — `ros_synthesis`
has no 2025 file, so the panel is empty by construction. **P4 stays ahead of P3** and retires that
placeholder for real.
→ `sessions/v1/P5-Self_Serve/SESSION_P5_S2D_REPORT.md` + `SESSION_P5_DEMO_LEAGUE_CLONE.md`.

## Deferred / parked (not blocking; each picked up in its project)

- **Deferred: let the join resolve a null position from the pinned registry.** `_apply_registry_eligibility`
  fires only on the *conflict* branch, so a rostered player with no `nflreadpy` row keeps a null position
  and falls to remainders — which is *why* `audit_join` synthesises repair rows at all. Coalescing the null
  retires that class, but it changes the corpus **row population** the L2 ledger grades against, and a
  refactor that changes a number is a bug until equivalence is proven. **Its own session; first deliverable
  is a corpus-wide count.** → `sessions/v1/P2-Go_Live_2026/SESSION_P2_AUDIT_JOIN_NULLS_REPORT.md`.

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
- **`weekly_refresh._resolve_scoring_key` would silently mis-score a stranger's league** (found in P5/S0).
  A league absent from `demo_manifest` falls back to `data_layer._active_league(season)[1]` — *the owner's*
  scoring key. Every user's league is absent from the catalog until the connect flow catalogs it, so this
  sits on P5's live path. Fix = derive from the league's own settings (`_keys.scoring_key_from_settings`,
  which is what the S0 harness does). Harmless today (nothing but demo slices refresh); **P5/S4 owns it.**
- **`matchup_win_probs` returns 50/50 whenever both σ are 0**, regardless of μ — a 30-point projected gap
  included. Pinned by `check_projections`, and it disagrees with the sim's own `_win_prob`, which returns
  1.0/0.0 there. Only reachable on a week with no projections at all.
- **`*_ppr` naming wart** — the `center_ppr` / `band_ppr` / … columns hold *league* points, not PPR; the
  rename is coupled to a frontend + schema change. → *see appendix: scoring-mechanism.*
- **Post-V1 features** — other scoring formats, dynasty, other platforms, owner-keyed dossiers, annual
  re-tune → `projects/post-v1/`.
