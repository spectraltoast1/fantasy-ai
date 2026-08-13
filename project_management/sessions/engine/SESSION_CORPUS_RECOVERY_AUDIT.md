# Corpus recovery — PM audit

**Audited:** 2026-08-13 · **Report:** the recovery session's report · **Brief:**
`SESSION_CORPUS_RECOVERY.md` · **Range:** `7c8ac11..563931d` (+ merge `3f22931`) ·
**Verdict: ENDORSED.** Two findings, one worth a follow-up chip, neither blocking.

The reconstruction is sound, the verdict labels are honest, and **the "zero residue" claim survives
an independent re-derivation** — including in a direction the report did not check.

---

## Verified independently — recomputed, not read from the report

| claim | verified |
|---|---|
| 271 rows | ✅ |
| strata 221 / 48 / 2 | ✅ `matched` 221, `generalization` 48, `mine` 2 |
| generalization "8 in every one of six seasons" | ✅ 2020–2025 all exactly 8 |
| **all 271 harvested carry `filter_result: "pass"`** (the brief's ASSERT) | ✅ zero fails |
| `divisions ≥ 2` → 25 division leagues | ✅ `has_divisions` true on exactly 25 |
| `corpus_two_way_flags` 10 rows | ✅ |
| `corpus_discovery` absent, **not an empty file** | ✅ genuinely not on disk |
| all corpus files now tracked in git | ✅ 4/4 in `git ls-files` |
| `.git/info/exclude:9` was the operative ignore rule, not `.gitignore` | ✅ `application/data/snapshots` is in `info/exclude` |

## The reconciliation — and a correction to MY number, not Code's

I re-derived both directions of the manifest↔ledger difference:

```
manifest distinct (season, league_id)  271
ledger   distinct (season, league_id)  276
shared                                 270
manifest − ledger  =  1   (2024, '1132400260048977920')   ← the predicted is_mine 2024 gap
ledger   − manifest =  6   ALL of them league_id = None
```

**The six "extra" ledger rows are not leagues.** Every one is a `None` league_id — one per season —
i.e. the ledger's **canonical, non-league-scoped** rows. Subtract them and the ledger holds exactly
**270** real league-seasons, precisely as the report claims.

**So the residue is genuinely zero, and the error was mine.** I told Code to explain "5 in the ledger
beyond the manifest." That came from my own raw count of 276 distinct pairs, which silently swept in
the canonical rows. Code's 270 was right and my 276 was a measurement artifact — I counted a set
without checking what was in it, which is the same shape as every other mistake I have made on this
project. **Code answered the question I should have asked instead of the one I did.**

`check_predictions` FAILING with exactly its one known red is treated as the **correct** outcome,
because green would have meant the reconstruction dropped the is_mine 2024 row. Using a known failure
as a positive oracle is the sharpest single move in this report.

---

## Finding A — the blunted gate is recoverable, and shouldn't be left dead

The report declares it plainly, which is why this is a follow-up and not a fault:

> *"Omitting the ~41 excluded rows cost a real tooth. `check_corpus`'s filter pass-rate now reads
> `100.0% over 269` instead of `86.8% over 310`. It still passes but it no longer detects anything
> and shouldn't be read as evidence."*

Confirmed: the restored manifest is **100% `pass`, 100% `scoreable`** — no excluded rows at all. So
the original file physically carried ~312 rows (271 selected + ~41 excluded); the restoration carries
the 271. **It is a faithful restoration of the selected population, not of the file** — which is
exactly why `CONSISTENT` rather than `EXACT` is the right label, and the labelling is correct.

**But the inputs to restore those rows exist, and the session already derived the split** — the report
does the arithmetic itself (`68 fails = 41 excluded + 27`), and `corpus_filter_cache.json` holds all
68 with their `filter_reason`. So this leaves a **permanently tautological gate** in a project whose
central discipline is that a gate must bite. A check that reads `100.0%` and can never read anything
else is worse than a missing check, because it appears in reports as evidence.

**Declaring a blunted gate is not the same as restoring it.** Recommend a small follow-up: add the ~41
excluded rows back from the filter cache and confirm `check_corpus` returns to `269/310 = 86.8%`
against the Session-0 reference of 87.0%. Not urgent, but it should not be left as the permanent state.

## Finding B — `selected_at` now asserts the corpus was selected today

Every one of the 271 rows carries `selected_at: 2026-08-13T20:48:22+00:00`. The corpus was selected
**mid-July**; the surviving inputs are dated Jul 13 and Jul 15.

That column now says the reconstruction date, and its name says selection date. The file has become
self-describing as a **fresh selection** — which is precisely the confusion this entire session was
built to prevent. *Regenerating and reconstructing are different operations*, and the manifest's own
metadata now claims the wrong one. It also erases the last trace of the corpus's true vintage.

**Do not fabricate a precise July timestamp** — that trades one wrong value for another. Either write
the known selection window with its imprecision visible, or leave the value and **document in the file
and in STATUS that `selected_at` on the restored manifest is the reconstruction timestamp, not the
original selection date.** As it stands, a future reader takes a false fact from a column that looks
authoritative — the same failure mode as the `posture.js` docstring and the Fly machine count.

---

## Assessed and agreed — no action

- **`league_format` NULL on 36 of 48 generalization rows.** Verified the nulls are confined to that
  stratum (`matched` and `mine` are complete). Refusing to default it is **correct**: 7 leagues known
  to be keeper/dynasty also lack the key, so the obvious default would have provably misclassified
  them. Absence reported, not fabricated. Since `settings.type` was never persisted, this is an
  irreducible offline gap — more evidence for `CONSISTENT` over `EXACT`. The offered 36-call top-up is
  optional; nothing structural depends on the column.
- **`corpus_discovery` left absent.** Correct, and executed exactly as briefed — the file is genuinely
  not on disk rather than empty, so it fails loudly instead of reading as a complete crawl.
- **Zero Sleeper calls.** The core requirement of the whole approach, met.
- **`two_way_flags.SEASONS` stops at 2025** — a forward-looking gap found incidentally: a 2026 league
  gets an empty reference by construction and a two-way player goes unflagged, silently. Real, and it
  bites at **Gate A**. Correctly chipped rather than fixed here.
- **The mechanical traps** (`info/exclude` vs `.gitignore`; data committable only from main because a
  worktree's `snapshots/` is a symlink git won't descend; `worktree-close.sh --merge` half-landing on a
  stale 0-byte `HEAD.lock`) all match what this PM session hit independently tonight.

## Verdict

**Endorsed.** Three artifacts, three different words — `EXACT`, `CONSISTENT`, `LOST` — for three
genuinely different epistemic states. That precision is the thing this project has been reaching for
all along, and it is the reason this restoration can be trusted rather than merely accepted.
