# Session 3d — The Generalization Robustness Pass (compute the spine on the 48 exotic leagues; find the shape bugs)

**Hand this file to Claude Code as the session brief.**

**Type:** robustness compute + shape-bug fixes · **Commits:** 3 (bounded — catalog · fix · gate; **split if the failure inventory is large**)
**Reads first:** `CLAUDE.md` · `LEAGUE_CORPUS.md` (the shape matrix) · `SESSION_3B_MATCHED_SPINE.md` (the spine + the threading it built) · `IMPROVEMENT_LOOP.md` (session 6 — "fix what the corpus broke")
**Blocks:** nothing hard — the generalization stratum is a **`never_tune` robustness set**, not a tuning input. Its value is *certifying* the any-league code, not feeding the Tuner.
**Prior:** 3b (threaded + computed the matched spine), 3c (`*_exp` backfilled NFL-globally — generalization gets §1 Quality for free). **Assumes the cleanup pass has landed** (value-based determinism gates; `reg_end` sanity floor) — if not, note it.

---

## Why this exists

3a harvested all 271 leagues' raw + join; 3b computed the 5-read spine for the **matched** 221. The **48
generalization leagues** still have **no spine** (verified: joins 48/48 present, `production_vor` 0/48). They
are the whole reason the generalization stratum exists — they carry the shapes the any-league code has **only
ever seen synthetically**:

| Axis | Generalization spread (verified 2026-07-15) |
|---|---|
| QB structure | **21 superflex** · 27 1QB |
| Divisions | **14 division leagues** · 34 flat |
| Scoring | ppr 27 · half 13 · **8 distinct custom `cust-` keys** |
| Size | 4 · 6 · 8 · 10 · 12 · 14 · 16 · **18** (2/2/9/10/20/2/2/1) |

These hit the code paths `LEAGUE_CORPUS` and `TECHNICAL_ARCHITECTURE` flag as **gated on synthetic configs
only**:

- **`_analytics.position_pools` — superflex.** The SF pool path "has never seen a real league."
- **`compute_bracket_sim._seed_table` / `_division_map`** — division seeding is "unvalidated on real data;
  `_division_map` currently returns `None`."
- **`_scoring.recompute_custom_points`** — rejects first-down / threshold bonuses; some of the 8 custom keys
  may trip it.
- **`lineup_slots`** — exotic lineups (superflex QB slot, 2-TE, 3-WR/2-FLEX, 18-team pools).

> **This session WILL find bugs. That is the point, not a risk** — infinitely better in a July backfill than
> in a stranger's live superflex league in week 6. `never_tune` means these leagues **never** enter the tuning
> set; they only prove the any-league generalizations survive real shapes.

---

## Commit 1 — Run the spine across the 48; catalog every failure by mechanism

- Drive `compute_spine` (from 3b) over the **generalization** stratum (48 leagues), same dependency order
  (`production_vor → { true_rank · positional_depth · bracket_odds } · player_signal`), league-keyed,
  idempotent/resumable. Reuse the harvest-time integrity flags (a degenerate league is **flagged, not
  silently dropped**).
- **Produce a failure inventory, not a pile of stack traces.** For every league that fails, record the
  **mechanism** (superflex pool / division seeding / custom scoring / lineup shape / other) and the smallest
  reproducing case. Leagues that compute cleanly are done — persist them.
- **⚠️ Bound the session.** If the inventory is small (a few mechanisms), proceed to Commit 2. **If it's large
  or spans many independent mechanisms, STOP after cataloging** and we scope the fixes as their own
  sessions — do not cram unbounded debugging into one worktree. The catalog itself is a valid deliverable.

## Commit 2 — Fix the shape bugs by mechanism — **without moving the matched spine**

- Fix each mechanism at its root (the shared any-league function), **proven against the real failing
  generalization league** — not a synthetic stand-in.
- **THE non-negotiable discipline: a fix to shared code must leave the matched (221) + is_mine spine
  byte-identical.** `position_pools`, `bracket_sim`, `_scoring`, `lineup_slots` are used by *every* league —
  a superflex fix that changes a 1QB pool, or a division fix that moves a flat-league seed, is a regression,
  not a fix (standing instruction 2). Re-run the matched + is_mine spine after each fix and prove **value-identical**.
- Where a shape is genuinely unsupportable (e.g. a custom scoring rule `_scoring` legitimately rejects),
  **flag the league with a named reason and exclude it** — a documented, mechanism-named exclusion, never a
  silent null (standing instruction 1).

## Commit 3 — Re-run the generalization spine + gate + docs

- Compute the full generalization spine (the now-fixed leagues + the cleanly-passing ones).
- **Extend the gate** (`check_spine`, or a generalization arm) to the 48: spine present for every
  non-flagged generalization league; cohort + probability integrity (playoff mass = slot count — now on
  **real division brackets**, the first true test); determinism (**value-based**, per the cleanup pass);
  `is_two_way` rides; and **`never_tune` is still true for every generalization row** (they must not have
  leaked into the tunable set). Prove the gate bites.
- **Prove matched is untouched** — the whole matched spine value-identical to its 3b/3c state (the shared-code
  fixes moved nothing there).
- **Docs:** `STATUS.md`, `TECHNICAL_ARCHITECTURE.md` (the any-league paths are now validated on real
  superflex / division / custom shapes — retire the "synthetic-gated only" caveats where earned; keep them
  where a mechanism was flagged-out), `READ_BUILD_ORDER.md`, `LEAGUE_CORPUS.md`. **The corpus spine is now
  complete across both strata — scope the L2 ledger in the closedown.**

---

## Acceptance gates

1. **Failure inventory produced** in Commit 1 (mechanism-named), and the session was bounded accordingly.
2. **Coverage:** every non-flagged generalization league has all 5 reads; flagged leagues carry a named
   mechanism (not a silent gap).
3. **Matched untouched:** the matched (221) + is_mine spine is **value-identical** to its pre-3d state after
   every shared-code fix.
4. **Real-shape integrity:** `bracket_odds` playoff mass = slot count on **division** leagues; superflex pools
   resolve; custom-key spines compute or are flagged.
5. **Determinism (value-based):** twice-compute value-identical; league-stable `bracket_sim` seed.
6. **`never_tune` intact:** every generalization row stays `never_tune = true` and is excluded from any
   tunable set.
7. **Seam held** — `queries.js` / views untouched.

---

## Out of scope

- **The L2 ledger / L3 scorer / L4 tuner.** 3d completes the corpus spine; it does not grade or tune. Report,
  don't tune. (Scope the ledger next — the corpus is now whole.)
- **Re-tuning the any-league constants** to "fix" a shape — a fix is a *correctness* fix (the code crashed or
  produced a nonsense read), never a re-fit. If a shape reveals a constant is mis-calibrated, **report it**;
  the Tuner owns re-fitting, and never on `never_tune` data.
- **Re-selecting the corpus / recomputing the substrate** (frozen; the 8 custom keys' substrate is built).
- **The matched degenerate league / `xtd`** — handled in the cleanup pass, not here.

---

## Definition of done

- The 48 generalization leagues' 5-read spine is computed (or each failure flagged with a named mechanism),
  league-keyed, idempotent.
- The shape bugs are fixed at the root, **each proven not to move the matched/is_mine spine.**
- The gate covers both strata with teeth; **matched value-identical**; `never_tune` intact.
- Corpus spine **complete across matched + generalization** — the L2 ledger scoped in the closedown.

---

> ## Standing instructions
> 1. **A suspiciously clean zero is a bug until proven otherwise.** *(A superflex league whose QB pool comes
>    back empty, a division league with all-zero seeds — flag the mechanism, don't ship the zero.)*
> 2. **A refactor/fix that changes a number is a bug** — prove equivalence. *(A shared-code shape fix must
>    leave every matched + is_mine number byte-identical; the ONLY new numbers are the generalization spine.)*
> 3. **If the fix wants to touch `queries.js` or a view, the seam has leaked.**
> 4. **Report, don't tune.** *(A shape may reveal a mis-calibrated constant — surface it; the Tuner re-fits,
>    never on `never_tune` data.)*
> 5. **Deleting dead code must not move a live number.**
> 6. **A plausible explanation is not a diagnosis** — name the mechanism, or write UNKNOWN and escalate.
>    *(Every failing league gets a named mechanism in the inventory — superflex pool / division seed / custom
>    scoring / lineup shape — not "it errored.")*
> 7. **"The artifact exists" and "the consumer uses it" are two different gates.** *(`bracket_odds` present on
>    a division league ≠ its playoff mass equals the real slot count. Gate the property.)*
> 8. **Persist the substrate; never re-derive from a moving source.** *(The spine reads the frozen substrate +
>    3a's persisted join; it computes deterministically, adds no fetch.)*
