# V1 · P5 · S4a — The cold onboard and the catalog a connected league lives in

**Shipped 2026-08-14.** **Brief:** `SESSION_P5_S4A_COLD_ONBOARD_AND_CATALOG.md` ·
**ADR:** `context/appendices/store-boundary.md` (corrected by this session).
**3 commits.** Worker redeployed. **The worker wrote a league into production Postgres that had
never existed anywhere.** No outage — the worker serves no traffic and the API was not redeployed.

> **Nothing in this system had ever catalogued a league.** Now something has, and the thing that did
> it was not the laptop.

---

## What shipped

### 1 · The artifact — a third catalog source, and the shape is the argument

`build_db._catalog()` was `demo_manifest ⧺ synthetic_catalog`; `_slices()` comes from it; `load_league`
refuses anything absent from it. `demo_manifest.parquet` is the frozen 31-row **corpus** slate the L2
ledger was derived from, `synthetic_catalog.parquet` is for **generated** clones. So a real user's
league had nowhere to be written down.

**`connected_catalog.parquet` — 31 + 1 + N**, following S2d's precedent rather than arguing with it.
`write_connected_league(df, league_id, season)` writes or replaces exactly one row, sorted so a
re-onboard cannot reorder, and it is **worker-owned**: the classification goes **11 → 12**.

**The append shape is the entire justification.** The ADR's objection to `write_leagues` was that a
whole-file writer on a machine that knows about fewer leagues silently shrinks the shared artifact.
A writer that replaces one row has no shrink to cause. Owner was never the issue; shape was.

**It casts dtypes, it does not merely select them.** `_catalog()` concatenates with polars' strict
`how="vertical"`. A row built from a dict arrives with `viewer_roster_id: Null`, and a `season` that
came back as `Int32` would raise `SchemaError` **for the whole catalog** — i.e. take the demo down
for every visitor, from one connected league's row. The three existing catalog writers enforce
column order only, which is safe for them because they write frames that came off disk.

### 2 · The entry point — one chain, not two

`bench_cold_league`'s own docstring said it twice: *"there is no single 'onboard a cold league' entry
point today. P5/S4 needs a real one; this composes the same steps in the same order meanwhile."*

The chain **moved** into `serve/onboard_league.py::run_chain`; the benchmark now imports it and
passes its `_Stage` as a stage observer. **One implementation.** Two copies would have meant S0's
measured 8.4–10.3s slowly stopped describing the thing that actually onboards a league — and nobody
would have noticed, because both would keep passing.

The onboarder adds what the benchmark deliberately omits: the coldness precondition, the catalog
row, and a load that **commits**.

### 3 · The scoring key — the one that mis-scores a season

`weekly_refresh._resolve_scoring_key` fell back to `_active_league(season)[1]` — **the owner's key**
— for any league absent from the catalog, which was every connected league in existence. Found in
S0, confirmed-not-fixed in S3, fixed here because S4a is what puts strangers' leagues on that path.

**The order is not the obvious one.** "Always derive from the league's own settings" reads better and
breaks: `refresh_league` calls this at line 100, *before* its fetch stage at 120, so a league whose
raw config is not yet on disk has nothing to derive from. The shipped order is **catalog → the
league's own Sleeper settings → RAISE**, which also preserves exact parity for all 32 slices that
refresh today (asserted, not assumed — `check_onboard` re-resolves every one).

### 4 · Both last-mile hazards — determined, and one of them measured

**(a) `reload_manifest` TRUNCATEs the catalog: REAL, and now guarded.** It re-COPYs `_catalog()` from
the *local* store, so on a worker — whose store is a seeded snapshot — it would delete every league
catalogued since the last seed. The whole-file-overwrite hazard reappearing at the Postgres layer.
It now **raises under `STORE_ROLE=worker`**: the first boundary guard at the database rather than the
file store. The scoped alternative is `upsert_catalog_row` — **DELETE + INSERT, not `ON CONFLICT`,
because `league_catalog` has no primary key and no unique constraint**, so there is no conflict
target to name. It runs inside the load's transaction, so a first connect is atomic.

**(b) An un-emitted column would fail the COPY: REAL in mechanism, ZERO occurrences in the store.**
Measured 2026-08-14 across **14 datasets × 272 on-disk leagues**: no column on disk is absent from
the deployed DDL. `teams.division` is the known shape-dependent column and it *is* emitted. So the
residual risk is a shape no corpus league has — exactly when a bare `UndefinedColumn` mid-COPY would
be least informative. **Reported, not patched:** `_assert_columns_live` refuses before the COPY and
names the column, the table, and that the remedy needs a planned outage. **`--emit` and `--load` were
not run.** `--emit` is also not *needed*: connected rows carry the same 12 columns and dtypes, so
`league_catalog`'s DDL is unchanged — only `MANIFEST.md`'s provenance line is now stale.

---

## Proof

**The proving league was enumerated, not taken from the brief.** 45 ids in `corpus_filter_cache.json`
pass the filter and are in neither `corpus_manifest` (271) nor `leagues.parquet` (278). Probing
Sleeper narrowed those to 5 that are 2025 + redraft + complete; all 5 were PPR.
Chosen: **`1258181662160719872` "Rex Lumber 2025"** — 12-team, 1QB, PPR, pure skill-position starters,
the most representative real home league of the five. **It never enters the frozen manifest.**

| DoD clause | result |
|---|---|
| **1 · cold before, catalogued after — shown** | worker volume: all 3 league dirs + `connected_catalog.parquet` **absent**; Postgres: **0** rows. After: `assert_cold` **refuses**, naming `connected_catalog.parquet`; `classify()` returns `reonboard` |
| **2 · runs ON the worker, from its own volume, and COMMITS** | **14,999 rows across 10 tables + 1 catalog row**, `league_catalog` **32 → 33** |
| **3 · visible to a granted account and nobody else** | see the three legs below |
| **4 · re-onboard is a clean no-op** | connected catalog **value-identical** (`canonical_rows`), **all 14 tables unchanged**, **1** catalog row — no duplicate |
| **5 · every other league + the demo untouched, by count** | every table's delta equals **exactly this league's rows**; other-league delta **+0 across all 14** |

**Per-table deltas** (before → after, and this league's share of each): `season` 69141→71232 (2091) ·
`teams` 374→386 (12) · `lineup_slots` 163→168 (5) · `league_settings` 2687→2735 (48) · `player_signal`
86240→89177 (2937) · `production_vor` 80918→83680 (2762) · `bracket_odds` 4554→4710 (156) ·
`positional_depth` 19632→20304 (672) · `projection_consensus` 192250→198350 (6100) · `schedule`
6696→6912 (216). `market_vor`, `ros_synthesis`, `manager_dossiers`, `ros_player_band`: **+0**, which is
the panel-flag rule holding — see below. Distinct leagues in `production_vor`: **32 → 33**.

### DoD clause 3, in the three legs Will specified

**(a) The positive, locally.** S4a ships no API code — the predicate is S2b's, already deployed and
gated — so clause 3 is a *data* question. Against a `CURRENT_SEASON=2025` process on **production
Postgres**: signed out → `[LoRP]`; the granted account → **`[Rex Lumber 2025, LoRP]`**, owned-first.
**All 11 reads serve the owner 200; all 11 refuse a signed-out caller 404.**

**(b) The negative, on live prod, as an assertion.** Signed out: **exactly the demo** (`DEMO-2025`,
one row). With the granted token: **also exactly the demo**, and `GET /api/standings?league_id=…`
**404** — body byte-identical to a league that never existed (`{"detail":"unknown league_id"}`).
It is absent **for the season reason and this is shown, not assumed**: `/api/me` proves the token is
accepted, the catalog comes back non-empty so it is not broken, prod `/health` reports
`season 2026 (derived)`, and the *same token* saw the league against a 2025 process in leg (a).

**(c) The 2026 arm pinned as fixtures.** `check_ownership` and `check_isolation` gained connected-league
cases — a 2026 connected league IS visible to its owner and to nobody else, a 2025 one is not, and
neither leaks signed-out — because those functions are pure and injectable precisely so a gate does
not need live accounts or a drafted league.

### Gates

| gate | result |
|---|---|
| `check_onboard --prove-bites` (**new**) | **20/20**; all **three** reverted legs break independently |
| `check_store_boundary --prove-bites` | **24/24**; neutered guard fails all **10** |
| `check_ownership` | **ALL GREEN**, 54 assertions; pre-S2a catalog fails 8 |
| `check_isolation` | **ALL GREEN**, 50 assertions; pre-S2b authorization fails 7 |
| `build_db --verify` **on the worker** | **VERIFY OK** — all 15 tables, `league_catalog` 33/33, RLS on all 15 |

**The instrument was verified, not just the reading.** The run was on a genuinely cold league, so
nothing could skip: `harvest._raw_present` was false, every spine read absent, and the stage log shows
real work (spine `bracket_odds=0.8s player_signal=0.5s …`, 14 weeks joined, schedule 216 rows). The
*second* run skipping is the point of clause 4, and is reported as such.

**`check_onboard`'s own prove-bites was rewritten mid-session because the first version was weak.**
It pooled one tally across three reverted legs and let an unrelated exception in leg 1 skip legs 2
and 3 entirely — then passed anyway, on a tolerance count I had written to absorb the difference.
That is the same "a proof that passes because it never exercised the path" trap S3 caught in its own
parity run. Each leg now runs independently and each must break on its own.

---

## Findings

**A · The ADR was wrong about the wall, and `write_leagues` was not touched.** It named
`write_leagues` as *"the wall P5/S4 must see coming"*. Enumerated: all **53** `_active_league` sites
and **3** `_active_league_any` sites are `x = x or _active_league(...)` — the `or` short-circuits, so
an explicit `league_id` never opens the file — and both resolvers filter `is_mine` **first**, so a
stranger row would be read by **nothing**. `pilot_cohort` has no legal value for a connected league,
`assert_cold` treats a registry row as **not cold**, and the entire `application/api/` never imports
`data_layer`. **Two readers do fire on a connected-league path and neither forces a row:**
`compute_bracket_sim:78` calls `_active_league` unconditionally but `try/except`s it and uses it only
for a seed-equality test a stranger's league fails anyway; and `_resolve_scoring_key`, which was a
genuine bug and is fixed from the league's own settings. **The wall is the catalog, not the registry.**
ADR corrected and re-stamped.

**B · `build_db --verify` has moved machines, and this is structural.** It compares *local* disk to
Postgres. The worker now builds leagues the laptop has never seen, so the laptop's store is a strict
subset: measured 2026-08-14, laptop **VERIFY FAILED** (10 tables + `league_catalog` 32 vs 33), worker
**VERIFY OK** (all 15). This inverts S3's cross-machine parity proof, which worked precisely because
the league existed on both. Not a regression — the first real consequence of the worker becoming an
*author* rather than a re-loader. In OPERATIONS; a scoped `--verify --league <id>` is the obvious
follow-up and is **not** built here.

**C · `assert_cold` was checking one catalog of three, and the gap predated this session.**
It read `demo_manifest` only. `synthetic_catalog` was never checked — the `is_synthetic()`
short-circuit covers only the hardcoded `frozenset({"DEMO-2025"})`, so a second clone would have
slipped straight through. It now checks all three served catalogs **and** the frozen corpus manifest.

**D · `check_store_boundary._sweep()` had a hole this writer would have fallen into.** It removes
files whose *path* contains `TMP_SEASON`/`TMP_LEAGUE`. `connected_catalog.parquet` is a single shared
file whose name contains neither — the throwaway is a **row**. Left behind it would join `_catalog()`
→ `_slices()`, and the next `--load` would fail on a league that does not exist. The new permits case
restores the file's exact bytes; `_sweep` gained a row-level purge behind it.

**E · `_ref()`'s `row(0)` is safer than the brief thought, and now says so.** It reads
`read_demo_manifest()` alone, never `_catalog()`, so a connected row **structurally cannot** become
the `--emit` schema reference for the whole database — asserted in the gate with an is_mine +
panels_market connected row, which is correctly ignored. Exactly **1** row satisfies the filter today,
and `_ref()` now raises rather than silently taking the first of many.

**F · A null seat on a stranger's league renders as no "you" — HAND TO S4b.**
`reads.resolve_viewer` falls back to matching `MY_USERNAME` against `teams.owner_name`. Measured on
the real connected league: **0 of 211 players flagged `isMe`, 0 matchup teams flagged** — degraded,
not wrong. **The hazard is the other branch:** if the owner's own Sleeper handle *is* an `owner_name`
in a connected league, that roster is silently highlighted as the *stranger's* "you", and nothing
checks the roster belongs to the caller. `build_demo_clone` already treats this as a two-lock problem
(`is_mine` False **and** an anonymisation map); a real connected league has no second lock.
`check_isolation:171` asserts the *authorize* layer returns `None` and never exercises the DB lookup.

**G · The panel-flag rule produced four `+0` tables, which is the rule working.** `panels_manager`
is **False** against S0's measurement, not by default: the dossier fan-out is 80s / 248 Sleeper calls
and S0 made it a *deferred job class*, so the chain does not run it and there are no `manager_dossiers`
rows. A true flag would light a panel with nothing behind it. **S4b's deferred job flips this row to
True**, and the append writer supports that — proven in `check_onboard`.

**H · `lineage_id` walks to the chain root rather than self-rooting.** Self-rooting is unstable: add
an earlier season and the root moves. The walk is bounded at 10 hops, survives a deleted prior season,
and returns *how* it resolved so a store-rooted fallback is visible. Rex Lumber has no
`previous_league_id`, so it is its own root — reported as such, not silently.

---

## The 2026 gap, said out loud (rule 10 — no silent caps)

**A 2025 run takes the `season < FIRST_HONEST_BAND_SEASON` branch and NEVER REACHES THE BAND** — the
exact blind spot that nearly shipped a broken worker in S3. The stage log confirms it:
`band → skipped: season < FIRST_HONEST_BAND_SEASON (2026)`.

S3 separately proved the band's worker-mode verify against the real 2026 ppr substrate (identical →
proceeds, perturbed → raises, restored → proceeds), so **the branch is covered**. **What is NOT
covered is the combination: a *cold 2026* league whose scoring key's substrate must already be on the
volume before the onboard can succeed.** The volume currently carries `projection_consensus` and
`ros_player_band` for `ppr` and `half` at 2026, so the expected path is clear — but it has never been
run, and a league on a third key would raise at the substrate assertion. **Gate A owns this.**

Second, smaller gap: production's derived season is **2026**, so the *deployed* API has never served
a connected league to anybody. Leg (a) proved the data and the predicate against production Postgres;
the deployed-API arm needs a 2026 league. **Also Gate A.**

## Deliberately not done

The `jobs` table, the lease, `POST /api/connect`, the progress screen, and identity acquisition
(**S4b** — the grant was made with `scripts/users.py --grant`) · the weekly cadence and
`weekly_refresh.yml` (**S4c**) · a scoped `build_db --verify --league` (finding B) · the null-seat
collision fix (finding F) · `--emit`/`--load` against production · `MANIFEST.md`'s stale provenance
line, which needs an `--emit` and changes no DDL.

**The release valve was NOT taken.** All five DoD clauses were proven, including clause 4.

## For Will

- **The grant is still in place.** `willdaniel.wrd@gmail.com` owns `1258181662160719872` in
  production. It is **invisible on the live site** (season 2026 vs the league's 2025) — that is leg
  (b) — and it is left in place so the proof stays checkable. To remove it:
  `application/api/.venv/bin/python scripts/users.py --revoke willdaniel.wrd@gmail.com 1258181662160719872`
- **`fly status -a fantasy-ai-worker`** — as in S3, the worker has no HTTP surface, so nobody outside
  the session can verify the deploy from the outside.
- **The laptop's `build_db --verify` will now report a mismatch.** That is finding B, not a fault.
