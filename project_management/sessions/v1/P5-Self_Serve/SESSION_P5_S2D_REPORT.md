# V1 · P5 · Session S2d — The demo clone, the RLS emit fix · REPORT

**Shipped 2026-08-12.** Brief: `SESSION_P5_S2D_DEMO_CLONE_AND_SELECTOR.md` (+ its 2026-08-11
amendment answering four questions). Companion: `SESSION_P5_DEMO_LEAGUE_CLONE.md`. Prior:
`SESSION_P5_S2C_AUDIT.md`. **Next: S2e** — the season selector (see "What did not ship").

Three commits: the rename · the generator + RLS emit · the load, the repoint and docs. **One planned
outage, 145s end to end.**

---

## What changed, in one line

Until today every anonymous visitor to surplusff.com was looking at **Will's real league**, with ten
real managers' Sleeper handles on a public page. Now they see **DEMO League**.

---

## Part 0 — the catalog table is `league_catalog`

`demo_manifest` named two things: the frozen corpus parquet and the Postgres table that was a
straight copy of it. Harmless until this session made them hold different counts. **Rename the one
that changed.**

Six live sites across four files — and two of them (`scripts/users.py`'s `_OWNED` join and
`_IN_CATALOG`) were **not in the brief's site list**, which is the argument for sweeping rather than
trusting a list. Table prose updated; **parquet references deliberately left alone**
(`read_demo_manifest`, the source column in `MANIFEST.md`, `load_league`'s membership gate). No
corpus-side code moved.

**The DB was deliberately not renamed when the code was.** An `ALTER TABLE` is instant, but it would
have broken the *deployed* site immediately and kept it broken for however long Part 1 took. The
rename landed with the load instead — leaving the worktree failing with exactly
`UndefinedTable: relation "league_catalog" does not exist`, verified to be that and nothing else.

**That produced the session's one non-obvious operational finding:** because deployed code queries
the old name, **the outage window is load → REDEPLOY, not the load.** It is in `OPERATIONS.md`.

---

## Part 1 — the clone is generated, not inserted

`application/data/serve/build_demo_clone.py` reads the frozen LoRP 2025 slice and writes a re-keyed,
anonymised copy under **`DEMO-2025`** (lineage `DEMO`) via the **standard `data_layer` paths in both
trees**. `build_db.DATASETS` needed **zero changes** — the path lambdas resolve by `league_id`, so a
league whose files sit where a league's files go loads with no special-casing. Per-table overrides
for one league would have put a permanent `if demo` inside the publish seam.

**11 artifacts written** (measured, not assumed). `ros_synthesis` and `ros_player_band` have no 2025
file, so skip-if-absent leaves those panels empty **by construction**; `projection_consensus` is
scoring-keyed and shared, so the clone inherits it by being in the load span.

### The anonymisation, and why the check is positive

A **committed literal map**, ten entries. Player names are never touched — they are real NFL players
and they are the demo's content. The check it enables is **positive and total**:

> every displayed `owner_name` / `team_name` in the clone appears in the map's **value set**, and no
> value equals any key.

That proves the mapping was **applied**. An absence check ("grep for the ten known real names, find
zero") could only ever prove those ten are gone — this project's own *a refusal alone proves nothing*,
applied to anonymisation.

`owner_id` is synthetic (`DEMO-OWNER-01`…). It is an internal join key that reaches **no payload** —
verified absent from `application/api/` and the frontend entirely — so it follows the identifier rule
rather than the display rule. **Synthetic ids, realistic names, split by whether a human sees it.**
Flagged because the brief's heading read "NOT `DEMO-OWNER-01`" while its body drew exactly this split;
the split is what was implemented.

Roster 4's `team_name` is **NULL in the source**. The clone fills it: a blank team name on the public
landing page reads as broken, and a NULL has no entry in the value set the total check runs against.

### The check caught a real bug on its first run

**`schedule` carries its own `league_id` column** (B1), which `build_db._copy_slice` asserts equals
the slice before dropping it. A clone that kept the source id **would have failed the load.** It was
found because the sweep looked for the *source league id* across every cloned parquet, not only the
tables with names in them. Fixed generally — re-key any `league_id` column — rather than for that one
table.

### `is_synthetic()` — one predicate, consulted by producers

```
A synthetic league is visible to what READS FOR SERVING (the loader, the API)
and invisible to what WRITES OR COMPUTES.
```

The hazard is concrete, not theoretical: the clone **is** in the loader's work-list, so
`weekly_refresh --league DEMO-2025` would have tried to fetch a league that does not exist on
Sleeper. Both Sleeper-reaching producers now refuse loudly, verified:

| entry point | result |
|---|---|
| `weekly_refresh --league DEMO-2025` | refuses: *"generated, not harvested… nothing to refresh from Sleeper"* |
| `bench_cold_league` `assert_cold` | refuses: *"there is no cold-load to benchmark"* |
| a real league id | passes through — the guard is not a blanket refusal |

Every other `--league`-taking entry point was enumerated and is a **reader**.
`league_registry` is a projection of the corpus manifest, so it is **asserted** clone-free rather
than guarded: a check that bites beats a branch that never runs.

### The layer split, and the trap

`demo_manifest.parquet` is a **corpus** artifact and stays at 31. The clone has **its own**
`synthetic_catalog.parquet`. `build_db._catalog()` unions them, and that one expression is the layer
boundary. Appending the clone to the corpus parquet would have been one line shorter and would have
quietly made the **engine's** work-list 32.

| layer | count | measured by |
|---|---|---|
| **engine** | **31** | `check_matchup_result` — *"31 slices, 4858 team-weeks, 0 changed"* |
| **serve** | **32** | `build_db --verify` — `league_catalog` 32/32 |

Two different checks state it, which is the point. The only executable `31` — `verify()`'s literal —
now derives from the same union the load reads; it would otherwise have failed as "the loader is
broken" rather than "a constant is stale".

---

## Part 3 — `--emit` emits RLS

`ALTER TABLE … ENABLE ROW LEVEL SECURITY` for all **15** tables, in **both** emit sites: the
`DATASETS` loop and the separate catalog block — the latter being exactly the one that would have
been missed. RLS was applied by hand and a later `--emit`/`--load` recreated `ros_player_band`
without it; emitting makes the property **reproducible instead of remembered**, which is the same
argument as generating the clone rather than inserting it.

**Measured baseline, because every doc said "13".** 18 public tables (15 served + 3 auth); RLS ON for
17, OFF for exactly one. **It is 14 of 15, not 13** — `demo_manifest` was the unaccounted table. The
**third** documented figure in this project to turn out never to have been measured (after the Fly
machine count, twice). Docs now carry the number and its date.

`--verify` asserts RLS **for the first time** — nothing anywhere read `relrowsecurity` before, which
is precisely why the gap sat unnoticed.

---

## The load — one outage, both proofs

| | |
|---|---|
| RLS before | 17 ON / 18; `ros_player_band` OFF — **plus `teams` dropped by hand**, deliberately, so the load had two to restore |
| load start | 01:54:06Z |
| load end | 01:55:28Z — **82s**, 32 slices × 15 tables |
| deploy done | 01:56:31Z |
| **outage, end to end** | **145s** |
| RLS after | **19 / 19 ON** — both the pre-existing gap and the hand-dropped table came back |
| catalog after | `league_catalog` = **32** |

**Both proofs came off the one load**, which is why the generator had to exist first: loading before
it would have proven nothing about reproducibility.

**A fossil the rename left, and its removal.** `--load` DROPs what `schema.sql` *names*, and the new
schema no longer names `demo_manifest` — so the old table survived with its 31 stale rows. Dropped,
and the public table count is back to 18 (15 + 3 auth). Worth recording as the general shape: **a
rename via regeneration creates the new table but never removes the old one.**

### Reproducibility, without a second outage

A second full `--load` would have been another 145s for no new information. Instead: regenerate the
artifact from scratch, then `--reload-league DEMO-2025` (scoped, transactional, no outage), then
compare the DB rows.

> **14 tables, 14,624 rows, value-identical 14/14.** The clone came back from its generator.

Value- rather than byte-identical on purpose: polars' parquet writer is physically non-deterministic.

---

## Live proof

Signed out, against production:

- `/api/leagues` → exactly one league: `DEMO-2025`, `"DEMO League"`, `is_mine: false`,
  `viewer_roster_id: null`.
- **Eight endpoints swept for all ten real handles, all nine real team names, the source league id and
  "League of Random People": 0 hits across 51,589 bytes.**
- The rendered SPA: DEMO League, invented team names, **zero `YOU` badges, zero me-row highlight**.
- The generated `schema.sql` diff is **exactly** the rename plus 15 RLS lines — no column changes,
  which independently proves the clone introduced no new columns.

**Gates green after the load:** `check_ownership`, `check_isolation`, `check_auth`, `check_signup`,
`check_scoped_reload`, `build_db --verify`, `check_matchup_result`, `build_demo_clone --check`, and
`build_demo_clone --prove-bites` (the engine sweep catches 3 injected leaks).

**The RLS assertion bites:** dropped RLS on `production_vor` by hand → `--verify` RED
(`*** RLS OFF on 1`) → restored → green.

---

## What did NOT ship, and why

**Part 2 — the season selector → S2e.** Decided **before** starting it, as the brief required: a
half-removed selector is worse than an untouched one. The deciding fact is that the brief's own commit
map — (1) rename, (2) generator + RLS, (3) load + repoint + docs — **has no slot for it**. Its ordering
constraint is now satisfied: the demo has its own lineage, so removing the selector can no longer
strand the demo. It is visibly pending — the demo has one season, so the switcher offers one option.

**The rest-of-season band and the synthetic AI outlook.** The clone is season 2025, below
`FIRST_HONEST_BAND_SEASON`, so the band panel is dark exactly as it was for the old demo; the AI
outlook is empty because `ros_synthesis` has no 2025 file. Both are the original clone brief's asks
and both stayed out of S2d's scope guard. P4 retires the outlook placeholder anyway.

---

## Docs (§7 — replace, don't append)

`STATUS.md` (S2d into current state; the RLS parked item **closed**, the season-selector bullet
rewritten as unblocked-and-S2e, the clone paragraph replaced with what shipped — **net +10 lines**,
recorded rather than trimmed out of the previous session's entry to flatter the number) ·
`ARCHITECTURE.md` (5 catalog references, the RLS line, the demo bullet) · `appendices/store-schema.md`
(the rename, 15 tables, the parquet-vs-table split) · `OPERATIONS.md` (**the outage number**, which is
the point of measuring it — at Week 1 the round trip is what you budget, not the load) ·
`projects/v1/P5_…md` (S2d shipped, S2e next).

Also folded in, per the S2c audit: `reads._denied_reads` is per-process and **two machines run**, so
`denied_reads()` is a **floor** — now stated where the counter is defined.
