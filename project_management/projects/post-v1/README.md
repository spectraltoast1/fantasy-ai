# Post-V1 Backlog

**What this is:** the "next improvements" bucket — the work that comes *after* V1 ships. By design, none of it
is core functionality for the invite-gated, live-2026, PPR/half redraft V1; it's formats, platforms, and
refinements. Reaching the state where everything left is in here is the point of V1.

Each doc is a scoped design doc (assessment + plan), not yet a runbook. Sequencing is decided when V1 is done.

| Doc | What it is | V1 relationship |
|---|---|---|
| `standard-scoring.md` | Standard (non-PPR) scoring — engine-complete; needs a substrate build + a demo/certification slice | none (V1 is PPR/half) |
| `custom-scoring.md` | Custom scoring — a first-down projection bridge recovers ~25pts of coverage; threshold bonuses stay a gated experiment | none |
| `dynasty.md` | Dynasty — a different *value* model (multi-year horizon, age curve); the biggest lift, and the one place the program fits new constants | none (V1 is redraft) |
| `owner-keyed-dossiers.md` | One coherent manager profile per person across leagues; small once multi-league users exist (B3 already carries `owner_id`) | builds on P5 (self-serve multi-league users) |
| `annual-retune.md` | Turn the offseason calibration into one command. Next offseason, not 2026. Distinct from P2, which builds the 2026 substrate *forward* | none |
| `ai-outlook-trust.md` | The full trust build for the §2 bull/bear/situation read | **P4 ships the V1 slice**; this is the remainder |

## See also

- **Engine reference** (how the reads and the measurement loop work): `context/appendices/engine-*`.
- **The 2026 pilot** (season validation gates): `context/appendices/pilot-2026`.
- **Not yet scoped as their own docs:** other-platform import (ESPN / Yahoo) and the silent-reads confidence
  gap (both named in `context/ROADMAP.md` / `STATUS.md`).
