# P5 · S3 — PM audit of the worker and the store boundary

**Audited:** 2026-08-14 · **Report:** `SESSION_P5_S3_REPORT.md` · **Brief:**
`SESSION_P5_S3_WORKER_AND_STORE_BOUNDARY.md` · **ADR:** `context/appendices/store-boundary.md` ·
**Range:** `719439c..e44e87e` (3 commits + merge + a docs tidy) ·
**Verdict: ENDORSED — but S3 is NOT CLOSEABLE YET.** One half of its DoD is outstanding by design,
and it needs Will.

---

## THE OPEN ITEM — the worker has never written Postgres

S3's DoD: *"The full pipeline completes on the worker for a replay league **and lands in Postgres**,
byte-parity with a local run."* The proving run used **`--no-load`**, because `DATABASE_URL` is the
one secret the worker needs and secrets are Will's to set.

So the pipeline half is proven and the **landing half is not**. The report says so plainly rather
than rounding up, which is the right call — but it means **S3 stays open until Will sets the worker's
secrets and the replay is re-run with the load enabled.** Do not mark it done on the strength of the
proof table.

**And the deploy claim is unverifiable from the PM seat.** *"New Fly app deployed."* The worker
deliberately has **no `http_service`**, so the technique that caught S2e's undeployed merge — fetching
a live URL — does not exist here. **Will: `fly status -a fantasy-ai-worker` and
`fly releases -a fantasy-ai-worker`.** Deploy is a separate gate from merge, and this is the one
session where nobody outside it can check.

---

## Verified independently — recomputed, not read

| claim | verified |
|---|---|
| `canonical_rows` **moved**, not duplicated | ✅ `data_layer.py:139`; `check_scoped_reload.py:55` is `_canon = data_layer.canonical_rows` — a re-export. Dependency direction is right (that module imports `build_db` → `data_layer`, so it could only move down) |
| `STORE_ROLE=worker` on **both** non-laptop machines | ✅ `fly.worker.toml:20` **and** `.github/workflows/weekly_refresh.yml:61` — the "three machines, one writer" reframe is built, not just asserted |
| ADR re-stamped and reframed | ✅ *Current as of 2026-08-14*, status **ACCEPTED and BUILT**, one-writer model at the head |
| separate Fly app, mount path, no server | ✅ `app = "fantasy-ai-worker"`, mount → `/app/application/data/snapshots`, **no `[http_service]`** with the reasoning written beside it |
| seed **measured**, not asserted | ✅ **37s**, decomposed 6s tar / 18s upload / 13s extract, 244 MB → 248 MB (28% of 1 GB), date-stamped, with the exact commands |
| §7 respected | ✅ STATUS **+73 / −55**, ARCHITECTURE **+15 / −3** — genuinely replacing, not appending |
| the guard's 2am message | ✅ names writer, role, cause, the boundary + its doc, and a `Remedy:` line — and its docstring says why a generic "permission denied" would be wrong |
| `worktree-setup.sh` repaired | ✅ `link_children` links the ten gitignored children and leaves the tracked one real |

*(One near-miss of my own: my first grep for the commit-floor rule was case-sensitive and briefly
said it had been deleted from `CODING_BIBLE`. It is there at `:88`. Third time today I have nearly
reported an artifact of my own method as a finding.)*

## What this session did unusually well

**It refused to accept its own passing proof.** The first parity run reported **seven skips** — every
step saying *"already banked / already covers"*, because the seeded volume was already at week 5.
That is a run that passes because it did nothing. Code deleted the five spine reads from the volume
(safe: it is a disposable cache, which is the ADR's own claim being used correctly) and re-ran to
force a genuine recompute. **Applying *a proof that passes because it never exercises the path is
weak* to its own evidence, unprompted, is the strongest thing in this report.**

**Finding D is the mirror of the defect the session was built to fix.**
`compute_ros_player_band.run()` *printed* a write it had not performed — a silent skip pointing the
other way. It surfaced only in the live 2026 exercise, which is precisely why that exercise was
protected from the release valve.

**Finding B is real operational knowledge.** `COPYFILE_DISABLE=1` is mandatory seeding from macOS:
without it the first seed shipped **16,089** AppleDouble `._` sidecars, inflated 248 MB → 311 MB, and
made parquet globs raise `ComputeError: file must end with PAR1` on files that were never parquet.
That is a 2am-during-recovery trap, found only because the brief insisted the seed be *measured*.

**Finding F upgraded exactly as asked** — `corpus_discovery` is now characterised as a live break
with its call sites named (`build_demo_manifest:54`/`:136`, `build_substrate:54`; only
`discover.py:103` is guarded), and the right remedy identified: **restore, not rebuild**, since
re-crawling could return a different candidate set.

## Finding — the release valve looks to have been taken silently

The brief named the **worker-vs-laptop timing comparison** (`bench_cold_league --json` both sides,
diffed) as the release valve if the commit cap bit. **The report never mentions `bench_cold_league`
at all** — no result, and no statement that it was deferred.

Taking the valve is fine; that is what it is for. **Taking it without saying so is not** — the
project's own rule is *no silent caps: if coverage is bounded, log what was dropped*, because
otherwise a report reads as complete coverage when it isn't. One line in the report closes this:
either the numbers, or "deferred, and here is the follow-up."

## My own error, inherited by this session

**Finding C is a consequence of my decision, not a pre-existing bug.** Tracking `snapshots/corpus/`
in git — my closedown item on the recovery brief — made the whole-directory symlink impossible, so
`worktree-setup.sh` left new worktrees with a **280 KB stub of the 389 MB store**. It bit this
session on its rebase.

I made a durability decision without tracing its effect on the worktree tooling — *"unreachable is a
claim about every caller"* applied to a **tooling** change rather than a code one. Code found it and
fixed it properly (link the children, leave the tracked directory real, and clear an empty leftover
that silently blocked the link). **The decision was still right; the blast-radius check was mine to
do and I didn't.**

## Verdict

**Endorsed.** The boundary is built before the machine that could violate it, the seed number is
measured and decomposed, the ADR is current, and the session audited its own proof harder than I
would have. **Two things stand between S3 and closed:** the worker's `DATABASE_URL` and a replay
re-run that actually lands in Postgres, and a `fly status` confirming the deploy.
