# READ BUILD ORDER

**Last reviewed:** 2026-07-09
**Companion to:** `PRODUCT_ROADMAP.md` (the *why* — phases, four design laws, scope filter) and the
**Decision Reads spec** (`DECISION_READS.md` — the *what*, full definition of each read).
This doc is the ***sequence*** — the order the seven reads get built and why that order is forced by
their dependencies.

> **Source-of-truth split.** Roadmap = phases & principles. Decision Reads spec = read definitions.
> This = build sequence. If a read's *definition* changes, edit the spec; if the *sequencing logic*
> changes, edit here; phases & design laws stay in the roadmap. Don't duplicate across the three.

---

## The seven reads (recap)

**Player reads:** (1) Opportunity, (2) ROS Outcome Shape, (3) Weekly Projection Spread, (4) Value/VOR.
**League reads:** (5) Posture Evidence, (6) Positional Depth, (7) Manager Dossiers.
Full definitions are in the Decision Reads spec; this doc references them by number (§1–§7).

## The dependency spine (why the order is forced)

Three facts set the whole sequence:

1. **Opportunity is the only read buildable with no projections** — descriptive, backward, running on
   usage data already in hand. So it's first (and already largely built — Phase 1).
2. **The borrowed projection substrate is the hinge.** Outcome shape, weekly spread, value/VOR, and the
   bracket simulation are all impossible without a forward prior. So the projection fetcher (Phase 2)
   is the single highest-leverage build — not one feature, but the gate on most of the read layer.
3. **Posture is the integration point.** Player Value aggregates up into true rank; the bracket sim
   consumes rank + weekly-spread variance; posture then flows back *down* as the risk-appetite lens on
   outcome shape and VOR. So posture builds late — it sits on top of nearly everything.

Everything else is downstream of those three.

## Cross-cutting (every stage — from the roadmap's design laws)

- **No fused "ultimate number."** Each read stays a separate, legible signal; the user synthesizes.
  That separation is the product — resist collapsing reads into one score.
- **Borrow the center, build the layer (law 3).** Projections and rankings are ingested, never built.
  Every forward read leans on the borrowed prior and adds only the decision layer.
- **Confidence-gated + dynamic (law 2).** Every read carries a confidence signal and degrades cleanly
  early season (the readiness gate shipped in Phase 1). Reads that shift over the season (ROS, posture)
  update on evidence + time decay.
- **AI in exactly two spots** — ROS *situation/narrative* (§2) and manager dossiers (§7), the two
  qualitative reads. Always confidence-gated, reasoning always shown, never a bare number.
- **Scope filter (roadmap):** nothing ships unless it's a borrowed input, a shared engine, or a
  decision-framed surface.

---

## The phased build order

Phase numbers track `PRODUCT_ROADMAP.md`; this maps the seven reads onto that spine.

### Phase 1 — Opportunity *(DONE — refined to spec 2026-07-08)* → §1
The descriptive base, shipped as `compute_player_signal`. **Delta closed:** `quality_rate` (weighted/
value-adjusted opportunity, from a new PBP `td_prob` aggregation), the **trust** axis (`direction` +
`reliability` from the player's own series; `security` from Sleeper injury/depth-chart data), and the
**point-correlation** companion (`pearson(xtd, td_pts)`) are now all shipped, kept separate from the
core volume/efficiency read per "don't collapse the axes." Sourcing the PBP quality signal and the
Sleeper injury/depth-chart fields broke the original "no new dependency" note on purpose — both came
from packages/endpoints already integrated, not a new external service. *Sharpens every forward read
that leans on opportunity.*

### Phase 2 — The projection substrate *(substrate DONE; disagreement blocked)* → enables §2, §3, §4, §5-bracket
The forward prior every read below rests on. **Source #1 — Sleeper weekly projections** (historical,
so it lines up with the frozen-2025 answer key) landed in a source-agnostic `projections` entity, and
`compute_projection_consensus.py` turns it into the borrowed **consensus center + spread band**, now
with **all three §3 components** (center / width / archetype skew), calibration-gated on the 2025
answer key. **The `disagreement` half is BLOCKED at the freeze** — a cross-source spread needs a live
2nd source, and no source but Sleeper serves *historical* 2025 weekly projections; it fills **in-season
via ffanalytics** (the `disagreement_ppr` column is scaffolded null till then — a value change, not a
schema change). **Still the highest-leverage build** — everything below leans on it. (= roadmap Phase 2.)

### Phase 3 — Cash in the projection: the quantitative forward reads *(COMPLETE — §3, §4, §5-half, §6 all done)* → §3, §4, §6, half of §5
Once the prior exists, these are near-term and mostly mechanical:
- ✅ **Weekly Projection Spread (§3) — DONE.** Percentile band around the borrowed weekly center
  (`compute_projection_consensus.py`), all three components incl. archetype skew; per-tail
  calibration-gated on the 2025 answer key. → start/sit. *(Built alongside the Phase-2 substrate.)*
- ✅ **Value / VOR (§4) — Production VOR DONE.** `compute_production_vor.py`: production VOR over the
  waiver line, normalized by pool spread (QB pool + pooled flex line); gated (projected ROS tracks
  actual at corr ~0.95, VOR tiers monotonic). → roster management (adds/drops). **Market VOR + the
  Production−Market gap remain V4** (LeagueLogs redraft profile) — the trade layer is not built here.
- ✅ **True rank (half of §5) — DONE.** `compute_true_rank.py`: aggregate Production VOR over each
  team's optimal lineup → record-independent roster-strength rank. → half of posture. *(Reused the
  optimal-lineup logic from `compute_team_leakage`, lifted into `_analytics` as shared
  `expand_slots`/`optimal_lineup`.)* Gated (projected strength tracks the actual ROS ceiling at
  Pearson 0.802 / Spearman 0.842, n=10 teams; strong half out-produces weak). Bracket math (§5 full) is Phase 4.
- ✅ **Positional Depth (§6) — DONE.** `compute_positional_depth.py`: re-slice Production VOR per
  position (QB/RB/WR/TE), net of the dedicated starting requirement, benchmarked vs the league →
  surplus / gap (marginal_vor gap indicator, surplus_startable = trade capital, advisory shape).
  → roster shape (trade + waiver/FAAB). Gated (per-position projected starter_value tracks the actual
  ROS ceiling, mean corr 0.861, n=10/pos; top half out-produces bottom). **Closes Phase 3.**

All quantitative, all leaning directly on the Phase-2 prior. VOR is also where the leakage-fix
"regress realized rate toward the prior" lands, and the *shared-engines* generalization (roadmap
Phase 3's framing) is the cross-cutting *how* of these reads, not a separate gate.

### Phase 4 — Integration + going live → §2 (skeleton), §5 (full), §7
- **Posture Evidence (§5, full)** — the **bracket-math Monte Carlo** (team score distributions from
  weekly-spread variance + true rank → per-matchup win prob → simulate the season) shown adjacent to
  true rank. Needs the live season + schedule. → the risk-appetite lens.
- **ROS Outcome Shape — quantitative skeleton (§2)** — bull/bear anchored on the borrowed ROS
  projection ± variance + time decay; situation/security from *structured* inputs (draft capital, depth
  chart, injury status). The AI narrative comes in Phase 6.
- **Manager Dossiers (§7)** — opponent behavioral profiles from transaction history. → trade targeting
  + waiver competition. (= roadmap Phase 4 — go live + opponent modeling.)

### Phase 5 — Model of you → extends §7
The dossier engine turned inward: graded decisions accumulate into *your* tendencies and personalize the
guidance. Falls out of the critique-first design. (= roadmap Phase 5.)

### Phase 6 — AI interpretation layer + forward advisory → completes §2, new surfaces
- **ROS situation — the AI half of §2:** interpret news into signals, write the bull/bear narrative,
  roll narrative + signals into the 1-10 grade. Confidence-gated, reasoning always shown.
- **Forward advisory loop** — the same engines pointed forward ("the better call *now*").
- **New surfaces** — draft & streaming, once the engine pattern is proven. (= roadmap Phase 6.)

---

## Open flags (carried from the reads spec)
- ROS **dynamic-update model** + the **1-10 precision-display** question (§2).
- **Redraft / format-matched market source** for market VOR (§4).
- ~~**Opportunity spec delta** — weighted opportunity + trust axis + point-correlation~~ — **closed
  2026-07-08** (the Phase-1 refinement).

## Status snapshot *(updated 2026-07-09)*
- **Done:** Phase 0 (descriptive dashboard); Phase 1 (Opportunity / spike signal-quality, refined to
  spec); **Phase 2 substrate** (Sleeper source + consensus/spread band, all 3 §3 components); and **all
  4 Phase-3 cash-in reads — Weekly Spread (§3), Production VOR (§4), True rank (half of §5), and
  Positional Depth (§6)** — all answer-key gated, data + gate only (no UI yet).
- **Phase 3 is COMPLETE.** **Next — Phase 4 (integration + going live):** the §5 bracket-math Monte
  Carlo (full posture — consumes True Rank + weekly-spread variance), the §2 ROS outcome-shape
  quantitative skeleton, manager dossiers (§7), and the **front-end surfacing** of the four gated
  forward reads.
- **Blocked (not next):** cross-source **disagreement** (the Phase-2 substrate's 2nd half) — needs a
  live 2nd source, fills in-season via ffanalytics. Market VOR + the trade gap (§4) remain V4.
- Everything past the substrate is gated on it; §3 + §4 + §5-half + §6 confirm the substrate cashes in.
