# ADR — The store boundary: what the laptop owns, what the worker owns

**Current as of: 2026-08-13.** **Status: PROPOSED — Will to accept before P5/S3 is briefed.**
**Scope:** P5/S3 (the Fly worker). **Supersedes:** the four-bullet rule in
`projects/v1/P5_ACCOUNTS_SELF_SERVE_ONBOARDING.md` § Context, which this expands and **corrects**.

---

## The decision

Data flows **one direction only: laptop → worker.**

| | owns (may write) | measured 2026-08-13 |
|---|---|---|
| **Laptop** | `derived/ledger` — the certification spine, never leaves | **145 MB** |
| **Laptop** | `derived/scoring` — the shared scoring-keyed substrate, authored locally, pushed up | **16 MB** |
| **Worker** | `derived/league` + the joins | **66 MB** (`derived/league`) |

**Postgres stays the served truth.** The worker's volume is a **reconstructible cache, not precious
data** — lose the host, re-seed it.

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
| **(b) The band is READ-ONLY on the worker** ← **RECOMMENDED** | Worker reads the substrate; if it is stale or missing, it **fails loudly** and that is a laptop job | Preserves one-directional flow, keeps constant-promotion human, and turns the rule into a property rather than a habit |
| **(c) Worker rebuilds and pushes back** | Two-directional | **Reject.** This is the divergence the rule exists to prevent. |

### What (b) costs, honestly

An operator step. When engine constants change, Will rebuilds the band locally and pushes it up
*before* the worker can serve leagues on that key. Between those two moments the worker refuses to
refresh rather than quietly building its own. **That refusal is the feature** — a loud stop beats a
silent divergence, and this is a once-a-season event (the annual re-tune), not a weekly one.

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

## Open question for Will

**(b) is a recommendation, not a decision.** It trades an occasional manual step for a guarantee that
no machine can quietly rebuild the shared substrate. If you would rather the worker be able to rebuild
the band unattended, say so — but then the ledger-style protection has to move somewhere else, because
the "never sends anything back" rule stops being true and the annual re-tune stops being human-gated.
