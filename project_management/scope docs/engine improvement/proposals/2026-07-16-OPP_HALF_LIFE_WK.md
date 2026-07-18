# Tuner proposal — `OPP_HALF_LIFE_WK` (HOLD)

**as-of:** 2026-07-16  ·  **rank:** 6  ·  **module:** `player_signal`  ·  **scope:** nfl

**baseline (frozen L3):** code_version `6dfcab270ee0` · constants_hash `a3d01b8e5f4d5131`

## Verdict: **HOLD**

- **current → proposed:** `None` → `None`
- **objective (lower better):** MAE(expected_ppg, rest_of_season_ppg)
- **TRAIN metric (current):** 2.8060  ·  **seasons fit:** 4
- **HELD-OUT (DEV 2024):** current 3.0340 · proposed 3.0340  (n=1)  [axis: season (DEV 2024)]
- **effect size (holdout):** 0.0000  ·  **floor:** 0.0500
- **inputs_ok over fit window:** 1.0000

### Guardrails
| holdout improves | no coupled regress | inputs_ok | effect > floor |
|---|---|---|---|
| False | True | True | False |

### Why HELD

current value is already the TRAIN+DEV optimum — the sweep confirms it out-of-sample; no change to propose (holdout effect 0)

---
*Auto-tune, human promotes: this is a proposal. No transform was edited and no constant was merged. Promote in a normal worktree session after review.*