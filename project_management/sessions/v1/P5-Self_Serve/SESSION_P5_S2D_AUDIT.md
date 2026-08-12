# P5 · S2d — PM audit of the demo-clone session

**Audited:** 2026-08-12 · **Report:** `SESSION_P5_S2D_REPORT.md` · **Brief:**
`SESSION_P5_S2D_DEMO_CLONE_AND_SELECTOR.md` (+ its four-question amendment) ·
**Range:** `1ca5d6e..df1c0cd` (3 commits + merge) · **Verdict: ENDORSED.**

**Two findings, neither S2d's fault** — one is a pre-existing UI bug that S2d made public (Will spotted it
on the live site), one is a dead branch it explains.

## Verified independently (not read from the report)

1. **The headline, live from outside the repo.** `GET https://surplusff.com/api/leagues` →
   `{"lineage_id":"DEMO","name":"DEMO League",…,"is_mine":false,"seasons":[{"season":2025,
   "league_id":"DEMO-2025",…,"viewer_roster_id":null}]}`. The public demo is no longer Will's league.
   **`is_mine: false` and `viewer_roster_id: null`** are the two that matter — there is no seat for a
   "YOU" badge to resolve to, which is a structural guarantee rather than a swept payload.
2. **The central exclusion predicate exists** — `data_layer.SYNTHETIC_LEAGUE_IDS = frozenset({"DEMO-2025"})`
   and `is_synthetic()`, with the concrete hazard (a producer trying to harvest `DEMO-2025` from Sleeper)
   written down beside it. That was the guard the amendment asked for, built as one predicate rather than
   scattered comparisons.
3. **The `league_catalog` rename landed and propagated** — `check_isolation` and `reads` both updated.
4. **The `denied_reads` floor comment is in** (`reads.py:1123`, `:1131`). *I nearly reported this missing:
   my first grep was case-sensitive and the comment says `FLOOR`. My own "grep finds the name, not the
   concept" lesson, in miniature.*
5. **`OPERATIONS.md` carries the outage number** — 82s load, 145s end to end — **and adds something better
   than asked for:** that a *scoped* reload is not an outage at all. That is the distinction Week 1
   actually needs, and nobody asked for it.
6. **Three commits, matching the agreed map** — rename · generator + RLS emit · load + repoint + docs.

## Finding A — the blank clinch line (Will, from the live site). Pre-existing; S2d made it public.

`/api/league`, fetched live:

| rank | team | playoff % | `magicWins` | `remainingGames` |
|---|---|---|---|---|
| 9 | Sunday Scaries | **0.3** | **`null`** | 10 |
| 10 | Cool Runnings | **0.3** | 10 | 10 |

**Two teams in materially identical positions; one gets a sentence, one gets nothing.** So this is not
"9 is eliminated and 10 isn't".

`League.jsx:292` — `magicLine()` returns `null` when `magicWins == null`. The team row renders it
`?? ''` (`:131`); the *your-team* panel renders the same null `?? '—'` (`:89`). **The same value, two
treatments** — and that inconsistency is what shows this is an oversight rather than a decision.

**The semantics already have a home.** A null magic number means *no number of wins guarantees a spot* —
which is exactly what the existing `'Needs help to clinch'` branch says. So the fix is to make that label
reachable rather than to invent copy:

> `magicLine`: if `remainingGames` is known and `magicWins` is null → **`'Needs help to clinch'`**.
> Only when `remainingGames` is *also* unknown does `—` apply.

**Why it matters more than it looks.** Standing instruction 5 is *honest, not hidden — absence is
reported, never fabricated*. A blank cell beside nine populated ones does not report absence; it reads as
broken. And as of S2d that row is on the **landing page every visitor sees**. Cosmetic, public, and cheap.

**Not S2d's doing** — it would have rendered the same way on Will's league. S2d changed who sees it.

## Finding B — `magicWins > remainingGames` is probably dead code

If the producer signals "cannot clinch by winning out" as **null** rather than as a number above
`remainingGames`, then `'Needs help to clinch'` never fires — which is precisely why nobody noticed the
null case had no label. **Confirm when A is fixed:** if that branch has never been reachable, it is a
condition that has never bitten, and this project's rule is that such a thing is untested rather than
correct.

## Smaller notes

- **The `schedule.league_id` bug is the positive-check framing paying off in a way I did not predict.**
  Asking for *every name must appear in the map's value set* forces enumeration of what SHOULD be there,
  which is what made Code sweep for the **source league id** across every cloned parquet rather than only
  the columns containing names. An absence check for ten handles would have sailed past a bug that would
  have failed the load. Worth keeping as the pattern, not just the outcome.
- **Third documented figure that was never measured** (RLS 14 of 15, not 13; after the Fly machine count
  twice). The habit that fixes it is already in place — measurements now carry their date.
- **`SESSION_P5_S2C_AUDIT.md` is missing from the project doc's audit list** (it names S2A and S2B only).
  §7 drift; one line.
- **S2e has no brief yet.** Its scope is properly recorded in `STATUS.md` and the project doc so it is not
  evaporating, but the brief should exist before handover. **Finding A belongs in it** — same file, same
  session, frontend-only.

## What S2d deliberately did not do (accepted)

The rest-of-season band and the synthetic AI outlook remain unbuilt; both were in the original clone brief,
both fell outside the scope guard, and the clone is season 2025 so the band panel is dark exactly as it was
before. **P4 retires the outlook placeholder anyway** — which is why P4 runs before P3.
