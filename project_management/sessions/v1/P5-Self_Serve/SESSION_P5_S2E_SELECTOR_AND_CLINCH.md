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

## 3. Playoff odds must not round to 0% or 100% (Will, 2026-08-12)

`League.jsx` renders `Math.round(playoffPct)` in three places (`:74`, `:135`, `:186`), so **0.3% displays
as 0%** — which reads as *mathematically eliminated* to every manager who sees it. That is fabricated
certainty, and the north star is confidence-**honesty**.

**Rounding only lies at the ends, so the rule is asymmetric** — a decimal in the middle would be false
precision, since 10,000 sims give roughly ±0.5pp around the midrange:

| value | display | why |
|---|---|---|
| 0 < p < 1% | **one decimal** (`0.3%`) | the difference between 0.3% and 0.03% is a real decision input |
| p == 0 from the sim | **`<0.1%`**, never `0%` | see below |
| 1% ≤ p ≤ 99% | integer | a decimal implies resolution 10k runs does not have |
| p > 99% | **`>99%`** | never assert a certainty the sim did not establish |

**The `0%` case is the important one, and it is subtler than rounding.** A Monte Carlo returning 0 out of
10,000 does **not** mean eliminated — it means "did not occur in 10,000 tries", i.e. below roughly 0.03%.
Displaying that as `0%` asserts an elimination the model never established. **True elimination is a
different fact** and would have to come from the bracket logic, not from a simulated frequency. If the app
ever wants to say "eliminated", that is a separate claim needing a separate source.

## 4. "Clinch in N of next 10" overstates what the number is

`compute_bracket_sim.py:63` — `MAGIC_ODDS = 0.90`, and the code calls the value a **"magic-number
proxy"**: *the fewest additional wins k such that, among the simulated seasons where the team won exactly
k of its remaining games, it made the playoffs in ≥90% of them.*

**That is not clinching.** Clinching means guaranteed regardless of other results. This says *nine times
out of ten*. A manager reading "Clinch in 5 of next 10" will believe winning 5 puts them in; it puts them
in 90% of the time. **The engine is honest — it says "proxy" — and the UI dropped the hedge.**

Fix is copy, not math: say what it is (e.g. *"5 of next 10 usually does it"*, or keep the number and
label the strength). Will's call on wording. **Do not retune `MAGIC_ODDS`** — report, don't tune; that is
a measured constant and this session is a labelling pass.

---

## Why these four belong in one session

Items 2, 3 and 4 are **the same defect in three costumes: the UI asserting more certainty than the model
has.** They stack on one row — rank 9 currently reads as *0%, no path* when the truth is *0.3%, needs
help*. Fixing one and not the others leaves the same wrong impression. **Frame S2e as the honesty pass on
the League screen**, not as a grab-bag — and it is the first concrete instance of the long-floating
*metric legibility* thread (Will's most-repeated user feedback), which still has no home in BUILD_ORDER.

## Also worth folding in (cheap, same area)

- `SESSION_P5_S2C_AUDIT.md` is missing from the project doc's audit list.
- The two pre-existing client bugs S2b filed: `TeamDetail` and `MatchupDetail` spin forever on a
  legitimate `200 null`. Same file family, same session shape.

## Scope guard

No data path, no loader, no engine, no store. No outage — nothing here requires a `--load`.
