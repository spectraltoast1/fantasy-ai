# Store-Migration Audit — Session 4 (League + Matchups + team-detail `thisWeek`)

**Reviewed:** 2026-07-25 · **By:** PM (independent, against the live git repo + real data)
**Scope:** the shared projection/win-prob engine, the four new endpoints (`/api/league`, `/api/positional-talent`,
`/api/matchups`, `/api/matchups/{id}`), and the `thisWeek` bar wired into `/api/teams/{id}`.

**Bottom line: complete, faithful, and the cleanest session yet.** No blocking issues; the findings are all
low/latent. Code also fixed the two process gaps from the Sessions 1–3 audit — it updated STATUS.md *and*
TECHNICAL_ARCHITECTURE.md at closedown, and it implemented the null-safe guardrail I asked for. It even added a
unit test I didn't require.

> **Correction to my read mid-review.** Earlier I reported Session 4 looked unfinished — engine built but "not
> wired," endpoints absent. **That was wrong, and the cause is worth flagging:** the file-sync bridge was serving
> me a **stale, pre-merge snapshot** of `reads.py`/`routes.py`/`STATUS.md` (it kept returning the old files even on
> re-stage). I caught it by going to git directly on your machine: HEAD contains the full wiring, the working tree
> is clean, and `reads.py`-at-HEAD matches the feature branch exactly. Session 4 is fully merged. Lesson for future
> audits: cross-check the bridge against `git` when something looks reverted.

---

## How this was verified

I audited the **live git HEAD** (not the stale bridge copy): the Session-4 diff of `reads.py`/`routes.py`
(commits `12c5b22` engine, `bf80d8c` matchups+thisWeek, `d38109d` league), `projections.py`, and
`check_projections.py`, field-by-field against the `queries.js` contract (`loadLeague` l.370, `loadPositionalTalent`
l.396, `loadMatchups` l.878, `loadMatchupDetail` l.942, `teamProjections` l.765, `teamMatchupSummary` l.846). Then,
independently:

- **Reproduced the win-prob engine against the real parquet** (as-of week 4 → week-5 slate). Every matchup's
  win-probability pair sums to exactly **100**, μ values land in a sane **94–133** range, and each optimal lineup
  fills the league's **8** starting slots (QB / 2·RB / 2·WR / TE / 2·FLEX). The math produces correct, coherent
  results on the live league.
- **Null-checked `projection_consensus`:** `center_ppr`/`band_ppr`/`p25`/`p50`/`p75` all have **zero nulls** in the
  current data, and week 5 has 298 projection rows (week 19 correctly empty). So the endpoints match today's app;
  the `_num` guardrail is protection for Stage B, not a live fix.
- **Confirmed the circular import resolves.** `reads` and `projections` import each other at top level; running the
  test locally sailed through both modules' imports and only stopped at a missing `psycopg` in the device VM — i.e.
  the cycle resolves cleanly (I couldn't run the test to green because the API venv isn't runnable in the bridge VM
  and it has no network for Supabase; I verified the test's assertions by hand instead — Φ(0.5)≈0.760 → 76/24,
  lineup total 85).

---

## What Code got right

- **The engine is built once and shared.** `projections.py` holds `expand_slots` / `optimal_lineup` /
  `team_projections` / `matchup_win_probs` / `normal_cdf` / `team_matchup_summary`, and all three surfaces
  (`load_matchups`, `load_matchup_detail`, the team-detail `thisWeek`) call it — not inlined three times, exactly as
  scoped.
- **All four endpoints + `thisWeek` are faithful ports.** Field names, nesting, null sentinels, and the sort orders
  match `queries.js` — including the two-key sorts (my team first → higher win % ; my game first → matchup_id
  ascending) and the matchup-detail Score Range (Σ starters' `p25 ?? pts`).
- **The subtle traps I flagged in the brief were all handled:** μ is `round1`'d at the team level *before* the
  win-prob math reads it; σ stays raw; `normal_cdf` uses `math.erf`; the roster read carries `ORDER BY
  sleeper_player_id` so the optimal-lineup tie-break is deterministic; `target_week = N+1`.
- **The null-safe guardrail is in.** `projections._num(x, default)` replaces bare `float()` on the nullable
  projection columns and reproduces the browser's `Number(null)===0` / `p25 ?? pts` fallbacks. Good judgment on
  where *not* to use it too — `load_positional_talent` keeps a bare `float(pos_vor)` because `sum(greatest(...,0))`
  over a non-empty group is provably never null.
- **Reused, didn't re-derive.** `reads._latest`, `reads._week_cutoff`, `reads._sql_standings_weeks`,
  `calcs.round1`/`js_round` are all reused, so the surfaces agree on who's rostered and how points round.
- **`MY_USERNAME`/`*_ppr` untouched; the seam held** (no `queries.js`/`db.js`/view edits).
- **Closedown discipline restored.** STATUS.md now reads "Session 4 SHIPPED … League + Matchups + team-detail
  thisWeek," with Session 5 as the next move and the prior entries preserved (a follow-up commit even restored the
  S1–3 audit's verbatim Prior entries); TECHNICAL_ARCHITECTURE.md notes the new engine. Both the doc gaps from the
  last audit are closed.
- **Bonus: a real unit test.** `check_projections.py` hand-checks the fiddly bits — expand-slots ordering, the FLEX
  taking the best leftover, first-seen winning a points tie, a hand-computed 76/24 win probability, and `_num`.

---

## Findings register — all low

| # | Severity | Finding |
|---|---|---|
| 1 | Low (latent) | `load_league` `playoffCut`/`nTeams`: if a `league_settings` row is *present with a null value*, JS yields `0` (`Number(null)===0`) while Python yields `None`. Same family as S1–3 finding 2; won't fire (these config values aren't null), and an *absent* row already matches (both → null/length). |
| 2 | Low | `reads` ↔ `projections` **circular import**. It resolves cleanly (verified) and Code documented why, but a small shared-helpers module (`_latest`/`_week_cutoff`) would be tidier than two modules importing each other. Cosmetic/architectural. |
| 3 | Low (efficiency) | Connections per request grew: `/api/teams/{id}` now opens ~5 psycopg connections (its own block + the `team_matchup_summary` → `target_week_for` / schedule / `team_projections` / sides chain); `/api/matchups` ~3. Fine at this scale over the session pooler; a note if traffic ever grows (the browser did one in-memory `Promise.all`). |

That's the whole list. Nothing blocks Session 5.

---

## Carry-forward (unchanged by this session)

- **Null policy → still Session 5.** The guardrail *pattern* now exists (`_num`), but the **decision** — show `0`
  vs render "—" — is still Session 5's call, and the S3 reads' bare `float()` on `playoff_odds`/`roster_total_points`/
  `vor`/`market_vor` still want the same treatment when that decision is made. Recommend Session 5 adopt `_num`
  across those reads at the same time.
- **Fly secrets → still deploy-time.** `LEAGUE_ID` + `MY_USERNAME` as Fly secrets remain a Session-5/6 checklist
  item; the endpoints are still local-only (the live app is the Session-1 skeleton).
- **Live curl-parity is the one check I couldn't run** — the device VM has no network to Supabase, so I verified the
  code + the engine math + the data (no nulls) rather than the deployed numbers. Code's brief-required curl check is
  the belt-and-braces; given zero nulls, parity should hold. Worth a glance at Code's verification output if it
  produced one.

## Recommendation
Proceed to Session 5 (the frontend swap). The backend read layer is now complete and sound across all surfaces.
Fold the null-policy decision + `_num` adoption into that session, and set the Fly secrets before go-live.
