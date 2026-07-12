# Fantasy Football Assistant — Product Roadmap

**Last reviewed:** 2026-07-09
**Supersedes:** the prior V1–V6 list in this file and in `STATUS.md § Version Roadmap`.
Those should now point here. (Leave the STATUS.md edit to a Claude Code session.)
**Phase mapping authority:** `READ_BUILD_ORDER.md` is the canonical map of which *read*
lands in which phase; this doc and STATUS.md are kept **in sync** with it. (Reconciled
2026-07-09 — Phase 3 is "cash in the projection," matching Build_Order.)

---

## The spine

**The unit of this product is the manager's *decision*, not the player.** Every
other fantasy tool's unit is the player ("who's good?"). Ours is the choice you're
about to make — or already made — in *your* league. Players are inputs to that.

The destination (see the end-state map): a season-long decision coach that knows
your league **and** knows you. It sits on commodity data (borrowed projections +
usage stats + your league context), runs a thin layer of shared engines that judge
decisions, and gets more personal the longer you use it. It starts as a **critic**
of past decisions (where we have the answer key) and grows into a forward **advisor**.

---

## Four design laws (apply to every phase, never traded away)

1. **Grade process, not outcome.** A bad result from a sound decision is *not* an
   error, and saying it is teaches the exact recency/spike bias we're fighting.
   Engines judge the decision against what was knowable at the time — never against
   what happened next. (This is already a live problem: see Phase 3 / leakage fix.)
2. **Speak only when confident.** Disagreement between sources, and small sample
   size, are first-class signals. When the read is a coin-flip, say so or stay
   silent. A wrong critic is worse than no critic.
3. **Borrow the substrate; build only the layer.** Projections, rankings, and raw
   stats are commodities — ingest them. We build the thin decision layer on top,
   never our own projection engine.
4. **Consultation, not autopilot.** Surface the decision point and the evidence;
   defer the call to the manager. (Already the stated mission in PROJECT_OVERVIEW.)

---

## Phase 0 — Current state (done)

What exists today, as the roadmap's starting line:

- **Data layer** (Python/polars, all I/O through `data_layer.py`) with fetchers:
  `nfl_stats` (usage: target share, air yards, wopr, snaps, EPA — weeks 1–18),
  `sleeper` (rosters, matchups, transactions, player registry), `leaguelogs`
  (daily market value).
- **Transforms** → derived parquet: join, audit, lineup slots, `compute_team_form`
  (EWMA trajectory), `compute_team_leakage` (lineup efficiency + coachable/variance).
- **Front-end** (React + Vite + DuckDB-WASM, client-side; `queries.js` is the
  data seam): League panel (power rankings + team drawer) and **Team Overview
  complete — all 4 lenses** (construction, star dependence, form, where-you-leave-points).
  **Players sub-view is a stub.**
- Frozen at **Week 4 of 2025** as the simulated "present." The **full 2025 season
  (wks 1–18) is available as an answer key** for backtesting engines.

**Read of it:** this is a strong *descriptive* dashboard — it shows your team's
state. The work ahead is the leap from *showing state* to *grading a decision
against a prior*. The dashboard isn't a detour; form/leakage/construction become
the "league context + your-team signal" inputs to the engines.

---

## Phase 1 — First engine slice: the spike signal-quality read  ← **kickoff target**

The one error, built end to end, to prove the whole pattern. **"Is this production
real, or is it noise?"** — the bias that recurs across waivers, start/sit, and
streaming.

**Why this slice first:** it's the only decision read that gets most of the way on
**data you already have** — no projections fetcher required to ship a useful v1. It
characterizes *why* a player's points happened, which is exactly the contextualization
gap no other tool fills.

**Build:**
- New transform `compute_player_signal.py` → `snapshots/derived/player_signal_{season}.parquet`
  (mirror the `compute_team_form`/`leakage` shape: pure functions, injected
  constants, shared helpers in `_analytics.py`). One row per rostered skill player.
- It splits recent production into **repeatable** (volume/opportunity: target share,
  carries, snap share, air-yards share, routes) vs **regression-prone** (efficiency,
  TD rate, big-play/aDOT spikes, low-volume outliers). Output is a *repeatability
  read* + the evidence behind it — **not** a points projection.
- `queries.js`: a `loadPlayerSignal` / `loadTeamPlayers(rosterId)` seam fn (reads the
  parquet; no math in JS).
- **Surface:** give the stubbed **Players sub-view** its purpose — per player, "this
  run looks volume-driven and sticky" vs "this was three TDs and a busted coverage;
  the underlying usage is flat." Framed as a *question the manager adjudicates* (law 4),
  language gated on sample size (law 2).

**Validate against the answer key:** backtest on full 2025 — does the
repeatability flag predict rest-of-season regression *better than raw recent
points*? If it doesn't beat the naive baseline, the engine isn't real yet. This is
the gate before it ships live.

**Done when:** a manager looking at a hot/cold player sees, in one place, whether
the production is the kind that continues — with the evidence — and the backtest
shows it beats "just look at recent points."

**Also build here (cross-cutting infra, cheap now):** the **per-panel readiness
gate** (STATUS backlog #2) — structural / point-in-time / trend regimes + a "too
early" fallback slot — so trend reads degrade cleanly and language calibrates to
weeks of data.

---

## Phase 2 — The projections substrate (the gating dependency for everything after) — *substrate DONE; disagreement blocked*

The forward prior every other decision slice rests on.

**Build:** a source-agnostic `projections` entity + a transform that produces a
**consensus + disagreement (spread)** read across whatever sources you pull. The
spread *is* the confidence signal for law 2 — tight consensus = act, wide spread =
coin-flip. (Vegas game totals/spreads via an `odds.py` fetcher are a cheap,
high-value add here — game environment — but optional.)

**State (2026-07-09):** **Source #1 = Sleeper weekly projections** (not FantasyPros
as first sketched — Sleeper serves *historical* weekly projections, so the prior
lines up with the frozen-2025 answer key and is backtestable). The **consensus +
spread band** (`compute_projection_consensus.py`) shipped, all three §3 components
incl. archetype skew, calibration-gated. The **disagreement half is BLOCKED** — it
needs a live 2nd source and none but Sleeper serves historical 2025; it fills
**in-season via ffanalytics** (`disagreement_ppr` scaffolded null till then).
FantasyPros joins later in-season through the same seam.

**Unlocks:** (a) calibrates the Phase 1 spike read's *forward* language; (b) makes
the leakage fix in Phase 3 credible; (c) gates every decision slice after this.

**Done when:** any engine can ask "what was the forward expectation, and how sure
were the sources?" through the data layer. *(Center + spread: yes. Cross-source
disagreement: pending the 2nd source.)*

---

## Phase 3 — Cash in the projection: the quantitative forward reads — *COMPLETE (§3, §4, §5-half, §6 all done)*

Once the prior exists, the quantitative reads that *consume* it are near-term and
mostly mechanical (per `READ_BUILD_ORDER.md`: §3, §4, §6, half of §5). This is also
where the one slice becomes the **reusable shared layer** and the known design debt
gets repaid — those are the cross-cutting *how* of these reads, not a separate gate.

- ✅ **Weekly Projection Spread (§3) — DONE.** The percentile band around the
  borrowed weekly center (`compute_projection_consensus.py`); the start/sit read.
  Built alongside the Phase-2 substrate, per-tail calibration-gated.
- ✅ **Value / VOR (§4) — COMPLETE (Production + Market + the gap).** Production VOR over the waiver line
  (`compute_production_vor.py`), answer-key gated → roster management (adds/drops). **Market VOR**
  (`compute_market_vor.py`) — the market-value twin on the borrowed LeagueLogs value, same engine, +
  the **Production−Market trade gap**; shipped early as the un-backdatable POC piece (the market is
  current-2026 and can't be backdated), cross-time-flagged at the freeze, internal-consistency gated.
- ✅ **True rank (half of §5) — DONE.** Aggregate Production VOR over each team's optimal
  lineup → record-independent roster strength (`compute_true_rank.py`), answer-key gated;
  half of posture. Reused the optimal-lineup engine (lifted into shared `_analytics`). Bracket
  math (§5 full) is Phase 4.
- ✅ **Positional Depth (§6) — DONE.** Re-slice Production VOR per position, net of the starting
  requirement, vs. league → surplus / gap (`compute_positional_depth.py`), answer-key gated
  (per-position corr mean 0.861). → roster shape (trade + waiver/FAAB). **Closes Phase 3.**
- **Fix the leakage "coachable" claim (STATUS backlog #1) — this is law 1 made
  real, and it lands *in* VOR.** Today it converts a 4-game realized sample into a
  forward imperative ("start Allen over Brown going forward") — and the rest-of-season
  data shows that call was backwards. Regress realized rate toward the Phase 2 prior
  before calling anything coachable; restate as a question, not an order.
- **Shared engines (cross-cutting):** as these reads land, the one slice generalizes
  into the reusable layer — *signal quality* (Phase 1 generalized), *context fit*
  (ceiling/floor given matchup + your team's need), *opponent model* (stub). Same
  engine, dressed per surface.

**Done when:** the four cash-in reads run on the borrowed prior, two+ surfaces share
the same engines with no duplicated logic, and no shipped read grades on outcome.

---

## Phase 4 — Integration + go live + opponent modeling *(UNDERWAY)*

Move from frozen-at-W4 to a living season, add the posture integration point, and the
"read the other team" half.

- ✅ **Posture Evidence (§5, full) — bracket-math Monte Carlo DONE.** `compute_bracket_sim.py`:
  team weekly score distributions (μ from the optimal-lineup projection, σ from the §3 band) →
  per-matchup win prob → a 10k-sim season over the real remaining schedule → playoff odds +
  magic number. With True Rank = §5 Posture complete. Config-light answer-key gate (Brier 0.224
  beats coin-flip; expected-wins Spearman 0.756; 6/6 actual playoff teams). The posture
  *presentation* (odds adjacent to true rank, the risk-appetite lens) is the front-end half.
- **ROS Outcome Shape (§2) skeleton** and **manager dossiers (§7)** are the remaining reads;
  **front-end surfacing** of the five gated forward reads turns the engines into product.
- In-season weekly refresh (the old V1.5 scheduler idea) — fetchers + transforms
  run on cadence; readiness gates from Phase 1 handle early-season thinness.
- **Opponent modeling:** their roster, needs, and tendencies — feeds trades, FAAB,
  and start/sit context. Build the **manager-dossier** infra here (transaction +
  waiver history → behavioral profile). This is also the precursor to Phase 5.
- Waiver and trade surfaces become real once opponent context exists.

**Done when:** the coach runs on this week's live data and can reason about
opponents, not just your own team.

---

## Phase 5 — The reflective loop: a model of YOU

The compounding asset and the real moat.

Every decision the coach grades becomes a data point about *your* tendencies. Over
a season it learns that you specifically chase spikes, or overrate your own RBs, and
frames guidance against *your* biases, not generic ones. The manager-dossier infra
from Phase 4, turned inward and accumulated. Falls out of the critique-first design
for free — no separate build, it just needs to be captured and surfaced.

**Done when:** the coach's guidance is visibly personalized to the user's own
decision history.

---

## Phase 6 — Forward advisory + interpretation layer (later)

- The **real-time advisory loop**: same engines pointed forward ("here's the better
  call *now*"), grown out of the proven reflective loop.
- An **AI interpretation layer** over the engines (the old "V5") — narrates and
  synthesizes; reads the same data layer, pre-filtered (principle #5). Strategy
  document stays auditable markdown (principle #6).
- New surfaces: **draft** and **streaming** (deliberately left empty in
  Error_Mapping until the engine pattern is proven — don't fill them early).

---

## Sequencing logic (why this order)

- Phase 1 before Phase 2 because the spike slice is the rare engine that proves the
  pattern *without* the substrate — fastest path to something usable and to learning
  whether the whole thesis holds.
- Phase 2 is the hinge: nothing past it is credible without a forward prior.
- Phases 3–4 generalize and go live; 5 compounds; 6 is the long arc.
- **Each phase is the same shape repeated, not new invention** — one engine, graded
  on process, surfaced as a decision. That's the discipline that keeps this from
  sprawling back into "build pipelines and hope."

## The scope filter (tape this to the wall)

> No pipeline, transform, or panel ships unless it traces to (a) a borrowed input,
> (b) one of the shared engines, or (c) a surface that frames an engine's output
> around a named decision. If it's none of those, it's out — no matter how
> interesting the data is.
