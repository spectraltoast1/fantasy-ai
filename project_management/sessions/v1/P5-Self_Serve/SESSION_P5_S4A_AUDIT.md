# P5 · S4a — PM audit of the cold onboard and the connected catalog

**Audited:** 2026-08-14 · **Report:** `SESSION_P5_S4A_REPORT.md` · **Brief:**
`SESSION_P5_S4A_COLD_ONBOARD_AND_CATALOG.md` · **ADR:** `context/appendices/store-boundary.md` ·
**Range:** `24db544..8cae3f1` (3 commits + merge) — diffed against the **branch's base commit**, not
main's working tree.
**Verdict: ENDORSED, and S4a is CLOSEABLE.** All five DoD clauses proven, the release valve not taken.
**One new hazard the session created and did not follow through — see below. It is not firing today,
and it must be written down before anyone runs `--load` or `reload_manifest` on the laptop.**

---

## THE FINDING — the catalog-clobber guard points the wrong way

The session correctly identified that `reload_manifest()` TRUNCATEs `league_catalog` and re-COPYs it
from the **local** store, and guarded it: it now raises under `STORE_ROLE=worker`, *"so any league the
laptop catalogued after the last seed would be silently deleted."*

**After S4a the asymmetry runs the other way, and the guard does not cover it.** The worker is the
**author** of `connected_catalog.parquet`. The laptop does not have that file at all.

**Recomputed on Will's disk, 2026-08-14 — not inferred:**

| | |
|---|---|
| `connected_catalog.parquet` on the laptop | **does not exist** |
| `read_connected_catalog()` when absent | returns an **empty frame**, silently, by design (*"empty-not-absent"*) |
| laptop `_catalog()` | `demo_manifest` **31** + `synthetic_catalog` **1** + connected **0** = **32** |
| production `league_catalog` | **33** |

So **`reload_manifest()` run on the laptop today TRUNCATEs a 33-row table and re-COPYs 32**, deleting
the connected league's catalog row. It is catalog-only, so the league's 14,999 data rows survive as
rows nothing names — `_slices()` no longer contains it, `load_league` would refuse it, and
`/api/leagues` stops showing it to its owner. **`build_db --load` is worse**: it DROP/CREATEs and
re-COPYs only `_slices()`, so the data rows go too.

**Three things make this sharper than a normal latent bug:**

1. **The documented remedy for the session's own finding (b) triggers it.** Finding (b) says an
   un-emitted column's fix is `--emit` + `--load` off a planned outage. Running that on the laptop
   today is a data-loss event for every connected league. The report also notes `MANIFEST.md`'s
   provenance line *"needs an `--emit`"*.
2. **Finding B disarms the alarm.** `build_db --verify` on the laptop now reports **VERIFY FAILED**,
   and the report correctly explains this is expected. The effect is that the one signal which would
   catch this has been pre-labelled as noise — an operator who has read the report sees VERIFY FAILED,
   thinks *"that's finding B"*, and reaches for `--load` to reconcile it. That is the failure path.
3. **It is the ADR's own failure class**: nothing crashes, the site just quietly stops serving a user
   their league.

**This is a consequence of the session's work, not an error in it** — the session is the reason the
worker became an author. **Remedy, and it is small:** `reload_manifest()` and `load()` should refuse
when `league_catalog` in Postgres holds `league_id`s absent from the local `_catalog()`, naming them.
That is the same shape as every other guard here — compare, then raise with the operator step.
**Assign to S4b as its first item; write the hazard into `OPERATIONS.md` today.**

## THE SECOND FINDING — the ADR's durability claim is now false and was left standing

`store-boundary.md:102` still reads: **"The worker's volume is a reconstructible cache, not precious
data — lose the host, re-seed it."** S3 earned that claim its first evidence and the ADR was updated
in three places for S4a (the classification table, the twelfth destination, the writer's shape).
**This line was not.**

It is no longer true. The worker's volume now holds `connected_catalog.parquet` and every connected
league's `derived/league/` artifacts, and **re-seeding from the laptop would produce a worker with no
connected leagues at all.** The data is regenerable — re-run `onboard_league` per league — and the
recovery *list* does exist, in Postgres (`league_catalog` + `user_leagues`). **But nothing says so,
and nothing has tested it**, which is exactly the standard the ADR itself set for S3: *"'just re-seed
it' is exactly the kind of unverified figure that has cost this project three documented
corrections."*

CODING_BIBLE §7: *a session whose work contradicts an appendix fixes the appendix in that same
session.* The classification was fixed; the consequence was not. **One paragraph in the ADR, and
STATUS's standing durability item now extends to the worker.**

---

## Verified independently — recomputed, not read

| claim | verified |
|---|---|
| signed-out live prod returns **exactly the demo** | ✅ **`surplusff.com` AND `fantasy-ai-api.fly.dev`**, byte-identical, one row `DEMO-2025`. Two hostnames, so this is not a cached read path — the leak direction is closed |
| `write_leagues` **not touched** | ✅ diff vs base `24db544` shows only a comment change and its unchanged position in `LAPTOP_OWNED_WRITERS`; the body is untouched |
| the API needed no redeploy | ✅ the only `application/api/` files in the diff are `check_ownership.py` and `check_isolation.py` — **gates, not served code**; `reads.py`/`routes.py` untouched, and `application/api/` imports `data_layer` **nowhere** (confirmed case-sensitively *and* with `grep -i`) |
| **one chain, not two** | ✅ `bench_cold_league:164` calls `onboard_league.run_chain`; `assert_cold` and `_league_dirs` are **re-exports** (`:137-138`), not copies. S0's number still describes what runs |
| `_ref()` raises instead of `row(0)` | ✅ `build_db:218-224` — and **exactly 1** row satisfies `is_mine & panels_market` in the 31-row manifest (recomputed) |
| `demo_manifest` still **31** rows / 12 cols | ✅ recomputed. `synthetic_catalog` 1. **`corpus_manifest` 271** — the frozen corpus intact, and `git status` under `snapshots/` is clean |
| `assert_cold` checks all three catalogs **+ corpus** | ✅ `onboard_league:89-99`, and the corpus check is the one that stops a "cold" run being aimed at the 269 spined leagues |
| `_resolve_scoring_key` order | ✅ catalog → the league's own settings → **raise**. The ordering rationale (`refresh_league` resolves *before* its fetch stage) is correct and I had not spotted it |
| `write_connected_league` is append-shaped | ✅ filters out `(league_id, season)`, concats one row, sorts — and **casts to `read_demo_manifest().schema`**, which is the non-obvious part |
| `upsert_catalog_row` DELETE+INSERT | ✅ and the reason is real: `league_catalog` has no PK and no unique constraint, so `ON CONFLICT` has no target |
| the release valve was **not** taken silently | ✅ stated explicitly, and clause 4 was proven — **this is the S3 audit's complaint fixed** |

**Not verifiable from the PM seat, and it is Will's check** — the same blind spot as S3: the worker has
no `http_service`, so `fly status -a fantasy-ai-worker` and the worker-side `build_db --verify`
(*"VERIFY OK, all 15 tables, `league_catalog` 33/33"*) can only be confirmed from the machine. The
Postgres per-table deltas are likewise unreachable from here.

## What this session did unusually well

**It rewrote its own prove-bites because the first version was weak — and said so.** The first
`check_onboard --prove-bites` pooled one tally across three reverted legs, let an unrelated exception
in leg 1 skip legs 2 and 3, and *passed anyway on a tolerance count written to absorb the difference.*
That is the "a proof that passes because it never exercised the path" trap, found in its own gate,
unprompted, and reported rather than quietly fixed. **Second session running that this has happened.**

**Finding E is a correction of my brief and it is right.** I told Code that `_ref()`'s `row(0)` could
let a connected row become the `--emit` schema reference for the whole database. It cannot:
`_ref()` reads `read_demo_manifest()` alone, never `_catalog()`, so connected rows are **structurally
invisible** to it. I reasoned from the union rather than from the function. The hardening was worth
doing anyway; the danger I claimed was not there.

**Finding D is the CODING_BIBLE §5 rule catching a case §5's own wording did not cover.**
`check_store_boundary._sweep()` purges files whose *path* contains `TMP_SEASON`/`TMP_LEAGUE`.
`connected_catalog.parquet` is a single shared file — **the throwaway is a row, not a file** — so a
leftover would have joined `_catalog()` → `_slices()` and failed the next `--load` on a league that
does not exist. That is the frozen-corpus incident's shape in a new costume, spotted before it fired.

**The proving league was enumerated, not taken from the brief.** 45 candidates from
`corpus_filter_cache.json` in neither the manifest nor the registry, narrowed by probing Sleeper to 5
that are 2025 + redraft + complete. **No crawl was re-run**, so the corpus machinery was never touched.

**Finding F is triaged correctly, and I want it characterised accurately so the next reader does not
over-react.** A null seat on a connected league renders as no "you" (measured: 0 of 211). The other
branch — the owner's Sleeper handle matching an `owner_name` in a connected league — mislabels *which
roster is you* **inside a league the caller is already entitled to read**. It is a display-integrity
defect, **not a cross-user leak**. S4b owns it; it is not a reason to hold anything.

## My own errors in the brief, for the record

1. **`_ref()`** — over-claimed, see finding E above.
2. **I asked Code to determine whether `write_leagues` was on the path, and it was not** — the wall was
   the catalog, as the brief suspected. Good outcome, but note the brief still *led* with the ADR's
   framing; the enumeration was Code's.
3. **I did not anticipate the clobber direction.** I wrote hazard (a) as *"the worker could erase what
   the laptop knows"* and the truth after this session is the reverse. Code implemented what I asked
   for and my framing pointed the guard the wrong way. **That is the finding at the top of this
   document, and its origin is this brief.**

## Verdict

**Endorsed. S4a closes.** Nothing in this system had ever catalogued a league; something has now, and
it was not the laptop. The artifact's shape is argued rather than asserted, the chain is one
implementation rather than two, the scoring-key bug that would have silently mis-scored every
stranger's league is fixed at the right seam, and the session audited its own gate harder than I did.

**Two documentation items before anything else runs on the laptop**, neither of which reopens S4a:
the `--load` / `reload_manifest` clobber (→ `OPERATIONS.md` now, guard → **S4b's first item**), and the
ADR's stale *reconstructible cache* claim (→ one paragraph, this week).
