# STATUS

**Last updated:** 2026-06-17 (per-panel readiness gate — Phase 1 complete)
**Target ship:** NFL kickoff, mid August 2026

---

## Project Management
- my role is CEO/CFO managing the project as a whole, role responsibilities include:
    - owning product direction decisions
    - connecting Claude Chat input/output and Claude Code input/output
- Claude Chat sessions will serve as Product Manager, role responsibilities include:
    - advising on project goals, product direction, and build method
    - writing prompt instructions for Claude Code to execute singular build tasks
    - review the after-build action report from Claude Code
- Claude Code sessions will serve as Software Engineer, role responsibilities include:
    - receive the prompt instruction from the Claude Chat

## Project Overview (what are we working toward)

Winning a redraft fantasy football championship is about more than just collecting all of the best players. It is about how you manage your specific team in your specific league. Knowing when you need to act - or not act - as a team manager is as valuable as knowing which individual players to target or avoid. This tool focuses on helping you navigate your league using real data signals: how your team is trending, where your real weaknesses are, and what your opponents look like. The goal is fewer decisions driven by anxiety or noise, and more decisions made on league-winning signal.

The project will do this in two ways: a dashboard for user-driven insight and an AI layer for interpretation and decision suggestions. The AI layer is not meant to run the team - it's a consultation, putting data-driven suggestions alongside the user's own analysis to produce better decisions.

> Tech non-negotiables (polars-only, all I/O through data_layer.py, client-side
> DuckDB-WASM with src/queries.js as the server seam) live in **CLAUDE.md** and
> **TECHNICAL_ARCHITECTURE.md** — not restated here.

## Today (the current status toward v1)

> **Maintenance (rolling log):** keep only the **most recent build + the 2 prior**
> (3 prose entries max). At closedown, prepend the new build and delete the oldest
> prose entry. Nothing is lost — the cumulative record lives in `> built` below; this
> section is just the recent-detail window. Keeps the doc light for every session.

> most recent build
**Phase 1 — the per-panel readiness gate (part 4). Phase 1 is now complete.** A
cross-cutting front-end seam so panels degrade cleanly when data is thin, rather than
each hard-coding its own week check. New **`readiness.jsx`**: `assessReadiness(regime,
weeks)` — a single home for the rule — maps a panel's **regime** (structural /
point-in-time / trend) + weeks elapsed to **ready / building / tooEarly**; a **`Gate`**
wrapper renders the content (with a subtle "early read — weight it lightly" note when
*building*, per law 2) or a **"too early" fallback slot** that accepts custom children
(the hook for preseason/qualitative content later, no rework). Wired into the Team tab:
construction = structural, Form + leakage = trend, Players = point-in-time. **Frozen at
week 4 → everything reads `ready`, no UX change** (exactly the spec's intent). A
`?weeksOverride=N` query param drives the clock for QA / in-season rehearsal. Verified
live across the clock: wk4 all ready (no regressions); wk3 trend panels show the
building note + content; wk2 trend panels hand off to the too-early slot while
structural stays on; wk0 Players shows the slot. No console errors. **Phase 1 (spike
signal-quality slice) is now end-to-end: engine + backtest gate + Players surface +
readiness gate — all four parts shipped.**

> earlier build
**Phase 1 — the Players sub-view: the spike signal surfaced on the front end.** The
engine shipped last session as parquet only; this session gives the stubbed Players
sub-tab its purpose. Per rostered skill player, a **sortable table** answers "is this
production real or noise?" — recent /g next to a **directional verdict** (Looks real /
Toss-up / Cooling likely / Too early), with the evidence (volume rank in position, TD
share). Per the product decision, the signal is shown as a **direction, never a points
projection**, and framed as **a question the manager adjudicates** (laws 2+4); thin
samples gate to "Too early" (e.g. Woody Marks 27.9 recent but 1 game → held). New seam
fn **`loadTeamPlayers(rosterId)`** reads `player_signal.parquet` and assembles
view-ready rows — **no signal math in JS** (it lives in the transform); `db.js`
registers the parquet; `TeamPanel` loads per selected team (respects the switcher).
This is where the dashboard first becomes a *decision coach* on the front end, not just
a state display. Verified live: 19 rows for the user's team, no console errors, sorting
toggles, sample-gating correct. **Remaining in Phase 1:** the per-panel readiness gate
(part 4).

> earlier build
**Phase 1 — the spike signal-quality engine + its backtest gate (data/backtest
only; no UI this session).** The first decision-critique slice: "is this production
real, or is it noise?", built on usage data already fetched (no projections needed).
New transform **`compute_player_signal.py`** → `snapshots/derived/player_signal_2025.parquet`,
one row per rostered skill player (172). Same SOLID shape as the team transforms (pure
`_player_signal` with **injected** constants `SHRINK_K`/`MIN_GAMES`/`SPIKE_BAND`/
`STICKY_BAND`/`POS_MEAN_MIN_OPP`, `compute()` the composition root, helpers from
`_analytics`). It decomposes recent production into **sticky opportunity** (`opp_g` —
targets / carries+targets / pass-att+carries, carried forward) vs **fragile efficiency**
(`ppo` = points/opportunity, shrunk toward the league-wide positional mean by sample
size). Headline `regression_risk = 1 − expected_ppg/recent_ppg`; a sample-gated
categorical `read` (too_early/spike/mixed/sticky) keeps language honest (law 2);
`td_share` carried as the legible evidence. It is a *characterization of past
production, not a forward projection* (law 3). New `data_layer` read/write fns; the
positional efficiency mean is taken over the full NFL stat pool (borrowed substrate),
not just rostered players. **`backtest_player_signal.py`** imports the *same* shipped
`_player_signal` and validates it against the full-2025 answer key (input wks 1–4,
truth wks 5–18): **predictive PASS** — signal cuts rest-of-season MAE 13.2% vs a naive
"recent-points" baseline (RMSE 3.88→3.42, corr .79→.82), robust at every freeze W3–W8;
**decision-relevant PASS** — among hot players (which naive can't tell apart) the
`spike` group regressed −3.9 pts/g (TD-share .38; e.g. Lamar 23.3→13.5, Fields
20.2→13.7) while the `sticky` group held flat (−0.02, TD-share .16). The engine is
proven real; this backtest-vs-answer-key pattern is the template for every future
slice. **Not yet built:** the Players sub-view surface + the per-panel readiness gate
(Phase 1 parts 3–4).

> built
    - nflreadpy fetcher
    - sleeper fetcher (includes fetch_players() for Sleeper player registry)
    - nfl_sleeper join (left join, Sleeper-authoritative)
    - audit_join (resolves unknown-position remainders post-join)
    - front-end skeleton (React + Vite + DuckDB-WASM, reads live parquet) — Power Rankings panel
    - leaguelogs fetcher (daily market-value snapshots, all profiles) + launchd 4am-ET scheduler
    - sleeper teams fetch (fetch_teams → teams_2025.parquet) — real team names on Power Rankings cards
    - roster_positions fetch + derive_lineup_slots transform — declared starting-lineup config (lineup_slots_2025.parquet)
    - Power Rankings team drill-down drawer — all-play true record, lineup efficiency, weekly scoring, consistency + positional-shape spectrums
    - tab nav shell (League | Team) — App.jsx shell + LeaguePanel/TeamPanel split
    - Team tab foundation — your-team resolver (loadTeams + MY_USERNAME), team switcher, Overview/Players sub-tabs (stubbed)
    - Team Overview sub-view — vitals + "how this team is built": rate-based depth chart, league-relative star dependence, auto-surfaced lineup/hole signals; loadTeamRosters(), shared posColors.js [Overview lenses 1–2 of 4]
    - Team Overview — Form / trajectory lens: direction headline (heating up/cooling off/steady), league-relative Fading↔Surging spectrum, weekly column chart (beat/below median); last-half vs first-half scoring swing in loadTeamRosters() [Overview lens 3 of 4]
    - Team Overview — Where-you-leave-points lens: season points-left + efficiency % on a league-relative Leaky↔Optimal spectrum, per-week leak chart, biggest specific start/sit misses (eligibility-aware pairing); shared optimalLineup()/expandSlots() helpers + computeLeakage() [Overview lens 4 of 4 — Overview complete]
    - Team Overview refinement — Form lens → recency-weighted EWMA slope (half-life 2wk, ±4%/wk direction band, recency-faded weekly bars); computeForm() rewritten [backlog item 2]
    - Team Overview refinement — Lens-4 reframe (retrospective → improvement): efficiency-led, season points-left split into variance vs coachable (repeatable >10% bench-over-starter fix, sum-exact), named-miss list replaced by one rate-gap fix; computeLeakage() takes season role+rate map [backlog item 1]
    - Architecture refactor — form + leakage analytics extracted from queries.js → Python transforms (compute_team_form.py + compute_team_leakage.py → snapshots/derived/), tuning constants moved with them; queries.js slimmed to a thin read+assemble seam (−253 lines); loadTeamDetails efficiency consolidated to read the leakage parquet. View components untouched.
    - Phase 1 spike signal-quality engine — compute_player_signal.py → derived/player_signal_{season}.parquet (opportunity-vs-efficiency decomposition, regression_risk, sample-gated read); backtest_player_signal.py validates the shipped function against the full-2025 answer key (beats naive recent-points 13% on MAE; spike group regresses ~3.9 pts/g while sticky holds). First decision-critique slice; data + backtest only, no UI yet.
    - Phase 1 Players sub-view — sortable table surfacing the signal read per player (recent /g, directional verdict, volume rank, TD share); loadTeamPlayers(rosterId) seam reads player_signal.parquet (no JS math); direction-not-projection, question-framed (laws 2+4), sample-gated. The front end's first decision-coach surface.
    - Phase 1 per-panel readiness gate — readiness.jsx (assessReadiness + Gate): per-panel regime (structural/point-in-time/trend) → ready/building/tooEarly, with a "too early" fallback slot (accepts preseason content later) and an early-read note when building; wired into the Team tab (?weeksOverride=N for QA). Closes Phase 1.

> not yet built
    >> backend
        - The Odds fetcher
        - FantasyPros fetcher
        - weather fetcher
    >> frontend
        - production front-end — React + DuckDB decided; Power Rankings panel built + deepened
          (team drill-down drawer with all-play, efficiency, weekly scoring, two spectrums).
          Remaining: more panels (per the Build Order below), deployment.

## Current build target
**Phase 1 (the spike signal-quality slice) is COMPLETE** — all four parts shipped:
(1) the engine (`compute_player_signal.py`), (2) the backtest gate (beats naive
recent-points −13% MAE on the full-2025 answer key), (3) the Players sub-view surface
(sortable table, direction-not-projection, question-framed), and (4) the per-panel
readiness gate (`readiness.jsx` — regimes + fallback slot). The descriptive dashboard
(Phase 0) plus the first decision-critique engine are both done; the project has made
the leap from *showing team state* to *grading a decision against a prior*. Still
frozen at Week 4 of 2025 for building.

**Next: Phase 2 — the projections substrate** (see Version Roadmap / PRODUCT_ROADMAP).
A `fantasypros.py` fetcher → current projections, plus a transform producing a
**consensus + disagreement (spread)** read. This is the hinge: it supplies the forward
prior every later decision slice rests on, calibrates the spike read's *forward*
language, and fixes the engine's one honest blind spot (the Kamara-style decline that
usage alone can't see — a real backtest miss this session surfaced). The spread itself
becomes the law-2 confidence signal (tight consensus = act, wide = coin-flip).

## Version Roadmap
→ **Source of truth: `scope docs/PRODUCT_ROADMAP.md`** — phase detail, the four
design laws (grade process not outcome; speak only when confident; borrow the
substrate; consultation not autopilot), sequencing logic, and the scope filter.
Summary only here:

- **Phase 0 — Descriptive dashboard** *(done)* — team overview, league standings,
  power rankings. Frozen at Week 4 of 2025.
- **Phase 1 — Spike signal-quality slice** *(current; kickoff target)* — "is this
  production real or noise?" on usage data already fetched; validated against the
  full-2025 answer key before going live.
- **Phase 2 — Projections substrate** — FantasyPros fetcher + consensus/disagreement
  spread (the forward prior; the hinge everything credible depends on). Odds/Vegas
  an optional cheap add.
- **Phase 3 — Shared engines + leakage fix** — generalize the slice into
  signal-quality / context-fit / opponent engines; fix the coachable-claim
  (process-not-outcome, regress to prior — backlog #1); add start/sit context.
- **Phase 4 — Go live + opponent modeling** — in-season weekly refresh; opponent
  reads + manager-dossier infra; waiver and trade surfaces.
- **Phase 5 — Model of YOU** — graded decisions compound into a per-manager
  tendency profile that personalizes guidance.
- **Phase 6 — Forward advisory + AI layer (later)** — real-time "better call now";
  AI interpretation over the engines; draft & streaming surfaces.

> **Old V# → phase map** (so version references elsewhere in this doc still resolve):
> V1 dashboard → Phase 0; V1.5 scheduler + V2 waivers → Phase 4; V3 start/sit →
> Phase 3 (projections = Phase 2); V4 trades → Phase 4; V5 AI → Phase 6.

## Known Scope Exclusions
→ Source of truth: **TECHNICAL_ARCHITECTURE.md § Known Scope Exclusions** (DST/K, waiver
wire / full player pool, IR roster overages, zero-stat rows). One product note kept here:
**Market value (V1)** is snapshotted daily now to bank the time-series, but the features
that consume it (trade analysis, value-aware rankings) are V4; any UI showing it must
carry the "Powered by LeagueLogs API" attribution.

## Next single highest-leverage move

**Phase 2 — the projections substrate.** With Phase 1 complete (engine + backtest +
Players surface + readiness gate), the next hinge is the forward prior every later
decision slice rests on. Build a **`fantasypros.py` fetcher** → current-season
projections (all I/O through `data_layer.py`; keyed on `sleeperPlayerId`), and a
transform producing a **consensus + disagreement (spread)** read across whatever
sources are pulled. Two payoffs: (a) the spread is the law-2 confidence signal — tight
consensus = act, wide = coin-flip; (b) it gives the spike read a *forward* prior to
regress toward, fixing the one honest blind spot the backtest surfaced (Kamara: usage
looked fine, the player declined — usage alone can't see talent/situation change).
Vegas game totals via an `odds.py` fetcher are an optional cheap add here (game
environment). Do **not** use prior-season carryover as the prior (biased by
age/injury/scheme). This is back to **Python/data-layer work** (fetcher + transform),
not front-end.

The readiness gate's `building`/`tooEarly` language is the first consumer waiting on
this: once a forward prior exists, early-season reads can be *calibrated* rather than
merely *gated*.

All Team-tab work should respect the team switcher already wired in.

## Refinement backlog — Team Overview (deferred, not blocking)

These refine shipped lenses; pick up alongside or after the Players sub-view.

> ✅ **Done (2026-06-07):** Lens-4 reframe (retrospective → improvement) and the Form
> lens EWMA switch both shipped. ✅ **Done (2026-06-17):** item 2 (per-panel readiness
> gate) shipped as `readiness.jsx` — see the maintenance log. **One backlog item remains:**

1. **Reframe the Lens-4 "coachable" fix from confident imperative → advisory question
   (and own its predictive weakness).** The shipped coachable fix says *"start X over Y
   going forward — +N/g on the season,"* which silently converts a tiny realized sample
   into a forward claim it can't support. **Worked example that exposes it:** at the wk-4
   freeze, Cousin 'Chilling's roster fired *"start Keenan Allen (16.3/g) over A.J. Brown
   (8.8/g) at WR going forward."* Pulling the *actual* rest-of-season from
   `nfl_stats_2025.parquet`: **Brown W5+ = 16.8/g, Allen W5+ = 9.0/g** — a near-total
   reversal; Brown won 7 of the next 10 head-to-heads by +67.7 pts. The call would have
   been backwards. Mechanism: 4 games, equal-weighted, **no talent prior** — Brown's two
   near-zero early games were noise a prior would discount; stars are the *worst* case for
   realized-rate reads. The leakage total is descriptively true (you did leave those
   points in wks 1–3); only the **forward language** overreaches. Directions:
   - **Language (near-term, cheap):** drop the imperative + "+N/g going forward." Pose it
     as a **question the manager adjudicates**, per the project mission (consultation, not
     autopilot): *"Is it time to pivot off Brown? He's scored 8.8/g to Allen's 16.3 over
     4 weeks — past fluke territory; decide if you still believe in him."* Surfaces the
     decision point; defers the call to the user.
   - **Trade-timing angle (V4):** a sustained underperformance isn't only a start/sit
     question — even if you *don't* believe the player rebounds, selling while perceived
     value is high (≈$0.85 on the dollar) beats holding until the market reprices
     (≈$0.35). Ties to the **LeagueLogs market-value** layer (V4). The signal's real job
     is to flag "make a call here," not to make it.
   - **Real fix (V3):** regress realized rate toward a forward prior (FantasyPros
     projections / ADP) before calling anything coachable; gate the language on sample
     size (see item 2). Until then, keep coachable **retrospective**, not predictive.

2. ✅ **DONE (2026-06-17) — Per-panel readiness gate.** Shipped as `readiness.jsx`:
   `assessReadiness(regime, weeks)` + a `Gate` wrapper. Regimes — **structural** (ready at
   roster lock), **point-in-time** (ready week 1, confidence grows), **trend** (ready
   ~week 3–4) — map to ready / building / tooEarly; a **"too early" fallback slot** accepts
   custom children (the preseason-content hook, no rework) and a *building* note calibrates
   language on thin samples. Wired into the Team tab (construction = structural, Form +
   leakage = trend, Players = point-in-time). Frozen at week 4 → all ready; `?weeksOverride=N`
   drives the clock for QA. The deeper "calibrate to a forward prior" half is **Phase 2**
   (projections) — the gate is the seam; the prior that sharpens it comes next.

## The step after (unconfirmed, subject to change)

Continue down the V1 Dashboard Build Order (standings with trajectory; manager dossiers;
positional strength vs. league average; head-to-head matchup breakdown).

## V1 Dashboard Build Order

Dashboard build structure:
Build first
    - Power rankings league overview
        What it shows: Composite team strength score with positional breakdown (QB/RB/WR/TE) as a detail layer.
        Data needed: nflreadpy weekly stats + Sleeper roster data + weekly data from the season join (nfl_sleeper_weekly_joined transform → season_{season}.parquet).
    - Points scored + consistency league overview
        What it shows: Average weekly points per team and a consistency signal — stable vs. high-variance output.
        Data needed: Sleeper matchup snapshots only. No join required.

Build second
    - Standings with trajectory lens league overview
        What it shows: Record + points for/against, past strength of schedule, remaining schedule difficulty, historical league baseline for wins needed to reach playoffs.
        Data needed: Sleeper matchup history + Sleeper league schedule + prior season backfill data.
    - Manager dossiers league overview
        What it shows: Static AI-generated profile per manager — waiver tendencies, trade behavior, roster construction patterns, positional preferences.
        Data needed: Sleeper transaction + waiver history. One-time AI synthesis pass per manager, output stored as static JSON or markdown.
    - Positional strength vs. league average team overview
        What it shows: Your team's output by position compared to league average. Identifies tradeable surplus and gaps to address.
        Data needed: weekly data from the season join (nfl_sleeper_weekly_joined transform → season_{season}.parquet).
    - Head-to-head position breakdown matchup overview
        What it shows: Your lineup vs. opponent's lineup by position — where's the edge, where's the risk.
        Data needed: Sleeper current roster + weekly data from the season join (season_{season}.parquet).

Build third
    - Production consistency per player team overview
        What it shows: Week-to-week variance per player. Who's reliable, who's boom/bust.
        Data needed: nflreadpy weekly stats.
    - Key player matchups + narrative read matchup overview
        What it shows: The 1-3 decisive spots in the matchup — who could swing the week, whether you're ahead or at risk.
        Data needed: Sleeper live scoring + nflreadpy historical context. Natural candidate for AI layer in V5.
