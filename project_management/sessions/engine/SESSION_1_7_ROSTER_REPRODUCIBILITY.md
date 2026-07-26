# Session 1.7 — Roster Substrate Reproducibility (pin the registry)

**Hand this file to Claude Code as the session brief.**

**Type:** determinism fix — **CHANGES NUMBERS BY DESIGN** (read the gate section twice) · **Commits:** 3
**Reads first:** `CLAUDE.md` · `S1_6_FINDING_roster_reproducibility.md` (the proven diagnosis) · `712_BACKEND_AUDIT.md` (S1.1)
**Blocks:** the corpus harvest (Session 3). **Does NOT block Session 2** (substrate backfill is projection/consensus — no roster path) — the two are independent; either order.

---

## The problem, in one line

> **`join_season` resolves rostered players against a 24-hour mutable registry, so the same code on the
> same season produces different rosters on different days.** Every league-scoped read is built on it.

Session 1.6 **proved** this (not guessed it — the mechanism is walked in the finding doc):

- **Travis Hunter** (`12530`, JAX), a two-way rookie. `nfl_stats` labels him **CB**; the Sleeper registry
  labels him **WR**. He falls out of the offensive join → becomes a "remainder" → `audit_join` asks the
  **live registry** whether to keep him → the answer flips with whatever the registry says **on rebuild day**.
- On-disk `production_vor`: 635 rows (Hunter present). Fresh recompute: 631 (Hunter gone). Same code, same season.

The drift enters through the **roster path** (`join_season ← audit_join ← 24h registry`). A **second**
drift path exists in `compute_market_vor` (a direct position join off the same registry) — this session
closes **both**.

**Why it's a blocker, not a curiosity:** a corpus and a prediction ledger both rest on determinism.
Harvest 276 leagues today, re-harvest next month, get different rows → the ledger cannot attribute a change
to a *cause*, which is its entire job. Two-way players are a **standing, growing** source of this across
every read built on `join_season`: `production_vor → true_rank → positional_depth → bracket_odds → ros_*`.

---

## ⚠️ This session is the exception to standing instruction #2

Every prior session's gate was *"prove no number moved."* **This one moves numbers on purpose** — the
finding says so: the fix changes which players appear. So the discipline inverts:

> **Do not prove nothing changed. Prove that (a) the ONLY things that changed are the drift-exposed
> two-way players, every one of them named and explained, and (b) the result is now STABLE — running the
> whole pipeline twice produces byte-identical output.**
>
> Making the red gate green by regenerating against "today's registry" is **forbidden** — that bakes in a
> transient state and re-hides the hole. Green must come from **determinism**, not from a lucky snapshot.

---

## The fix — pin the registry (root cause, both paths)

Two options were proposed in the finding. **Recommendation: pin the registry snapshot (option 2 in the
finding), not just freeze position into `join_season`.** Reasoning:

| | freeze position into `join_season` | **pin the registry snapshot** |
|---|---|---|
| Fixes recompute-from-disk (the red gate) | yes | yes |
| Fixes **re-harvest from scratch** (the corpus case) | **no** — first write still uses live registry | **yes** |
| Fixes the `market_vor` direct-position drift | no | **yes — same fix, both paths** |
| Single source of truth | two (nflreadpy + frozen col) | **one pinned registry** |

Pinning is the only option that makes a **from-scratch harvest** reproducible, which is exactly the
operation Session 3 performs 276 times.

**Shape of it:**
- Snapshot the Sleeper `players.parquet` registry with a **version id**; record the **active snapshot id**
  in config (tracked), the snapshot itself living in the gitignored runtime store (the existing
  "runtime lives in main" model — don't fight it).
- `audit_join` and `compute_market_vor` read the **pinned** snapshot for a season, **never "today's."**
- A new snapshot becomes a **deliberate, versioned event** that triggers a rebuild + a no-regression
  review — never an ambient 24-hour drift. (This is the "single source of truth" discipline the project
  already applies to scoring/config, extended to the registry.)

---

## ⚠️ The corpus wrinkle you must NOT paper over

**Pinning gives determinism. It does NOT give historical accuracy — and those are different problems.**

The registry is **current-state only.** For a 2021 corpus league, "the pinned registry" is still *today's*
labels — a player who retired in 2022 may be missing; a since-relabeled player may be wrong. Pinning makes
the 2021 result **stable and re-runnable**; it does not make it **historically correct** for the small class
of players who resolve through the registry rather than through season-accurate `nfl_stats`.

**Do not silently equate the two.** The honest scope of this session is **determinism**. Historical
accuracy of registry-resolved remainders is a **separate, bounded limitation** — commit 3 quantifies it so
you know whether it's material, rather than assuming.

---

## Commit 1 — Pin the registry
- Version/snapshot `players.parquet`; config carries the active snapshot id; `data_layer` reads the pinned
  snapshot.
- Repoint `audit_join` and `compute_market_vor` to the pinned snapshot.
- **No rebuild yet** — just the plumbing, so commit 2's rebuild is attributable to one change.

## Commit 2 — Rebuild + the movement-is-bounded-and-stable gate
- Rebuild `join_season` (2025) and everything downstream from the pinned registry.
- **The gate (this is the session):**
  1. **Bounded:** diff new vs old on-disk for `production_vor` / `true_rank` / `positional_depth` /
     `bracket_odds` / `market_vor`. **Every changed row traces to a named two-way / registry-remainder
     player.** No unexplained movement. (Extend `backtest_roster_shape`'s `--diagnose` to print the full
     changed set, not just the count.)
  2. **Stable:** run the **entire** rebuild→compute pipeline **twice** and assert **byte-identical** output.
     *This is the actual proof the hole is closed* — a single run passing frame-eq proves nothing about
     drift.
  3. Every other gate exits 0.
- `backtest_roster_shape` goes **green legitimately** (deterministic), not by regeneration-to-taste.

## Commit 3 — Quantify the exposure, the answer-key wrinkle, docs
- **Quantify the drift-exposed class** (standing instruction #6 — measure, don't assume): across
  `nfl_stats` 2020–2025, how many rostered players resolve via the **registry-remainder** path rather than
  season-accurate nflreadpy? That number is the corpus's historical-accuracy exposure. **Report it. If it's
  a handful, it's a documented footnote; if it's material, it's a Session-3 selection rule.**
- **The two-way answer-key wrinkle:** Hunter's `fantasy_points_ppr` come from his **CB** line, so the
  realized-ROS *answer key* for a two-way skill player scores the wrong position. Orthogonal to
  reproducibility, same root. Quantify how many two-way skill players this touches across the corpus;
  recommend **accept / flag / exclude** — don't fix here.
- Promote `S1_6_FINDING_roster_reproducibility.md` to **RESOLVED** (determinism) with the residual
  limitation named. Update `STATUS.md`, `TECHNICAL_ARCHITECTURE.md` (the pinned-registry principle + S1.1
  struck), `READ_BUILD_ORDER.md`.

---

## Acceptance gates
1. **Bounded movement:** every row that changed vs the old on-disk parquets is a named two-way /
   registry-remainder player. Zero unexplained deltas.
2. **Determinism proven:** the full pipeline run **twice** is **byte-identical**. *(The headline gate. If
   this doesn't hold, the hole is not closed.)*
3. `backtest_roster_shape` green **from determinism**; every other gate exits 0.
4. `market_vor`'s direct-position path reads the pinned snapshot too (both drift paths closed — verify, don't assume).
5. The drift-exposed player count + the two-way answer-key count are **reported with real numbers**.

---

## Out of scope
- **Fixing** two-way answer-key attribution (quantify + recommend only).
- Re-tuning any constant; the harvest; the ledger; the scorer.
- Retro-sourcing historical registry snapshots (they don't exist — determinism is the achievable goal).

---

## Definition of done
- Registry pinned; both drift paths (`audit_join`, `market_vor`) read it.
- **Pipeline is deterministic — proven by a twice-run byte-identical check**, not a single frame-eq.
- All gates green from determinism; every changed row named.
- Corpus historical-accuracy exposure quantified; the finding doc marked RESOLVED with the residual limitation recorded.

---

> ## Standing instructions
> 1. A suspiciously clean zero is a bug until proven otherwise.
> 2. A refactor that changes a number is a bug — **EXCEPT here: this session changes numbers by design.
>    The substitute proof is "bounded + explained + twice-run-identical."**
> 3. If the fix wants to touch `queries.js` or a view component, the seam has leaked.
> 4. Report, don't tune.
> 5. Deleting dead code must not move a live number.
> 6. A plausible explanation is not a diagnosis. Name the mechanism, or write UNKNOWN and escalate.
