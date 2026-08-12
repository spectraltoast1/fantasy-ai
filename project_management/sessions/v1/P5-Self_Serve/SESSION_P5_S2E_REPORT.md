# V1 · P5 · S2e — the honesty pass on the League screen, and the season selector

**Shipped 2026-08-12.** **Brief:** `SESSION_P5_S2E_SELECTOR_AND_CLINCH.md` · **Prior:**
`SESSION_P5_S2D_AUDIT.md` (Finding A + B). **3 commits.** Frontend + two server edits. No `--load`,
no outage.

> Four of the five items are **one defect in four costumes: the UI asserting more certainty than the
> model has.** They stacked on a single row of the page every visitor lands on — rank 9 read
> *"0%, no path"* when the truth is *"0.3%, needs help"*.

---

## What shipped

### 1 · Playoff odds — hedged at both ends

| value | before | after |
|---|---|---|
| 0.3 | `0%` — reads as mathematically eliminated | **`<1%`** |
| 0 from the sim | `0%` | **`<1%`** — 0 of 10,000 is "did not occur in ten thousand tries" |
| 99.6 | `100%` | **`>99%`** |
| 94.2 | `94%` | `94%` |

**The brief named three render sites. There are five** — it missed `Teams.jsx:93` and
`TeamDetail.jsx:58`, so a brief-literal fix would have left `0%` printing on the Teams tab and the
team drill-down, and the stated proof ("no served payload can produce 0%") would have been false on
two surfaces. All five now go through one pure formatter.

**All-play % deliberately keeps plain rounding.** It is a realized record — 0 of 45 really is 0% —
so hedging it would be *less* honest, not more. The distinction is the point of the whole session.

### 2 · The blank clinch line, and the label set

`magicLine` returned `null` when *either* input was null, and that null rendered `''` on the team row
(`League.jsx:131`) and `'—'` on the your-team panel (`:89`) — the same value, two treatments, which
is what showed it was an oversight rather than a decision.

| condition | label |
|---|---|
| `magicWins <= 0` | **Likely a playoff team** *(was "Clinched a spot")* |
| `0 < magicWins < remainingGames` | **X of the next Y should clinch a spot** *(was "Clinch in X of next Y")* |
| `magicWins == remainingGames` | **Has to win out** |
| `magicWins` null, `remainingGames` known | **Needs help to clinch** ← previously unreachable |
| `remainingGames` unknown | `—` |

**"Clinched a spot" had to go.** `MAGIC_ODDS = 0.90` and the engine itself calls the value a
*"magic-number proxy"*, so the string was the simulation asserting a certainty it cannot support.
The engine was honest; the UI dropped the hedge.

### 3 · `posture` withheld — one server line, four client sites

Removed from the `load_standings` row build (`reads.py`). The key is **absent, not null**: we are not
failing to compute it, we are declining to serve it. It is `derive_posture`'s only caller and it feeds
**both** `/api/standings` and `/api/league` (which nests the same object again under `me`).

The map **kept its scatter and lost its interpretation** — the dot positions are true measurements;
the diagonal, the quadrant washes and the four buy/sell corners were not.

### 4 · Season selector removed, catalog flattened

`/api/leagues` is now one entry per visible (league, season) with the season on the row. The
lineage→seasons tree existed only to feed the selector. **`season` still travels on every request** —
it has never been a SQL filter, and `check_isolation` asserts `slice_params`' parameter set, so
dropping it would be an API change this session was not asked to make.

### 5 · The two `200 null` spinners (filed in S2b)

`TeamDetail` and `MatchupDetail` used `null` as **both** the in-flight sentinel and the successful
"no such thing" payload, so `.then(null)` left `if (!team)` true for ever. Now three states:
`undefined` in flight, `null` = an honest empty state, object = data.

---

## Findings

**A · `magicWins > remainingGames` is dead code — proven, not suspected.** (S2d Finding B asked.)
`compute_bracket_sim.py:292` loops `for k in range(R + 1)`, and `R` is the same scalar written as
`remaining_games` (`:301`, `:356`). So `magic_wins ∈ {0..R} ∪ {None}` **by construction**, and
"cannot clinch by winning out" is signalled *only* as `None` (`:287`, `:291`) — which the old
`magicWins == null` guard swallowed one line earlier. The team that most needed the message got a
blank cell, and the string that would have said it was unreachable. The branch is **kept** (it is the
correct answer if the producer changes) and is now **driven by a fixture**, so it stops being a
condition that has never run.

**B · The `0%` is manufactured server-side too.** `compute_bracket_sim.py:351` persists
`round(playoff_odds, 3)`, so 4/10,000 — a real 0.04% — is stored as exactly `0.0`, and 9,996/10,000
as `1.0`. The display rule handles both correctly, but the surface can never distinguish 0.04% from
0. **Reported, not fixed:** that is a transform, outside the scope guard.

**C · `remaining_games` is one scalar shared by every team** (`compute_bracket_sim.py:356` — no
`[i]`, unlike every neighbouring field) and counts remaining *weeks*, not that team's *games*. A bye
or an odd team count makes "Has to win out" overstate. Harmless on the 10-team demo. **Reported, not
fixed.**

**D · The brief's `posture.js` claim is false.** `frontend/src/posture.js` does not exist — it was
deleted with the DuckDB-WASM client (`e94eba7`). `derive_posture` lives in **one** place,
`api/calcs.py`; the docstrings naming `posture.js` are fossils, now marked as such. **This makes the
metric session cheaper than the brief sized it** — there is no second implementation to move.

**E · The build had drifted from its own spec, and the drift is what broke.**
`appendices/engine-decision-reads.md` §5 specifies posture as *adjacency*: "Posture itself is *not*
computed or labeled." The shipped code computed one anyway. So the open question for the metric
session is not only *which axes* but **whether a computed label should exist at all** — the appendix
now carries that note.

**F · `Teams.jsx` does not "degrade correctly."** The brief's table said the chip "renders nothing"
when `posture` is null; its else branch (`:89-91`) actually renders `—`, so the Teams table now shows
a `Posture` column of ten em-dashes under a header promising a read, with a sub-header sentence still
explaining the chip. **Raised before coding; Will chose brief-literal.** Recorded as an accepted
state, not an oversight — the cheap follow-up is deleting the column, the header and one sentence.

**G · Removing `posture` also retired a latent.** The server emitted it with **no** season-shape
gate, so a 0/0 all-play record coerces to `0` and manufactured *"Riding luck"* at week 0/1. Only the
client's `hasShape` held that back — and both sparkline colour sites bypassed `hasShape` entirely,
tinting a row "Riding luck" amber while the chip beside it was deliberately withheld.

---

## Proof

- **`check_league_copy.mjs` — 39 checks, green.** Dependency-free (this repo has no test runner, and
  adding one would write into main's symlinked `node_modules`). Covers every `magicLine` branch
  including both nulls separately; the whole 396-combination input domain, asserting no input can
  produce "Clinched" / "Clinch in" / "Eliminat" / "Guarantee" / "Certain"; and a **100,001-value scan
  of `fmtOdds` over [0,100]** proving it can never print `0%` or `100%`, with the lowest and highest
  printable integers pinned at 1 and 99. **Prove-it-bites: 26 of the 39 fail against the pre-S2e
  logic.**
- **`check_ownership` and `check_isolation` — ALL GREEN after the flatten**, still failing 8 and 7
  assertions respectively against the pre-S2a/S2b code.
- **Payload parity: 40 of 43 demo payloads byte-identical** to prod, captured before the change and
  after. The three that move are exactly `standings`, `league` and the catalog — and `standings` and
  `league` are **identical once `posture` is stripped from the baseline** (10 posture objects → 0),
  while hand-flattening the baseline catalog **reproduces the new payload exactly**, so no
  information was lost, only re-shaped.
- **Live in the browser, signed out:** rank 9 reads "Needs help to clinch · `<1%`", rank 10 "Has to
  win out · `<1%`", the map plots all ten dots with no diagonal or corners, no season control in the
  top bar, the league select keyed on `DEMO-2025`, and a week switch still re-scopes every surface
  (with the readiness gates firing correctly at 2 weeks). Clean console on a fresh load.
- **Both `200 null` spinners driven end-to-end** through the real component path, with the API
  response forced to `200 null` — "No such team in this league." and "No matchup here for this week"
  instead of a permanent spinner.

## Deliberately not done

Fixing the posture **metric** (its own measured session — see STATUS and finding E) · retuning
`MAGIC_ODDS` / `BAND` / `LEVEL_CUT` · building clinch/elimination bracket math (deferred by Will) ·
removing the now-empty Teams `Posture` column (finding F — Will chose brief-literal) · touching any
pipeline, transform, loader, engine constant, the store or the frozen corpus.
