# ROADMAP — Highest-Level View

**Updated:** 2026-07-26 · The master arc + the index of every project. For current state see `STATUS.md`;
for what each project entails, open its folder under `projects/`.

---

## The arc

1. **Build the engine + make it honest — DONE.** The measurement/tuning machinery (corpus, ledger, scorer,
   tuner) and the decision reads, tuned out-of-sample and shipped deliberately honest. → `projects/engine/`.
2. **Migrate the store, go live — DONE (Stage A).** Moved from in-browser DuckDB-WASM to FastAPI + Supabase
   Postgres on Fly; the app is a real, deployed website. → `sessions/v1/`.
3. **V1 — the active work.** Turn the single-league, frozen-2025 replay into a working, **invite-gated
   self-serve** product for **Sleeper PPR/half redraft** (1QB + superflex), on **live 2026 data**, ready for
   the invited cohort by **Week 1**. → `projects/v1/`.
4. **Post-V1 — next improvements.** Once V1 ships, the remaining work is formats, platforms, and refinements
   — not core functionality. → `projects/post-v1/`.

## The projects

### `projects/v1/` — the active build (7 projects)

`BUILD_ORDER.md` is the project→project guide; each `P0`–`P6` is a project brief with a session map. In
short: **P0** finish multi-league · **P1** reliable off-laptop collection · **P2** go live on the 2026 season
· **P3** waiver / free-agent value · **P4** live AI outlook · **P5** accounts + invite-gated self-serve
onboarding · **P6** launch hardening + instrumentation. Critical-path spine is **P0 → P2 → P5**, with P1 as
an early parallel prerequisite; P3/P4 are the deferrable flex.

### `projects/post-v1/` — the next-improvements backlog

Scoped design docs, out of V1 by design: standard scoring, custom scoring, dynasty, owner-keyed manager
profiles, the annual re-tune automation, and the full AI-outlook trust build. See
`projects/post-v1/README.md`.

### `projects/engine/` — the prior, largely-complete track

The engine-improvement project: the measurement loop and the honest-engine work, tackled before the V1 path.
Its live knowledge (how the reads work, the current trust state) lives in `context/appendices/engine-*`; its
session history is in `sessions/engine/`. → `projects/engine/ROADMAP.md`.

## How the docs are organized

- **`context/`** — load-first SOT: `STATUS`, `ARCHITECTURE`, `CODING_BIBLE`, `PRODUCT`, this `ROADMAP`,
  `SESSION_GUIDE`, and `appendices/` (deep rationale, pulled in only when a task needs it).
- **`projects/`** — one folder per project (roadmaps + briefs only).
- **`sessions/`** — reference-only session records, organized by project.
- **`_deprecated/`** — gitignored old-state, preserved for history.
