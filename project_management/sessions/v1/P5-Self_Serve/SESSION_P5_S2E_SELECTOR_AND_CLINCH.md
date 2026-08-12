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
**Verified 2026-08-12: that math does not exist** — zero hits for "clinch"/"eliminat" anywhere in project
code. **DEFERRED by Will, 2026-08-12: do not build it.** *"There's still enough value in the estimates."*
The display simply never asserts either. When someone does build it, the cheap version is the right one —
a conservative bound (your best case vs rivals' worst, losing every tiebreak when proving elimination and
winning every one when proving a clinch) is sound-but-incomplete, which is exactly the honest posture: it
can never falsely declare, only stay silent.

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

## 5. The posture read is INVERTED — everywhere, not just on the demo (measured 2026-08-12)

**Scope correction (Will, 2026-08-12).** The PM first wrote this up as "inverted on the public landing
page". **It is inverted for every league.** `derive_posture` runs on every standings row the API serves —
the demo, Will's own league when he signs in, every user's league after S4/S5, and all 31 corpus slices.
The demo is only where it was *measured*, not where it applies. **Second time in this project the PM has
let the sample stand in for the scope** (after the Fly machine count) — the standing lesson is *a sample
supports a hypothesis, not an invariant*, and it applies to blast radius as much as to behaviour.

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

### DECIDED (Will, 2026-08-12) — **(b)**: keep the scatter, drop the interpretation.

"Withhold posture" is broader than "hide the map", so here is exactly what goes and what stays.

**Withheld under any option:** the four `posture` sites — the map's classification, the *Your Race* chip,
the chip on every Teams row, and the sparkline's posture-derived colour (falls back to `var(--violet)`).
**Never withheld:** playoff odds, all-play %, records, ranks, the sparkline itself, the magic line, and
everything else on League and Teams. **The data stays; the classification goes.** We are not hiding
information, we are removing a label that misclassifies.

The fork is only about the map's panel:

| | what the visitor sees | cost |
|---|---|---|
| **(a) withhold the whole panel** | a `PanelOff` slot with an honest reason | smallest |
| **(b) keep the scatter, drop the interpretation** ← **CHOSEN** | every team plotted by odds × all-play, **no diagonal, no corner labels, no buy/sell** | slightly more — delete a few JSX elements and rewrite the caption |

**Recommendation: (b).** The dot *positions* are true — 94% odds against 82% all-play is a real
measurement. What is false is the **diagonal** (which implies the two axes are comparable) and the
**corner labels** (which assert buy/sell). Removing those leaves an honest "here is where everyone sits"
and keeps a working panel on the page a visitor lands on — a `PanelOff` slot on the demo says *this
product has broken parts*. The elements are already separate in the JSX (polygons, the dashed line, four
corner divs, the axis label, then the dots), so this is deletion, not a rebuild. **The caption must be
rewritten** — it is currently entirely about off-diagonal reads.

It also means the eventual metric fix reuses this plot with better axes rather than rebuilding it.

**What (b) actually leaves:** the picture, not the sentence. Every team still plotted by playoff odds ×
all-play, so a reader can see who is strong on both and who is strong on neither — both true readings,
since the axes point the same direction for quality. What goes is the *luck* claim, which is the part
that was junk. **If the panel feels pointless without a sentence once it is live, that is a signal for the
metric session, not a reason to revisit now** — and flipping to (a) later is deleting a component rather
than unpicking anything.

**Proposed caption** (Will to overrule — it is his voice, not the PM's):

> *Each team by playoff odds and true record. Strong on both sits top-right; strong on neither, bottom-left.*

It states only what the two axes measure and makes no claim about the distance between them. **Delete the
old caption entirely** — it is written end to end about off-diagonal reads.

### What to do — two pieces, different sessions

**IT IS NOT ONE SURFACE. `posture` renders in FOUR places** — gating only the map leaves the same wrong
label on three of them:

| site | what it shows | behaviour if `posture` is null |
|---|---|---|
| `League.jsx:75-77` | the posture **chip** on *Your Race* | `shape && me.posture ?` → renders nothing ✅ |
| `League.jsx:134` | the **sparkline colour** in Playoff Picture | `t.posture ? tone : 'var(--violet)'` → default ✅ |
| `League.jsx:157-190` | the **map** | `.filter(… && t.posture)` → **empty chart** ❌ |
| `Teams.jsx:82-87` | the posture **chip on every Teams row** | `shape && t.posture ?` → renders nothing ✅ |

**Will's own screenshot confirms the blast radius:** the sparkline colours in Playoff Picture break at
exactly the playoff line — ranks 1-4 one tone, 5-10 another. That is the same broken classification
colouring a different panel.

**Recommended implementation — one server switch, not four client edits.** Stop serving `posture` from
`reads.py:607` (return `None`). Three of the four sites already have null-guards and degrade correctly
on their own; only the map needs handling, because an empty chart is exactly what `PanelOff`'s own
docstring says not to draw. **Use `PanelOff` with its `note` override** — it exists for precisely this
(*"honest 'not here' rather than an empty chart… `note` overrides the default sentence when a panel is
off for a reason worth naming"*). **Do NOT use `Gate`** — that is the readiness/weeks mechanism, and
using it here would state the wrong reason: this panel is not too early, it is wrong.

Enforcing it in one place rather than four is the same seam principle S2b established, and re-enabling it
after the metric is fixed is one line. **Code should verify those null-guards behave as read** rather
than trusting this table.

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

---

## The brief to paste to Code — S2e

```
Goal: V1 Project 5, Session S2e (projects/v1/P5_ACCOUNTS_SELF_SERVE_ONBOARDING.md) — the honesty pass on
the League screen, plus the season selector S2d deferred. Five items. Frontend + ONE server line. No
outage; nothing here needs a --load.

Read first: sessions/v1/P5-Self_Serve/SESSION_P5_S2E_SELECTOR_AND_CLINCH.md (this brief — every item is
decided, nothing is open), SESSION_P5_S2D_AUDIT.md, context/CODING_BIBLE.md, SESSION_GUIDE.md. Check the
brief against observable reality before executing.

Items 2-5 are ONE defect in four costumes: the UI asserting more certainty than the model has. They stack
on the same row — rank 9 currently reads "0%, no path" when the truth is "0.3%, needs help".

1. SEASON SELECTOR. Remove it from the frontend and flatten the catalog's lineage->seasons grouping.
   Unblocked since S2d gave the demo its own lineage. `season` is not a SQL filter anywhere in the read
   layer, so this is frontend + catalog shape and touches NO data path. The LEAGUE and WEEK switchers STAY.

2. THE BLANK CLINCH LINE. League.jsx magicLine() returns null when magicWins is null; the team row renders
   it `?? ''` (:131) while the your-team panel renders the same null `?? '—'` (:89). Same value, two
   treatments. A null magicWins means "no number of wins guarantees a spot" — which is exactly what the
   existing, currently-UNREACHABLE 'Needs help to clinch' branch says. Make it fire: if remainingGames is
   known and magicWins is null -> 'Needs help to clinch'. `—` only when remainingGames is unknown too.
   THEN CHECK whether `magicWins > remainingGames` was ever reachable. If the producer only ever signals
   that case as null, that branch is dead — a condition that has never fired is untested, not correct.
   Report which.

3. PLAYOFF ODDS — integers, with <1% and >99% at the ends. Math.round is at League.jsx:74, :135, :186, so
   0.3% currently prints as 0%, which reads as mathematically eliminated.
     0 < p < 1  -> "<1%"      1 <= p <= 99 -> the integer      p > 99 -> ">99%"
   A sim result of 0 is ALSO "<1%": 0 out of 10,000 means "did not occur in ten thousand tries" (below
   ~0.03%), NOT eliminated. Never print 0% or 100%.

4. THE MAGIC-LINE LABEL SET (copy, not math — do NOT retune MAGIC_ODDS; it is a measured constant):
     magicWins <= 0                        -> "Likely a playoff team"
     0 < magicWins < remainingGames        -> "X of the next Y should clinch a spot"
     magicWins == remainingGames           -> "Has to win out"
     magicWins null, remainingGames known  -> "Needs help to clinch"
     remainingGames unknown                -> "—"
   NOTE the existing `magicWins <= 0 -> 'Clinched a spot'` branch MUST GO. That string is the SIMULATION
   asserting a certainty. MAGIC_ODDS is 0.90 and the engine itself calls the value a "magic-number proxy",
   so "Clinch" overstates it by construction. Clinched/Eliminated may only ever come from real bracket
   math — which does not exist, and Will has DEFERRED building it. Do not build it.

5. WITHHOLD `posture`. It is INVERTED for EVERY league (not just the demo): BAND=9 and the smallest |gap|
   in the live league is 12.0, so every team is Riding luck or Unlucky and Contender/Rebuild/On pace are
   unreachable. The label is the playoff line relabelled, and the best team by both measures is told to
   sell. Cause: playoff odds and all-play % are not the same unit. This session WITHHOLDS it; fixing the
   metric is its own measured session — do NOT attempt it here, and do not retune BAND/LEVEL_CUT.
   It renders in FOUR places: League.jsx:75-77 (Your Race chip), :134 (sparkline COLOUR), :157-190 (the
   map), Teams.jsx:82-87 (chip on every Teams row).
   - Cleanest: ONE server switch — stop serving `posture` from reads.py:607. Three of the four sites
     already null-guard and degrade correctly (chips vanish; the sparkline falls back to var(--violet)).
     VERIFY that rather than trusting it.
   - The MAP needs handling, because an empty chart is what PanelOff's own docstring says not to draw.
     Will chose: KEEP THE SCATTER, DROP THE INTERPRETATION. Teams still plot by odds x all-play. DELETE
     the diagonal, the quadrant polygons, the four corner labels (UNLUCKY/CONTENDER/REBUILD/RIDING LUCK)
     and the buy/sell language. The dot POSITIONS are true; the interpretation was not.
   - Replace the caption entirely (the current one is written end-to-end about off-diagonal reads):
       "Each team by playoff odds and true record. Strong on both sits top-right; strong on neither,
        bottom-left."
   - Use PanelOff (with its `note` override) if any slot is needed. Do NOT use Gate — that is the
     readiness/weeks mechanism and would state the wrong reason: this panel is not too early, it is wrong.

Prove it:
- Every state of magicLine renders the right string, including the null case, driven by fixtures.
- No served payload can produce "0%", "100%" or "Clinched a spot".
- `posture` is absent from the API payload, and all four sites render sensibly without it — screenshot the
  League and Teams surfaces signed out.
- The season selector is gone; the LEAGUE and WEEK switchers still work; a league/week switch still
  re-scopes every surface.
- Parity: every read payload except `posture` and the catalog shape is value-identical.

Scope guard — does NOT: fix the posture METRIC (its own measured session); retune MAGIC_ODDS, BAND or
LEVEL_CUT; build clinch/elimination bracket math (deferred by Will); touch read scoping (done, S2a/S2b);
touch any pipeline, transform, loader, engine constant, the store or the frozen corpus. No --load, no
outage.

Also fold in if cheap, else report: the two pre-existing client bugs S2b filed — TeamDetail and
MatchupDetail spin forever on a legitimate `200 null`. And add SESSION_P5_S2C_AUDIT.md to the project
doc's audit list.

Follow SESSION_GUIDE.md: fresh worktree, <=3 commits, update STATUS.md + ARCHITECTURE.md per §7 (replace,
don't append), then close/merge/push. Touches application/api/* and application/frontend/* — REDEPLOY and
confirm live on https://surplusff.com/. Sweep .git for stale lock files at closedown.
```

## Will's checks after the deploy

1. `https://surplusff.com/` signed out — the Playoff Picture bottom rows say **`<1%`**, not `0%`, and
   **rank 9 has a sentence** like every other row.
2. The Posture Map still shows every team as a dot, with **no diagonal and no buy/sell corners**, and no
   posture chip anywhere on League or Teams.
3. The **season selector is gone**; the league and week switchers still work.
