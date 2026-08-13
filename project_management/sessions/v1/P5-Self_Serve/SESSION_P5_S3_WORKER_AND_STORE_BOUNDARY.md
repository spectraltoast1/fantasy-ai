# V1 · P5 · Session S3 — The Fly worker and the store boundary

**Written 2026-08-13.** **Status: READY — paste-block below.**
**Prior:** `context/appendices/store-boundary.md` (the ADR — **ACCEPTED, option (b)**) ·
`SESSION_P5_S0_REPORT.md` (the latency spike that sized this).
**Goal: the laptop stops being infrastructure.**

> **What this session does:** stands up a second machine that can build a user's league without Will's
> laptop being on — and, first, builds the boundary that stops that machine writing things it must not.

---

## Why the boundary comes before the worker

The ADR found that **S3 cannot "run the existing pipeline unchanged,"** which is what the P5 doc's DoD
says. `serve/weekly_refresh.py:173-185` rebuilds a stale `ros_player_band` into `derived/scoring/` —
laptop-owned. That artifact is **shared across every league on a scoring key** and is built under
**engine constants**, which are propose-only and human-promoted.

So the order matters: **build the guard, then build the machine that could violate it.** One
architectural change at a time, and the worker never runs a single unguarded minute.

## 1 · The write guard — one seam, defaults to today's behaviour

Enforce in **`data_layer`**, which the CODING_BIBLE already names as *"the only code that knows where
data lives."* Same shape as S2b's authorization seam: one predicate, one place, no caller repeats it.

- **Env-first, mirroring `SNAPSHOT_BACKEND`** (that pattern is already established in this module).
  Default = laptop = **today's behaviour exactly**. Nothing changes unless the worker sets it.
- With worker mode on, the **laptop-owned writers raise**: `write_ros_player_band`,
  `write_projection_consensus`, and every `derived/ledger` appender
  (`write_predictions` / `write_outcomes` / `write_resolutions` / `write_engine_scorecard`).
- **An explicit raise, NOT a read-only mount.** An `OSError` surfacing from inside a transform reads as
  a bug and sends the next person debugging filesystem permissions. A raise names the boundary, the
  reason, and the remedy ("rebuild locally and push up").
- **The error must be actionable at 2am.** It is the only thing Will will see when the annual re-tune
  makes the substrate stale, and `OPERATIONS.md` should gain the one-line remedy.

**Enforcement by omission is NOT available — do not attempt it.** I checked: `weekly_refresh.py:38`
and `bench_cold_league.py:46` import `compute_spine`/`harvest` from `data/corpus/`, the same package
that holds the ledger writers (`corpus/compute_engine_scorecard.py:600`). **`data/corpus/` straddles
the boundary**, so the worker cannot simply be shipped without it.

## 2 · The worker — a separate Fly app, and a stateful singleton

- **A SEPARATE Fly app from `fantasy-ai-api`.** Non-negotiable: do not entangle the API's
  scale-to-zero with a multi-minute job.
- **Fly volumes attach to exactly one machine and are pinned to a physical host** — no multi-attach, no
  moving. The worker is a **stateful singleton**, not a pool. That is the right shape for an invited
  cohort and it is a known limit, not an oversight.
- **Sizing from S0: 1 GB `shared-cpu-1x` + a 1 GB volume** (~$7/mo flat to 200 leagues). Comfortable
  against a **measured 244 MB**.
- **The volume must mount at `<app>/application/data/snapshots`.** `data_layer.py:8-9` computes
  `_SNAPSHOT_DIR` from the source file's location and it is not configurable. Mounting is the cheap
  answer; making the path env-first touches every read in the system for no gain **unless the mount
  proves impossible — then env-first, and say so.**
- **Its own secrets.** `DATABASE_URL` and friends are secrets on the API app; the worker needs its own
  set. Do not assume they are shared.
- **No queue, no connect endpoint** — a manually triggered run. Those are S4.

## 3 · Seeding — and the number nobody has ever measured

The volume takes **everything except `derived/ledger`**: measured **389 MB total − 145 MB ledger =
244 MB**. (`derived/scoring` 16 MB, `derived/league` 66 MB and growing ~**0.4 MB per onboarded league**,
plus the joins and raw substrate.)

**"Reconstructible cache, lose the host and re-seed it" is a CLAIM. It has never been done.** Seeding an
empty volume *is* the recovery procedure, so this session produces the recovery number for free —
**but only if it is measured and date-stamped rather than asserted.** Three documented figures on this
project turned out never to have been measured; this is the one that gets read under stress.

Deliverable: the **exact operator command** and the **measured wall-clock**, into `OPERATIONS.md`.

## 4 · Proving it

- **Value-identical, not byte-identical.** `check_scoped_reload` already establishes why and how: COPY
  row order is nondeterministic, so it compares a canonical row multiset. Reuse that comparator rather
  than inventing one.
- **`serve/bench_cold_league.py` was committed by S0 specifically so S3 re-runs it unchanged.** Use it.
- **The real DoD is a demonstration, not a log line:** Will powers his laptop off, and a league still
  builds end to end.

## Scope guard

Does **NOT**: build the job queue or the connect endpoint (**S4**); fix
`weekly_refresh._resolve_scoring_key`'s owner-key fallback (**S4 owns it** — but *confirm* the replay
path does not hit it, and say so); route the pipeline through the Supabase bucket backend (the ADR
records that as the deliberate **exit**, not this session); touch engine constants, the corpus, the
frozen corpus, or any transform's maths.

**Named release valve** (this project's own pattern — S2d's valve became S2e): if the 3-commit cap
bites, ship the **correctness** proof and defer the **worker-vs-laptop timing comparison** from
`bench_cold_league` to a short follow-up. Correctness is the DoD; the timing delta is information.
**The seed measurement is NOT the valve** — it is the recovery number.

---

## The brief to paste to Code — S3

```
Goal: V1 Project 5, Session S3 (projects/v1/P5_ACCOUNTS_SELF_SERVE_ONBOARDING.md) — stand up the Fly
worker so the laptop stops being infrastructure, and FIRST build the store boundary that stops the
worker writing what it must not.

Read first: context/appendices/store-boundary.md (the ADR — ACCEPTED, option (b); it CORRECTS the P5
doc's S3 row), sessions/v1/P5-Self_Serve/SESSION_P5_S3_WORKER_AND_STORE_BOUNDARY.md (this brief),
SESSION_P5_S0_REPORT.md, context/CODING_BIBLE.md, OPERATIONS.md, SESSION_GUIDE.md. Check the brief
against observable reality before executing.

THE P5 DOC'S DoD IS WRONG AND THE ADR SUPERSEDES IT. It says "run the existing pipeline unchanged."
You cannot: serve/weekly_refresh.py:173-185 rebuilds a stale ros_player_band via
compute_ros_player_band.run() -> data_layer.write_ros_player_band() -> derived/scoring/<key>/, which is
LAPTOP-OWNED. That artifact is SHARED by every league on that scoring key and is built under engine
constants (propose-only, human-promoted), so an unattended worker rebuilding it promotes constants for
every user at once.

1. THE WRITE GUARD — BUILD THIS FIRST, before the worker exists.
   One seam in data_layer (the CODING_BIBLE's "only code that knows where data lives"). Env-first,
   mirroring the existing SNAPSHOT_BACKEND pattern in that module. Default = laptop = TODAY'S BEHAVIOUR
   EXACTLY; nothing changes unless the worker sets it.
   In worker mode these RAISE: write_ros_player_band, write_projection_consensus, and every
   derived/ledger appender (write_predictions, write_outcomes, write_resolutions,
   write_engine_scorecard).
   An EXPLICIT RAISE, not a read-only mount: an OSError from inside a transform reads as a bug and
   sends the next person debugging filesystem permissions. The message must name the boundary and the
   remedy ("rebuild locally and push up") — it is what Will sees at the annual re-tune.
   DO NOT try to enforce by omitting data/corpus from the worker image: weekly_refresh.py:38 and
   bench_cold_league.py:46 import compute_spine/harvest from that package, which ALSO holds the ledger
   writers (corpus/compute_engine_scorecard.py:600). data/corpus straddles the boundary.
   PROVE IT BITES, BOTH HALVES: with the flag on, a laptop-owned write raises; a worker-owned write
   (derived/league, the joins) still SUCCEEDS. A refusal alone proves nothing.
   PARITY: with the flag off, every existing check stays green and no number moves.

2. THE WORKER — a SEPARATE Fly app from fantasy-ai-api. Non-negotiable: do not entangle the API's
   scale-to-zero with a multi-minute job. 1 GB shared-cpu-1x + a 1 GB volume (S0's sizing).
   Fly volumes attach to ONE machine and are pinned to a physical host, so this is a stateful
   singleton, not a pool — that is intended.
   THE VOLUME MUST MOUNT AT <app>/application/data/snapshots. data_layer.py:8-9 derives _SNAPSHOT_DIR
   from the source file's location and it is NOT configurable. If the mount genuinely cannot be placed
   there, make _SNAPSHOT_DIR env-first instead — and say which you did and why.
   The worker needs its OWN Fly secrets (DATABASE_URL etc.); do not assume the API's are shared.
   NO queue and NO connect endpoint — a manually triggered run. Those are S4.

3. SEED THE VOLUME, AND MEASURE IT. Contents = everything EXCEPT derived/ledger. Measured 2026-08-13:
   snapshots/ total 389 MB, ledger 145 MB, so 244 MB goes up (derived/scoring 16 MB, derived/league
   66 MB at ~0.4 MB per league, plus joins and raw substrate).
   "Reconstructible cache — lose the host and re-seed it" is a CLAIM that has NEVER been tested.
   Seeding an empty volume IS the recovery procedure, so measure it: the exact operator command and the
   wall-clock, written into OPERATIONS.md and DATE-STAMPED. Do not assert a number you did not measure.

4. PROVE IT.
   - The full pipeline completes ON THE WORKER for a replay league and lands in prod Postgres.
   - Parity is VALUE-identical, not byte-identical — COPY row order is nondeterministic. Reuse
     check_scoped_reload's canonical row-multiset comparator; do not invent another.
   - Re-run serve/bench_cold_league.py UNCHANGED on the worker. S0 committed it for exactly this.
   - The real proof is a demonstration: with Will's laptop OFF, a league builds end to end.
   - Confirm the replay path does NOT hit weekly_refresh._resolve_scoring_key's owner-key fallback, and
     say so explicitly. Do not fix it — S4 owns it.

Scope guard — does NOT: build the job queue or connect flow (S4); fix _resolve_scoring_key (S4); route
the pipeline through the Supabase bucket backend (the ADR records that as the deliberate EXIT, not this
session); touch engine constants, any transform's maths, the corpus or the frozen corpus.

Release valve if the 3-commit cap bites: ship the CORRECTNESS proof and defer the worker-vs-laptop
TIMING comparison from bench_cold_league to a short follow-up. The seed measurement is NOT the valve —
it is the recovery number.

Suggested commit map (3): (1) the guard + its prove-it-bites check; (2) the worker app, volume and
seed, with the measured seed time; (3) the proving run + docs.

Follow SESSION_GUIDE.md: fresh worktree, <=3 commits, update STATUS.md + ARCHITECTURE.md per §7
(replace, don't append) and OPERATIONS.md (the seed/recovery procedure + the guard's remedy), then
close/merge/push. This creates a NEW Fly app — deploying it is part of the session, and "merged" is not
"deployed." Sweep .git for stale lock files at closedown.
```

## Will's checks after

1. **The demonstration, not the log:** laptop off, trigger a build, watch a replay league land in
   Postgres.
2. **The guard's error message** — read it as if it is 2am in February and the substrate is stale. Does
   it tell you what to do?
3. **`OPERATIONS.md` carries a measured, date-stamped seed time** — not "a few minutes".
