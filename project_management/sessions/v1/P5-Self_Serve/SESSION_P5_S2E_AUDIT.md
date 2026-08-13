# P5 · S2e — PM audit of the honesty pass

> **CLOSED 2026-08-13 — deployed (Fly v27) and confirmed live.** `/api/standings` carries no
> `posture` key and `/api/leagues` is flat, on both `surplusff.com` and `fantasy-ai-api.fly.dev`.
> The body below is left exactly as written at audit time.
>
> **The blocking finding was correct, and one of my follow-up probes was not.** Will's
> `fly releases` settles the first half: at audit time the current release was **v25, 22h old —
> older than the S2e merge**, so production genuinely was not running it. **v26** and **v27**
> are his deploys after the audit.
>
> **My error, and it cost Will a round trip.** After he deployed I kept reading pre-S2e payloads
> and told him the release had not taken. It had. **`WebFetch` does not honour an appended
> cache-buster** — `?…&_cb=<new value>` returned my *morning's* cached body every time, which is
> why every "fresh" probe came back byte-identical down to the floating-point noise. Changing the
> **parameter order** (`?zz=1&league_id=…`) produced a genuine fetch, and it showed the deploy
> live. **Reordering works; appending does not.**
>
> The lesson is the one this audit is about, turned around on me: *check the instrument before
> trusting the reading.* I verified the site and never verified the tool I was verifying it with —
> a byte-identical repeat reading is evidence of a cache, not of a stable system, and I had
> already written the "identical bytes" observation down twice without asking what else explains
> it. **A second hostname was the cheap independent check** (`fantasy-ai-api.fly.dev` disagreed
> with `surplusff.com` while DNS proved both resolve to the same Fly IP — same app, so the
> difference could only be in my read path).


**Audited:** 2026-08-12 · **Report:** `SESSION_P5_S2E_REPORT.md` · **Brief:**
`SESSION_P5_S2E_SELECTOR_AND_CLINCH.md` · **Range:** `84a08c1..3c0aed2` (3 commits + merge, pushed) ·
**Verdict: CODE ENDORSED — SESSION NOT COMPLETE. One blocker: it is not deployed.**

The five items are built correctly and the three findings the report volunteers all survive independent
re-derivation. But **surplusff.com is still serving pre-S2e payloads**, so none of it is live, and all
three of Will's post-deploy checks fail today for a reason that has nothing to do with the code.

---

## BLOCKER — merged and pushed, not deployed

The brief's closing line: *"Touches `application/api/*` and `application/frontend/*` — **REDEPLOY and
confirm live on https://surplusff.com/**."* The report is headed **"Shipped 2026-08-12"** and never
mentions a deploy anywhere in its body.

**I captured the live payloads BEFORE the merge** (baseline in project memory, `s2e-baseline-2026-08-12`).
Re-fetched after, cache-busted with a throwaway query param on every call:

| probe | expected after S2e | actual, live now |
|---|---|---|
| `/api/leagues` | flat, one entry per (league, season) | **`seasons:[…]` still nested** — pre-S2e |
| `/api/standings?league_id=DEMO-2025` | no `posture` key | **`posture` present on all 10 rows** |
| `/api/league?league_id=DEMO-2025` | no `posture`, `<1%` reachable | **byte-identical to the pre-merge baseline** |

Meanwhile `main` is unambiguously correct: `reads.py:610` withholds `posture` with the reasoning in
place, and `reads.py:1253` documents the catalog as **"FLAT since P5/S2e"**. **The code is right; the
running binary is old.**

**Four probes, two endpoints, all consistent — so this is not a half-landed deploy.** I checked
deliberately, because `denied_reads` being per-process told us there are **two Fly machines**, and a
deploy that reached one of them would be far nastier than one that reached neither. It didn't split.

**Stated honestly:** I could not run `fly status` — no egress from the container to fly.dev, and none
from the device VM at all. So the *observation* is "production serves pre-S2e payloads on every probe";
the *inference* is "the deploy never ran or failed outright." Per this project's own rule — **config
declares intent, only the platform knows the fact** — treat the inference as unconfirmed. Every
explanation (no deploy, failed deploy, rollback) needs the same next action.

**Action: `fly deploy`, then re-run Will's three checks.** Nothing else is outstanding.

## The report's strongest verb doesn't hold

> *"**Live in the browser, signed out:** rank 9 reads 'Needs help to clinch · `<1%`'…"*

That was a **local** browser, not surplusff.com — the live site cannot produce that string today, because
it still serves `posture` and still rounds 0.3 to `0%`. The observations are almost certainly true of the
build that was running; the word **live** reads as production and isn't. This is the project's own
standing lesson (*check the report's strongest verb — ask what artifact backs it*) landing on a single
adjective, and it is the second half of the same gap as the missing deploy: **deploy is a separate gate
from merge, and "verified in a browser" is a separate claim from "verified in production."**

---

## Verified independently — not read from the report

1. **The copy gate reproduced from scratch.** Staged `check_league_copy.mjs` + `format.js` into a clean
   container and ran them on `node v22`: **39/39 green.**
2. **And it bites — at exactly the claimed strength.** I reconstructed the pre-S2e logic from
   `League.jsx:291-296` at `84a08c1` (`'Clinched a spot'`, `'Must win out'`, `` `Clinch in…` ``, bare
   `Math.round`), substituted it for `format.js`, and re-ran: **13/39 pass → 26 fail.** The report claims
   *"26 of the 39 fail against the pre-S2e logic."* **Exact.** A prove-it-bites number that survives an
   independent reconstruction is the strongest artifact in this report.
3. **Finding A — the dead branch is dead by construction, as claimed.** `compute_bracket_sim.py:290-296`:
   `R = len(list(weeks))`, `for k in range(R + 1)`, so `m ∈ {0..R} ∪ {None}`; `:301` returns
   `"remaining_games": R` — **the same scalar**. Therefore `magic_wins > remaining_games` is unreachable
   from this producer. The report proves this rather than asserting it, and **keeps** the branch behind a
   fixture — correct, and consistent with the S2c precedent that a pure predicate's contract is its
   signature, not today's callers.
4. **Finding B — confirmed.** `:351` persists `round(float(agg["playoff_odds"][i]), 3)` on a **0-1
   fraction**, so a genuine 4/10,000 lands as exactly `0.0` before display sees it. Correctly scoped as
   *reported, not fixed* — it is a transform, outside the scope guard.
5. **Finding C — confirmed, and the tell is precise.** `:301` `"remaining_games": R` is a scalar while
   `"magic_wins": magic` is per-team; `:356` consumes it as `agg["remaining_games"]` with **no `[i]`**,
   unlike every neighbouring field. Real, latent on a 10-team league.
6. **Finding D — matches my own pre-session finding exactly.** `frontend/src/posture.js` was deleted in
   `e94eba7`; `derive_posture` has one home. I had found this before the session and filed it; the report
   reached it independently. **The brief was wrong and both of us caught it separately.**
7. **The map is reshaped, not gutted.** Diagonal, quadrant washes and the four corner labels are gone;
   the dot filter correctly re-bases from `t.posture` to `t.allPlayPct != null` (it would have rendered an
   empty chart otherwise); the caption is replaced; the tooltip uses `fmtOdds` for odds and plain rounding
   for all-play.
8. **The existing `<Gate regime={REGIME.TREND}>` was preserved.** I had flagged this as the brief's one
   real misread risk — *"Do NOT use Gate"* sits next to a component already wrapped in one, and removing
   it would have regressed P2/S4a's thin-data window. Code kept it **and wrote down why**.
9. **Docs honour §7.** STATUS **277 → 279** and ARCHITECTURE **195 → 200** while adding a new caveat —
   condensed, not appended. The P5 audit list gained **S2C_AUDIT.md *and* S2D_AUDIT.md**; the brief only
   noticed the first.
10. **All-play % deliberately kept plain rounding.** Correct and the sharpest judgement call in the
    session: all-play is a **realized** record, so 0 of 45 really is 0%; hedging it would have been less
    honest. Distinguishing an estimate from a realized count is the whole point of the pass.

## Finding — F is slightly larger than the report scopes it

Report finding F (Will chose brief-literal, so this is accepted debt, not an error) names the Teams
`Posture` column, its header and one sub-header sentence. There is a fourth site: **the League panel is
still titled "Posture Map"**, with the note *"playoff odds × true record"* — a panel named for the read
the product has just decided not to make. `Teams.jsx:44-45` also still tells the reader *"The **posture**
chip reads standing against true record"* above ten em-dashes.

Not urgent and not wrong — but worth naming, because the honesty pass ships a column that **promises a
read and delivers ten dashes**, one click from the landing page. Standing instruction 5 says *absence is
reported, never fabricated*; a uniformly empty column under a promising header is closer to fabrication
than the blank cell that started this session. The follow-up is small: drop the column, the header, the
sentence, and rename the panel.

## Named gaps — what the demo cannot prove

Not faults. Recording them so nobody counts them as evidence later.

- **`me.posture` is unexercised.** `/api/league` nests the same row under `me`, but `me` is `null` on the
  signed-out demo. The withhold on that path is proven by **shared code**, not by observation. First real
  exercise is **Gate A**, when Will's league gives a viewer seat.
- **`>99%` and `magicWins <= 0` never fire on live data** (max odds 94.2, min `magicWins` 5). Fixture-only
  — which is correct, and the gate covers both. But no live screenshot can ever demonstrate them.
- **`check_ownership` / `check_isolation` green** is read from the report; both need a live DB I cannot
  reach from here.

## Verdict

**Endorse the code. Do not mark S2e shipped until it is deployed.** The engineering is strong — three
volunteered findings beyond the brief, all three correct under independent re-derivation, plus two brief
errors caught (`posture.js`, and the render-site undercount I had also flagged pre-session). The single
gap is the last step in the brief's own closing line.

**One action: deploy, then re-run the three checks in the brief.**
