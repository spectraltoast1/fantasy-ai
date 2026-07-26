# Session 2 — The NFL Substrate Backfill (2020–2025)

**Hand this file to Claude Code as the session brief.**

**Type:** data backfill + leakage fix · **Commits:** 3
**Reads first:** `CLAUDE.md` · `LEAGUE_CORPUS.md` · `SPIKE_CORPUS_FINDINGS.md` (probe A)
**Blocks:** the corpus harvest (Session 3) — **hard prerequisite, nothing can be computed without it**
**Prior:** Session 1 (L0 keying) — the store is now scope-keyed (`derived/league/{id}/`, `derived/scoring/{key}/`)

---

## Why this session exists

The corpus is 221 matched league-seasons across **2020–2025**. The read spine every one of them must run
is:

```
projections → projection_consensus → production_vor → { true_rank · positional_depth · bracket_odds }
                                                     → ros_player_band → ros_league_view
```

**Coverage check (verified 2026-07-14):**

| NFL-global entity | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|
| `nfl_stats` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `adp_preseason` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **`projections`** | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **`projection_consensus`** | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ (ppr only) |

**Projections exist for 2025 and nothing else.** Harvesting 276 league-seasons into a spine with no
forward prior produces a corpus of nulls.

**Good news: Session 0 already proved the data is there.** Probe A pulled populated `pts_ppr` boards for
**2019–2025** off `api.sleeper.com/projections/nfl/{season}/{week}`. This is a fetch, not a research
problem.

**Note this session is league-independent.** It isn't really "corpus work" — it's the engine finally
having a **multi-season substrate**, which it has never had. It would be needed for a one-league corpus too.

---

## Commit 1 — Backfill `projections`, 2020–2024

`sleeper.py projections <season> <week>` already exists and already routes through `_http`. Run it for
**5 seasons × 18 weeks = 90 fetches** (~2 min). Idempotent by construction (`write_projections` dedups on
`(season, week, source)`).

### ⚠️ Pre-check FIRST — do this before backfilling all five seasons

Pull **one old week (e.g. 2021 wk5)** and diff its schema against 2025's.

The `projections` entity carries **component columns** — `proj_pass_yd`, `proj_rush_yd`, `proj_rec_yd`,
`proj_pass_td`, `proj_rush_td`, `proj_rec_td`, `proj_rec`, `proj_pts_std` — and they are **load-bearing**:

- `_scoring.recompute_custom_points()` builds its delta from them,
- `_scoring.expected_points_expr()` / the §1 Quality axis depends on the matching `nfl_stats` `*_exp` side.

**If old payloads are missing components, say so loudly and stop.** A silently-null `proj_rec` would make
every custom/half recompute wrong for that season, and it would fail *quietly*. Report exactly which
columns are present per season before you write anything.

---

## Commit 2 — `projection_consensus` × scoring_key × season

Compute for the **matched stratum's scoring keys only: `ppr` and `half`.**

```
derived/scoring/{ppr,half}/projection_consensus_{2020..2025}.parquet   →  12 runs
derived/scoring/{ppr,half}/ros_player_band_{2020..2025}.parquet
```

Cheap — 2025/ppr is 6,100 rows, so the whole set is ~75k rows.

> **Deliberately NOT computing the generalization stratum's substrate.** It carries **33 distinct custom
> scoring keys**, and consensus is scoring-scoped — 33 keys × 6 seasons is a compute multiplier for a set
> you will **never tune on**. Generalization substrate is deferred to Session 3, *after* the
> generalization re-select caps the distinct-key count (~12). **Matched is what you tune and gate on;
> that's what this session serves.**

**Re-run the existing gates** (`backtest_projection_consensus --season 2025`, and now the other seasons)
and **report per-season calibration**. This is your **first-ever multi-season look** at whether
`BAND_Z = 0.55` / `SKEW_GAIN = 1.5` hold outside 2025.

> **Report it. Do not re-tune it.** Tuning is the Tuner's job (a later session) and it must happen on the
> proper train/holdout split, not opportunistically here. **If 2025's calibration turns out to be the
> outlier, that is the single most important finding of the session — say so plainly and leave the
> constants alone.**

---

## Commit 3 — ⚠️ Leak-free `adp_points_curve` (per held-out season)

**This is a real leakage bug that a multi-season corpus creates and the current design cannot survive.**

`compute_adp_points_curve.py` fits the ADP-rank → realized-points curve over prior seasons **with the
target season held out** (it has a `--holdout` arg). But **only ONE curve is persisted** —
`derived/adp_points_curve.parquet`, 240 rows, season-agnostic.

The moment you backtest `ros_player_band` on 2023, that single curve **has already seen 2023**. The §2
preseason anchor (`ANCHOR_W = 0.25`) would be fit on the very outcomes it's being graded against. **Every
§2 result on the corpus would be optimistic and unfalsifiable.**

**Fix:** persist **one curve per held-out target season**.

```
derived/adp_points_curve/holdout_{season}.parquet     # fit on all seasons EXCEPT {season}
```

`compute_ros_player_band(season=S)` must load `holdout_S`. Never the pooled curve.

**Gate it:** assert that the curve used for season S contains **no** data from season S. Make it a hard
check — this is exactly the class of error (silent, optimistic, invisible in the output) that the whole
improvement loop exists to prevent, and it would be deeply ironic to bake one into its foundation.

Then: update `STATUS.md` / `TECHNICAL_ARCHITECTURE.md` (the new per-holdout curve entity) and
`READ_BUILD_ORDER.md`.

---

## Acceptance gates

1. **Schema honesty:** the per-season component-column presence table for `projections` is reported. **If
   any season is missing a load-bearing component, the session STOPS and reports** — it does not write a
   partial substrate and hope.
2. `projections` present for **2020–2025**, all 18 weeks; `write_projections` dedup verified idempotent
   (re-run a week, row count unchanged).
3. `projection_consensus` + `ros_player_band` present for **{ppr, half} × 2020–2025**.
4. **No-regression:** 2025/ppr `projection_consensus` is **byte-identical** to the pre-session file. *(You
   are adding seasons, not changing 2025. If 2025 moves, something is wrong.)*
5. **Per-season calibration reported** for `BAND_Z` / `SKEW_GAIN` — 6 seasons, side by side. **Reported,
   not acted on.**
6. **Leak gate:** `adp_points_curve/holdout_S` provably excludes season S, for every S. Hard fail if not.

---

## Out of scope

- **Re-tuning ANY constant.** Report the multi-season calibration; leave `BAND_Z`, `SKEW_GAIN`, `BULL_Z`,
  `ANCHOR_W`, `OPP_HALF_LIFE_WK` exactly as they are. The Tuner session owns this, on a proper split.
- **Harvesting any league.** Session 3.
- Generalization-stratum substrate (deferred — see commit 2), and the generalization season-gap defect
  (still flagged in `check_corpus`; fixed in Session 3).
- The ledger, the scorer, the front end.

---

## Definition of done

- 6 seasons of `projections`, component columns verified present and named.
- 12 `projection_consensus` + 12 `ros_player_band` slices ({ppr, half} × 2020–2025).
- **Per-holdout ADP curves, leak-gated** — the §2 anchor can no longer see its own answer key.
- 2025 reproduced byte-identical; **per-season calibration table reported and left alone.**

---

> ## Standing instructions (carried forward)
> 1. **A suspiciously clean zero is a bug until proven otherwise.**
> 2. **A refactor that changes a number is a bug, not a refactor.** Prove equivalence.
> 3. **If the fix wants to touch `queries.js` or a view component, the seam has leaked.**
> 4. **NEW — Report, don't tune.** This session will surface the first honest multi-season read on
>    constants fit in-sample. **Surfacing it is the deliverable. Acting on it here would be tuning on the
>    test set** — the exact sin the whole programme exists to stop.
