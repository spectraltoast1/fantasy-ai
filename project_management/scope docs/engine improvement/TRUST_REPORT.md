# Engine Trust Report — the first measurement (L3 scorer)

*Generated from `engine_scorecard_{season}` over seasons [2020, 2021, 2022, 2023, 2024, 2025] (270 spined league-seasons). The scorer **judges distributions, never single claims**; it **changes no constant** — a red light is a finding for the Tuner (L4) / Proposer (L6), not a fix. Traffic lights are pooled across seasons (n-weighted); the season + cohort rows carry the out-of-sample story.*

## Headline

- **Projection optimism is real and stable.** `production_vor` **loses to carry-recent-form-forward every season** (skill < 0) while ranking well — it prices the ORDER right but the LEVEL high. The `ros_player_band` under-covers (~0.55 vs 0.80 target) with PIT piled at the edges. Two independent reads, one story. *(A Tuner lead, not fixed here.)*
- **The measurement reads hold out-of-sample** (§1 signal, §5 rank, §6 depth) — the pre-registered prediction stands.
- **Confidence-honesty (law 2) — the headline — is mixed.** Playoff odds and true-rank sort honestly by error; the **band's `ros_cv` is INVERTED** (its narrowest bands miss by the most) and positional_depth's `spectrum_pos` doesn't sort. 4 reads state no confidence at all.

## Traffic lights (pooled across seasons)

| Read | n | Skill | Calibration | Confidence-honesty (law 2) | Pre-registered |
|---|--:|---|---|---|---|
| production_vor — rest-of-season VOR (the foundation) | 692,671 | 🔴 -0.25 | ⚪ n/a (no stated distribution) | ⚪ unmeasurable (no native confidence — law-2 gap) | — |
| ros_player_band — the ROS range (bear/center/bull) | 86,547 | ⚪ n/a (calibration read) | 🔴 KS 0.47, cover 0.57/0.80 | 🔴 INVERTED/flat — laundering noise (ρ=+0.58, ros_cv) | §3 band calibrated to ~0.80: SURPRISE ✗ |
| player_signal — expected ppg (§1 repeatability) | 658,395 | 🟡 +0.03 | ⚪ n/a (no stated distribution) | 🟢 honest (ρ=-0.04, regression_risk) | §1 signal HOLD (measurement): HOLD ✓ |
| player_signal — trend direction | 658,395 | 🔴 -0.11 | ⚪ n/a (no stated distribution) | ⚪ unmeasurable (no native confidence — law-2 gap) | — |
| true_rank — final-standing rank (§5) | 43,124 | 🟢 +0.34 | ⚪ n/a (no stated distribution) | 🟢 honest (ρ=-0.11, spectrum_pos) | §5 true-rank HOLD (measurement): HOLD ✓ |
| positional_depth — roster×position surplus (§6) | 172,415 | 🟢 +0.07 | ⚪ n/a (no stated distribution) | 🟡 weak (ρ=+0.02, spectrum_pos) | §6 depth HOLD (measurement): HOLD ✓ |
| bracket_odds — playoff odds (§5) | 40,020 | 🟢 +0.50 | 🟢 KS 0.012, Brier 0.126 | 🟢 honest (ρ=-0.89, playoff_odds) | §5 Brier < 0.25: HOLD ✓ |
| bracket_odds — projected wins | 40,020 | 🟢 +0.44 | ⚪ n/a (no stated distribution) | ⚪ unmeasurable (no native confidence — law-2 gap) | — |
| bracket_odds — projected seed | 40,020 | 🟢 +0.61 | ⚪ n/a (no stated distribution) | ⚪ unmeasurable (no native confidence — law-2 gap) | — |

## What we'd honestly tell a user (per read)

- **production_vor/point** — Ranks rest-of-season value well (Spearman 0.88) but point totals run high (median +29) — trust the ORDER, not the level. Confidence-honesty UNMEASURABLE (no native confidence signal — law-2 gap).
- **ros_player_band/interval** — The range is too narrow — truth lands in-band only 0.57 of the time (target 0.80); widen the error bars. Confidence (ros_cv) does NOT sort by error — FLAG.
- **player_signal/point** — About even with 'recent form carries forward' (skill 0.03) — a thin edge on near-random weekly scoring. Confidence (regression_risk) IS honest.
- **player_signal/direction** — Trend calls barely beat guessing the base rate (skill -0.11). Confidence-honesty UNMEASURABLE (no native confidence signal — law-2 gap).
- **true_rank/ordinal** — Ranks final standings materially better than chance (skill 0.34). Confidence (spectrum_pos) IS honest.
- **positional_depth/point** — Weak signal on an APPROXIMATE answer key (skill 0.07, coverage-flagged) — directional only. Confidence (spectrum_pos) does NOT sort by error — FLAG.
- **bracket_odds/probability** — Playoff odds are well-calibrated (Brier 0.13 < 0.25) and beat a coin flip (skill 0.50). Confidence (playoff_odds) IS honest.
- **bracket_odds/point** — Win projections beat a .500 baseline (skill 0.44). Confidence-honesty UNMEASURABLE (no native confidence signal — law-2 gap).
- **bracket_odds/ordinal** — Seed projections beat random ordering (skill 0.61). Confidence-honesty UNMEASURABLE (no native confidence signal — law-2 gap).

## Out-of-sample: skill by season (does it hold on the TEST years?)

| Read | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|--:|--:|--:|--:|--:|--:|
| production_vor/point | -0.39 | -0.36 | -0.24 | -0.17 | -0.16 | -0.34 |
| player_signal/point | -0.02 | +0.01 | +0.03 | +0.03 | +0.03 | +0.04 |
| player_signal/direction | -0.17 | -0.26 | -0.11 | -0.09 | -0.06 | -0.12 |
| true_rank/ordinal | +0.31 | +0.30 | +0.36 | +0.33 | +0.32 | +0.39 |
| positional_depth/point | +0.06 | +0.08 | +0.06 | +0.04 | +0.06 | +0.09 |
| bracket_odds/probability | +0.55 | +0.46 | +0.55 | +0.48 | +0.47 | +0.52 |
| bracket_odds/point | +0.45 | +0.39 | +0.49 | +0.44 | +0.42 | +0.47 |
| bracket_odds/ordinal | +0.61 | +0.57 | +0.64 | +0.59 | +0.59 | +0.64 |

## Cohort: does it hold on the 48 never-tune generalization leagues?

| Read | matched (skill) | generalization (skill) | Δ |
|---|--:|--:|--:|
| production_vor/point | -0.27 | -0.15 | +0.13 |
| player_signal/point | +0.03 | +0.02 | -0.01 |
| player_signal/direction | -0.12 | -0.07 | +0.05 |
| true_rank/ordinal | +0.32 | +0.47 | +0.14 |
| positional_depth/point | +0.03 | +0.20 | +0.17 |
| bracket_odds/probability | +0.48 | +0.58 | +0.10 |
| bracket_odds/point | +0.43 | +0.52 | +0.09 |
| bracket_odds/ordinal | +0.60 | +0.66 | +0.06 |

## Method + boundaries

- **Skill** = `1 − metric_engine/metric_naive` vs a **declared naive baseline** (`scorecard_registry.py`): 2 promoted from the backtests (player_signal→naive_ppg, playoff-odds→0.25 Brier), the rest declared canonical (recent-form-forward, pool-mean, closed-form random-permutation `(n²−1)/(3n)`, .500 win-rate). The band is **skill n/a by design** — its lens is calibration.
- **Calibration** = PIT-uniformity (KS) + coverage for the interval band, Brier + PIT for the probability read. Point/ordinal/direction state no distribution → no PIT.
- **Confidence-honesty (law 2)** = Spearman(the read's own stated confidence strength, realized error) — honest when NEGATIVE (more confidence ⇒ less error). Extremeness signals (`spectrum_pos`, `playoff_odds`) use `|x−0.5|`; inverted signals (`ros_cv`, `regression_risk`) use `−x`. 4 reads carry **no native confidence** → law-2 unmeasurable (reported, not fabricated).
- **Quarantine:** the `overall` verdict is on `inputs_ok ∧ resolved` only; `inputs_ok=false` and unresolved live in their own slices, never blended. `mine`/2025 is in-sample + partially realized (a live league) — read the matched + generalization cohorts as the honest evidence.
