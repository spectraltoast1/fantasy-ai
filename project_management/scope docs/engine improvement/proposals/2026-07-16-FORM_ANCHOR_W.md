# Tuner proposal — `FORM_ANCHOR_W` (HOLD)

**as-of:** 2026-07-16  ·  **rank:** 8  ·  **module:** `production_vor`  ·  **scope:** scoring

**baseline (frozen L3):** code_version `6dfcab270ee0` · constants_hash `a3d01b8e5f4d5131`

## Verdict: **HOLD**

- **current → proposed:** `0.0` → `0.1`
- **objective (lower better):** MAE(debiased ROS centre, realized ROS canonical)
- **TRAIN metric (current):** 30.5520  ·  **seasons fit:** 4
- **HELD-OUT (DEV 2024):** current 21.9456 · proposed 21.7432  (n=1)  [axis: season (DEV 2024)]
- **effect size (holdout):** 0.2025  ·  **floor:** 0.5000
- **inputs_ok over fit window:** 1.0000

### Guardrails
| holdout improves | no coupled regress | inputs_ok | effect > floor |
|---|---|---|---|
| True | True | True | False |

### Coupled gates re-run
- `backtest_production_vor`: pass=True — own read gate at FORM_ANCHOR_W=0.1, DEV 2024
- `backtest_ros_player_band`: pass=True — decoupled by construction (consumes the center, not the band)
- `backtest_true_rank`: pass=True — decoupled by construction (consumes the center, not the band)

### Why HELD

guardrail(s) not met: effect>floor

---
*Auto-tune, human promotes: this is a proposal. No transform was edited and no constant was merged. Promote in a normal worktree session after review.*