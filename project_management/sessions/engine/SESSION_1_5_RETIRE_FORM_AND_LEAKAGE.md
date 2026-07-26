# Session 1.5 — Retire `team_form` and `team_leakage`

**Hand this file to Claude Code as the session brief.**

**Type:** deletion / scope correction · **Commits:** 3
**Reads first:** `CLAUDE.md` · `DECISION_READS.md` · `PRODUCT_ROADMAP.md` (design law 1)
**Do before:** the corpus harvest — otherwise both get computed **276 times** for reads that don't exist
**Front-end track:** currently idle. This session owns `queries.js` / `db.js` for its duration.

---

## Why (record this — it's the point of the session)

Both entities are **fully orphaned**. Three independent confirmations:

1. **Neither appears in `DECISION_READS`.** The spec is §1–§7 and neither is one of them.
2. Their only consumers — `TeamPanel.jsx`, `LeaguePanel.jsx` — are **not imported by `App.jsx`.** They are
   pre-Gridiron legacy.
3. The `queries.js` seam functions that read them — `loadPowerRankings`, `loadTeamDetails`,
   `loadTeamRosters` — are imported by **nobody**.
   *(Careful: `loadTeamDetail` — **singular** — IS live. Different function. Do not touch it.)*

They are still computed on every run and still shipped to the browser.

### `team_leakage` — retired on principle, not just for tidiness

It graded lineup decisions against **realized points**. So it produced advice like *"start the waiver
fringe player over your stud — he's outscoring him"*, when the truth was a below-average week from the stud
and an above-average week from the fringe guy.

That is **design law 1, violated at the concept level**:

> *"Grade process, not outcome. A bad result from a sound decision is not an error, and saying it is
> teaches the exact recency/spike bias we're fighting."*

Worse than useless — it actively coached the exact error listed in `Error_Mapping.md` under START/SIT
(*"starting a player based off a spike week"*). The `COACHABLE_RATE_MARGIN` split was an attempt to patch
this with season rates; it can't work, because a fringe player's season rate can beat a stud's over a small
sample and that is still noise. **No constant fixes an outcome-graded read.**

### `team_form` — retired as noise
An EWMA "heating up / cooling off" team trend. Close to the recency bias `Error_Mapping.md` exists to fight.

### ⚠️ The concept is retired, not the idea — record this so nobody rebuilds the same mistake

Leakage was built in **Phase 0/1, before the projections substrate existed.** Realized points were the only
"truth" available, so it *had* to be outcome-graded. `projection_consensus` did not exist yet.

**A legitimate future read exists and is different in kind:** grade a start/sit decision against **the prior
that was available when the decision was made** ("you started A when B was projected higher on Sunday
morning") — never against what happened next. **That is now buildable and wasn't before.** Out of scope
here. **Write it down** so the reasoning survives the deletion.

---

## ⚠️ Two landmines — read before deleting anything

Both are functions **leakage originally authored** that are now **load-bearing elsewhere.** A naive
"delete everything leakage touched" breaks the §4/§5 reads *and* the Matchups tab.

| Keep | Where | Now used by |
|---|---|---|
| `expand_slots` · `optimal_lineup` · `position_pools` | `transforms/_analytics.py` | `compute_production_vor` · `compute_true_rank` · `compute_bracket_sim` + their gates |
| `expandSlots` · `optimalLineup` | `frontend/src/queries.js` | `teamProjections()` → **live Matchups slate + detail** |

**These already live outside leakage.** They were lifted out in an earlier refactor. **Do not delete them.**

---

## Commit 1 — Backend

**Delete:**
- `transforms/compute_team_form.py`, `transforms/compute_team_leakage.py`
- `data_layer`: `_team_form_path`, `write_team_form`, `read_team_form`, `_team_leakage_path`,
  `write_team_leakage`, `read_team_leakage`
- the persisted parquets (all leagues)

**Update (do not delete):**
- **`backtest_roster_shape.py`** — it imports `compute_team_leakage as leak` and frame-checks leakage as one
  of its four no-regression targets. **Drop leakage from the target list; keep the other three**
  (`production_vor`, `true_rank`, `positional_depth`) and keep the synthetic-superflex check.
- **`backtest_l0_keying.py`** — remove the `team_form` / `team_leakage` entities from its keying check.

**Verify `_analytics.py` is untouched.** Byte-compile clean; no dangling imports anywhere.

## Commit 2 — Front end

**Delete:**
- `TeamPanel.jsx`, `LeaguePanel.jsx` (orphaned components)
- `queries.js`: `loadPowerRankings`, `loadTeamDetails`, `loadTeamRosters`, plus `SQL_TEAM_FORM`,
  `SQL_TEAM_LEAKAGE`, `SQL_TEAM_EFFICIENCY` and any `computeForm` / `computeLeakage` / assemble helpers
  **that nothing else calls**
- `db.js`: the `team_form` + `team_leakage` `registerParquet` lines
- the two `public/data/` symlinks

**KEEP — verify by grep before deleting anything adjacent:**
- `queries.js` `expandSlots` / `optimalLineup` (used by `teamProjections`)
- `loadTeamDetail` (**singular** — live)
- `readiness.jsx`, `posture.js`, `posColors.js` — check whether any reference is a genuine dependency or
  just a substring match on "form" (e.g. `format`, `inform`). **Grep, don't assume.**

## Commit 3 — Docs

- **`DECISION_READS.md`** — add a short "Retired reads" note: `team_leakage` (outcome-graded ⇒ law-1
  violation; the *process*-graded version against `projection_consensus` is legitimate future work) and
  `team_form` (recency noise). **Preserve the reasoning, not just the fact.**
- **`TECHNICAL_ARCHITECTURE.md`** — remove both from the folder structure / derived list; add to **Known
  Scope Exclusions**; remove their tuning constants from the "future config seed" list (`HALF_LIFE_WK`,
  `DIRECTION_BAND`, `MIN_GAMES`, `COACHABLE_RATE_MARGIN`, `HABITUAL_STARTER_THRESHOLD`).
- `STATUS.md`, `READ_BUILD_ORDER.md`.

---

## Acceptance gates

1. **Every remaining gate exits 0 with identical numbers.** `backtest_player_signal`,
   `backtest_projection_consensus`, `backtest_production_vor`, `backtest_true_rank`,
   `backtest_positional_depth`, `backtest_bracket_sim`, `backtest_ros_player_band`,
   `backtest_scoring_recompute`, `backtest_roster_shape` (**leakage removed from its targets**),
   `backtest_l0_keying`, `backtest_manager_features`, `check_market_vor`, `check_corpus`, the `ai/check_*`.
   **Deleting a dead read must not move a single live number.**
2. **Front end renders identically.** Load it, walk **all five** surfaces (Players · Dossier · Teams ·
   League · Matchups), **take a screenshot and look at it.** Zero console errors. **Matchups especially** —
   it depends on the JS helpers leakage authored.
3. **No dangling references:** zero imports of the deleted modules/functions; zero `registerParquet` of a
   file that no longer exists; no orphaned `public/data` symlink.
4. `python3 -m compileall application` clean.

---

## Out of scope

- Building the process-graded decision-review read. **Record the idea; don't build it.**
- Any change to a surviving read's math.
- Harvesting, the ledger, the scorer.

---

## Definition of done

- Both entities gone from transforms, `data_layer`, disk, `db.js`, `queries.js`, and the docs.
- **`_analytics.py` and `queries.js`'s `expandSlots`/`optimalLineup` untouched and still working.**
- All gates green with **identical numbers**; all five surfaces screenshot-verified.
- The **reasoning** for the retirement is recorded in `DECISION_READS.md` — including that the
  process-graded version is legitimate future work.

---

> ## Standing instructions (carried forward)
> 1. **A suspiciously clean zero is a bug until proven otherwise.**
> 2. **A refactor that changes a number is a bug, not a refactor.** Prove equivalence.
> 3. **If the fix wants to touch `queries.js` or a view component, the seam has leaked.** *(This session is
>    the exception — it owns the seam. Normal service resumes after.)*
> 4. **Report, don't tune.**
> 5. **NEW — Deleting dead code must not move a live number.** If a gate shifts, you removed something that
>    was load-bearing. Stop and find it.
