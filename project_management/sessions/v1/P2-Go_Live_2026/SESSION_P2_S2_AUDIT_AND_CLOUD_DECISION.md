# P2 · S2 Audit + Cloud-Execution Decision

**Reviewed:** 2026-07-28 · **By:** PM (live git + the loader/orchestrator diffs + Code's escalation memo).
Commits `2725f81` (scoped-reload loader + parity oracle), `59cfd79` (orchestrator), `7858fbe` (prod proof +
cron), `f3ed956` (CI config fix) + merges on `main`, pushed. Report: `…/P2-Go_Live_2026/SESSION_P2_S2_REPORT.md`.

**Bottom line: the core of S2 succeeded — endorse it — and Code's escalation is accurate and well-judged. The
riskiest change in all of V1 (swapping the production loader to a per-league scoped reload) landed safely with
byte-parity and idempotency proven on the production database; the engine can now advance a league a week at a
time. Code then hit a real limit — the refresh can only run where the derived store lives (locally), so it
can't run unattended in the cloud without a cross-cutting data-layer refactor — and flagged it honestly
instead of quietly building it. My call: endorse the core; do NOT do the cloud refactor now; re-home it as a
prerequisite of P5 (not a P6 afterthought); don't pre-commit to the "full refactor" approach; quiet the failing
cron; continue P2 with S3.**

## Verified — the un-freeze works (this is the win)

- **The scoped-reload loader is correct and safe.** `load_league()` does, in one transaction, a DELETE of a
  league's rows across the 13 data tables + a re-COPY of its slice — other leagues and the catalog untouched,
  **never DROP/CREATE**. The full `--load` stays as the fallback *and* the parity baseline. A dedicated
  parity oracle (`check_scoped_reload.py`) proves scoped == full.
- **Proven on prod, with the guard I insisted on.** The orchestrator advanced the owner's 2025 league
  **week 4 → 5 on the production DB**: join wk5 → recompute spine → scoped reload; `load_weeks` now returns
  [1..5]; a re-run is a clean **no-op**; a second league is **untouched**; the parity oracle stays green at the
  advanced state. That's the exact definition of done, met.
- **Scope held.** Loader + orchestrator + the new `weekly_refresh.yml` + a couple of honest enabling fixes
  (a `diagonal` column-align on the join append; declaring `numpy`; env-first config resolution so the loader
  imports without the gitignored `config.py`). No frontend, no auth.

## The gap — accurate, and I'd reframe where it belongs

Code's diagnosis is right: the whole data layer reads/writes the derived store from **local disk**, and P1's
Supabase-bucket backend is wired into only the narrow daily-collector path — so the refresh, which touches the
general store (catalog, join, substrate, spine), fails on a stateless cloud runner's empty disk. Running it
unattended in the cloud is a real, cross-cutting refactor, not a config toggle.

**One reframe on Code's prioritization, and it matters:** Code homed this in "P6 / ops." But the very same
capability — *run the ingestion pipeline in the cloud with the store accessible* — is what **P5's self-serve
onboarding requires**: when a user connects their league, that fetch→join→spine→load pipeline has to run
on-demand in the cloud, not on someone's laptop. So this is better understood as a **P5 prerequisite**, not a
weekly-cron nicety for P6. Same problem, and P5 can't ship without it.

## Why we do NOT do it now

- **Nothing is driving it yet.** It's preseason — no 2026 games, so the weekly refresh has nothing to advance;
  and there are no real users yet (P5 hasn't happened). Both triggers are still months off.
- **It's not on the critical path we're on.** P2/S3 (surface the honest band + the live market read) is
  frontend/read work that doesn't need cloud execution; and "the app runs on live 2026 data" already works
  **when run locally**. Code said this plainly and it's correct.
- Spending the tight ~6-week runway on an app-wide data-layer refactor *now* — ahead of P5, which is already
  the biggest block — would be exactly the kind of scope creep that threatens Week 1.

## The approach is NOT settled — don't pre-commit to the full refactor

Code's default is the full cloud refactor (route the whole store through the bucket). I'd keep that open, not
locked, for two reasons: (1) Code itself flagged a **latency risk** — the spine's heavy reads from object
storage over the network could be slow/fragile; (2) the cheaper alternative Code offered (a small **always-on
host that holds the store** and runs the existing pipeline as-is) may be **both cheaper and technically
better** for a compute-heavy batch job, since it keeps the store on fast local/attached disk. When we scope
the P5-adjacent work, run Code's short latency spike first and choose full-bucket-backed vs. stateful-host on
the evidence — don't buy the biggest option by default.

## Decision + immediate actions

1. **Endorse S2's core.** The un-freeze mechanism is done and safe; S2's actual goal is met. The cloud cadence
   spins out as a separate, well-scoped follow-on — a success with a follow-on, not a failure.
2. **Quiet the failing cron now.** Disable the `weekly_refresh` workflow in the GitHub Actions UI (zero code) —
   it will fail-email weekly otherwise, and it's non-functional in the cloud today anyway. The interim way to
   advance a league is the local command, which nothing needs until games start.
3. **Re-home cloud pipeline execution as a P5 prerequisite.** Log it there; scope it (approach after the
   spike) when we open P5. Not now.
4. **Continue P2 with S3** — it's unblocked.

## One thing to be aware of (minor, your call)

The proof advanced the **live demo's is_mine league to Week 5 on prod** — honest 2025 data, and it's the
un-freeze genuinely working, but it did move the frozen demo forward a week (the showcase was pinned at
Week 4). It's reversible with a reload from the frozen slice. Decide whether to pin the demo at a set week or
let it sit at 5 — either is fine; just flagging that the public demo changed.
