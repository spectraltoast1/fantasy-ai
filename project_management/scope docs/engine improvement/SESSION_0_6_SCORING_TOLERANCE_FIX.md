# Session 0.6 — The `_scoring` Float32 Tolerance Fix (+ corpus re-select)

**Hand this file to Claude Code as the session brief.**

**Type:** bug fix — **live production bug**, found by the corpus · **Commits:** 3
**Reads first:** `CLAUDE.md` · `SPIKE_CORPUS_FINDINGS.md` · `SESSION_0_5_CORPUS_SELECTION.md`
**Blocks:** L0 keying (Session 1) — the corpus manifest is wrong until this lands

---

## The bug

`application/data/transforms/_scoring.py`:

```python
_TOL = 1e-9                                                    # line ~53

def scoring_profile(scoring: dict) -> str:
    ...
    for key, std in _STANDARD.items():
        if abs(float(scoring.get(key, std)) - std) > _TOL:     # line ~103
            return "custom"
```

**Sleeper serves scoring weights at float32 precision.** A standard PPR league comes back as:

```
rush_yd = 0.10000000149011612     (not 0.1)   → drift 1.49e-9
rec_yd  = 0.10000000149011612     (not 0.1)   → drift 1.49e-9
pass_yd = 0.03999999910593033     (not 0.04)  → drift 8.9e-10
```

`1.49e-9 > 1e-9` ⇒ **a bog-standard PPR league is classified `custom`.**

---

## What it cost (measured against the persisted `corpus_discovery.parquet`)

**100% of 2020–21 leagues (258 of 258) are float32-drifted.** That — not the composition of the
neighbourhood — is why Session 0.5 reported *zero* matched supply in those years and wrote off two
seasons.

| | 0.5 reported | Truth |
|---|---|---|
| matched-eligible 2020 | **0** | **10** |
| matched-eligible 2021 | **0** | **19** |
| matched-eligible 2022 / 23 / 24 / 25 | 21 / 58 / 65 / 117 | **30 / 66 / 70 / 125** |
| matched-eligible **total** | 261 | **320** (+23%) |
| leagues misclassified `custom` | — | **272** (2025 alone: **36**) |
| the `custom` pool (39.2%-unscoreable denominator) | 2,045 | **1,765** — inflated **13.7%** |
| **usable seasons** | **4** | **6** |

**It is not an "old data" problem.** Every season is affected; it is a *precision* bug that merely
happens to be universal in old data.

---

## ⚠️ This is a LIVE bug, not a corpus bug

`scoring_profile()` is core engine code. Callers:

| Caller | Effect of the bug | Severity |
|---|---|---|
| `compute_projection_consensus` | a drifted PPR league takes the `recompute_custom_points` path instead of the canned column. `backtest_scoring_recompute` proves custom == canned on standard inputs (≈0.01 rounding), and the delta on a drifted weight is ~1e-9 ⇒ **numerically benign**. Slower and mislabelled, not wrong. | low |
| **`_manager.classify_league` / `is_comparable` (§7)** | your clean `ppr` league vs a candidate's **wrongly-`custom`** profile ⇒ **not comparable ⇒ silently dropped from the fan-out.** `manager_activity` thins → `manager_features` thins → dossiers get worse. **~10% of 2025 leagues are drifted, so this is happening now.** | **HIGH** |

> **Testable hypothesis worth chasing (commit 3):** STATUS documents §7 depth as *"honestly thin
> (recurring-league friend group)."* **Some of that thinness may be this bug, not your friend group.**

**Your own league's stored scoring is clean** (`rec 1.0 · pass_yd 0.04 · rush_yd 0.1 · rec_yd 0.1 ·
pass_td 4.0 · rush_td 6.0 · rec_td 6.0`, verified in `league_settings_2025.parquet`). It already
classifies `ppr`. **So the fix cannot move the live app's numbers — the no-regression gate below is a
guarantee, not a hope.** Prove it anyway.

---

## Commit 1 — Fix the classifier (and gate that nothing moved)

**Recommended fix: compare at real-world precision, not float epsilon.**

Sleeper scoring settings are 2–4 decimal places *by construction* (the UI can't express more). So round,
don't loosen:

```python
def _weights_match(value, std) -> bool:
    return round(float(value), 4) == round(float(std), 4)
```

This is **semantically exact** for every real league and **immune to float32 drift**. (A plain
`_TOL = 1e-6` also works — 1.49e-9 ≪ 1e-6 ≪ 0.01, the smallest real deviation — but rounding states the
intent instead of picking a magic epsilon. Either is fine; rounding is preferred.)

**Guard against over-loosening — this is the real risk of the fix.** A genuinely custom league
(`rush_yd = 0.11`, say) deviates by **0.01** — seven orders of magnitude above the drift. It must
*still* classify `custom`. Assert this.

**Also audit, don't assume:**
- `grep` **every** use of `_TOL` in `_scoring.py` — fix each, or justify leaving it.
- **`_nonzero(value)`** on the bonus / `_fd` keys: can a drifted *zero* (e.g. `1e-9`) read as non-zero
  and force `custom`? Check and harden the same way.
- `recompute_custom_points`' `w_custom − w_std` delta on a drifted weight is ~1e-9 ⇒ contributes nothing.
  Confirm; don't change.

### The no-regression gate (this is the actual work)

The repo's existing discipline — `backtest_roster_shape.py`'s *"no-regression frame-equal"* — is the
model. **All of these must hold:**

1. `scoring_profile()` on the **live 2025 league** still returns **exactly `ppr`**.
2. `compute_projection_consensus.compute(2025)` reproduces the on-disk
   `projection_consensus_2025.parquet` **frame-for-frame**.
3. **Every downstream gate exits 0 with identical numbers:** `backtest_scoring_recompute`,
   `backtest_projection_consensus`, `backtest_production_vor`, `backtest_true_rank`,
   `backtest_positional_depth`, `backtest_bracket_sim`, `backtest_ros_outcome_shape`,
   `backtest_roster_shape`, `backtest_player_signal`.
4. **New unit tests** (network-free, in `backtest_scoring_recompute` or a sibling):
   - a **float32-drifted PPR** dict (`rush_yd = 0.10000000149011612`, …) ⇒ **`ppr`** *(the fix)*
   - a **float32-drifted half-PPR** dict ⇒ **`half`**
   - a **genuinely custom** dict (`rush_yd = 0.11`) ⇒ **still `custom`** *(the guard)*
   - a **TE-premium** dict (`bonus_rec_te = 0.5`) ⇒ **still `custom`** *(the guard)*

---

## Commit 2 — Re-select the corpus (**no re-crawl**)

`corpus_discovery.parquet` persists the raw `scoring_settings_json`. **Re-classify offline. Zero API
calls.** *(This is why persisting discovery was the right call in 0.5.)*

- Re-run `corpus/select.py` against the fixed classifier → regenerate `corpus_manifest.parquet`.
- **Restate the three numbers** in `STATUS.md`, replacing the buggy ones:
  1. **Matched crosstab, corrected**, per NFL season — **six seasons now, not four.**
  2. **Achieved season balance** post-filter, post-cap.
  3. **The corrected unscoreable rate** — recompute against the *true* 1,765-league custom pool, not the
     inflated 2,045. **Report the delta explicitly**, because the old 39.2% is now in STATUS and is wrong.
- **Propose the corrected split.** My prior, given six seasons and the recency skew:
  > **TRAIN 2020–2023 · DEV 2024 · TEST 2025** — temporal order preserved, and 2025 is the closest
  > analogue to the 2026 conditions the constants will actually face. 2020–21 are thin (~8 and ~16 after
  > the filter), so **use league-wise k-fold *within* the train seasons for hyperparameter selection**
  > rather than leaning on a thin season-wise dev. Both holdout axes, no wasted season.

**Also fix a reporting error from 0.5:** STATUS reports matched-per-season as **21/58/65/117** — those are
the *pre-filter, pre-cap **eligible*** counts. The manifest actually holds **16/45/58/60**. Report
**eligible** and **selected** as separate, labelled columns.

---

## Commit 3 — Test the §7 hypothesis, then docs

**Did the bug suppress §7 comparability on the real league?**

1. **Snapshot the current `manager_activity_2025.parquet`** before touching anything (you're about to
   overwrite it — it's replace-by-`owner_id`).
2. Re-run `sleeper.py fetch-manager-activity 2025` with the fixed classifier (~10 managers, cheap).
3. **Compare, per manager: `n_leagues` · `n_seasons` · `n_transactions` · `depth_tier`, before vs after.**
4. If comparability improved: re-run `compute_manager_features` and regenerate `manager_dossiers`
   (~$0.025). **A free quality win on a shipped read.**
5. If it didn't: say so plainly. The friend-group explanation stands and that's a real finding too.

Then: update `LEAGUE_CORPUS.md` + `SPIKE_CORPUS_FINDINGS.md` with a correction note (**don't silently
rewrite the old numbers — mark them corrected, with the reason**; the finding that the corpus caught a
live bug is itself worth preserving), and add the 0.6 entry to `STATUS.md` and `READ_BUILD_ORDER.md`.

---

## Out of scope

- **Extending** `_scoring` to handle first-down / threshold-yardage bonuses. **Quantify only.** That's a
  roadmap decision, not a fix to sneak in here.
- `league_id` / `scoring_key` keying — that's L0 (Session 1), and it consumes the corrected manifest.
- Any new corpus crawling.
- Any change to a transform's *math*.

---

## Definition of done

- The classifier is drift-proof; **all four guard tests pass** (drifted-PPR ⇒ `ppr`; genuinely-custom ⇒
  `custom`).
- **Every existing gate exits 0 with identical numbers**, and `projection_consensus_2025.parquet` is
  reproduced **frame-for-frame**.
- `corpus_manifest.parquet` regenerated with **six** seasons; `check_corpus.py` exits 0.
- The three numbers restated in STATUS (with the old ones marked corrected), and the split proposed.
- The §7 hypothesis is answered **either way**, with before/after numbers.

---

> ## Standing instruction, carried out of this session
> **A suspiciously clean zero is a bug until proven otherwise.**
> Session 0.5 found "0 matched leagues in 2020 *and* 2021" — a hard zero across 258 leagues — and
> recorded it as a fact, then designed the train/test split around it. **Two seasons of corpus were
> nearly thrown away because an implausible result wasn't challenged.** When a number comes back
> perfectly empty, perfectly full, or perfectly round: **go find the mechanism before you build on it.**
