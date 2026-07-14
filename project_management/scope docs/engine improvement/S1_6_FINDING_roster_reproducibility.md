# Finding (Session 1.6, Commit 2) — the roster substrate is not reproducible across registry refreshes

**Status:** PROVEN mechanism · reported, **not fixed** (per the §1.6 brief: "prove it; don't fix it — it
earns its own session"). This doc is the escalation + fix proposal for a PM to formalize into a session.

**Reproduce:** `python3 -m application.data.transforms.backtest_roster_shape --season 2025 --diagnose`

---

## What was red

`backtest_roster_shape`'s `production_vor` frame-eq: fresh `compute()` = **631 rows**, on-disk parquet =
**635**. Four rows diverge. `.equals()` only returns a bool, so the gate never named them — the new
read-only `--diagnose` mode does.

## The four rows are one player

**Travis Hunter** (`sleeper_player_id = 12530`, JAX), at `as_of_week` 1/2/3/4 on `roster_id 8`. On disk,
absent from a fresh compute.

## Mechanism — PROVEN, not plausible

The drop-point walk on the fresh inputs:

| Check | Result |
|---|---|
| (a) projected remaining week in `projection_consensus`? | **yes** (7 rows, WR) — not a projection loss |
| (b) present in `join_season` / `roster_as_of(N)`? | **NO — absent from `join_season` entirely** |
| (c) position → pool? | WR → FLEX, fine |

The smoking gun is a **position conflict between the two substrates**:

- **`nfl_stats` (nflreadpy) labels Hunter `CB`** for every week (his `fantasy_points_ppr` are computed from
  IDP/return production).
- **The Sleeper registry labels him `WR`** (`depth_chart_position = SWR`).

Hunter is a **two-way rookie**. `join_season` is built by `join_nfl_sleeper_weekly`, and `audit_join`
resolves rostered players missing from the nflreadpy offensive join ("remainders") **from the 24-hour
Sleeper current-state registry** — keeping a remainder **only if the registry then labels him a skill
position**. So Hunter's presence in the roster substrate depends entirely on the registry's label **at the
moment `join_season` was last rebuilt**:

- on-disk `production_vor` (635, **with** Hunter as WR) was written from a `join_season` built when the
  registry labeled him WR;
- the current `join_season` (171 players, **without** Hunter) was rebuilt during a window when he resolved
  as non-skill, so `audit_join` discarded him;
- a fresh `production_vor.compute()` reads that current `join_season` → drops him → 631.

> **Same code, same season, different answers on different days — because the registry moved underneath.**
> This is audit S1.1's reproducibility hole, manifesting through the **roster path**
> (`join_season` ← `audit_join` ← 24h registry), not the direct position-join the brief hypothesised (that
> path is real too, but it lives in `compute_market_vor`, not `compute_production_vor`).

## Why this matters (unchanged from the brief's framing)

A corpus and a prediction ledger both rest on determinism. Harvest 276 leagues today, re-harvest next
month, get different rows — and the ledger's whole purpose (attributing a change to a *cause*) collapses.
Two-way players (Hunter; and this class will grow) are a standing source of non-determinism in **every**
read built on `join_season`: `production_vor → true_rank → positional_depth → bracket_odds → ros_*`.

## Proposed fix (a follow-up session — do NOT do it in 1.6)

Do **not** regenerate the parquets to make the gate green: that bakes in whichever transient registry state
happens to be live, and re-hides the hole. Instead, make the roster substrate **deterministic**:

1. **Freeze `position` (and skill-eligibility) into `join_season` at write time**, from the registry
   snapshot in force when the season is first built — so every downstream read depends on a pinned label,
   not a moving cache. (Preferred: local, cheap, kills the drift at the source.)
2. **or Pin/version the Sleeper `players.parquet` registry** (snapshot-id it; `audit_join` reads the pinned
   snapshot for a given season, never "today's"). Broader; also fixes the `market_vor` position join.

Either way the gate then reproduces frame-for-frame **and stays reproducible**. Budget a no-regression proof
(the fix changes which players appear, so it will move numbers by construction — that is the point, and it
earns its own session).

## The two-way answer-key wrinkle (report, secondary)

Hunter's `nfl_stats.fantasy_points_ppr` come from his **CB** line, so even the realized-ROS answer key for a
two-way player scores his defensive production, not WR receiving. Orthogonal to the reproducibility hole,
but the same root (two-way players), and worth the follow-up session's attention.
