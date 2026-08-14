# V1 · P5 · S3 — The Fly worker and the store boundary

**Shipped 2026-08-14.** **Brief:** `SESSION_P5_S3_WORKER_AND_STORE_BOUNDARY.md` ·
**ADR:** `context/appendices/store-boundary.md` (ACCEPTED option (b), now BUILT).
**3 commits.** New Fly app deployed. No outage — the worker serves no traffic.

> **The laptop is no longer the only machine that can build a league** — and the guard that stops
> that machine writing what it must not was built *first*, so the worker never ran an unguarded
> minute.

---

## What shipped

### 1 · The boundary — one predicate, one place

Enforced in `data_layer`, the module the CODING_BIBLE already calls *"the only code that knows where
data lives"*. Same shape as S2b's authorization seam. Enforcement by **omission** was checked and is
unavailable: `data/corpus/` holds both `harvest`/`compute_spine` (which the worker must run) and the
ledger writers, so the package straddles the boundary.

**The rule is ONE WRITER, not laptop-vs-worker.** The ADR's model had two machines; there are
**three** — the laptop, the Fly worker, and the GitHub Actions runner, which writes prod Postgres on
a cron. Stated by role, `STORE_ROLE=worker` is set on both non-laptop machines.

**Allow-list, not deny-list**, so a destination nobody has classified — and any writer added later —
refuses by default. The ADR's 3-row ownership table is now **11 rows**; the brief's "four ledger
appenders" is **six**.

### 2 · The band verifies instead of refusing — the finding that mattered

`weekly_refresh` rebuilds `ros_player_band` **unconditionally** for `season >= 2026` (deliberately:
an existence check passes on a stale file). So a plain raise-on-write guard would have refused
**every** 2026 refresh, not just the unsafe ones, and **the worker could never have onboarded a real
league.**

It would not have been caught, either. The proving run is a **2025** replay, which takes the
`season < 2026` branch and never reaches the band — the session could have gone green and shipped a
worker that cannot do its job. That is why the DoD carried a 2026 exercise.

On a worker the writer compares and distinguishes three outcomes: **identical** → return, refresh
proceeds, and `weekly_refresh` *logs it* (a skip nobody logs is indistinguishable from a step that
never ran); **different** → raise; **missing** → raise. **Value**-identical via
`data_layer.canonical_rows` — moved down from `check_scoped_reload` rather than reimplemented, since
that module imports `build_db` which imports `data_layer`, so the dependency could only run one way.

### 3 · The worker

Separate Fly app, `iad`, 1 GB `shared-cpu-1x` + 1 GB volume, no `http_service`. Its own
`Dockerfile.worker` — the API's image installs `api/requirements.txt` (no polars) and its
`.dockerignore` excludes a bare `data`, which drops the pipeline **source**, not just the runtime.

**The mount path is not a choice:** `data_layer._SNAPSHOT_DIR` is computed from the source file's own
location, so the volume lands where the code already looks.

### 4 · Consolidating `frozen_writers` was a bug fix

Three rescore gates each carried a hand-maintained copy and **all three had drifted** —
`check_debias` 4 entries, `check_band_honesty` 5, `check_center_shrink` 6 — so two of them would
**not** have caught a `write_center_gap` call during a rescore. They now share
`LAPTOP_OWNED_WRITERS`.

---

## Proof

| what | result |
|---|---|
| `check_store_boundary.py --prove-bites` | **21/21 green**; the neutered guard **fails all 10** |
| Damage check (`git status` under `snapshots/`) | **clean** — corpus 271 rows, flags 10 |
| 2026 exercise (a) identical | **proceeds**, no raise, file untouched |
| 2026 exercise (b) perturbed +0.1 | **raises**, names the staleness and the operator step |
| 2026 exercise (c) restored | **proceeds** again |
| Worker pipeline, 2025 replay | spine **recomputed** on the worker |
| Parity, laptop vs worker | **10/10 artifacts** value-identical (canonical row multiset) |
| Seed | **37s**, 244 MB → 248 MB on the volume, 28% full |

**The parity run was made real on purpose.** The first attempt reported seven skips — every step
said "already banked / already covers" because the seeded volume was already at week 5. That is a
run that passes because it did nothing. The five spine reads were deleted from the volume (safe: it
is a disposable cache) and the run repeated, which forced a genuine recompute.

**`_resolve_scoring_key` did NOT hit the owner-key fallback** — the league is in the catalog, so
`weekly_refresh.py:44-46` matched on `(league_id, season)` and line 47 was unreachable. Confirmed on
the worker, **not fixed — S4 owns it.**

**What is NOT proven, stated plainly.** *"Will powers his laptop off and a league still builds"* — I
run on the laptop and cannot demonstrate that. What is proven is that the worker builds from its own
volume with **no laptop in the data path**; the laptop only sent the trigger. The remaining gap is
the **Postgres write**: the proving run used `--no-load`, because `DATABASE_URL` is the one secret
the worker needs and secrets are Will's to set. **That is the one piece of the DoD outstanding.**

---

## Findings

**A · `cache/` is load-bearing and the volume does not cover it.** Neither brief nor ADR mentions it.
`_CACHE_DIR` is a *sibling* of `snapshots/`, and `join_nfl_sleeper_weekly` + `compute_player_signal`
both read the pinned players registry from it — `weekly_refresh` runs both, so a worker without it
fails on its first league. It is now **symlinked onto the volume**. Baking it into the image was the
first attempt and **cannot work from a worktree**: there `data/cache` is a symlink into main, and a
Docker context will not follow a symlink out of its root. The volume is better anyway — the cache
survives restarts, and the pinned snapshot sitting on a mutable volume is safe *because* the guard
makes it read-only there.

**B · `COPYFILE_DISABLE=1` is mandatory when seeding from macOS.** The first seed shipped **16,089**
AppleDouble `._` sidecars onto the volume, inflating it from 248 MB to 311 MB and making
`*.parquet` globs raise `ComputeError: file must end with PAR1` on files that were never parquet.
The measured 37s and the OPERATIONS command are both the corrected version.

**C · `worktree-setup.sh` was broken by the corpus recovery, and it broke this session.** Tracking
`snapshots/corpus/` makes the whole-directory symlink impossible: git materialises the tracked files
at that path, replacing the link, and the worktree is left with a **280 KB stub of the 389 MB
store**. It happened here on the rebase. The script now links the ten gitignored **children** and
leaves the tracked one real, and clears an *empty* leftover directory (a check script that creates
and sweeps a throwaway path leaves exactly that, and it silently blocked the link).

**D · `compute_ros_player_band.run()` printed a write it had not done.** On a worker it printed
`→ snapshots/…` after merely verifying — the same defect as a silent skip, pointing the other way.
Caught by the first live 2026 exercise; now role-aware.

**E · The GHA workflow's hazard is real but manual-only.** I had justified guarding it as *"already
on a cron twice weekly"*. **That was wrong** — the `--live` path has never worked and dies at
`shared/league_resolver.py` before any pipeline step, because its hardcoded `LEAGUE_ID` is a 2025
league and the resolver now asks Sleeper for 2026. A manual `workflow_dispatch` in replay mode
bypasses the resolver and *would* reach the band, so the one env line still earns its place — as
defence in depth, not as closing an actively firing hole. S4 guts that file anyway.

**F · `corpus_discovery.parquet` is a live break, not a missing file nobody reads** (out of scope —
named follow-up). `read_corpus_discovery` is a bare `pl.read_parquet`, so every unguarded caller
raises today. The two that matter are both in `build_demo_manifest` (`:54` `_prev_map`, `:136`
`build`) — a module the project re-runs; P5/S2d used it. Also `build_substrate.py:54`. Only
`discover.py:103` is safe (gated on `corpus_discovery_exists()`). It wants a **restore**, not a
rebuild: re-running `discover.py` re-crawls Sleeper and could return a different candidate set.

---

## Deliberately not done

The job queue and connect flow (**S4**) · `_resolve_scoring_key`'s fallback (**S4** — confirmed only)
· `write_leagues`' whole-file overwrite shape, the wall S4 hits when the worker must catalog a league
(**documented in the ADR, not fixed**) · disabling the GHA cron (its replacement is unproven; don't
retire a fallback first) · the Supabase-bucket backend (the ADR's recorded exit) · the corpus audit's
two chips (the ~41 excluded rows, `selected_at` provenance).
