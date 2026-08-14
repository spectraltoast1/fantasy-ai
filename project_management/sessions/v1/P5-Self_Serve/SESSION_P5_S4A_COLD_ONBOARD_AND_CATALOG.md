# V1 · P5 · Session S4a — The cold onboard and the catalog a connected league lives in

**Written 2026-08-14.** **Status: READY — paste-block below.**
**Prior:** `context/appendices/store-boundary.md` (the ADR — ACCEPTED and BUILT; **this session
corrects its "S4 wall" section**) · `SESSION_P5_S3_REPORT.md` + `SESSION_P5_S3_AUDIT.md` (the worker) ·
`SESSION_P5_S0_REPORT.md` (the latency spike, and `bench_cold_league`, which this session promotes).
**Goal: the store can accept a league it has never seen.**

> **What this session does:** builds the one thing standing between a working worker and a working
> product — somewhere a stranger's league can legally be written down, and a single entry point that
> puts it there. No queue, no connect endpoint, no UI.

---

## Why S4 is now S4a, S4b, S4c

S4 as written in `P5_ACCOUNTS_SELF_SERVE_ONBOARDING.md` is a job queue **plus** a connect endpoint
**plus** a progress screen **plus** identity acquisition **plus** the catalog wall **plus** the weekly
cadence **plus** two carried fixes. Against the 3-commit cap that is three sessions. **S2 was one row
in the same table and became S2a–S2e**; the project's own rule is *one brief per session, do not
re-bundle*. Split (Will, 2026-08-14):

| | scope |
|---|---|
| **S4a — this session** | the connected-league catalog artifact + an append-shaped writer, `_resolve_scoring_key` from the league's own settings, and **one real cold league onboarded end to end on the worker** |
| **S4b** | the Postgres `jobs` table + the worker's lease + `POST /api/connect` + the progress screen + **identity acquisition** (Sleeper handle → `user_leagues.roster_id`) |
| **S4c** | the weekly cadence: enumerate connected leagues, take the lease, **gut `weekly_refresh.yml` to a pure trigger**, and decide what the Action pokes (the worker has no `http_service`) |

**S4a is first because it is the only one where nobody knows whether it works**, and because
everything downstream stands on it: a queue whose payload cannot run, and a cadence over leagues that
cannot be connected, are both proofs that pass by doing nothing — the failure this project has now
hit twice.

## The wall is bigger than the ADR recorded, and it is the whole session

The ADR names **`write_leagues`** as *"the wall P5/S4 must see coming."* Read against the code, that
is the wrong wall — or at least not the only one, and probably not the load-bearing one.

**Three laptop-owned whole-file writers guard the catalog**, not one: `write_leagues`,
`write_demo_manifest`, `write_synthetic_catalog` (`data_layer.py:2195`, `:2270`, `:2325` — each
`_require_laptop(..., _WHY_REGISTRY, _FIX_REGISTRY)`). And it is the **last two** that matter, because
`build_db._catalog()` is `read_demo_manifest() ⧺ read_synthetic_catalog()`, `_slices()` is built from
`_catalog()`, and `load_league` refuses anything absent from it — **in as many words**:

```
league {lid} is not a served slice — nothing to reload
(cataloging a brand-new league is onboarding/P5, not the scoped reload).
```

**So there is today no artifact a real user's league row can legally live in.** `demo_manifest.parquet`
is the frozen 31-row **corpus** slate that `compute_demo_slices`, `check_matchup_result` and the L2
ledger all count on; `synthetic_catalog.parquet` is for **generated** clones and its ids are
deliberately not Sleeper-shaped. S2d's own reasoning is the precedent to follow, not to argue with:
*"Keeping them separate is what lets the corpus stay 31 while the served `league_catalog` becomes
32."* A connected league is a **third kind of thing** and wants a third artifact — 31 + 1 + N.

**Nothing in this system has ever catalogued a league.** `bench_cold_league` — the S0 instrument this
session promotes — says so in its own docstring, twice: it **rolls the load back** specifically to
*"sidestep `build_db.load_league`'s demo_manifest gate — cataloging a brand-new league is onboarding
(P5/S4), not something a measurement should do,"* and *"there is no single 'onboard a cold league'
entry point today … P5/S4 needs a real one; this composes the same steps in the same order meanwhile."*
**S4a is the session that cashes both of those cheques.**

**This also unblocks Gate A.** STATUS files the first real 2026 load as *"a manual admin load, not
P5."* There is no manual admin load available: it needs the same catalog row, and the only two places
to put one are the frozen corpus slate and the synthetic clones. Gate A is ~2 weeks away.

## 1 · The artifact — a third catalog source, append-shaped

- **One row per connected `(league_id, season)`**, the **same twelve columns** as
  `_DEMO_MANIFEST_COLS`, because `_catalog()` vertical-concats them. Suggested
  `connected_catalog.parquet`, following `synthetic_catalog`'s naming; **push back if a better name
  exists** — it will be read by people who have to guess what it holds.
- **The writer is append-shaped and per-league**: it writes or replaces exactly the row for one
  `(league_id, season)` and leaves every other row byte-untouched. **Idempotent** — re-onboarding the
  same league must not duplicate or reorder. This is the property the whole-file writers lack, and the
  reason a worker may hold this pen at all.
- **It is WORKER-owned**, so the ADR's classification goes from eleven destinations to twelve.
  `check_store_boundary` gains the case, and **prove it bites both halves**: the new writer succeeds
  under `STORE_ROLE=worker`, and the three whole-file catalog writers still refuse.
  **§5 applies**: this writer takes a `league_id`, so it *can* go in the destructive leg — aim it at a
  throwaway id, never at a real one.
- **`assert_cold` must learn about it** (`bench_cold_league.py:146`). It checks `leagues.parquet`,
  `demo_manifest.parquet` and the three on-disk directories — it does **not** check
  `synthetic_catalog`, and it will not check the new artifact unless you add both. A coldness check
  that misses a catalog is a coldness check that lies.

### Decide, don't assume: does a connected league need a `leagues.parquet` row at all?

The ADR assumes it does. **Enumerate every reader of `read_leagues()` / `_active_league()` /
`_active_league_any()` / `league_resolver` and state which of them fire on a connected-league path.**
My reading is that all of them are `is_mine`-scoped defaults for a caller who passed no explicit
`league_id`, and every connected-league call site passes one — in which case **`write_leagues` is not
on this path at all**, stays laptop-owned, and is not touched. **If that holds, say so and correct the
ADR**: the wall is the *catalog*, not the *registry*. If it does not hold, name the reader that breaks
it. Do not add a `leagues.parquet` row "to be safe" — an is_mine registry gaining stranger rows is a
new class of bug.

### The twelve column values — state a rule, then apply it

Do not hand-pick these. **A panel flag is true only if that read is honest for that slice today**, and
the other columns follow the league's own facts:

- **`is_mine` must be FALSE, and there is a trap behind it.** `build_db._ref()` is
  `read_demo_manifest().filter(is_mine & panels_market).row(0, named=True)` — **`row(0)` silently
  takes the first of many.** `_ref()` is the `--emit` schema reference for the entire database. Add an
  assertion that exactly one row satisfies that filter, and that connected rows can never enter it.
- **`panels_market` FALSE** (the market read is gated off everywhere and is cross-time —
  `STATUS.md`). **`panels_ros` FALSE.** **`panels_manager`**: S0 measured the dossier fan-out at
  **80s / 248 Sleeper calls** and made it a *deferred job class* — so decide it against that
  measurement and say which way you went and why.
- **`viewer_roster_id`**: leave null. The seat is a *user × league* property (`user_leagues.roster_id`,
  S2b) and acquiring it is S4b. **But check the fallback**: `auth_schema.sql:104` says a null seat
  *"falls back to `MY_USERNAME`"*, which is correct for the demo and is not obviously correct for a
  stranger's league. Report what a null seat actually renders on a connected league. Do not fix it
  here if it is wrong — report it and hand it to S4b.
- **`lineage_id`, `previous_league_id`, `name`, `num_teams`, `scoring_key`** come from the league's
  own Sleeper settings. `lineage_id` is defined as the chain **root**; a first connect has no prior
  season in the store, so state the rule you applied and why it stays stable if an earlier season is
  ever added.

## 2 · The entry point — `bench_cold_league` is a measuring instrument; promote its chain

`bench_league` composes the real chain in the real order (fetch raw → resolve the key from the
league's own settings → substrate check → join every week → spine → schedule → load) and then
**deliberately rolls back**. S4a's job is a **real** entry point that runs the same steps, catalogs the
league, and **commits**.

- **Compose, do not fork.** If the onboard path and the benchmark drift into two implementations of the
  same chain, the number S0 measured stops describing the thing that runs. One chain; the benchmark
  wraps it in timing, the onboarder wraps it in a catalog write and a commit.
- **Fix `_resolve_scoring_key` here — it is on this exact seam.** `weekly_refresh.py:47` falls back to
  `data_layer._active_league(season)[1]` — ***the owner's* scoring key** — for any league absent from
  the catalog, which is every connected league until the moment this session's writer runs. The fix
  already exists and `bench_cold_league:212` already uses it:
  `scoring_key_from_settings(read_scoring_settings(season, league_id=lid))`. S3 confirmed the replay
  does not hit the fallback; **S4a owns the fix** and it is one line plus a gate.
- **The substrate assertion is not optional.** `bench_cold_league:216-220` already raises when a
  league is the first on its scoring key. Keep that behaviour and keep it **loud** — a league silently
  onboarded against a missing `projection_consensus` is the mis-scoring §4 of the CODING_BIBLE forbids.

## 3 · Two hazards on the last mile — find out whether they are real

Both are between the built league and a user seeing it. **Neither is a claim; determine each and
report the answer.**

**(a) `reload_manifest` TRUNCATEs the catalog table.** `build_db.reload_manifest()` does
`TRUNCATE league_catalog` then re-COPYs `_catalog()` from **the local store**. On the worker, the demo
and synthetic parquets are **seeded, read-only, and can be stale** — so a worker calling it could erase
catalog rows the laptop knows about. This is the same whole-file-overwrite shape as the parquet wall,
reappearing at the Postgres layer. Determine whether the connected row can reach `league_catalog` by a
**single-row upsert** instead, and if not, say what the worker must never call.

**(b) The union-superset schema may not have a column a stranger's league carries.**
`_table_schema` builds the DDL as a union across the slices that existed **at the last `--emit`**;
`_copy_slice_tx` issues `COPY "table" (its own columns)`. `division` is the known case — the docstring
says *"division-aware corpus leagues carry a `division` column the is_mine slice lacks."* Determine
whether a connected league carrying an un-emitted column fails the COPY. **If it does, this is a real
onboarding failure mode for strangers and it must be reported, not patched over** — the remedy
(`--emit` + `--load`) **DROPs every table on the production database**, which is why S2c moved it out
and S2d only ran it off a planned 145s outage. Report it; do not run `--load`.

## 4 · Proving it — a real 2025 league, and the 2026 gap stated plainly

**A 2026 league cannot prove this and Will was right to say so** (2026-08-14): most or all of his 2026
leagues have not drafted, so there are no rosters, no matchups and nothing to join. **Prove against a
real, played 2025 league.**

**State the predicate; enumerate it yourself.** The proving league must be: a real Sleeper league,
**redraft, PPR or half-PPR, 1QB or superflex**; with a played 2025 season; and **cold** by
`assert_cold` *extended to every catalog* — absent from `leagues.parquet`, `demo_manifest.parquet`,
`synthetic_catalog.parquet`, the new artifact, **and the 271-row corpus manifest**, and absent from all
three on-disk league directories. Corpus leagues are **not** cold — the spine ran on 269 of them.
Preferred source: **one of Will's own non-LoRP 2025 leagues** (it is the most realistic shape and he
can supply the id). Fallback: a 2025 id from `corpus_crawl_state.json` / `corpus_filter_cache.json`
that is not in the manifest — **the manifest is immutable and this league never enters it.**

**The DoD, and every clause is load-bearing:**

1. The league is **cold before, catalogued after** — shown, not asserted.
2. The chain runs **on `fantasy-ai-worker`, from its own volume**, and **commits** to production
   Postgres. *(S3's `--reload-league` proof was a league that already existed; this is the first time
   the worker creates one.)*
3. `GET /api/leagues` returns it **to a granted account and to nobody else.** Use the existing
   `scripts/users.py --grant` — acquisition is S4b. **Signed-out must still return exactly the demo**;
   re-run `check_ownership` and `check_isolation` and report the counts.
4. **A re-onboard of the same league is a clean no-op** — the append writer's whole point.
5. **Every other league and the demo are untouched**, by count, the way S3 showed it.

**Say the 2026 gap out loud — rule 10, no silent caps.** A 2025 run takes the
`season < FIRST_HONEST_BAND_SEASON` branch and **never reaches the band**; that is the exact blind spot
that nearly shipped a broken worker in S3. S3 separately proved the band's worker-mode verify against
the real 2026 ppr substrate (identical → proceeds, perturbed → raises, restored → proceeds), so the
branch is covered — **what is not covered is the combination**: a *cold* 2026 league whose key's
substrate must already be on the volume. **Write that sentence into the report and hand it to Gate A.**

## Scope guard

Does **NOT**: build the `jobs` table, the lease, `POST /api/connect` or the progress screen (**S4b**);
map a Sleeper handle to an app user or write `user_leagues` from a sign-in (**S4b** — use
`--grant`); touch `.github/workflows/weekly_refresh.yml`, `MY_USERNAME` or `LEAGUE_ID` (**S4c**);
add `--delete` to `scripts/users.py` (**S4b**, account lifecycle); run `build_db --load` or `--emit`
against production; touch the frontend; touch engine constants, any transform's maths, the corpus, the
frozen corpus manifest, or `demo_manifest.parquet`'s 31 rows.

**Named release valve** (this project's pattern — S2d's valve became S2e): if the 3-commit cap bites,
ship the catalog artifact + writer + the entry point + the **cold onboard on the worker**, and defer
**DoD clause 4, the re-onboard idempotency drill**, to a short follow-up — **and say in the report that
you did.** The worker run is **not** the valve; a laptop-only proof leaves S4b building a queue for a
machine that has never done the job.

**Bank before the load (CODING_BIBLE §6).** The commit that lands the writer goes in *before* anything
COPYs into production.

---

## The brief to paste to Code — S4a

```
Goal: V1 Project 5, Session S4a (projects/v1/P5_ACCOUNTS_SELF_SERVE_ONBOARDING.md) — make the store
able to accept a league it has never seen: a third, append-shaped catalog artifact a connected league
can legally live in, plus a real cold-onboard entry point, proven by onboarding one real 2025 league
END TO END ON THE FLY WORKER into production Postgres.

Read first: context/appendices/store-boundary.md (the ADR — this session CORRECTS its "S4 wall"
section), sessions/v1/P5-Self_Serve/SESSION_P5_S4A_COLD_ONBOARD_AND_CATALOG.md (this brief),
SESSION_P5_S3_REPORT.md, SESSION_P5_S0_REPORT.md, context/CODING_BIBLE.md, SESSION_GUIDE.md,
OPERATIONS.md. CHECK THIS BRIEF AGAINST OBSERVABLE REALITY BEFORE EXECUTING — on this project the
brief has been wrong more often than you have.

S4 HAS BEEN SPLIT (Will, 2026-08-14). S4a is this. S4b = jobs table + lease + POST /api/connect +
progress screen + identity acquisition. S4c = the weekly cadence + gutting weekly_refresh.yml. Do not
build S4b or S4c work here.

THE PROBLEM. build_db._catalog() = read_demo_manifest() ++ read_synthetic_catalog(); _slices() comes
from _catalog(); load_league REFUSES anything absent from it ("cataloging a brand-new league is
onboarding/P5, not the scoped reload"). demo_manifest.parquet is the FROZEN 31-row corpus slate;
synthetic_catalog is for GENERATED clones. So a real user's league has nowhere to be written down, and
nothing in this system has ever catalogued a league — bench_cold_league rolls its load back
specifically to sidestep that gate, and its own docstring says "there is no single 'onboard a cold
league' entry point today. P5/S4 needs a real one."

THE ADR UNDERCOUNTS THE WALL. It names write_leagues. There are THREE laptop-owned whole-file catalog
writers (data_layer write_leagues :2195, write_demo_manifest :2270, write_synthetic_catalog :2325) and
it is the last two that block the loader. Correct the ADR in this session (CODING_BIBLE §7: a session
whose work contradicts an appendix fixes it, and re-stamps the date).

1. THE ARTIFACT — a third catalog source, append-shaped, WORKER-OWNED.
   One row per connected (league_id, season), the SAME twelve columns as _DEMO_MANIFEST_COLS because
   _catalog() vertical-concats them. Suggested name connected_catalog.parquet (follows
   synthetic_catalog); propose a better one if you have it.
   The writer writes/replaces exactly ONE (league_id, season) row and leaves every other row untouched.
   Idempotent: re-onboarding must not duplicate or reorder. That append shape is the ONLY reason a
   worker may hold this pen — the ADR's objection to write_leagues is its SHAPE, not its owner.
   Boundary: this is a NEW worker-owned destination — the ADR's classification goes 11 -> 12.
   check_store_boundary gains the case and PROVES IT BITES BOTH HALVES: the new writer SUCCEEDS under
   STORE_ROLE=worker, the three whole-file catalog writers still REFUSE. CODING_BIBLE §5: this writer
   takes a league_id, so the destructive leg aims it at a THROWAWAY id, never a real one.
   assert_cold (bench_cold_league.py:146) must learn about the new artifact AND about
   synthetic_catalog, which it does not check today.

   DECIDE, DO NOT ASSUME: does a connected league need a leagues.parquet row at all? ENUMERATE every
   reader of read_leagues / _active_league / _active_league_any / league_resolver and state which fire
   on a connected-league path. If they are all is_mine-scoped defaults for callers who passed no
   league_id — and every connected-league call site passes one — then write_leagues is NOT on this path,
   stays laptop-owned, is not touched, and the ADR's "S4 wall" is the CATALOG not the REGISTRY. Say
   which it is. Do NOT add a leagues.parquet row "to be safe".

   COLUMN VALUES — apply a rule, do not hand-pick. A panel flag is true only if that read is honest for
   that slice today.
   - is_mine MUST be False, and there is a trap: build_db._ref() is
     read_demo_manifest().filter(is_mine & panels_market).row(0, named=True) — row(0) silently takes the
     first of many, and _ref() is the --emit schema reference for the whole database. Assert exactly one
     row satisfies that filter and that connected rows can never enter it.
   - panels_market False (the market read is cross-time and gated off everywhere). panels_ros False.
     panels_manager: S0 measured the dossier fan-out at 80s / 248 Sleeper calls and made it a DEFERRED
     job class — decide against that measurement and say which way you went.
   - viewer_roster_id null (the seat is user x league, user_leagues.roster_id — S4b acquires it). BUT
     auth_schema.sql:104 says a null seat "falls back to MY_USERNAME", which is right for the demo and
     is not obviously right for a stranger's league. REPORT what a null seat actually renders on a
     connected league. Do not fix it here — hand it to S4b.
   - lineage_id / previous_league_id / name / num_teams / scoring_key from the league's own Sleeper
     settings. lineage_id is defined as the chain ROOT; state the rule you applied for a first connect
     and why it stays stable if an earlier season is added later.

2. THE ENTRY POINT — promote bench_cold_league's chain; do not fork it.
   bench_league already composes the real chain in the real order (fetch raw -> resolve the key from
   THIS league's settings -> substrate check -> join every week -> spine -> schedule -> load) and then
   deliberately ROLLS BACK. Build the real entry point that runs the same steps, catalogs the league,
   and COMMITS. ONE chain: the benchmark wraps it in timing, the onboarder in a catalog write. If they
   become two implementations, S0's measured number stops describing what runs.
   FIX _resolve_scoring_key HERE. weekly_refresh.py:47 falls back to _active_league(season)[1] — THE
   OWNER'S scoring key — for any league absent from the catalog, i.e. every connected league until this
   session's writer runs. The fix exists and bench_cold_league:212 already uses it:
   scoring_key_from_settings(read_scoring_settings(season, league_id=lid)). Gate it.
   KEEP THE SUBSTRATE ASSERTION LOUD (bench_cold_league:216-220): a league that is first on its scoring
   key must RAISE, not onboard against a missing projection_consensus. CODING_BIBLE §4 — never silently
   mis-score.

3. TWO LAST-MILE HAZARDS — DETERMINE EACH, REPORT THE ANSWER, DO NOT PATCH OVER EITHER.
   (a) build_db.reload_manifest() does TRUNCATE league_catalog + re-COPY _catalog() FROM THE LOCAL
       STORE. On the worker the demo/synthetic parquets are seeded, read-only and can be STALE, so the
       worker calling it could erase catalog rows the laptop knows about — the same whole-file-overwrite
       shape reappearing at the Postgres layer. Determine whether the connected row can reach
       league_catalog by a SINGLE-ROW UPSERT instead; if not, state what the worker must never call.
   (b) _table_schema builds the DDL as a union across the slices present at the LAST --emit;
       _copy_slice_tx issues COPY "table" (its own columns). `division` is the known case (the docstring
       says division-aware corpus leagues carry a column the is_mine slice lacks). Determine whether a
       connected league carrying an un-emitted column FAILS the COPY. If it does, that is a real
       onboarding failure mode for strangers — REPORT it. The remedy (--emit + --load) DROPs every table
       on the PRODUCTION database, which is why S2c moved it out and S2d only ran it off a planned
       outage. DO NOT RUN --load OR --emit.

4. PROVE IT — a real 2025 league. A 2026 league CANNOT prove this: Will's 2026 leagues have not
   drafted, so there are no rosters and nothing to join.
   STATE THE PREDICATE, ENUMERATE IT YOURSELF — do not take a league id from this brief. The proving
   league must be a real Sleeper league; redraft; PPR or half-PPR; 1QB or superflex; with a played 2025
   season; and COLD by assert_cold EXTENDED TO EVERY CATALOG — absent from leagues.parquet,
   demo_manifest.parquet, synthetic_catalog.parquet, the new artifact AND the 271-row corpus manifest,
   and absent from all three on-disk league directories. CORPUS LEAGUES ARE NOT COLD — the spine ran on
   269 of them. Preferred: one of Will's own non-LoRP 2025 leagues (ask him for the id). Fallback: a
   2025 id from corpus_crawl_state.json / corpus_filter_cache.json that is NOT in the manifest — the
   manifest is IMMUTABLE and this league never enters it.
   DoD, every clause load-bearing:
   (1) cold before, catalogued after — SHOWN, not asserted.
   (2) the chain runs ON fantasy-ai-worker FROM ITS OWN VOLUME and COMMITS to production Postgres.
       S3's --reload-league proof was a league that already existed; this is the first time the worker
       CREATES one.
   (3) GET /api/leagues returns it to a GRANTED account and to nobody else (use scripts/users.py
       --grant; acquisition is S4b). SIGNED-OUT MUST STILL RETURN EXACTLY THE DEMO. Re-run
       check_ownership and check_isolation and report the counts.
   (4) a re-onboard of the same league is a CLEAN NO-OP.
   (5) every other league and the demo untouched, BY COUNT, the way S3 showed it.
   VERIFY THE INSTRUMENT, NOT JUST THE READING: a run that skips work because everything is "already
   current" is not a proof — that trap has now fired twice (weekly_refresh's _db_max_as_of no-op, and
   the parity run's seven "already banked" skips). Force the work.
   SAY THE 2026 GAP OUT LOUD (rule 10, no silent caps): a 2025 run takes the
   season < FIRST_HONEST_BAND_SEASON branch and NEVER REACHES THE BAND — the exact blind spot that
   nearly shipped a broken worker in S3. S3 separately proved the band's worker-mode verify against the
   real 2026 ppr substrate, so the branch is covered; what is NOT covered is the COMBINATION — a COLD
   2026 league whose key's substrate must already be on the volume. Put that sentence in the report and
   hand it to Gate A.

Scope guard — does NOT: build the jobs table, the lease, POST /api/connect or the progress screen
(S4b); map a Sleeper handle to an app user or write user_leagues from a sign-in (S4b — use --grant);
touch .github/workflows/weekly_refresh.yml, MY_USERNAME or LEAGUE_ID (S4c); add --delete to
scripts/users.py (S4b); run build_db --load or --emit against production; touch the frontend, engine
constants, any transform's maths, the corpus, the frozen corpus manifest, or demo_manifest.parquet's
31 rows.

Release valve if the 3-commit cap bites: ship the artifact + writer + entry point + THE COLD ONBOARD ON
THE WORKER, and defer DoD clause (4), the re-onboard idempotency drill — AND SAY IN THE REPORT THAT YOU
DID. The worker run is NOT the valve: a laptop-only proof leaves S4b building a queue for a machine
that has never done the job.

CODING_BIBLE §6 — the commit FLOOR: the commit that lands the writer goes in BEFORE anything COPYs into
production.

Suggested commit map (3): (1) the connected-catalog artifact + append writer + the boundary
classification + prove-it-bites + assert_cold; (2) the onboard entry point + _resolve_scoring_key from
the league's own settings; (3) the proving run on the worker + docs.

Follow SESSION_GUIDE.md: fresh worktree, <=3 commits, update STATUS.md + ARCHITECTURE.md per §7
(REPLACE, don't append) and the store-boundary ADR (it is contradicted by this session's work), then
close/merge/push. "Merged" is not "deployed" and neither is "written to prod" — say which you did.
Sweep .git for stale lock files at closedown.
```

## Will's checks after

1. **Sign out and load surplusff.com.** The catalog must still be exactly the demo. A connected league
   visible to a logged-out visitor is the one failure in P5 with no alarm attached.
2. **Ask where the row went.** If the answer is `demo_manifest.parquet`, the session missed the point —
   that file is the frozen corpus slate and the ledger counts on its 31 rows.
3. **Ask whether `write_leagues` was touched.** The right answer is probably *"no, and here is why the
   ADR was wrong about that."* If it was touched, ask which reader forced it.
4. **`fly status -a fantasy-ai-worker`** — as in S3, the worker has no HTTP surface, so nobody outside
   the session can verify a deploy from the outside.
