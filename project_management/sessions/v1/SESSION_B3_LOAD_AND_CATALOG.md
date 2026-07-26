# Stage B — Session B3: Load all slices + the `/api/leagues` catalog — a brief for Code

**Last reviewed:** 2026-07-26 · **Status:** Ready to run · **Owner:** Code drives; Will kicks it off + eyeballs
the parity check. **This is the first Stage-B session that touches the production database** — read the parity
guard (decision 4) before running the load.

> **What this session does:** turn the 31 computed demo slices (B2's derived parquet) into a **live,
> multi-league database**, and add the **catalog endpoint** the future league/season switcher reads from.
> Two halves: (1) upgrade the loader `build_db.py` from "one league from `public/data`" to "all 31 slices
> from the **derived store**," tolerating the fact that different slices carry different panels; (2) add
> `GET /api/leagues` — the lineage→seasons→slice tree the frontend (B5) will render as dropdowns. **Nothing a
> user sees changes yet** — the deployed app still shows the one is_mine league until B4/B5 parameterize the
> reads and add the selectors. This is plumbing that must not disturb the live site. `MULTI_LEAGUE_STORE_MIGRATION.md` B3.
>
> **Depends on:** B2 (all 31 slices computed as derived parquet — done) and B1 (the league-scoped schedule
> path — done). B3 is the consumer of both.

## Your part, Will (~10 min to kick off; then it runs)
Kick off the brief. When it's done, the check that matters is the **parity guard**: after the loader reloads
the production DB from the derived store, the deployed app at fantasy-ai-api.fly.dev must render **exactly what
it does today** (still your one is_mine league — Week 4, record, playoff odds, matchups all identical), because
B3 only *adds* the other 30 leagues alongside it; it doesn't rewire the reads. And a quick look at
`GET /api/leagues` returning your ~12 lineages grouped with their seasons. That's your "looks right."

> **Optional pre-step (recommended, from the B2 audit):** before B3, run the one-command dossier backfill for
> the two deep showcases the B2 run skipped — they'll load automatically, no B3 change:
> `python3 -m application.data.corpus.compute_demo_slices --phase dossiers --dossier-lineages 515692323082268672 606543373242806272`
> (trap + ypfl; both are 12-team PPR redraft — nbl's twin profile, which came back 12/12 rich). If you skip
> it, B3 still works — those leagues just show "No dossier for this manager," which is a valid state.

## Decisions I made for you (Code: follow unless you hit a reason not to)

1. **Source = the derived store, not `public/data`.** Today `build_db.py` reads
   `application/frontend/public/data/*.parquet` (the single published slice). Rewrite it to read each dataset
   from the **per-league derived dir** `derived/league/<league_id>/<dataset>_<season>.parquet`, driven by the
   **manifest as the work-list** (`data_layer.read_demo_manifest()` → the 31 slices). Route **all** reads
   through `data_layer` (the I/O-through-data_layer rule) — no hand-built paths. Two source shapes:
   - **League-keyed (12 of 13 datasets):** `season, teams, lineup_slots, league_settings, player_signal,
     production_vor, market_vor, ros_synthesis, bracket_odds, positional_depth, manager_dossiers, schedule`
     → `derived/league/<id>/`.
   - **Scoring-keyed (1):** `projection_consensus` → `derived/scoring/<scoring_key>/projection_consensus_<season>.parquet`.
     Load it **per slice, stamped with that slice's `league_id`+`season`** (same as the current loader stamps
     it) so the reads stay unchanged — accept that slices sharing a `(scoring_key, season)` load duplicate
     projection rows under different `league_id`s. (A later normalization to load it once keyed by scoring is
     possible but out of scope — don't change the read SQL here.)
2. **Tolerate per-slice panel gaps — this is the core new behavior.** Not every slice has every dataset. Base
   analytics exist for all 31; **`manager_dossiers` exists for only ~11 slices** (lorp, nbl, dysf, wcfc — plus
   trap/ypfl if the pre-step ran); **`market_vor` / `ros_synthesis` exist for exactly one** (lorp 2025). For
   each `(slice, dataset)`, **skip if the parquet is absent** — load zero rows from that slice into that table,
   never crash, never fabricate. A league with no dossier rows is correct: the read's `WHERE league_id = …`
   returns empty → the endpoint's `{"missing": True}` → the front-end's "No dossier / No intel" state. (This is
   the locked "gate historical, keep dossiers where they exist" policy, now enforced at load time.)
3. **`schedule` already carries a `league_id` column — de-dup it.** B1 stamped `league_id` onto the schedule
   rows *and* the loader's `_plan` adds a constant `league_id` column to every table. Loading schedule as-is
   would create **two `league_id` columns** (a SQL error). Fix: for the one dataset that already carries
   `league_id` (schedule), drop the parquet's own `league_id` before COPY and use the stamped constant (assert
   they're equal first as a guard), so every table has exactly one `league_id`. Season is likewise stamped from
   the slice, not a hardcoded `2025`.
4. **Parity guard — do NOT disturb the live app (this session reloads production).** The schema is
   `DROP + CREATE`, so the load **replaces the whole production DB**. The deployed app filters every read on
   `settings.league_id()` (the Fly secret `LEAGUE_ID` = the is_mine 2025 league) — so once all 31 slices are
   loaded, the app must still resolve to **exactly** its current slice. **Prove it:** before load, capture the
   is_mine 2025 slice's per-table row counts (and a spot-check of a few endpoint responses); after load,
   confirm the is_mine 2025 rows are **identical**, and hit the deployed URL to confirm every tab renders the
   same as today. Do **not** change the Fly secrets (`LEAGUE_ID` / `MY_USERNAME` stay on the is_mine league) —
   the selector that lets those vary is B4/B5. If the is_mine slice doesn't reload byte-faithfully from the
   derived store, **stop and diff** (derived/league/1182… should match what `public/data` published in Stage A;
   B1 already proved the schedule pairings are byte-identical).
5. **Carry `owner_id` as a first-class key** (the `OWNER_KEYED_MANAGER_PROFILES.md` prerequisite). `owner_id`
   is already a column on the `manager_dossiers` parquet (confirmed on disk), and the loader loads every parquet
   column — so it flows through automatically. **Make it deliberate:** keep `owner_id` in the loaded
   `manager_dossiers` table and **add an index on `(league_id, owner_id)`** (alongside the existing
   `roster_id`). That single choice keeps the deferred owner-keyed dossier refinement a small read-swap later,
   not a reload. Do **not** re-key the table now — just don't drop the column, and index it.
6. **`verify()` must go multi-league.** The current `verify()` asserts `n_leagues == 1` per table — that will
   now (correctly) fail. Replace it with **per-table expectations from the manifest**: each table's row count =
   the sum over the slices that have it; `manager_dossiers` distinct `league_id`s = the count of slices that had
   a dossier file; `market_vor`/`ros_synthesis` = 1 league; base tables = 31. Print the per-table league counts
   so the panel gating is visible in the verify output.

## The catalog endpoint — `GET /api/leagues` (the second half of B3)

The frontend (B5) needs a tree of what's loadable. Serve it as a **pure DB read** (consistent with the
Stage-A "API reads Postgres only, no parquet at request time" architecture):

- **Load the manifest into a catalog table.** Add `demo_manifest` (or `league_catalog`) as a loaded table
  (a 14th dataset from `snapshots/demo_manifest.parquet` via `data_layer.read_demo_manifest()`), so the
  endpoint reads it from Postgres, not a runtime parquet.
- **`GET /api/leagues` groups by `lineage_id`** and returns the tree below. `weeks_available` is **derived at
  query time** from the loaded data (e.g. `SELECT DISTINCT week` from `schedule`/`season` for that
  `league_id`), not stored. Panels come from the manifest's three flags. `name` from the manifest.

```jsonc
{
  "leagues": [
    {
      "lineage_id": "1132400260048977920",          // the root league_id (B0's stable key), NOT a slug
      "name": "League of Random People 2.0",
      "scoring_key": "ppr",
      "is_mine": true,
      "seasons": [
        { "season": 2025, "league_id": "1182101676608823296",
          "weeks_available": [1,2,3,4], "viewer_roster_id": 8,     // NOTE: 8, not 7 (the B0-flagged slip)
          "panels": { "market": true,  "manager": true, "ros_synthesis": true } },
        { "season": 2024, "league_id": "1132400260048977920",
          "weeks_available": [1,2,"…",15], "viewer_roster_id": 8,
          "panels": { "market": false, "manager": true, "ros_synthesis": false } }
      ]
    }
    // …12 lineages total; seasons sorted desc; lineages a sensible order (is_mine first is fine)
  ]
}
```

Two corrections to the contract as written in `MULTI_LEAGUE_STORE_MIGRATION.md` (it predates B0): **`lineage_id`
is the root `league_id` string**, not the human slug (`"lorp"`) — the slug was a brief-only label; the display
string is `name`. And **lorp's `viewer_roster_id` is 8**, not 7 (the manifest is correct; the doc's example is
the slip we already flagged). Mirror the manifest, not the doc's example.

## The brief to paste to Code

```
Goal: Stage B, Session B3 (MULTI_LEAGUE_STORE_MIGRATION.md B3) — load all 31 demo slices from the DERIVED store
into the production Postgres, keyed by league_id+season, and add GET /api/leagues (the lineage-grouped catalog).
Depends on B2 (derived parquet for all 31 — done) + B1 (league-scoped schedule path — done). This session
RELOADS production — the parity guard below is non-negotiable.

Part 1 — multi-slice loader (application/data/serve/build_db.py):
- Replace the source: read each dataset from the derived store via data_layer, driven by
  data_layer.read_demo_manifest() as the work-list (31 slices), NOT from frontend/public/data. League-keyed
  datasets → derived/league/<league_id>/<dataset>_<season>.parquet; projection_consensus → the scoring-keyed
  derived/scoring/<scoring_key>/ substrate, stamped per slice with that slice's league_id+season. No hand-built
  paths — everything through data_layer.
- Per (slice, dataset): SKIP IF ABSENT. Base analytics exist for all 31; manager_dossiers for ~11 slices;
  market_vor/ros_synthesis for only the is_mine 2025 slice. A missing dataset for a slice loads zero rows for
  that slice — never crash, never fabricate. A league with no dossier rows must load clean (WHERE returns empty
  → {"missing": True}).
- schedule already has a league_id column (B1): drop the parquet's own league_id before COPY (assert it equals
  the stamped constant first), so every table has exactly ONE league_id. Stamp season from the slice, not a
  hardcoded year.
- Keep owner_id on manager_dossiers (it's already a column; the loader loads all columns) and ADD an index on
  (league_id, owner_id) alongside roster_id — the owner-keyed-dossier prerequisite. Do not re-key the table.
- Rewrite verify(): drop the n_leagues==1 assertion; assert per-table row counts = sum over slices that have
  the dataset, and print per-table distinct-league_id counts so panel gating is visible (base=31,
  manager_dossiers=~11, market_vor/ros_synthesis=1).

Part 2 — catalog:
- Load snapshots/demo_manifest.parquet as a 14th table (demo_manifest/league_catalog) so the endpoint is a pure
  DB read.
- Add GET /api/leagues: group by lineage_id (the ROOT league_id string — not a slug), return
  lineages → seasons(desc) → {league_id, weeks_available, viewer_roster_id, panels}. weeks_available derived at
  query time (DISTINCT week from schedule/season for that league_id). panels from the manifest flags
  (market/manager/ros_synthesis). name + is_mine from the manifest. Mirror the manifest values exactly — lorp
  viewer_roster_id is 8 (the doc's "7" example is a known slip).

PARITY GUARD (this reloads production — do this, don't skip it):
- Before load: record the is_mine 2025 slice's per-table row counts + a couple endpoint responses from the live
  app.
- After load: confirm the is_mine 2025 rows are identical, then hit https://fantasy-ai-api.fly.dev/ and confirm
  every tab (Players/Matchups/Teams/League) renders exactly as today at Week 4 and an earlier week. The app
  still shows ONLY the is_mine league (its LEAGUE_ID Fly secret is unchanged) — B3 adds the other 30 leagues to
  the DB but does not rewire the reads (that's B4/B5). Do NOT change Fly secrets. If the is_mine slice doesn't
  reload byte-faithfully from derived/league/1182…, STOP and diff (it should match Stage A's public/data;
  B1 proved schedule parity).

Follow SESSION_GUIDE: fresh worktree, scripts/worktree-setup.sh, 3-commit cap, update STATUS.md, close/merge,
push. Suggested commits: (1) build_db multi-slice source + skip-if-absent + schedule league_id de-dup +
owner_id index; (2) GET /api/leagues + catalog table load; (3) the production reload + verify + live parity
check + STATUS. Show me: the verify() per-table league-count table, the /api/leagues JSON for two lineages
(one is_mine, one corpus), and the live-app parity confirmation.

Close: update STATUS.md (B3 done: all 31 slices in the DB, panel gating enforced at load, GET /api/leagues live,
live app parity held; next = B4 — parameterize the reads on league_id+season). Merge/push.
```

## Definition of done
✅ `build_db.py` loads all 31 slices from the **derived store** (manifest-driven), stamping `league_id`+`season`,
**skipping absent per-slice datasets** (dossiers ~11, market/ros 1, base 31) without crashing; the `schedule`
double-`league_id` is de-duped; `owner_id` is retained + indexed on `manager_dossiers`; `verify()` reports
per-table league counts (no `n_leagues==1`). `GET /api/leagues` returns the lineage→seasons→slice tree from a
DB read, grouped on the **root `league_id`**, with correct `viewer_roster_id` (lorp = 8), `weeks_available`,
and panel flags. **Parity held:** the production reload leaves the deployed app rendering the is_mine league
exactly as before; Fly secrets unchanged; STATUS updated with B4 next.

## Notes / gotchas
- **This is the first Stage-B production write.** B0–B2 were all offline/parquet-only. B3 reloads Supabase. The
  parity guard is the whole safety net — the app must be indistinguishable afterward. If in doubt, load into a
  scratch table set first and diff, then swap.
- **Skip-if-absent is a feature, not an error path.** The demo *deliberately* has sparse panels (30 of 31 have
  no market/news; ~20 have no dossiers under the current run). The loader encoding that sparsity faithfully is
  the point — don't "helpfully" backfill or error on a missing file.
- **projection_consensus duplication is acceptable for the demo.** Stamping the shared substrate per league
  bloats that one table (same players under many `league_id`s) but keeps the read SQL untouched. Normalizing it
  to a single scoring-keyed load is a real option — flag it for later, don't do it here.
- **`weeks_available` reflects reality per slice.** Completed historical seasons run the full slate (1..N);
  the is_mine 2025 slice is frozen at ~4 weeks. Derive it from the data, don't hardcode — the frontend uses it
  to bound the week switcher per league.
- **Hand-off to B4:** the reads are still hardwired to one league via `settings.league_id()`. B4 parameterizes
  every endpoint on `league_id`+`season` (path or query param) and filters the SQL — then B5 adds the
  selectors + per-slice `viewer_roster_id` and the panel-gating in `readiness.jsx`. B3 just makes the data and
  the catalog exist.
- **Dossier coverage is whatever's on disk at load time.** If the trap+ypfl backfill (B2 audit rec) is run
  first, those 11 slices load automatically and the demo is materially richer; if not, they load as "no
  dossier." Either is valid — B3 doesn't gate on it.
```
