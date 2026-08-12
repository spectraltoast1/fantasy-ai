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

## 3. Playoff odds — integers only, with `<1%` and `>99%` at the ends (Will, 2026-08-12)

`League.jsx` renders `Math.round(playoffPct)` in three places (`:74`, `:135`, `:186`), so **0.3% displays
as 0%** — which reads as *mathematically eliminated*. That is fabricated certainty, and the north star is
confidence-**honesty**.

**The rule (Will's, simpler than the PM's decimal proposal and it solves the actual problem):**

| value | display |
|---|---|
| 0 < p < 1 | **`<1%`** |
| 1 ≤ p ≤ 99 | the integer |
| p > 99 | **`>99%`** |
| p == 0 from the sim | **`<1%`** — see below |

**A sim result of 0 is not elimination.** 0 out of 10,000 means "did not occur in ten thousand tries",
i.e. below roughly 0.03% — not impossible. So it takes `<1%` like any other sub-1% value.

**`Clinched` and `Eliminated` may only come from real bracket math, never from the simulation** (Will).
Neither exists yet; when it does, they become their own labels. Until then the display never asserts
either.

## 4. "Clinch in N of next 10" overstates what the number is

`compute_bracket_sim.py:63` — `MAGIC_ODDS = 0.90`, and the code calls the value a **"magic-number
proxy"**: *the fewest additional wins k such that, among the simulated seasons where the team won exactly
k of its remaining games, it made the playoffs in ≥90% of them.*

**That is not clinching.** Clinching means guaranteed regardless of other results. This says *nine times
out of ten*. A manager reading "Clinch in 5 of next 10" will believe winning 5 puts them in; it puts them
in 90% of the time. **The engine is honest — it says "proxy" — and the UI dropped the hedge.**

**The label set — DECIDED (Will, 2026-08-12).** Copy, not math. **Do not retune `MAGIC_ODDS`** — report,
don't tune; it is a measured constant and this is a labelling pass.

| condition | label |
|---|---|
| `magicWins <= 0` | **"Likely a playoff team"** |
| `0 < magicWins < remainingGames` | **"X of the next Y should clinch a spot"** |
| `magicWins == remainingGames` | **"Has to win out"** |
| `magicWins` null, `remainingGames` known | **"Needs help to clinch"** |
| `remainingGames` unknown | `—` |
| *(future, from bracket math only)* | `Clinched` / `Eliminated` |

**A consequence of Will's rule that is easy to miss: the existing `magicWins <= 0 → 'Clinched a spot'`
branch has to go.** That string is the simulation asserting a certainty, which is exactly what the rule
forbids — it becomes **"Likely a playoff team"**. It is the same defect as the `0%` rounding, in the one
place nobody was looking because the panel was *flattering* rather than grim.

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


---

## 5. The Posture Map is INVERTED on the live demo — measured 2026-08-12, not theorised

Will asked how hard a reshape would be. Measuring it to answer produced a defect instead.

**`/api/league` on the live demo, every team:**

| rank | team | playoff % | all-play % | gap | label |
|---|---|---|---|---|---|
| 1 | The Replacements | 94.2 | 82.2 | −12.0 | **Riding luck** |
| 2 | Scoop and Score | 93.2 | 57.8 | −35.4 | Riding luck |
| 3 | Certified Lads | 92.0 | 53.3 | −38.7 | Riding luck |
| 4 | Comeback Szn | 79.0 | 62.2 | −16.8 | Riding luck |
| 5 | Forty Yard Trash | 19.9 | 48.9 | +29.0 | **Unlucky** |
| 6 | Bijan Mustard | 10.4 | 46.7 | +36.3 | Unlucky |
| 7 | No Punt Intended | 6.2 | 62.2 | +56.0 | Unlucky |
| 8 | Waiver Wire Fire | 4.5 | 44.4 | +39.9 | Unlucky |
| 9 | Sunday Scaries | 0.3 | 24.4 | +24.1 | Unlucky |
| 10 | Cool Runnings | 0.3 | 17.8 | +17.5 | Unlucky |

**Every team is lucky or unlucky. `Contender`, `Rebuild` and `On pace` are unreachable** — `BAND = 9`
and the *smallest* |gap| in the league is 12.0. Three of five labels have never fired.

**The label carries no information beyond rank.** It is the playoff line, relabelled: top four = sell,
bottom six = buy. And it is **inverted** — the best team in the league by both measures (82.2% all-play,
the highest) is told to **sell**.

**Root cause: the two axes are not commensurable.** Playoff odds *saturate* toward 0 and 100; all-play %
*compresses* toward 50. Their difference is therefore dominated by the odds axis, so `gap` measures the
shape of the odds curve, not luck. Team 7 is a genuine unlucky story (3rd-best all-play, 6.2% odds) and
team 9 is simply bad (24.4% all-play) — the metric cannot tell them apart, because the odds term swamps
both.

**This is a correctness defect, not a calibration one.** The formula compares two quantities that are not
the same unit. Retuning `BAND` cannot fix it; it would only move which rank the split lands on.

### What to do — two pieces, different sessions

1. **NOW, in S2e: gate the panel off.** The project's own standing rule is *"gate a panel OFF only when a
   read is **misleading**, not merely uncertain."* This read is mechanically misleading, it is on the
   **public landing page**, and it tells visitors to sell the best team. Gating is the rule's own remedy.
2. **Its own measured session: compare like with like.** The likely answer is **all-play % vs actual win
   %** — same unit (share of games won), so the gap *is* luck, which is the canonical fantasy read. Cheap
   to compute if win% is already served. `BAND`/`LEVEL_CUT` must then be **re-measured** on the new scale
   — 9 points is meaningless against odds and plausible against win%. Note `derive_posture` exists twice:
   `api/calcs.py:32` and `frontend/src/posture.js` ("mirrors posture.js exactly") — both move together.
   **Rank-vs-rank** (standing rank vs all-play rank) is the fallback if win% is not available.

## Sizing the reshape (asked 2026-08-12) — supersedes nothing above; item 5 is the reason it matters

**Short answer: cheap to reshape, expensive to redefine.** The cost depends entirely on whether the change
is about how it *looks* or what it *means*.

| change | size | why |
|---|---|---|
| **Layout, dot style, labels, legend, aspect ratio, responsiveness, captions** | **small — half a session** | `PostureMap` is one self-contained ~50-line component in `League.jsx` with **no charting library**: a hand-rolled `<svg>` for the quadrants and diagonal, then absolutely-positioned divs for dots. Plus CSS. No API or engine change. |
| **A different axis** (something other than playoff odds × all-play) | **medium** | X and Y read `playoffPct` and `allPlayPct`, both already served by `loadStandings`. Any *other* field needs the read extended, and possibly the engine. Bounded, but it stops being frontend-only. |
| **Redefining posture itself** — the quadrant boundaries, what counts as "riding luck" | **its own measured session** | `posture` is **server-side**: `reads.py:607` → `calcs.derive_posture(playoff_pct, all_play_pct)`. Changing the thresholds is an engine-constant change, which is **propose-only, human-promoted, and needs measurement** under this project's own rules. Not a presentation task at all. |

**One thing to check during any reshape, and possibly a live bug now:** the `<svg>` uses
`viewBox="0 0 100 100"` with **`preserveAspectRatio="none"`**, so the dashed "ON PACE" diagonal stretches
with the container. **It only reads as a true on-pace line if the panel renders square.** If it does not,
a dot that appears above the line may not actually be above it — and the whole panel's read is
*off-diagonal is the signal*. Worth measuring before redesigning around it.

**Also note:** this panel is gated behind `REGIME.TREND` in `readiness.jsx`, which is **shared with other
panels** — so changing *when* it appears has blast radius beyond this map, unlike changing how it looks.
