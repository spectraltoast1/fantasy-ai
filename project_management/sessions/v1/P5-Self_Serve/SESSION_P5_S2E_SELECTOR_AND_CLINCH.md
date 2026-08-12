# V1 · P5 · Session S2e — The season selector, and the blank clinch line — SKETCH

**Written 2026-08-12.** **Status:** sketch — flesh into a paste-block before handover.
**Prior:** `SESSION_P5_S2D_AUDIT.md` (Finding A is item 2). **Frontend-only; no data path, no outage.**

> **What this session does:** finishes what S2d's release valve deferred, and fixes a blank cell on the
> landing page that Will spotted on the live site.

## 1. Remove the season selector; flatten the catalog

Unblocked as of S2d — the demo has its own lineage (`DEMO`), so removing the selector can no longer make
it unreachable. Prior seasons are corpus, not product. **`season` is not a SQL filter anywhere in the read
layer**, so this is frontend + catalog shape and touches no data path. **The league and week switchers
stay.** Visibly pending today: the demo has one season, so the switcher offers exactly one option.

## 2. The blank clinch line (S2d audit, Finding A)

Live data: rank 9 `magicWins: null`, rank 10 `magicWins: 10`, **both at 0.3% playoff odds** — so the blank
is not "eliminated vs not". `magicLine()` returns null for a null magic number; the team row renders it
`?? ''` while the your-team panel renders the same null `?? '—'`.

- **Fix:** a null `magicWins` with a known `remainingGames` means *no number of wins guarantees a spot* —
  which is what the existing `'Needs help to clinch'` branch already says. Make it reachable. `—` applies
  only when `remainingGames` is unknown too.
- **Then check whether `magicWins > remainingGames` was ever reachable.** If the producer only ever signals
  that case as null, that branch is dead — a condition that has never fired is untested, not correct.
- **Why it is not cosmetic-only:** *absence is reported, never fabricated*. A blank beside nine populated
  rows reads as broken, on the page every visitor lands on.

## Also worth folding in (cheap, same area)

- `SESSION_P5_S2C_AUDIT.md` is missing from the project doc's audit list.
- The two pre-existing client bugs S2b filed: `TeamDetail` and `MatchupDetail` spin forever on a
  legitimate `200 null`. Same file family, same session shape.

## Scope guard

No data path, no loader, no engine, no store. No outage — nothing here requires a `--load`.
