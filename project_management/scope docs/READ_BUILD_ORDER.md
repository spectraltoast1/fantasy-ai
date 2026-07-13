# READ BUILD ORDER

**Last reviewed:** 2026-07-12
**Companion to:** `PRODUCT_ROADMAP.md` (the *why* — phases, four design laws, scope filter) and the
**Decision Reads spec** (`DECISION_READS.md` — the *what*, full definition of each read).
This doc is now the ***state of build*** — what's Built (Backend / Frontend) and what's
Unbuilt+Blocked — kept in front of a condensed record of the sequencing logic that got us here.

> **Source-of-truth split.** Roadmap = phases & principles. Decision Reads spec = read definitions.
> This = build sequence **+ the Built/Unbuilt breakdown**. `STATUS.md` = current state, recent-build
> changelog, and the immediate next move. If a read's *definition* changes, edit the spec; if the
> *sequencing logic* changes, edit here; phases & design laws stay in the roadmap. Don't duplicate.

---

## The seven reads (recap)

**Player reads:** (1) Opportunity, (2) ROS Outcome Shape, (3) Weekly Projection Spread, (4) Value/VOR.
**League reads:** (5) Posture Evidence, (6) Positional Depth, (7) Manager Dossiers.
Full definitions in the Decision Reads spec; referenced here by number (§1–§7).

## The dependency spine (why the order was forced)

Three facts set the whole sequence — kept because they still explain *why* the Built set looks the
way it does:

1. **Opportunity is the only read buildable with no projections** — descriptive, backward, running on
   usage already in hand. So it went first (Phase 1).
2. **The borrowed projection substrate is the hinge.** Outcome shape, weekly spread, value/VOR, and
   the bracket sim are all impossible without a forward prior, so the projection substrate (Phase 2)
   was the single highest-leverage build — the gate on most of the read layer.
3. **Posture is the integration point.** Player Value aggregates up into true rank; the bracket sim
   consumes rank + weekly-spread variance; posture flows back *down* as the risk-appetite lens. So it
   built late — it sits on top of nearly everything.

**Cross-cutting design laws** (from the roadmap): no fused "ultimate number" (each read stays a
separate legible signal); borrow the center, build only the decision layer (law 3);
confidence-gated + dynamic (law 2); AI in exactly two spots — ROS situation/narrative (§2) and
manager dossiers (§7); nothing ships unless it's a borrowed input, a shared engine, or a
decision-framed surface.

---

## Built — Backend

Every read below is **data + answer-key gate** (validated against the full-2025 answer key or, where
behaviour has no answer key, an internal-consistency gate). All are `compute_*.py` → `derived/*.parquet`
with a paired `backtest_*.py` / `check_*.py`. **No UI yet on any of these** — see Unbuilt.

- **§1 Opportunity** — `compute_player_signal.py` (+ `backtest_player_signal.py`). Sticky opportunity
  vs. fragile efficiency, regression_risk, sample-gated read; Trust axis (direction/reliability/security)
  + point-correlation companion. Quality axis (`quality_rate`) is now **expected fantasy points per
  opportunity** from `ff_opportunity`'s empirical component model, re-scored under league settings
  (`_scoring.expected_points_expr`; 710 audit #3 done). *Remaining sub-component: "routes run" volume —
  deferred (coverage gaps in free data / behind paid charting; snap-share stands in).*
- **§3 Weekly Projection Spread** — `compute_projection_consensus.py` (+ `backtest_projection_consensus.py`).
  Borrowed center + spread band, all three components (width = shrunk residual std, skew =
  Cornish-Fisher from shrunk residual skewness); per-tail calibration-gated.
- **§4 Value/VOR (COMPLETE — Production + Market + the trade gap)** — Production VOR
  `compute_production_vor.py` (+ `backtest_production_vor.py`): ROS value over the waiver line,
  normalized by pool spread; QB pool + pooled flex line; answer-key gated. **Market VOR**
  `compute_market_vor.py` (+ `check_market_vor.py`): the market-value twin — the SAME waiver=0 ÷
  pool-spread VOR (reuses `position_pools`/`_pool_lines`/`_vor`/`_roster_as_of` — no new math) on the
  borrowed LeagueLogs `value` (format-matched profile `redraft-1qb-12t-ppr1`; position from the Sleeper
  registry), tall over the market's `snapshot_date` axis. The **Production−Market gap** (`trade_gap`) is
  folded in. **Internal-consistency gate** (no answer key: the market is current-2026, no future truth at
  the 2026-offseason freeze). **Time-world:** rosters are frozen-2025 but the market is current-2026 and
  can't be backdated → the gap is **cross-time by construction**, flagged (`is_cross_time`) and treated as
  POC/architecture validation, not a live trade call, until the season rolls to 2026.
- **§5 Posture (complete)** — True Rank `compute_true_rank.py` (+ `backtest_true_rank.py`,
  record-independent roster strength) **and** bracket-math `compute_bracket_sim.py`
  (+ `backtest_bracket_sim.py`, 10k-sim playoff odds over the real remaining schedule; Brier 0.224
  beats coin-flip, expected-wins Spearman 0.756, top-4 by odds = 3/4 actual playoff teams).
- **§6 Positional Depth** — `compute_positional_depth.py` (+ `backtest_positional_depth.py`).
  Production VOR re-sliced per position net of starting need → surplus / gap vs league.
- **§2 ROS Outcome Shape (COMPLETE — quantitative + AI interpretation)** — quantitative skeleton
  `compute_ros_outcome_shape.py` (+ `backtest_ros_outcome_shape.py`): bull/bear = borrowed ROS centre
  ± BULL_Z·√Σband², floored, emergent time decay; situation/security carried as evidence; **preseason
  ADP/draft-capital anchor** blended in (`compute_adp_points_curve.py` + `fetchers/adp.py`; 710 audit
  #4). **AI interpretation half** — `application/ai/write_ros_synthesis.py` (+ `ros_synthesis_prompt.py`
  / `check_ros_synthesis.py`): a per-player Haiku call fusing the anchor + `player_news_slice` news +
  Sleeper facts → bull/bear/situation 1–10 grades (each with a prose note) + grounded headlines + a
  confidence flag → the `ros_synthesis` entity. Both AI-layer reads (§2 + §7) are now shipped.
- **§7 Manager Dossiers (complete)** — Phase A: cross-league acquisition (`sleeper.py fetch-manager-activity`
  → `manager_activity`) + deterministic features (`compute_manager_features.py` → `manager_features`,
  gated by `backtest_manager_features.py`). Phase B: the AI layer — `application/ai/` writes one
  Claude-Haiku dossier per manager (`write_manager_dossiers.py` → `manager_dossiers`, an included
  AI run — ungated; gated by `check_manager_dossiers.py`).

**Supporting substrate (built, underpins the reads):** `data_layer.py` (the single I/O seam); fetchers
`nfl_stats.py` / `sleeper.py` / `leaguelogs.py` / `news.py` / `adp.py`, all routed through the shared
`fetchers/_http.py` resilience layer (timeout / backoff / retry / throttle / per-item isolation) with a
`run.py` collector registry/dispatcher + `check_collectors.py` coverage gate (QUEUED #1); joins
`join_nfl_sleeper_weekly.py` + `audit_join.py`; `derive_lineup_slots.py`; the `_scoring.py` dispatcher +
custom-scoring recompute engine + `expected_points_expr`; the AI seam `application/ai/client.py`; shared
pure helpers `_analytics.py` / `_manager.py`; the `league_settings`, multi-source `projections`, ADP
(`adp_preseason` / `adp_points_curve`), and §2 team-news pipeline (`team_news_raw` → `team_news_dossier`
→ `player_news_slice`) entities; the season-replay `as_of_week` tall dimension; and the `position_pools`
/ any-league generalization (superflex, custom scoring, division seeding).

**Corpus & Improvement Loop (Track A — offline tuning asset).** **Session 0** (spike, throwaway) verified
the corpus is viable — see `LLM context/SPIKE_CORPUS_FINDINGS.md`. **Session 0.5** built it: the additive
`application/data/corpus/` package — `discover.py` (persisted/resumable manager-keyed BFS →
`corpus_discovery.parquet`, 2,729 league-seasons found, a lower bound), `select.py` (classification-narrow →
inclusion filter + scoreability on a bounded pool → the stratified **league registry**
`corpus_manifest.parquet`, 319 rows: matched 179 / generalization 58 / mine 2 / excluded 80), and
`check_corpus.py` (internal-consistency gate). **Narrow-corpus decision:** only the `matched` stratum
(PPR/half·1qb·redraft·10-14t) tunes/gates; exotic leagues are a `never_tune` robustness set. **Split: TRAIN
2023-24 · DEV 2022 · TEST 2025** (2020-21 have no matched leagues). **Next: L0 keying** (`league_id` +
`scoring_key`, partition derived parquet by league, split `ros_outcome_shape`) — keys against this manifest;
then Session 4 harvest → L2 ledger backfill (`IMPROVEMENT_LOOP.md`, `LEAGUE_CORPUS.md`).

## Built — Frontend

Production front end — **React + Vite + DuckDB-WASM**, reads live parquet client-side. `src/queries.js`
is the single data-access seam (the front-end mirror of `data_layer.py`); `src/db.js` is the DuckDB-WASM
loader; view components are pure renderers. Frozen at Week 4 of 2025 for building. *(This is the full
build detail — its former home in STATUS.md's "V1 Dashboard Build Order" section has been retired.)*

- **Skeleton + seam** — `App.jsx` tab shell, `LeaguePanel.jsx` / `TeamPanel.jsx` views, `queries.js`
  data-access layer, `db.js` loader, `readiness.jsx` gate, `posColors.js`.
- **Power Rankings (League)** — teams ranked by avg PPG with a QB/RB/WR/TE positional breakdown, record,
  week-to-week consistency, and a 0–100 power score.
- **Team drill-down drawer (League)** — all-play true record, lineup efficiency, weekly scoring,
  consistency + positional-shape spectrums.
- **Tab nav shell** — League | Team split (`App.jsx` shell + the two panels).
- **Team tab foundation** — your-team resolver (`loadTeams` + `MY_USERNAME`), team switcher,
  Overview / Players sub-tabs.
- **Team Overview — lenses 1–4:** (1–2) rate-based depth chart + league-relative star dependence +
  auto-surfaced lineup/hole signals; (3) Form / trajectory — recency-weighted EWMA slope (half-life
  2wk), Fading↔Surging spectrum, weekly beat/below-median chart; (4) Where-you-leave-points — season
  points-left split into variance vs. coachable, efficiency % on a Leaky↔Optimal spectrum
  (reframed retrospective → improvement).
- **Team tab — Players sub-view** — the per-player spike signal-quality read (recent /g, directional
  verdict, volume rank, TD share); direction-not-projection, question-framed, sample-gated.
- **Per-panel readiness gate** — `readiness.jsx` (`assessReadiness` + `Gate`): structural /
  point-in-time / trend regimes → ready / building / tooEarly, with a "too early" fallback slot.
- **Season-replay week selector** — global "As of" week dropdown in the App shell; one selection drives
  League + Team and persists across tabs; threads through `queries.js` (`asOfSlice` / `weekCutoff`),
  drives the readiness gate, retired the `?weeksOverride` QA param. Default = latest; travels back only.
- **Architecture refactor** — the heavy Team Overview math (form + leakage) was extracted from
  `queries.js` into Python transforms (`compute_team_form.py` / `compute_team_leakage.py` → `derived/`);
  `queries.js` slimmed to a thin read + assemble seam.

## Unbuilt + Blocked

Each with the reason it isn't built. Ordered roughly by how soon it matters.

- **Front-end surfacing of the gated backend reads** — UNBUILT; **now the immediate next work** (Market
  VOR closed the backend read layer — every §1–§7 read is built + gated). The front end surfaces only
  `team_form` / `team_leakage` / `player_signal`. No UI yet for `production_vor` / `market_vor` (§4),
  `true_rank` / `bracket_odds`
  (§5), `positional_depth` (§6), `ros_outcome_shape` + `ros_synthesis` (§2), `projection_consensus`
  (§3), `manager_features` / `manager_dossiers` (§7). Includes the posture *presentation* (True Rank +
  odds shown adjacent, the risk-appetite lens).
- **§3 cross-source disagreement** — BLOCKED at the freeze. A cross-source spread needs a live 2nd
  projection source, and no source but Sleeper serves *historical* 2025 weekly projections.
  `disagreement_ppr` is scaffolded null; it fills **in-season via ffanalytics** (a value change, not a
  schema change).
- ~~**§4 Market VOR + the Production−Market trade gap**~~ — **BUILT (2026-07-12)** — see Built — Backend
  above (`compute_market_vor.py` + `check_market_vor.py`). Mirrors the `compute_production_vor.py` engine
  + `position_pools` on the borrowed LeagueLogs market value (format-matched profile
  `redraft-1qb-12t-ppr1`); the Production−Market gap isolates the speculation premium; cross-time-flagged
  at the freeze (market current-2026 vs rosters/production frozen-2025). **Purely additive — nothing
  reads it yet, so building it on current data does not affect app functioning.** The §6→§7
  trade-targeting handoff (consuming the gap) remains for the front-end/opponent work.
- **§1 "routes run" volume sub-component** — DEFERRED (the genuinely hard one): coverage gaps in free
  data / behind paid charting; snap-share stands in. (The rest of §1 Quality — empirical expected-points
  per opportunity — shipped, 710 audit #3.)
- **Fetchers** — `fantasypros.py` (the §3 2nd source, in-season), `odds.py` (Vegas game totals —
  optional environment add), `weather.py` — none built.
- **Off-laptop collector host** — UNBUILT; **merges with Deployment.** The shared resilience *code*
  SHIPPED (QUEUED #1): `fetchers/_http.py` (timeout / backoff / retry / throttle / per-item isolation),
  all fetchers routed through it — `leaguelogs._get` gained the missing retry + per-item isolation (the
  fix for the audit's ~7 transient-fail days), plus a `run.py` collector registry/dispatcher and a
  `check_collectors.py` coverage/health gate that certifies a banked series. What remains is the
  **host**: two fetchers bank a now-only, un-backfillable series — `leaguelogs.py` (market values → §4)
  and `news.py` (team news → §2) — and launchd skips a powered-off run with no catch-up, so the ~8
  laptop-off days can't be fixed locally. A static deploy has no compute, so a scheduled runner (GitHub
  Actions the lead) both collects *and* publishes parquet — **decide it WITH Deployment below.** Interim:
  multi-fire the plists + install the written-but-unloaded `com.fantasyai.news-snapshot` job.
- **Multi-user / multi-league plumbing** — UNBUILT. Storage keys, config, and front-end addressing are
  single-league / single-user (`{season}`-keyed paths, one `SLEEPER_LEAGUE_ID`, hardcoded
  `MY_USERNAME` / single-season parquet names in `db.js`). The *any-league engine* (scoring / roster /
  playoff config) is built; the *plumbing* to hold more than one league at once is not. Seams are
  documented in `TECHNICAL_ARCHITECTURE.md`.
- **Deployment / hosting** — UNBUILT (static client-side today). Going server-side is expected, not
  hypothetical; the `queries.js` seam is the swap point. **It also subsumes the collectors' off-laptop
  host:** a static deploy has no compute, so a scheduled runner (GitHub Actions the lead) both collects
  the daily snapshots *and* publishes their parquet to the site — decide the two together (see
  Daily-collector reliability above).

---

## Open flags (carried from the reads spec)
- **1-10 precision-display** question (§2) — now a frontend/presentation decision: the 1–10 roll-up
  itself shipped in `ros_synthesis`, and ROS scores already update weekly via the `as_of_week` tall
  dimension, so the "dynamic-update model" is handled in the data. What's open is how to *show* a
  qualitative 1–10 without implying false precision (the note rides with the grade — a UI choice).
- ~~**Redraft / format-matched market source** for Market VOR (§4)~~ — **RESOLVED**: Market VOR uses the
  **`redraft-1qb-12t-ppr1`** profile (redraft ✓, 1QB ✓, full-PPR ✓ — matches the league's scoring/QB
  structure). LeagueLogs only publishes 12-team profiles vs the league's 10 teams; that's a **documented
  non-issue** — the waiver line is computed from the league's own roster/available split, so the profile's
  team count only sets the valuation context, not the anchor. (Dynasty profiles are excluded — they bake
  in age + multi-year outlook, noise for a redraft call.)
- **Backend hygiene backlog** — **RESOLVED**: all seven `710_AUDIT.md` items closed (six fixed; the
  read-modify-write append pattern is a documented no-op-by-design migration trigger, not a fix).
