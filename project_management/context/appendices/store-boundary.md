# ADR — The store boundary: what the laptop owns, what every other machine only reads

**Current as of: 2026-08-14.** **Status: ACCEPTED (Will, 2026-08-13), BUILT (P5/S3), EXTENDED
(P5/S4a).** Option (b).

> **Built, with three corrections this ADR did not anticipate** — all three are folded in below:
> the model is **one writer**, not laptop-vs-worker (there is a third machine); the classification
> needed **eleven** rows, not three; and the band could **not** simply raise — see "what (b) costs".
>
> **P5/S4a made it twelve, and corrected the wall.** This ADR named `write_leagues` as "the wall
> P5/S4 must see coming". **That was wrong** — the wall is the *catalog*, not the *registry*, and
> `write_leagues` is not on the connected-league path at all. See "The wall P5/S4 hit" below.
**Scope:** P5/S3 (the Fly worker) + P5/S4a (the connected catalog). **Supersedes:** the four-bullet
rule in `projects/v1/P5_ACCOUNTS_SELF_SERVE_ONBOARDING.md` § Context, which this expands and
**corrects**.

---

## The decision

Data flows **one direction only: ONE WRITER — the authoring laptop — and everything else reads.**

**Corrected in build (P5/S3):** this was written as "laptop → worker", which undercounts the
machines. There are **three** that run this pipeline — the laptop, the Fly worker, and the GitHub
Actions runner — so the rule is stated by role, not by hostname. Anything that is not the authoring
laptop sets `STORE_ROLE=worker` and gets the shared substrate read-only.

**The classification is now complete.** The three rows below described a store with eleven
destinations; the rest were unclassified, which is how the guard would have been written with holes
in it. Enforced as an **allow-list** in `data_layer` — the worker may write only what it is granted,
so a destination nobody has thought about, and any writer added later, refuses by default.
**P5/S4a added the twelfth** (`connected_catalog.parquet`) and the allow-list made that additive:
nothing had to be re-classified, because the default was already deny.

| destination | owner | why |
|---|---|---|
| `derived/ledger` (**6** writers, not 4) | **laptop** | the certification spine; immutable, append-only, never leaves. `write_tune_proposals` and `write_center_gap` live here too |
| `derived/scoring` (2 writers) | **laptop** | SHARED by every league on a scoring key, and built under engine constants — propose-only, human-promoted |
| `derived/adp_points_curve` | **laptop** | the leak-free per-holdout curve; corpus-shaped, not per-league |
| `corpus/*` manifests (3 writers) | **laptop** | corpus selection is a human, versioned decision |
| `leagues.parquet` | **laptop** | whole-file overwrite of the shared registry — see the S4 wall below |
| `demo_manifest` / `synthetic_catalog` | **laptop** | the served catalog; generated, not harvested |
| `cache/` pinned players snapshot | **laptop** | an immutable versioned event (already write-once guarded) |
| `derived/league` (12 writers) | **worker** | per-league — this is the worker's job |
| the joins (3 writers) | **worker** | per-league |
| per-league raw (Sleeper teams/matchups/transactions) | **worker** | it is the fetcher |
| `cache/` player-id map + Sleeper registry | **worker** | a routine 24h refresh from Sleeper |
| **`connected_catalog.parquet`** (1 writer, P5/S4a) | **worker** | one row per connected `(league_id, season)`, **replaced not rewritten** — the only catalog a machine other than the laptop may touch, and the shape is the whole reason |

Measured 2026-08-13: `derived/ledger` **145 MB** · `derived/scoring` **16 MB** ·
`derived/league` **66 MB**.

### The wall P5/S4 hit — it was the CATALOG, not the registry

**This section previously named `write_leagues` and it was wrong.** Recorded as a correction rather
than edited away, because the ADR being confidently wrong about which artifact blocked onboarding is
the kind of thing the next session needs to know happened.

**The real wall: three whole-file catalog writers, and it is the last two that block the loader.**
`build_db._catalog()` was `read_demo_manifest() ⧺ read_synthetic_catalog()`, `_slices()` comes from
`_catalog()`, and `load_league` refuses anything absent from it. `demo_manifest.parquet` is the
frozen 31-row **corpus** slate the L2 ledger was derived from; `synthetic_catalog.parquet` is for
**generated** clones whose ids are deliberately not Sleeper-shaped. So there was nowhere a real
user's league row could legally live, and **nothing in this system had ever catalogued a league.**

**P5/S4a's answer, following S2d's precedent rather than arguing with it:** a **third** artifact,
`connected_catalog.parquet` — 31 + 1 + N. `data_layer.write_connected_league(df, league_id, season)`
writes or replaces exactly one row and leaves every other row untouched, sorted so a re-onboard
cannot reorder, and casting to the demo manifest's dtypes because `_catalog()`'s concat is polars'
**strict** `how="vertical"` (a dtype slip in one connected row would raise for the whole catalog,
i.e. take the demo down for every visitor).

**`write_leagues` was NOT touched, and here is why it is not on this path.** Every reader of
`leagues.parquet` — `_active_league` (53 call sites), `_active_league_any` (3), `league_resolver`,
`read_leagues` — filters `is_mine` **before anything else**, so a stranger row with `is_mine=False`
would be read by *nothing*. Its `pilot_cohort` column has no legal value for a connected league
(the map covers corpus strata only), and `assert_cold` treats presence in the registry as **not
cold**, so a row would permanently disqualify the league from ever being benchmarked. Two readers
do fire on a connected-league path and neither forces a row: `compute_bracket_sim:78` calls
`_active_league` unconditionally but `try/except`s it and uses it only for a seed-equality test a
stranger's league fails anyway, and `weekly_refresh._resolve_scoring_key`, which was a genuine bug
and is fixed in S4a from the league's own Sleeper settings. **The registry is an is_mine-scoped
default table. It is not the catalog.**

### The Postgres layer has a boundary too now (P5/S4a)

The whole-file-overwrite hazard this ADR is about **reappears at the database**. `reload_manifest()`
TRUNCATEs `league_catalog` and re-COPYs it from `_catalog()` **on the local store** — so a worker
calling it would publish its seeded snapshot over the real thing, deleting every league catalogued
since the last seed. Same shape, different layer, same answer:

- **`reload_manifest()` raises under `STORE_ROLE=worker`.** It is guarded in `build_db`, not in
  `data_layer`'s allow-list, because it writes Postgres rather than the file store — the allow-list
  covers destinations under `snapshots/`, and stretching it to cover a table would have hidden that
  distinction rather than stated it.
- The worker's scoped equivalent is **`build_db.upsert_catalog_row(conn, lid)`**: DELETE by
  `league_id` + INSERT, in the caller's transaction. Not `ON CONFLICT` — `league_catalog` has no
  primary key and no unique constraint, so there is no conflict target to name. `load_league(...,
  catalog=True)` runs it inside the load's own transaction, so a first connect is atomic:
  discoverable and readable together, or neither.

**Postgres stays the served truth.**

### "Reconstructible cache, lose the host and re-seed" — TRUE UNTIL S4a, NOW CONDITIONAL (2026-08-14)

This ADR said the worker's volume is *"a reconstructible cache, not precious data — lose the host,
re-seed it,"* and S3 earned that claim its first evidence. **S4a made it conditional, and the
condition is not automatic.** The worker is now the **author** of `connected_catalog.parquet` and of
every connected league's `derived/league/` artifacts. **The laptop has neither** — verified
2026-08-14: the file does not exist there, and `read_connected_catalog()` returns an *empty frame*
when absent, silently, by design. So **re-seeding from the laptop reconstructs a worker with no
connected leagues at all.**

The data is regenerable — re-run `onboard_league` per league, re-fetching from Sleeper — and the
recovery **list** exists in Postgres (`league_catalog` ⋈ `user_leagues`). **So the correct statement
is: the volume is reconstructible *from Postgres plus Sleeper*, not from the laptop.** That procedure
has never been run. By this ADR's own standard for S3 — *"'just re-seed it' is exactly the kind of
unverified figure that has cost this project three documented corrections"* — it is a claim until
somebody measures it.

### The clobber hazard runs LAPTOP → Postgres, not worker → Postgres

`reload_manifest()` refuses under `STORE_ROLE=worker` because it TRUNCATEs `league_catalog` and
re-COPYs from the local store. **After S4a the exposed direction is the opposite one.** Recomputed
2026-08-14: laptop `_catalog()` = **32** rows (31 demo + 1 synthetic + **0** connected); production
`league_catalog` = **33**. So `reload_manifest()` **on the laptop** deletes the connected league's
catalog row, and `build_db --load` drops its data rows as well.

Two things make it sharp: the documented remedy for an un-emitted column (`--emit` + `--load`) *is*
this failure, and the laptop's `build_db --verify` now legitimately reports **VERIFY FAILED** — so the
one alarm that would catch it has already been explained away as expected. **Guard: `reload_manifest`
and `load` must refuse when Postgres holds `league_id`s absent from the local `_catalog()`, naming
them. Assigned to P5/S4b.**

**Volume size — measured, not quoted.** Total `snapshots/` is **389 MB**; minus the ledger it is
**244 MB**, which is where the project's existing "~245 MB" figure comes from. That number **still
holds** (the first of these figures to survive re-measurement on this project). Provision with room:
`derived/league` grows per onboarded league at **~0.4 MB each** (measured across the ten league
directories on disk), so the cohort's growth is negligible against the substrate.

---

## Why this is a decision and not a detail

Today one machine writes derived data. S3 creates a second. From that moment two copies of the same
fact can disagree — and this failure has **no alarm attached**: nothing crashes, the site just serves
numbers built from a stale substrate. It is the same failure class as the isolation work in S2 (silent,
no feedback signal), which is why it gets decided before it gets built rather than after.

---

## THE CORRECTION — the rule as written is already violated by the code S3 plans to run

**This is the finding that justified writing the ADR before the brief.**

S3's definition of done says to *"run the existing pipeline unchanged"* on the worker. It cannot.

`serve/weekly_refresh.py:173-185` — the per-league refresh, i.e. **exactly the worker's job** —
detects a stale rest-of-season band and rebuilds it:

```
compute_ros_player_band.run(season, scoring_key=scoring_key)
```

which lands at `transforms/compute_ros_player_band.py:321` →
`data_layer.write_ros_player_band(df, season, scoring_key=scoring_key)` → a write into
**`derived/scoring/<key>/` — laptop-owned territory.**

So "the worker never sends anything back" is **not true of the code today**, and nothing enforces it.
It has been safe only because nothing but the laptop has ever run that path.

**Why this one is worse than a normal boundary violation:** `derived/scoring` is *shared*. A band is
keyed by scoring key, not by league, so a worker that rebuilds `ppr` touches the substrate **every ppr
league reads**. A per-league mistake damages one user; this damages all of them, from a code path that
fires automatically on drift detection.

It also collides with a standing rule: the band is built **under engine constants**, and engine
constants are *report-don't-tune, propose-only, human-promoted*. A machine that rebuilds the band
unattended is promoting constants without a human.

### The three ways out

| | what it means | verdict |
|---|---|---|
| **(a) Move `derived/scoring` to worker-owned** | Redraw the line; let the worker write the shared substrate | **Reject.** Makes the shared artifact the divergent one — the worst possible thing to put on the wrong side. |
| **(b) The band is READ-ONLY on the worker** ← **ACCEPTED (Will, 2026-08-13)** | Worker reads the substrate; if it is stale or missing, it **fails loudly** and that is a laptop job | Preserves one-directional flow, keeps constant-promotion human, and turns the rule into a property rather than a habit |
| **(c) Worker rebuilds and pushes back** | Two-directional | **Reject.** This is the divergence the rule exists to prevent. |

### What (b) costs, honestly

An operator step. When engine constants change, Will rebuilds the band locally and pushes it up
*before* the worker can serve leagues on that key. Between those two moments the worker refuses to
refresh rather than quietly building its own. **That refusal is the feature** — a loud stop beats a
silent divergence, and this is a once-a-season event (the annual re-tune), not a weekly one.

### CORRECTION from the build: a plain refusal would have bricked the worker

This ADR says the worker fails loudly "if it is stale or missing". **There was no staleness test
behind that sentence.** `weekly_refresh` rebuilds the band *unconditionally* for
`season >= FIRST_HONEST_BAND_SEASON` — deliberately, because an existence check passes on a stale
file, which is the drift it exists to catch. So a guard that simply refused `write_ros_player_band`
would have refused **every** 2026 refresh, not only the unsafe ones, and the worker could never have
onboarded a real league at all.

Worse, it would not have been caught: the S3 proving run is a **2025** replay, which takes the
`season < 2026` branch and never reaches the band. The session could have gone green and shipped a
worker that cannot do its job.

**So on a worker the writer VERIFIES instead of writing**, and distinguishes three outcomes:
identical → return and let the refresh proceed (reported, not silent); different → raise; missing →
raise. The comparison is **value**-identical via `data_layer.canonical_rows` — polars' parquet
writer is physically non-deterministic, so a byte comparison would have blocked the worker on
layout noise, which is the same outage by another route.

*Proven on the live worker, 2026-08-14, against the real 2026 ppr substrate: identical → proceeds;
one field perturbed by +0.1 → raises with the operator step; restored → proceeds again.*

---

## How it gets enforced — one seam, and prove it bites

**A rule with nothing enforcing it is a comment.** I checked whether the boundary could be enforced by
simply not shipping the ledger-writing code to the worker. **It cannot:** `weekly_refresh.py:38` and
`bench_cold_league.py:46` both import `compute_spine` and `harvest` from `data/corpus/`, the same
package that holds the ledger writers (`corpus/compute_engine_scorecard.py:600`). **`data/corpus/`
straddles the boundary**, so omission is not available.

So enforce it where every write already passes — `data_layer`, the module the CODING_BIBLE already
names as *"the only code that knows where data lives."* Same shape as S2b's authorization seam:

- A worker-mode flag (env, like `SNAPSHOT_BACKEND`) makes the **laptop-owned writers raise** —
  `write_ros_player_band`, `write_projection_consensus`, and every `derived/ledger` appender.
- **Not a filesystem permission.** A read-only mount produces an `OSError` from inside a transform,
  which reads as a bug; an explicit raise names the boundary and the remedy.
- **Prove it bites:** run the guard on, call a laptop-owned writer, assert it raises — and assert a
  worker-owned write still succeeds. *A refusal alone proves nothing; test both halves.*

---

## The mount path is not free-choice — a constraint S3 must design around

`data_layer.py:8-9`:

```
_HERE = Path(__file__).resolve().parent
_SNAPSHOT_DIR = _HERE / "snapshots"
```

The store root is **hardcoded relative to the source file**, not configurable. So either the volume
mounts exactly at `<app>/application/data/snapshots`, or `_SNAPSHOT_DIR` becomes env-configurable.
**Prefer the mount** — changing the path resolution touches every read in the system for no gain, and
`SNAPSHOT_BACKEND` already establishes env-first configuration as the pattern if it is ever needed.

---

## Alternative considered and rejected: use the Supabase bucket instead of a volume

P1 already built `_SupabaseSnapshotStore` — an S3-compatible object backend selected by
`SNAPSHOT_BACKEND=supabase`, where "the object key is the snapshot path relative to `_SNAPSHOT_DIR`,
so the on-disk hierarchy maps 1:1 to bucket keys." Reusing it would make the worker **stateless** and
retire the volume, the single-host pinning, and the whole re-seed problem.

**Rejected for S3, deliberately, and it is closer than it looks.** Its docstring is explicit that it
serves *"the diskless CI collectors"* and that **"only the two raw collector series are wired through
it; every other read/write in this module keeps its direct local-path IO."** Routing the full pipeline
through it is a real project — it downloads on first access and uploads at `flush()`, which is a
sensible batching model for a daily bank and an unproven one for a multi-minute pipeline over ~244 MB.

**But record it as the exit.** If the volume's single-host pinning becomes painful — one bad host and
the cohort's onboarding stops — this is the way out, and it is *partially built*. Revisit at P6 or
post-launch, not at S3.

---

## Consequences — including the one nobody has measured

1. **The worker is a stateful singleton, not a pool.** Fly volumes attach to exactly one machine and
   are pinned to a physical host. Correct for an invited cohort; it does not scale by adding machines.
2. **It must be a separate Fly app from the API** — do not entangle the API's scale-to-zero with a
   multi-minute job.
3. **"Reconstructible cache" is a CLAIM, not a measured fact.** Nobody has ever rebuilt this volume.
   **S3 must measure the re-seed, not assert it** — how the 244 MB gets there the first time, how long
   it takes, and what the operator actually runs. Until that number exists and is date-stamped, the
   phrase "just re-seed it" is exactly the kind of unverified figure that has cost this project three
   documented corrections (the Fly machine count, the RLS table count, `posture.js`).
4. **Byte-parity needs a named artifact.** S3's DoD says the worker's output must match a local run.
   Name the comparison before the session: `serve/bench_cold_league.py` is already committed for the
   worker to re-run unchanged, and `check_scoped_reload.py` already holds a parity oracle. Use them
   rather than inventing a new one. Say **value**-identical unless comparing bytes — polars' parquet
   writer is physically non-deterministic.
5. **P5/S0's sizing stands:** 1 GB `shared-cpu-1x` + a 1 GB volume, ~$7/mo flat to 200 leagues. The
   volume figure is comfortable against a measured 244 MB.

## The decision, recorded

**Will accepted (b) on 2026-08-13**, on this reasoning:

**(c) is ruled out on principle, not cost.** Two machines writing the same fact and reconciling is the
classic distributed-data problem and this project has no mechanism for it. It would leave two versions
of a shared artifact with no way to say which is correct — and because nothing crashes, the first
alarm would be a user.

**(a) vs (b) is narrower than it looks** — both keep exactly one writer, so the only question is which
machine holds the pen. Two facts settle it. The worker's disk is **explicitly disposable** (the design
says lose the host and rebuild), so (a) puts the most-shared, most-consequential artifact on the
machine we are prepared to throw away. And changing this artifact means changing **engine constants**,
which are human-approved by standing rule — so the pen belongs where the human is.

**What (b) costs, accepted with eyes open:** when engine constants change (realistically the annual
re-tune, ~February), the worker refuses to onboard leagues on that scoring key until Will rebuilds the
substrate locally and pushes it up.

**The refusal is the point, not the price.** It is the same instinct as the rest of the product — the
UI prints `<1%` rather than `0%` because a confident wrong answer is worse than an honest stop. This is
that principle applied to infrastructure: a machine declining to build something it is not authorised
to build, rather than silently producing a version nobody approved. The failure it prevents is the kind
with no alarm attached — nothing errors, the site just serves numbers built from a recipe that was
never signed off, to everyone, until somebody happens to notice.
