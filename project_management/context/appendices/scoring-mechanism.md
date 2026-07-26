# Appendix: Scoring Mechanism

**Scope:** how scoring is represented and applied. Referenced from `ARCHITECTURE.md`. The forward-looking
scoring work (standard, custom, dynasty) lives in `projects/post-v1/`.

## `scoring_key` classifies the reception tier only

`scoring_key` ∈ {`ppr`, `half`, `std`, `cust-<hash>`}. It classifies **only the reception tier** — *not* the
full scoring dict. **Two leagues sharing a `scoring_key` (e.g. both `ppr`) genuinely score a player-week
differently** when they differ on INT penalty, yardage/reception bonuses, or first-down points. Verified
against the live store: ~10% of shared player-weeks diverge (spreads up to ~21 pts).

Consequence, baked into the ledger's `outcomes` entity — two realized-point series are kept:
- `player_weekly_pts` — **league-scoped** (each league's exact realized truth; grades that league's reads).
- `player_weekly_pts_canonical` — **scoring-scoped** (the league-independent basis the shared band was
  projected under; grades the band).

Implication: the shared scoring-scoped band carries an inherent per-league error floor for atypical same-key
(e.g. bonus-heavy) leagues. This is honest and acceptable for V1, but should be surfaced in onboarding copy.

## Where scoring is applied

- **Realized points** arrive **pre-scored from Sleeper** (`sleeper_points`) — so the *displayed actuals* are
  exact for every league.
- **Projected points** are scored at the **consumption layer** by the dispatcher `transforms/_scoring.py`:
  the projection entity stays generic (`pts_ppr`/`pts_half`/`pts_std` + component stats) and
  `compute_projection_consensus` applies the league's profile. This is why one set of projections serves any
  league.
- **Scoring-scoped substrate** (`projection_consensus`, `ros_player_band`) is stored under
  `derived/scoring/<key>/` and **shared across leagues on the same key** — keeps AI cost flat as leagues grow.

## The custom delta engine

`recompute_custom_points` scores a custom league as **standard baseline + Σ (per-component weight deltas)**
— exact for a standard league (all deltas 0). It **supports** any reception value, 6-pt pass TD, non-standard
yardage/TD rates, and position-conditional reception bonuses (TE-premium). It **rejects (raises, never
silently mis-scores)** first-down bonuses and threshold/milestone yardage bonuses, because the projections
carry no component for them — which makes ~45% of real custom leagues unscoreable today. Full plan:
`projects/post-v1/` (custom scoring).

## Tuned constants are scoring-invariant

The engine's tuned constants describe NFL player-week residual shape and horizon decay, **not** the points
transform — so a scoring change is *certify, don't re-tune*. Standard and custom keys enter only as
certification / holdout targets, never as fit inputs. (Dynasty is the exception — a different *value* model,
not a scoring change.) See appendix: engine-improvement-loop.
