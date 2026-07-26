# Session 1.6 — Gate Repair (and one reproducibility question)

**Hand this file to Claude Code as the session brief.**

**Type:** repair + diagnosis · **Commits:** 3
**Reads first:** `CLAUDE.md` · `712_BACKEND_AUDIT.md` · `IMPROVEMENT_LOOP.md`
**Blocks:** Session 2 (substrate) and Session 3 (harvest). **Neither starts until this is green.**

---

## Why this is a dedicated session, not a bundle

Four gates are red. The follow-up note from §1.5 proposed fixing them *"before/with the Session 2 corpus
harvester."* **Reject the "with."**

You are about to compute `production_vor → true_rank → positional_depth → bracket_odds → ros_player_band`
across **276 league-seasons**. If `production_vor` is silently dropping players, that gets baked into every
one of them — and then you attempt to measure improvement against a baseline you can't trust.

> **A red gate suite is a broken instrument. The entire premise of the improvement loop is that the gates
> tell you the truth. You cannot begin measuring with a broken measuring device.**

---

## ⚠️ Standing instruction, sharpened — read this before you triage

The §1.5 note diagnosed two of these four as *"stale parquet"* and *"expected freeze-time state."* **Neither
diagnosis is supported.** This is now the **third** time an anomaly has been handed a plausible story
instead of a mechanism:

- §0.5: a hard zero across 258 leagues → *"dynasty-heavy neighbourhood"* → **wrong** (float32 bug)
- §0.6: the unscoreable rate → *"will soften"* → **wrong, it sharpened**
- §1.5: 4 missing rows → *"stale parquet"* → **unproven**

Every story was reasonable. **None was tested.**

> ### **A plausible explanation is not a diagnosis. Name the mechanism, or mark it UNKNOWN.**
> "It's probably X" is not an outcome of this session. Either you can point at the line of code / the row of
> data that causes it, or you write **UNKNOWN** and escalate. Both are acceptable. Guessing is not.

---

## Commit 1 — The two real L0 fallout bugs

**`check_market_vor`** — `check_market_vor.py:55` calls `data_layer._market_vor_path(season)`, but L0 keying
made `league_id` required. `TypeError`.
**Fix:** make it consistent with every other entity — give `_market_vor_path` a default-resolving `league_id`
via `_active_league`, rather than patching the one call site. **Check whether any *other* path fn has the
same inconsistency** — if `_market_vor_path` was missed, others may have been too. Grep them all.

**`check_ros_synthesis`** — `ValueError: No is_mine league for season 2026 in leagues.parquet`.
`ros_synthesis` is keyed on the **2026 news world**, but the registry only carries an `is_mine` league for
2025.

**Decide deliberately, don't patch:** `ros_synthesis` is **scoring-scoped**, not league-scoped — it has no
`roster_id`. So it arguably should not be resolving a league at all. **The right fix is probably that it
resolves a `scoring_key`, not an `is_mine` league.** If instead you add a 2026 registry row, you're papering
over a scope error. Look at which it actually is, then fix the cause.

---

## Commit 2 — 🔍 Diagnose the 4 missing `production_vor` rows

`backtest_roster_shape`'s frame-eq: fresh recompute = **631 rows**, on-disk = **635**. Four players are gone.

**Reject the current reasoning.** *"`backtest_production_vor` passes calibration, therefore it's not a code
regression"* is a **non-sequitur**: that gate is a ~0.95 correlation check across 635 players. Dropping 4 of
them moves a correlation by essentially nothing. **A calibration gate is physically incapable of detecting 4
missing rows.** The frame-eq check is the instrument that *can* — and it is the one that's failing. Trusting
the insensitive test over the sensitive one is backwards.

### The task: **name the four players. Then name the mechanism.**

Diff the on-disk parquet against a fresh `compute()`. Print the 4 `sleeper_player_id`s, their names,
positions, teams, and `as_of_week`. Then determine which of these is true:

| If the 4 players... | Mechanism | Severity |
|---|---|---|
| lost their **position** in the Sleeper registry | the registry is a **current-state cache that moved under you** | **🚨 see below** |
| lost a **`projection_consensus` row** | the §0.6 scoring fix changed consensus — its "byte-identical" claim was incomplete | high |
| dropped out of **roster resolution** (`_roster_as_of`) | L0 keying regression | high |
| have **no projection** | upstream `projections` shifted | medium |

### 🚨 The hypothesis to test first — because it's the one that undermines everything

`compute_production_vor` joins **position** from `cache/sleeper/players.parquet` — a **current-state registry
refreshed every 24 hours.** If a player retired, was cut, or had his status change, he can **silently vanish
from a 2025 derived read.**

If that's the cause, this is **not a stale parquet. It is a reproducibility hole in the foundation:**

> **Same code, same season, different answers on different days — because the registry moved underneath.**

**A corpus and a prediction ledger both rest on determinism.** Harvest 276 leagues today, re-harvest next
month, get different numbers — and the ledger's whole purpose (attributing a change to a *cause*) collapses.

**If confirmed:** do **not** silently regenerate the parquets. **Report it, name it, and propose the fix**
(pin/version the registry snapshot, or freeze `position` into the season join at write time so derived reads
never depend on a moving cache). **The fix itself is a follow-up session** — it's a structural change and it
deserves its own no-regression proof. This session's job is to *prove the mechanism*.

**If it's something else:** fix it, and re-verify frame-eq.

**If you cannot determine it:** write **UNKNOWN**, show what you ruled out, and escalate. That is an
acceptable outcome. A guess is not.

---

## Commit 3 — Redefine the `ros_player_band` population (report, do not tune)

### What actually happened

The L0 split changed the population the band is calibrated on:

| | old `ros_outcome_shape` | new `ros_player_band` |
|---|---|---|
| scope | **rostered** (`roster_id`) | **whole NFL pool** (no roster) |
| players | ~160 / week | **~544 / week** |
| as-of weeks | 1–4 | **1–17** |
| rows | 635 | **8,305** |

`BULL_Z = 1.44` was swept on the **rostered, freeze-week** population. It is now graded on a whole-pool,
full-season population **3.4× larger** — and the players it added are the *marginal* ones (deep bench, waiver
fodder, low-volume), whose ROS outcomes swing far wider relative to their projections.

**Coverage falling 0.817 → ~0.70 is exactly what you'd predict.** This is **not** a calibration regression and
**not** "expected freeze state." **It is a constant fitted to a population that no longer exists.**

### The product decision (made 2026-07-14)

The band should cover the **decision-relevant** population: everyone a manager could plausibly act on —
**rostered players plus the waiver-wire players worth picking up.** Whole-pool is polluted with noise;
rostered-only can't price a pickup candidate, which is a core surface.

> **Population = top 300 skill players by projected ROS value, per (season, as_of_week).**
>
> Comfortably covers a 14-team league's rostered pool (~210 skill players) plus a real waiver buffer.
> **League-agnostic**, so it preserves the scoring-scoped design — do **not** define this in terms of
> "rostered," or you re-couple the entity to a league and undo the L0 split.

**Implement with per-position floors** (e.g. ≥32 QB, ≥32 TE). A flat top-300 by raw projected points will
**quietly starve TE and over-weight QB** in most scoring. **Report the positional composition of the pool** so
this is visible, not assumed.

The pool naturally shrinks as the horizon closes (544 → 361 by wk17): use `min(300, available)`. A player
entering or leaving the pool week to week is **correct** (a breakout WR should enter it).

### Suppression — this is the important part

**Add `in_calibrated_pool` as a first-class column.** A band is only honest *within* the population it was
calibrated on. **If the UI renders bull/bear for a player outside the pool, that band is uncalibrated and it
violates law 2.**

> **This is the project's first suppression rule** — the ability to say *"we don't have a read on this"* and
> show nothing. Build it as a **reusable mechanism**, not a one-off filter. It will be needed again.

**Note for `ros_synthesis`:** players outside the pool now get `has_ros_anchor = false` and degrade to
news-only with capped confidence. **The existing graceful-degradation design already handles this** — verify
it, don't rebuild it.

### 🚫 Do NOT touch `BULL_Z`

Define the population, recompute, and **report** the coverage under the **current, unchanged** `BULL_Z = 1.44`.

The constant is now definitionally mis-fit. **That is fine** — nothing is in users' hands. **Re-fitting it
belongs to the Tuner, on the corpus, with proper holdouts.** Re-sweeping it here, on 2025, would be **tuning
on the test set** — the exact sin this entire programme exists to prevent. **The gate may stay red on
calibration. Say so honestly and leave it.**

---

## Acceptance gates

1. `check_market_vor` exits 0. **All `data_layer` path fns audited for the same `league_id` inconsistency.**
2. `check_ros_synthesis` exits 0 — via the **right** scope fix, with the reasoning recorded.
3. **The 4 players are NAMED**, and the mechanism is either **proven** or explicitly marked **UNKNOWN** with
   what was ruled out. *(If the registry-drift hypothesis is confirmed, it is reported — not silently
   patched.)*
4. `ros_player_band` carries `in_calibrated_pool`; the top-300 pool's **positional composition is reported**;
   coverage is reported **on the pool** and **on the whole pool** as evidence.
5. **`BULL_Z` is unchanged.** Any recommendation to move it is written down, not applied.
6. Every other gate still exits 0 with **identical numbers**.

---

## Out of scope

- Re-tuning **any** constant.
- **Fixing** the registry-reproducibility problem, if that's what commit 2 finds. **Prove it; don't fix it.**
  It's a structural change and it earns its own session.
- The harvest, the substrate backfill, the ledger, the scorer.

---

## Definition of done

- All four gates green **or** honestly red with a named, proven reason (`ros_player_band` calibration may
  legitimately remain red pending the Tuner).
- The 4 players are named. The mechanism is proven or marked UNKNOWN.
- The top-300 pool + `in_calibrated_pool` suppression flag ships; positional composition reported.
- `BULL_Z` untouched.
- STATUS records the reproducibility question if it was confirmed.

---

> ## Standing instructions
> 1. **A suspiciously clean zero is a bug until proven otherwise.**
> 2. **A refactor that changes a number is a bug, not a refactor.**
> 3. **If the fix wants to touch `queries.js` or a view component, the seam has leaked.**
> 4. **Report, don't tune.**
> 5. **Deleting dead code must not move a live number.**
> 6. **NEW — A plausible explanation is not a diagnosis.** Name the mechanism, or write UNKNOWN and escalate.
