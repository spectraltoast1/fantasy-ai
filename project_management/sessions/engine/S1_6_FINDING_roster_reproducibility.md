# Finding (Session 1.6, Commit 2) — the roster substrate is not reproducible across registry refreshes

**Status:** ✅ **RESOLVED (determinism) — Session 1.7.** The roster substrate is now reproducible: the
**pinned** Sleeper registry snapshot is authoritative for rostered skill-eligibility (join +
audit_join + market_vor read it), and the full rebuild pipeline run twice is byte-identical. Original
status (1.6): PROVEN mechanism, reported not fixed.

> ## ⚠️ Mechanism correction (Session 1.7 — the 1.6 diagnosis was outdated by the time of the fix)
> This doc (1.6) attributed the drop to **`audit_join` discarding a remainder** when the 24h registry
> labelled Hunter non-skill. **That path was SUPERSEDED by the time 1.7 ran.** nflreadpy had accumulated
> Hunter's **CB** rows for wk1–7, so a fresh join now **matches** his CB `nfl_stats` row and the
> SKILL_POSITIONS filter drops him **before** the remainder step — the **wk1–4 remainders are empty; he is
> not a remainder at all.** The registry⇄nfl_stats conflict is the correct **root cause**, but the **drop
> point is the join skill-filter**, not `audit_join`. Proven empirically (`remainders_exist` → 0 rows;
> `nfl_stats` Hunter = CB wk1–7). The reframe that fixes it: for a **rostered** player, skill-eligibility
> ("what slot does he fill?") is a **fantasy** question (Sleeper registry); stats ("what did he produce?")
> are an **NFL** question (nflreadpy). The bug was that eligibility was answered by the stats source.
> `audit_join` is still repointed to the pinned snapshot (dormant today — empty remainders — but the same
> drift class, and it wakes for a 276-league corpus).

**Reproduce (pre-fix):** `python3 -m application.data.transforms.backtest_roster_shape --season 2025 --diagnose`

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

---

## RESOLUTION (Session 1.7 — determinism, with the residual limitation named)

**What shipped.** The pinned Sleeper registry snapshot (`data_layer.ACTIVE_PLAYERS_SNAPSHOT` +
`read_pinned_sleeper_players`) is authoritative for rostered skill-eligibility. `join_nfl_sleeper_weekly`
overrides a rostered player's stats-source position with the registry's when they disagree on
skill-eligibility; `audit_join` and `compute_market_vor` (and `compute_player_signal`'s security axis) read
the pin, not the 24h cache. **The bounded/stable proof:** rebuilding join_season (2025 wk1–4) + everything
downstream moved **exactly one player — Travis Hunter (12530)** — every changed row named, no unexplained
movement; and the full pipeline run **twice is byte-identical**. `backtest_roster_shape` is green from
determinism (fresh compute == on-disk, 635/40/160), with a new twice-compute determinism check.

**Exposure quantified (measure, don't assume).** Corpus-wide two-way ceiling (nfl_stats non-skill players
scoring PPR): ~28–37/season, of which only **~4–6/season score ≥20 pts** (mostly FBs / punters / fluke-TD
DBs — few are true two-way skill players). **2025 real-roster exposure: exactly 1 (Hunter).**

**Residual limitation (NOT closed — different problem).** Pinning gives **determinism**, not **historical
accuracy**: the registry is current-state, so for a 2020–2024 corpus league the pin is still *today's*
labels. Session 3 must weigh this for registry-resolved players; it is a bounded footnote (the material
class is ~handfuls/season), not a blocker.

**Answer-key wrinkle — recommendation: FLAG, not exclude.** Hunter is rostered WR but his 63.8 season PPR
come from his CB line, so the realized-ROS answer key scores the wrong position. At n=1 in 2025 it does not
materially bias any gate (n=164–635). Recommend a first-class *cross-position two-way* flag on the answer
key rather than exclusion; defer the mechanism to Session 3 (corpus selection), where the class is still
only ~handfuls/season.
