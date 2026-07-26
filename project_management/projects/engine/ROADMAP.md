# Project: Engine — Roadmap & Status

**Status:** largely complete (the prior track, tackled before the V1 path) · **Updated:** 2026-07-26

> This is the engine-improvement project's roadmap. Its *live* knowledge — how the reads work, the current
> trust state — lives in `context/appendices/engine-*`; its session history is in `sessions/engine/`. This
> doc is the status + what remains.

## What the project was

Build the product's decision engine **and** the machinery to prove it honest. The thesis: fantasy weeks are
near-random, so the win is confidence-honesty, not accuracy (see `context/PRODUCT.md`). That meant not just
building reads, but building a measurement loop that could tell whether a read is trustworthy.

## The measurement loop (L0–L6)

Corpus + keying (L0/L1) → prediction ledger (L2) → scorer (L3) → tuner (L4) → AI eval (L5) → proposer (L6).
Full design → *appendix: engine-improvement-loop*. The corpus (270 league-seasons across 2020–2025, plus a
never-tune generalization holdout) is what let the constants be tuned **out-of-sample** rather than fit to
one league.

## What shipped

- **The decision reads:** production VOR, projection consensus bands, playoff-odds Monte Carlo, positional
  depth, true rank, player signal, market VOR, the ROS bull/bear/situation outlook, manager dossiers. →
  *appendix: engine-decision-reads.*
- **The measurement stack:** the ledger, the scorer, the Trust Report, the split-aware tuner.
- **The honest engine ("8c"):** the first *shipped* engine change — a lower center (`CENTER_SHRINK=0.8`) and
  a wider two-sided band on `ros_sigma` (the old `ros_cv` confidence was proven inverted). Decision:
  honest-and-lower over impressive-and-wrong.

## Current state

Measured, gated, and made deliberately honest. The headline trust findings: production VOR ranks
rest-of-season value well but runs the level high; the band was re-tuned to ~0.86 coverage; playoff odds and
true rank sort honestly by confidence; four reads carry no confidence signal (the law-2 gap). Full scorecard
→ *appendix: engine-trust.*

## What remains (each its own effort, mostly outside this project)

- **Surface the honest band to the UI** — the 8c band is in the constants but the front-end still reads the
  old one. Lands with the 2026 substrate build → `projects/v1/` (P2).
- **Silent-reads confidence** — give production VOR, player-signal direction, and playoff wins/seed a
  confidence signal (close the law-2 gap). Parked, its own session.
- **Live-season validation** — the 2026 pilot: `served=true` writes, decision-touch, the season go/no-go
  gates → *appendix: pilot-2026*; the V1 instrumentation slice is `projects/v1/` (P6).
- **Annual re-tune automation** and the **full AI-outlook trust build** → `projects/post-v1/`.

## Reference

Live design/reference: `context/appendices/engine-decision-reads`, `-improvement-loop`, `-corpus`, `-trust`,
`-read-build-order`, `pilot-2026`. Session history: `sessions/engine/`.
