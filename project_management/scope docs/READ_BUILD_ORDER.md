# READ BUILD ORDER

**Last reviewed:** 2026-07-08
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

### Phase 1 — Opportunity *(DONE; refine to spec)* → §1
The descriptive base, shipped as `compute_player_signal`. **Delta to close:** the spec's opportunity
read is richer than the shipped version — **weighted** (value-adjusted) opportunity, the explicit
**trust** axis (recency / direction / reliability / security), and the **point-correlation** companion.
Fold these in as a refinement; no new dependency. *Sharpens every forward read that leans on opportunity.*

### Phase 2 — The projection substrate *(NEXT — the hinge)* → enables §2, §3, §4, §5-bracket
Build the **FantasyPros fetcher → consensus + disagreement spread**, both **ROS and weekly**. Gate on
most of the read layer; nothing below is possible until it lands. **Highest-leverage build in the plan.**
(= roadmap Phase 2.)

### Phase 3 — Cash in the projection: the quantitative forward reads → §3, §4, §6, half of §5
Once the prior exists, these are near-term and mostly mechanical:
- **Value / VOR (§4)** — production VOR over the waiver line + market VOR (LeagueLogs, redraft profile)
  + the gap. → roster management (adds/drops) + trades.
- **Positional Depth (§6)** — immediate re-slice of Value/VOR by position vs. league. → roster shape.
- **Weekly Projection Spread (§3)** — percentile band around the borrowed weekly center. → start/sit.
- **True rank (half of §5)** — aggregate Value into optimal-lineup roster strength. → half of posture.

All quantitative, all leaning directly on the Phase-2 prior. (Roadmap Phase 3 — shared engines; VOR is
also where the leakage-fix "regress realized rate toward the prior" lands.)

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
- **Opportunity spec delta** — weighted opportunity + trust axis + point-correlation (the Phase-1 refinement).

## Status snapshot
- **Done:** Phase 0 (descriptive dashboard), Phase 1 (Opportunity / spike signal-quality — refine to spec).
- **Next:** **Phase 2 — the projection substrate** (the hinge).
- Everything past Phase 2 is gated on it.
