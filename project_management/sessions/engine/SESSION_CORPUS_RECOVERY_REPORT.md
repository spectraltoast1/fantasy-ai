# Engine · Corpus recovery — REPORT

**Ran 2026-08-13.** Brief: [`SESSION_CORPUS_RECOVERY.md`](./SESSION_CORPUS_RECOVERY.md).

## Verdict

| artifact | outcome | verdict |
|---|---|---|
| `corpus_two_way_flags.parquet` | restored, 10 rows | **EXACT** |
| `corpus_manifest.parquet` | restored, 271 rows | **CONSISTENT** (not identical — see §4) |
| `corpus_discovery.parquet` | **LOST, DELIBERATELY NOT RECONSTRUCTED** | — |

Restored by **offline reconstruction from surviving artifacts, with zero Sleeper calls.** Nothing was
re-crawled and nothing was re-selected, so the manifest still names the population the immutable L2
ledger was derived from rather than a fresh August-2026 corpus wearing its name.

---

## §0 Exact restore — exhausted before anything else ran

The only APFS local snapshot is `com.apple.TimeMachine.2026-08-13-124631.local`, ~14 h **after** the
22:25 overwrite. The Time Machine destination ("Vision") is detached and its only backup is
2026-08-13, the first since Jan 2026 — i.e. before the corpus existed (created Jul 13–15). No stray
copy exists anywhere on disk (`find` over `/Users`, `mdfind`). **No backup can exist in the window.**

Both regeneration inputs were copied off-tree first, checksum-verified, before any command ran:

```
corpus_crawl_state.json   212,974 B  sha256 6f0da690719fa46c…
corpus_filter_cache.json   56,402 B  sha256 8b0db425019283b2…
→ /Users/willdaniel/Documents/corpus-survivors-backup-2026-08-13/  (+ a second copy in the session scratchpad)
```

`leagues.parquet` was later added to that backup: it turned out to be the **only surviving witness for
`league_format`** (§4), and `league_registry.build()` would have overwritten it.

---

## §1 The reconciliation — every delta explained, zero residue

| step | n | why the delta |
|---|---|---|
| judged (`corpus_filter_cache.json`) | **427** | league-seasons — every league appears in exactly one season, so `league_id` is 1:1 with a league-season |
| passed the filter | **359** | 68 rejected, each carrying a recorded `filter_reason` |
| harvested (real) | **271** | **88** passed but were never selected — see below |
| raw dirs on disk | **272** | 271 real + `DEMO-2025`, the generated demo clone (`data_layer.SYNTHETIC_LEAGUE_IDS`) — never crawled, never judged, never a manifest row |
| the lost manifest (selected) | **271** | matches exactly |
| L2 ledger league-seasons | **270** | 271 − the is_mine 2024 slice `1132400260048977920` (spined for the demo, never backfilled) |

**Will's ASSERT holds.** All 271 harvested league-seasons are present in the filter cache and **every
one carries `filter_result: "pass"`. Zero fails.** Nothing to escalate. The single harvest dir absent
from the cache is `DEMO-2025`, correctly so.

**The 88, and the 41 excluded — the arithmetic closes exactly.** The filter cache accumulates across
every `select.py` run ever made (it is loaded, added to, and flushed — never cleared), while the final
manifest holds only what the last run filtered. The lost manifest was **312 rows** (271 selected + 41
excluded, per [`engine-read-build-order.md:131`](../../context/appendices/engine-read-build-order.md)):

```
427 judged  −  312 in the final manifest  =  115 residue from earlier runs
115 residue =  88 passed-but-not-in-the-final-manifest  +  27 failed-but-not-in-it
68 fails    =  41 excluded (in the manifest)            +  27 (residue)      ✓
```

Independently confirmed by `check_corpus` itself: the original manifest's filter-honesty line would
have read `269/310 = 86.8%` against the Session-0 reference of 87.0%. That the two agree to 0.2 pp is
strong evidence the 312/41 split is right.

### Two numbers in the brief were wrong

1. **The ledger holds 270 league-seasons, not 276.** The 276 counts six phantom `(season, null)`
   pairs: 158,086 `ros_player_band` claims are **player-level and league-agnostic**, so their
   `league_id` is null by design (`data_layer.read_predictions` documents this). Measured twice
   independently. The only `276` in the codebase is a stale Session-2-era projection at
   `transforms/audit_join.py:43`, not a measurement. So the brief's delta #3 ("5 beyond the manifest,
   explain which") is really **1 short of it**, and already explained by the known red.
2. **88 passed but were never harvested, not 87.** `359 − 271`, not `359 − 272`; `DEMO-2025` is not in
   the pass list because it was never judged.

Both corrections make the reconciliation cleaner, not messier.

---

## §2 Independent corroboration of the restored population

The reconstruction was not merely internally consistent — it was checked against artifacts it did not
derive from:

- **The immutable L2 ledger.** 270 league-seasons compared on `(season, league_id, scoring_key)`:
  **0 mismatches.** `ledger − manifest = 0` (a strict subset); `manifest − ledger = 1`, and that one is
  exactly `(2024, 1132400260048977920)` — the predicted known red.
- **Strata.** Land on exactly **221 matched / 48 generalization / 2 mine**, from three independent
  directions: the 235 format-known leagues classify to 221 + 12 + 2; the 36 format-unknown are
  generalization-eligible on shape alone; 12 + 36 = 48. `reconstruct_manifest.run()` **refuses to
  write** unless it hits these counts.
- **Divisions.** `divisions >= 2` yields exactly **25**, matching the documented 25 real corpus
  division leagues (11 matched + 14 gen).
- **Per-season shape.** Matched `{2020: 9, 2021: 15, 2022: 24, 2023: 53, 2024: 60, 2025: 60}` — 2024/25
  sit exactly on `MATCHED_CAP_PER_SEASON = 60`. Generalization is **8 in every one of the six seasons**,
  exactly `GEN_PER_SEASON_TARGET`, with 8 distinct custom keys (cap 12) — the Session-2.5
  season-collapse fix, intact.
- **`check_matchup_result --full-corpus`** swept **271 league-seasons and found exactly the four
  allowlisted ties** — an allowlist that is hardcoded and manifest-independent.

---

## §3 Gate results

| gate | before | after |
|---|---|---|
| `check_corpus` | FAIL — 2 ✗ (both season floors) | **PASS** (exit 0), `strata: {matched: 221, generalization: 48, mine: 2}` |
| `check_harvest` | **crashed** `ColumnNotFoundError:190` | **PASS** (exit 0) — check 5 green (10 rows; `is_two_way` present 271/271, never null, correctly applied) + all 7 prove-bites |
| `check_spine` | **vacuous PASS at 0 leagues** | **PASS at 269 leagues**, 269 present + 0 flagged-degenerate |
| `check_predictions` | **crashed** `ColumnNotFoundError:150` | **FAIL with exactly one red** — the known is_mine 2024 gap |
| `check_matchup_result --full-corpus` | FAIL (0 targets) | **PASS** — 271 swept, 4 changed |

Three notes the next session should not have to rediscover:

- **`check_spine`'s green was vacuous before this session and would have been believed.** Its results
  list is non-empty only because of its own prove-bites, so on a 0-row manifest every real check
  passed over an empty set and it printed `VERDICT: PASS`. **Read `len(tgts)` in the header line, not
  the VERDICT** — it now reads 269.
- **`check_predictions` keeps its one known pre-existing red, and that is the correct outcome.** It
  could not be *observed* before this session (the gate crashed first), so the baseline was
  re-measured, not assumed. Had it gone green, that would have been a **regression disguised as a
  fix** — it would mean the reconstruction had dropped the is_mine 2024 row.
- The `Reconciled: … ✗` lines inside `check_harvest` are diagnostic prints from the join
  re-computation, not gate assertions. They are the documented deferred null-position/remainders
  class in `STATUS.md`, pre-existing and unrelated to this recovery.

---

## §4 What was NOT recovered — stated plainly

**`league_format`, and hence the format suffix of `shape_key`, for 36 of 271 rows (all generalization).**

Sleeper's `settings.type` was never persisted: `fetchers/sleeper.fetch_league_config` keeps an explicit
playoff-key allowlist that excludes it. Absence on disk is therefore **not** evidence of "redraft" —
`_manager.league_format(None)` returns `"redraft"` because *Sleeper* omits the key on a classic redraft
league, but our harvester drops it unconditionally. **Measured proof: 7 leagues known from
`leagues.parquet` to be keeper/dynasty also have no `type` key on disk**, so mapping absent → redraft
would provably have misclassified them. The stale Jul-14 `leagues.parquet` carries `shape_key`, whose
suffix is the format, and covers 235 of the 271; for the other 36 the column is left **NULL rather than
guessed**.

This costs nothing structural: all 36 are generalization-eligible on shape alone (superflex /
divisions / custom / exotic size — none of which consults format), no matched row is affected,
`check_corpus` applies the matched predicate only to matched rows, and `shape_key` is registry
metadata that nothing partitions on (`league_registry.py:54`; the derived layers key on `scoring_key`).
**A targeted top-up is available if wanted:** 36 `GET /league/{id}` calls would fill it, and because the
population is already pinned by the harvest, reading one attribute of 36 known leagues cannot change
which leagues are in the corpus. Not done here — it is network, and the session's mandate was offline.

**`selected_at`** is a wall-clock column and is lost for every row; the restore stamp is written
instead. This alone is why the manifest is **CONSISTENT, not EXACT**.

**The ~41 `excluded` rows are gone.** They were never harvested, so no persisted payload exists for
their classification columns. They were omitted rather than emitted with null classification — they
have zero consumers (`league_registry.py:91` filters `stratum != "excluded"`, `harvest.HARVEST_STRATA`
excludes them, no `check_corpus` assertion needs them), and a plausible-but-wrong row is exactly what
the absence-is-reported-never-fabricated rule forbids. **Declared consequence:** `check_corpus`'s
filter-honesty pass-rate now reads `100.0% over 269 filtered` instead of `86.8% over 310`. That tooth
is now vacuous. It is a *reported* number, not an assertion, so the gate still passes honestly — but it
no longer detects anything, and should not be read as evidence.

### `corpus_discovery` — LOST, DELIBERATELY NOT RECONSTRUCTED

`expanded_leagues` (725) ∪ `queue` (6,937) misses **320 of the 427 judged leagues**: the crawl state is
the *frontier as it stood at save time*, not a record of what was discovered. Reconstructing from it
would produce a table that is **wrong, not merely partial** — and because its only consumer is
`select.py`, a future re-selection would silently draw from a universe where
considered-and-rejected is indistinguishable from never-discovered. A re-crawl was equally rejected:
an August discovery table beside a July manifest asserts a provenance relationship that does not exist.

The damaged 135-byte 0-column husk was **deleted**, so `corpus_discovery_exists()` now returns `False`.
This matters beyond tidiness: while the husk existed, `discover.py` would have taken its **resume**
branch, skipping the 325 already-`visited` managers and then overwriting `corpus_crawl_state.json` at
its first 25-manager checkpoint — destroying the last surviving record of the July crawl.

> **Capability loss, stated up front:** corpus selection can no longer be re-run against the July
> universe. Any future re-selection begins with a fresh crawl and defines a **NEW** corpus — not a
> continuation of this one. `corpus_crawl_state.json` and `corpus_filter_cache.json` are now the
> authoritative surviving record of the July crawl, and are tracked in git as of this session.

---

## §5 The live degradation, closed — and a correction to the brief's diagnosis

Restoring the flags closes it: `audit_join._two_way_ids` now returns 1/1/3/1/4 ids for 2021–2025
(2020 legitimately has no material two-way player), so `weekly_refresh.py:166` no longer
short-circuits.

**Brief §3's diagnosis was wrong in a way that matters.** The no-op was *not* caused by the
skip-on-any-exception guard. `_two_way_ids` returns `set()` without raising (the file existed, and
`iter_rows` on a 0×0 frame yields nothing), and `weekly_refresh.py:166` short-circuits on
`if flag_ids and …`. The `except` never fired, so **there was no `skipped` log line at all** — the
refresh report was indistinguishable from a league with no two-way players. A session looking for that
breadcrumb would have found nothing and concluded the path was healthy.

**Forward-looking gap (not fixed here, out of scope):** `two_way_flags.SEASONS` stops at 2025, so a
2026 league advancing through `weekly_refresh` gets an empty reference by construction. Travis Hunter
(`12530`, 63.8 PPR as a 2025 WR/CB) is very likely still two-way in 2026 and would not be flagged.

---

## §6 Durability — the corpus dir is now tracked in git

`.gitignore` gains a carve-out (the blanket `application/data/snapshots/` exclusion stays; only
`corpus/` is un-ignored, and the four files are named individually so a *new* file there stays ignored
until someone decides it belongs). Total ~281 KB, frozen since mid-July, so no repo churn.

This is a principled exception to the SESSION_GUIDE rule against re-adding data files, not an erosion
of it: `player_id_map.parquet` and `nfl_stats_2025.parquet` are **runtime data** — large, regenerable,
constantly changing. These four are **frozen provenance**, closer to a lockfile, and they define the
population the immutable L2 ledger was derived from.

**Two mechanical findings for whoever does this next:**

- `.gitignore` was not the operative rule. **`.git/info/exclude:9` (`application/data/snapshots`)** is
  what actually ignored these paths — a per-clone, unversioned file. The carve-out in `.gitignore` is
  still correct and is what will work on a fresh clone, but on this machine the files had to be
  force-added (`git add -f`); once tracked, ignore rules no longer apply to them.
- **The data files can only be committed from `main`.** In a worktree, `application/data/snapshots` is
  a symlink created by `worktree-setup.sh`, and git refuses to descend past it
  (`fatal: pathspec … is beyond a symbolic link`). The code and doc commits are on the branch; the
  data-file commit is made in main after the merge.
