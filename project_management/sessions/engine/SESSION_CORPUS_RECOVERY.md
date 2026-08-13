# Engine · Corpus recovery — restoring the frozen manifest

**Written 2026-08-13.** **Status: DONE (2026-08-13) — restored by offline reconstruction.
Results, and three corrections to this brief, in [`SESSION_CORPUS_RECOVERY_REPORT.md`](./SESSION_CORPUS_RECOVERY_REPORT.md).
`corpus_discovery` is deliberately NOT restored.**
**Cause + the rule it bought:** `CODING_BIBLE` §5, prove-it-bites bullet.
**Blocked by this:** the engine-track gates (`check_corpus`, `check_harvest`, `check_spine`,
`check_predictions`). **NOT blocked:** the live site, and P5/S3.

---

## What happened

On **2026-08-13 at 02:25 UTC** (22:25 ET, 2026-08-12), a `check_store_boundary --prove-bites` run
overwrote three files in `application/data/snapshots/corpus/` with empty frames:

| file | was | now |
|---|---|---|
| `corpus_manifest.parquet` | the final frozen **271-league** manifest | **0 rows** (135 bytes) |
| `corpus_discovery.parquet` | the discovery table | **0 rows** |
| `corpus_two_way_flags.parquet` | the two-way flags | **0 rows** |

`--prove-bites` deliberately neuters the guard and drives every laptop-owned writer for real. A
throwaway season (`99998`) isolated the writers that take a season or an id; these three take **only a
dataframe**, so there was no throwaway target — their target *was* the real and only copy.

**Verified independently by the PM, 2026-08-13:** all three are 135 bytes at that mtime; they were
**never tracked by git** (`.gitignore:194` covers `application/data/snapshots/`); no other copy exists
anywhere in the repo tree.

## What survived — verified, not assumed

- **The whole L2 ledger is intact** — all 26 files, mtimes unchanged from July, including
  `center_gap` and `tune_proposals`. This is the irreplaceable artifact and it was untouched.
- **Both regeneration inputs are intact:** `corpus_crawl_state.json` (212,974 B, Jul 13) and
  `corpus_filter_cache.json` (56,402 B, Jul 15).
- `demo_manifest` (31 rows), `synthetic_catalog` (1), `leagues.parquet` (278) — intact.
- **The live site is unaffected.** It serves `league_catalog` from Postgres, built from
  `demo_manifest` + `synthetic_catalog`, neither of which moved.

## §0 — ORDER OF OPERATIONS. Do not skip.

1. **BACK UP THE TWO SURVIVING JSONs, off this folder, before running anything.** They are the
   regeneration inputs, they are untracked, and nothing currently protects them. If they go, so does
   the fallback. *(A full Time Machine backup ran 2026-08-13 — the first since Jan 2026, so the ledger
   and these two JSONs are now on a second physical device. Still take a working copy you can reach
   without a TM restore.)*
2. **Exhaust exact restore first.** APFS keeps hourly **local** snapshots even with no Time Machine
   disk attached, for roughly 24 hours — `tmutil listlocalsnapshots /`, and `tmutil destinationinfo`
   for a detached backup disk. **A byte-exact restore ends this session at step 2** and is strictly
   better than anything below, because it needs no defending.
3. Only if 1–2 fail: regenerate, then **reconcile** per §1. Regeneration without the reconciliation is
   not a recovery, it is a new manifest wearing the old one's name.

## §1 — The actual problem: three sources, three numbers

This is why this is a session and not a command. Measured 2026-08-13:

| source | count | what it is |
|---|---|---|
| the lost manifest | **271** league-seasons | per `STATUS` and `check_matchup_result` |
| `nfl_sleeper_weekly_joined/league/` | **272** dirs | everything ever joined |
| the **L2 ledger** (`predictions_2020..2025`) | ~~**276**~~ → **270** distinct `(season, league_id)` | everything ever predicted on |

> **⚠️ CORRECTED 2026-08-13 (measured twice, independently).** The ledger holds **270**, not 276. The
> 276 counts six phantom `(season, null)` pairs — 158,086 `ros_player_band` claims are **player-level
> and league-agnostic**, so their `league_id` is null by design. The only `276` in the codebase is a
> stale Session-2-era projection at `transforms/audit_join.py:43`, not a measurement. The ledger is a
> strict **subset** of the joins, and the whole three-way disagreement resolves with zero residue:
> `272 joins − 1 synthetic (DEMO-2025) = 271 manifest`, and `271 − 1 (the is_mine 2024 slice) = 270
> ledger`. Both subtrahends are already-documented entities.

**None of these is a drop-in oracle.** The ledger is the richest — it carries `league_id`, `season`
**and `scoring_key`**, so most of the manifest's likely content is independently attested for 276
pairs — but it is a *superset*, and a known pre-existing red (`check_predictions`: the is_mine **2024**
slice is spined for the demo but never backfilled) proves the relationship is not 1:1 in either
direction.

**The deliverable is an explained reconciliation, not a matching row count.** For every league-season
in the symmetric difference of those three sets, say which source it is in, which it is missing from,
and why that is correct. A regenerated manifest that happens to total 271 without that account has not
been recovered — it has been guessed.

**The one genuine reason for optimism:** `select.py` documents the filter cache as existing precisely
so *"a re-run never re-hits Sleeper for a league already judged; verdicts are deterministic."* If that
holds, regeneration should be **exact**, and the reconciliation becomes a proof rather than a repair.
Test that claim; do not assume it.

## §2 — Why a differing manifest is a real problem, not a cosmetic one

The frozen corpus is the population the **immutable L2 ledger** was derived from. If the regenerated
manifest differs from the one the ledger was built against, then the ledger's reproducibility claim is
broken — and that claim is what the whole engine-honesty argument rests on. **A difference is a finding
that stops the session and gets escalated to Will. It is never quietly accepted.**

## §3 — One live degradation to close

> **⚠️ CORRECTED 2026-08-13 — the diagnosis below names the wrong guard.** The no-op was real, but the
> `except` **never fired**: `audit_join._two_way_ids` returns `set()` without raising (the file existed,
> and `iter_rows` on a 0×0 frame yields nothing), and `weekly_refresh.py:166` short-circuits on
> `if flag_ids and …`. So there was **no `skipped` log line at all** — the refresh report was
> indistinguishable from a league with no two-way players. A session hunting for that breadcrumb would
> have found nothing and concluded the path was healthy. Closed 2026-08-13 by restoring the flags.

`weekly_refresh`'s `is_two_way` re-apply reads the flags table and is wrapped in a
**skip-on-any-exception** guard, so with `corpus_two_way_flags` at 0 rows it now **silently no-ops**.
It will keep silently no-opping until the flags are restored. Restoring that file closes it; while it
is open, any league advanced through `weekly_refresh` carries no two-way flags.

---

## The brief to paste to Code — corpus recovery

```
Goal: restore application/data/snapshots/corpus/{corpus_manifest,corpus_discovery,corpus_two_way_flags}
.parquet, which a check_store_boundary --prove-bites run overwrote with empty frames on 2026-08-13.
Read first: sessions/engine/SESSION_CORPUS_RECOVERY.md (this brief), context/CODING_BIBLE.md (§5's
prove-it-bites rule, which this incident bought), context/appendices/store-boundary.md.

STOP AND CONFIRM WITH WILL BEFORE REGENERATING. Exact restore from an APFS local snapshot beats
regeneration and needs no defending. Do not start until Will confirms that avenue is exhausted.

0. FIRST, before running anything at all: copy corpus_crawl_state.json (212,974 B) and
   corpus_filter_cache.json (56,402 B) somewhere outside application/data/. They are the regeneration
   inputs, they are untracked, and nothing protects them. Verify the copies by checksum.

1. REGENERATE via the documented path. select.py states the filter cache exists so that "a re-run never
   re-hits Sleeper for a league already judged; verdicts are deterministic." TEST THAT CLAIM rather
   than assuming it — report whether the run hit Sleeper at all, and how many verdicts came from cache.

2. RECONCILE — this is the deliverable, not the row count. Three independent sources disagree:
     lost manifest              271 league-seasons (per STATUS / check_matchup_result)
     joined league dirs         272
     L2 ledger predictions      276 distinct (season, league_id)   <- also carries scoring_key
   For every league-season in the symmetric difference, state which sources hold it, which do not, and
   why that is correct. Note the known pre-existing red (check_predictions: the is_mine 2024 slice is
   spined for the demo but was never backfilled into the ledger) — it proves the relationship is not
   1:1, so do not assume a clean superset/subset story in either direction.

3. IF THE REGENERATED MANIFEST DIFFERS from what the ledger and harvest imply: STOP AND ESCALATE. The
   frozen corpus is the population the immutable L2 ledger was derived from, so a difference breaks the
   ledger's reproducibility claim — the thing the engine's honesty argument rests on. Never paper over
   it, never "reconcile" by editing the manifest to match.

4. RESTORE corpus_two_way_flags too, and confirm it closes a live degradation: weekly_refresh's
   is_two_way re-apply reads that table behind a skip-on-any-exception guard, so at 0 rows it SILENTLY
   no-ops today.

Prove it:
- check_corpus, check_harvest, check_spine and check_predictions green again (check_predictions keeps
  its one known pre-existing red — say so explicitly rather than counting it as new).
- The reconciliation table above, written into the session report.
- A stated verdict on whether the restore is EXACT (byte- or value-identical to what the ledger
  implies) or merely CONSISTENT. Say which. Do not use "identical" for "consistent".

CLOSEDOWN — MAKE THE RESTORED FILES UN-LOSABLE. This is part of THIS session, not a follow-up.
Once the three parquets are restored and the reconciliation is defended, TRACK application/data/
snapshots/corpus/ IN GIT: add a negation to .gitignore (the blanket `application/data/snapshots/`
exclusion at :194 stays; carve out corpus/ only) and commit all five files.
  MEASURED 2026-08-13: leagues.parquet holds 278 rows in 6,150 bytes, so the 271-league manifest is
  ~6 KB; the whole corpus dir is ~276 KB today and under ~400 KB restored. It is also FROZEN — nothing
  has written it since mid-July — so it adds no repo churn.
  I KNOW THIS CUTS AGAINST A STANDING RULE. SESSION_GUIDE says player_id_map.parquet and
  nfl_stats_2025.parquet were deliberately `git rm --cached`'d and not to re-add data files. That rule
  is right and this is a principled exception, not an erosion: those are RUNTIME DATA — large,
  regenerable, constantly changing. The corpus manifest is FROZEN PROVENANCE, closer to a lockfile than
  to data, and it defines the population the immutable L2 ledger was derived from. Lockfiles belong in
  version control precisely because everything downstream is defined against them.
  If you disagree after seeing the restored sizes, say so and leave it — do not silently skip it.

Scope guard — does NOT: build the durability/versioning tier for the LEDGER (its own session — see
below; the corpus carve-out above is in scope because it is 400 KB and it is what broke); re-run or
re-tune anything downstream of the corpus; touch the ledger, engine constants, any transform's maths,
the store's serve layer, or P5/S3's work.
```

## The follow-on this incident argues for — a separate session

**A mirror would not have prevented this.** The overwrite happened at 02:25; a sync job at 02:26 would
have pushed three empty files over three good ones. The fix is **object versioning**, not backup.

The store-boundary ADR already did the classification: **laptop-owned = irreplaceable = needs versioned
durability; worker-owned = reconstructible = does not.** What qualifies: `derived/ledger` (145 MB — a
record of predictions made at a point in time; it cannot be regenerated by anything, ever), `corpus/`
(today's lesson), `derived/scoring` (16 MB, slow to rebuild). Not `derived/league` or the joins.

**The mechanism already exists** — `_SupabaseSnapshotStore` maps the on-disk hierarchy 1:1 to bucket
keys, so this extends something working rather than building something new. ~162 MB fits the free tier;
real object versioning wants R2/S3.

**This is the second time this gap has bitten** — the first was `ros_player_band` losing its RLS to a
full `--load`, which is why the demo clone is generated rather than inserted. Same shape both times:
irreplaceable state in one place with nothing versioning it. **And P5/S3 makes it worse by adding a
second machine with write access.** Currently sits in P6; worth pulling forward.
