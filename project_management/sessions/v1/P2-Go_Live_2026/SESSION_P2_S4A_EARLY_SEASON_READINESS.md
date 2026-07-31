# V1 · Project 2 · Session S4a — Early-season readiness (the "too early" regimes) — a brief for Code

**Last reviewed:** 2026-07-31 · **Status:** Ready to run · **Owner:** Code drives; Will confirms the one
voice-fork (honest-low-confidence vs gate) + eyeballs the early-week states on the 2025 replay. **Project:**
`projects/v1/P2_GO_LIVE_2026.md` (S4a of P2). **The honest-launch core: make every surface behave truthfully
in the thin-data window every invitee will hit.**

> **What this session does:** make the product degrade *honestly* across the early-season window — preseason
> (0 games) → Week 1 (1 game) → Weeks 2–3 (thin) → normal. The engine already *advances* cleanly on
> projections-only (S2), but the *display* side isn't truthful for thin data: the silent reads (production
> VOR, player-signal direction, playoff wins/seed) show authoritative-looking numbers with **no confidence
> signal** (the logged law-2 gap), and there's no explicit "too early" state. S4a gives the thin-data window
> an honest voice. Built + proven on the 2025 replay (simulate Weeks 1–3) + the 2026 preseason substrate;
> data-proven live at the calendar gates.

> **Why it's launch-critical:** every invitee onboards into an early-season regime (preseason at launch prep,
> then Weeks 0–3 live). A Week-1 playoff-odds number that looks precise but is near-noise is exactly the
> dishonesty the north star forbids. Unlike the band (S3b) and market (S3), early-season honesty is exercised
> the moment *any* real league loads — so it can't ship dark; it must be right before the cohort onboards.

## The timing reality (shapes verification)
It's preseason — 2026 has no games. So S4a is BUILT and PROVEN against a season that has weeks: replay the
is_mine **2025** league at Weeks 1, 2, 3 to exercise each surface's thin-data state, and use the 2026
preseason substrate for the 0-games state. When 2026 games start (Week 1) the same states light up on real
data — no new code. Don't wait for 2026 games to build this.

## Your part, Will (~5 min — one voice-fork + the eyeball)
One call: **when a surface has near-zero signal early (playoff odds in Week 0–1 especially), do we show the
honest low-confidence number flagged "too early," or gate the panel off?** I recommend **show + flag**
(honest-not-hidden), gating only where a metric is genuinely undefined at 0 games. Then the eyeball: on the
2025 replay at Week 1, every surface should read as *honestly uncertain* — wide bands, explicit
"too early / leaning on baseline" cues — not false precision, and nothing crashes.

## Decisions I made for you (Code: follow unless you hit a reason not to)

1. **Prefer an honest low-confidence state over gating (recommended).** The north star is honest, not hidden.
   Where a surface has *some* signal, show it with an explicit confidence/too-early cue (wide band, "leaning
   on preseason baseline," "too early to separate"). Gate a panel OFF only when the metric is genuinely
   undefined at 0 games. *(Contrast the market, which gates off because a cross-time number is misleading; a
   wide early band is honest, so it shows.)*
2. **Give the silent reads a confidence signal — this is the core.** Production VOR, player-signal direction,
   and playoff wins/seed render with no confidence cue today (the law-2 gap) and are most dangerously
   overconfident early. Add a confidence/too-early signal keyed to how much real data the league has. Meatiest
   piece; if the session runs long, the **playoff-odds too-early state + band captions must ship**, and the
   fuller VOR/player-signal calibration can split to a fast-follow.
3. **One source of truth for "how early are we."** Derive a single games-played / as-of-week signal per league
   (the engine already advances `as_of_week`) that every surface keys off — don't let each surface invent its
   own threshold. Default: 0 games = preseason; <3 games of real results = early. Adjustable.
4. **Bands already widen honestly — verify + caption, don't re-tune.** The projection + ROS bands lean on
   positional priors when the player's residual sample is thin (S1's forward path), so they're *already*
   honest-wide early. Verify that's legible (a thin-sample band reads as uncertain, not broken) and add a
   short "early-season: leaning on positional baseline" caption below the threshold. Do NOT change band
   constants — that's a tuner/propose-only matter, not S4a.
5. **No-crash invariant.** Every read must handle a 0-actuals / thin week without erroring (projections-only),
   consistent with S2's pipeline handling. Prove it on a preseason (0-games) league and a Week-1 league.
6. **Scope guard.** Touches the reads (early-season signals) + the frontend (too-early states/captions) + a
   small games-played helper → redeploy. Does NOT touch the loader/refresh mechanics (S2), the market turn-on
   (S4b — separate), auth/onboarding (P5), the frozen corpus, or band constants. Runs locally; the states are
   data-proven live at the gates.

## The brief to paste to Code

```
Goal: V1 Project 2, Session S4a (projects/v1/P2_GO_LIVE_2026.md) — early-season readiness. Make every
user-facing surface degrade HONESTLY across preseason (0 games) -> Week 1 -> Weeks 2-3 -> normal: honest
low-confidence / "too early" states and wide-but-honest bands instead of false precision, and never crash on
a thin/empty nfl_stats week. BUILD + PROVE on the 2025 replay (is_mine league at Weeks 1/2/3) + the 2026
preseason substrate; the same states light up on live 2026 at kickoff with no new code.

Part 1 — one "how early are we" signal:
- Derive a single games-played / as-of-week signal per league that all surfaces key off (don't let each
  surface invent a threshold). Default: 0 games = preseason; <3 games of real results = early. Adjustable.

Part 2 — give the silent reads a confidence signal (the core; law-2 gap):
- production VOR, player-signal direction, playoff wins/seed render with no confidence cue and are most
  overconfident early. Add a confidence/too-early signal keyed to the how-early signal. Prefer an honest
  low-confidence state over gating; gate a panel off only when a metric is genuinely undefined at 0 games.
- Playoff odds (Monte Carlo) in Week 0-1: show an explicit "too early to separate" low-confidence state, not
  a false-precise number.

Part 3 — bands: verify + caption (do NOT re-tune):
- Confirm the projection + ROS bands widen honestly on thin samples (they lean on positional priors - S1's
  forward path) and read as uncertain, not broken. Add a short "early-season: leaning on positional baseline"
  caption below the threshold. Do NOT change band constants (tuner/propose-only).

Part 4 — no-crash invariant:
- Every read handles a 0-actuals / thin week without erroring (projections-only). Prove on a preseason
  (0-games) league and a Week-1 league.

Verify by replaying the is_mine 2025 league at Weeks 1, 2, 3: each surface reads as honestly uncertain early
and sharpens as weeks accrue; the 2026 preseason substrate renders the 0-games state; nothing crashes.

Scope guard: touches reads + frontend + a small games-played helper. Does NOT touch the loader/refresh (S2),
the market turn-on (S4b), auth (P5), the frozen corpus, or band constants. Redeploy to surface.

Follow SESSION_GUIDE: fresh worktree, worktree-setup.sh, 3-commit cap, update STATUS.md, close/merge, push.
Suggested commits: (1) the how-early signal + no-crash invariant + tests; (2) silent-reads confidence signal
+ playoff-odds too-early state; (3) band early-season captions + redeploy + live verify + STATUS. If long, the
full VOR/player-signal calibration is the piece to split to a fast-follow; playoff-odds + captions must ship.
Show me: the is_mine 2025 league at Week 1 vs a later week on a couple of surfaces - honestly uncertain
early, sharpening later.

Close: update STATUS.md (P2/S4a done: early-season regimes honest across surfaces; silent reads carry a
confidence/too-early signal; bands captioned early; no-crash on thin weeks; proven on 2025 replay, live at
kickoff. Next = load the first 2026 league at draft to data-prove the ready-but-dark work; S4b market turn-on
post-launch). Merge/push.
```

## Definition of done (S4a)
✅ Across preseason → Weeks 1–3, every surface reads honestly: the silent reads (production VOR, player-signal,
playoff wins/seed) carry a confidence/too-early signal; playoff odds show "too early to separate" rather than
false precision in Week 0–1; the projection + ROS bands widen honestly on thin samples with an early-season
caption; and no read crashes on a 0-actuals/thin week. Proven by replaying the is_mine 2025 league at Weeks
1/2/3 (honestly uncertain early, sharpening later) + the 2026 preseason state. Loader/market/auth/constants
untouched. Redeployed. STATUS updated; next = load the first 2026 league.

## Notes / gotchas
- **Honest, not hidden.** The default is to *show* uncertainty (wide band, low-confidence flag), not to gate.
  Gating is for *misleading* reads (the cross-time market); an honestly-wide early band is exactly what we
  want a user to see.
- **Don't re-tune the engine.** S4a is a display/honesty session. Band widths and constants are the tuner's
  domain (propose-only). If a band looks wrong early, that's a finding to log, not to fix here.
- **Handoff:** after S4a, the next event is loading the first real 2026 league (Will's draft, ~late Aug) — the
  milestone that data-proves S3b's band, S2's refresh, and S4a's regimes at once. S4b (market turn-on) is the
  post-launch fast-follow.
