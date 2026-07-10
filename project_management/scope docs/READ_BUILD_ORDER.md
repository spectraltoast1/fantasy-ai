# READ BUILD ORDER

**Last reviewed:** 2026-07-10
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
  + point-correlation companion. *Caveat: the Quality axis (`quality_rate`) is a TD-probability proxy,
  not the full empirical-EV-weight spec — see `710_AUDIT.md` item 3.*
- **§3 Weekly Projection Spread** — `compute_projection_consensus.py` (+ `backtest_projection_consensus.py`).
  Borrowed center + spread band, all three components (width = shrunk residual std, skew =
  Cornish-Fisher from shrunk residual skewness); per-tail calibration-gated.
- **§4 Production VOR** — `compute_production_vor.py` (+ `backtest_production_vor.py`). ROS value over
  the waiver line, normalized by pool spread; QB pool + pooled flex line. (*Production* only; Market
  VOR + the trade gap are Unbuilt.)
- **§5 Posture (complete)** — True Rank `compute_true_rank.py` (+ `backtest_true_rank.py`,
  record-independent roster strength) **and** bracket-math `compute_bracket_sim.py`
  (+ `backtest_bracket_sim.py`, 10k-sim playoff odds over the real remaining schedule; Brier 0.224
  beats coin-flip, expected-wins Spearman 0.756, top-4 by odds = 3/4 actual playoff teams).
- **§6 Positional Depth** — `compute_positional_depth.py` (+ `backtest_positional_depth.py`).
  Production VOR re-sliced per position net of starting need → surplus / gap vs league.
- **§2 ROS Outcome Shape (quantitative skeleton)** — `compute_ros_outcome_shape.py`
  (+ `backtest_ros_outcome_shape.py`). Bull/bear = borrowed ROS centre ± BULL_Z·√Σband², floored,
  emergent time decay; situation/security carried as evidence. *Missing: the preseason ADP/draft-capital
  anchor and the AI narrative + 1–10 roll-up — see Unbuilt / `710_AUDIT.md` item 4.*
- **§7 Manager Dossiers (complete)** — Phase A: cross-league acquisition (`sleeper.py fetch-manager-activity`
  → `manager_activity`) + deterministic features (`compute_manager_features.py` → `manager_features`,
  gated by `backtest_manager_features.py`). Phase B: the AI layer — `application/ai/` writes one
  API-key-gated Claude-Haiku dossier per manager (`write_manager_dossiers.py` → `manager_dossiers`,
  gated by `check_manager_dossiers.py`).

**Supporting substrate (built, underpins the reads):** `data_layer.py` (the single I/O seam); fetchers
`nfl_stats.py` / `sleeper.py` / `leaguelogs.py`; joins `join_nfl_sleeper_weekly.py` + `audit_join.py`;
`derive_lineup_slots.py`; the `_scoring.py` dispatcher + custom-scoring recompute engine; shared pure
helpers `_analytics.py` / `_manager.py`; the `league_settings` entity; the multi-source `projections`
entity; the season-replay `as_of_week` tall dimension; and the `position_pools` / any-league
generalization (superflex, custom scoring, division seeding).

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

- **Front-end surfacing of the 8 gated backend reads** — UNBUILT, and the **immediate next work.** Of
  the 11 derived parquets on disk, the front end surfaces only `team_form` / `team_leakage` /
  `player_signal`. No UI yet for `production_vor` (§4), `true_rank` / `bracket_odds` (§5),
  `positional_depth` (§6), `ros_outcome_shape` (§2), `projection_consensus` (§3), `manager_features` /
  `manager_dossiers` (§7). Includes the posture *presentation* (True Rank + odds shown adjacent, the
  risk-appetite lens).
- **§3 cross-source disagreement** — BLOCKED at the freeze. A cross-source spread needs a live 2nd
  projection source, and no source but Sleeper serves *historical* 2025 weekly projections.
  `disagreement_ppr` is scaffolded null; it fills **in-season via ffanalytics** (a value change, not a
  schema change).
- **§4 Market VOR + the Production−Market trade gap** — UNBUILT (V4). LeagueLogs market values are
  being snapshotted daily but **nothing consumes them yet** — the entire trade layer of §4 (and the
  §6→§7 trade-targeting handoff) is absent.
- **§2 preseason anchor** (realistic draft-capital / ADP ceiling & floor for bull/bear) — UNBUILT; the
  shipped band is a pure statistical spread off the projection. See `710_AUDIT.md` item 4.
- **§2 AI narrative + 1–10 roll-up** — deferred to Phase 6 (the AI-interpretation half of §2).
- **§1 full Quality spec** (empirical EV-weights per chance-type, re-derived under league scoring) —
  UNBUILT; the shipped `quality_rate` is a TD-probability proxy. See `710_AUDIT.md` item 3.
- **Fetchers** — `fantasypros.py` (the §3 2nd source, in-season), `odds.py` (Vegas game totals —
  optional environment add), `weather.py` — none built.
- **Multi-user / multi-league plumbing** — UNBUILT. Storage keys, config, and front-end addressing are
  single-league / single-user (`{season}`-keyed paths, one `SLEEPER_LEAGUE_ID`, hardcoded
  `MY_USERNAME` / single-season parquet names in `db.js`). The *any-league engine* (scoring / roster /
  playoff config) is built; the *plumbing* to hold more than one league at once is not. Seams are
  documented in `TECHNICAL_ARCHITECTURE.md`.
- **Deployment / hosting** — UNBUILT (static client-side today). Going server-side is expected, not
  hypothetical; the `queries.js` seam is the swap point.

---

## Open flags (carried from the reads spec)
- ROS **dynamic-update model** + the **1-10 precision-display** question (§2).
- **Redraft / format-matched market source** for Market VOR (§4).
- **Backend hygiene backlog** — packaging, the append pattern, spec-completeness gaps, config/deps/doc
  drift — tracked in **`710_AUDIT.md`** (LLM context).
