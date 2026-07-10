# STATUS

**Last updated:** 2026-07-10 (§7 Manager Dossiers reshaped into a **cross-league, Claude-API-key-gated AI read** — the design, locked parameters, and buildable facts are recorded in `DECISION_READS.md` §7 for the next build session (a docs-only planning session; no code). Prior build: the §2 ROS Outcome Shape skeleton shipped — bull/bear = borrowed ROS centre ± BULL_Z·√Σband², calibration-gated (coverage 0.835), completing the player-read backend §1–§4. Phase 4 still UNDERWAY — remaining: §7 dossiers (design recorded) + front-end surfacing)
**Target ship:** NFL kickoff, mid August 2026

---

## Project Management
- my role is CEO/CFO managing the project as a whole, role responsibilities include:
    - owning product direction decisions
    - connecting Claude Chat input/output and Claude Code input/output
- Claude Chat sessions will serve as Product Manager, role responsibilities include:
    - advising on project goals, product direction, and build method
    - writing prompt instructions for Claude Code to execute singular build tasks
    - review the after-build action report from Claude Code
- Claude Code sessions will serve as Software Engineer, role responsibilities include:
    - receive the prompt instruction from the Claude Chat

## Project Overview (what are we working toward)

Winning a redraft fantasy football championship is about more than just collecting all of the best players. It is about how you manage your specific team in your specific league. Knowing when you need to act - or not act - as a team manager is as valuable as knowing which individual players to target or avoid. This tool focuses on helping you navigate your league using real data signals: how your team is trending, where your real weaknesses are, and what your opponents look like. The goal is fewer decisions driven by anxiety or noise, and more decisions made on league-winning signal.

The project will do this in two ways: a dashboard for user-driven insight and an AI layer for interpretation and decision suggestions. The AI layer is not meant to run the team - it's a consultation, putting data-driven suggestions alongside the user's own analysis to produce better decisions.

> Tech non-negotiables (polars-only, all I/O through data_layer.py, client-side
> DuckDB-WASM with src/queries.js as the server seam) live in **CLAUDE.md** and
> **TECHNICAL_ARCHITECTURE.md** — not restated here.

## Today (the current status toward v1)

> **Maintenance (rolling log):** keep only the **most recent build + the 2 prior**
> (3 prose entries max). At closedown, prepend the new build and delete the oldest
> prose entry. Nothing is lost — the cumulative record lives in `> built` below; this
> section is just the recent-detail window. Keeps the doc light for every session.

> most recent build
**ROS Outcome Shape — the §2 bull/bear/situation quantitative skeleton (completes the player-read backend, §1–§4).**
The forward player read that frames "what's the realistic rest-of-season range for this player, and how solid
is the ground under the bet?" — built as the **ROS-horizon analog of the already-calibrated §3 weekly spread.**
`compute_ros_outcome_shape.py` → `derived/ros_outcome_shape_{season}.parquet`, tall over (as_of_week, roster_id,
player). **Bull/bear = the borrowed ROS centre ± BULL_Z·ros_sigma, floored at 0:** `ros_center` is Production
VOR's `ros_value` **reused directly** (Σ weekly consensus centres over the remaining schedule — borrowed, can't
drift from §4, law 3); `ros_sigma = √(Σ band_ppr² over the same remaining weeks)` — the §3 shrunk weekly
residual std combined under **weekly independence** (the same assumption `compute_bracket_sim`'s team σ
documents). New pure `_ros_sigma` (mirrors `_ros_values` but aggregates band²) + `_outcome_band`; `ros_cv =
sigma/centre` as a fragility proxy; a per-position league-relative `spectrum_pos` on the bull ceiling. **Time
decay is emergent, not a mechanism:** as N advances the remaining schedule shrinks → Σband² shrinks → the band
compresses toward the realised path (verified: 0 of 142 players' σ grew wk1→wk4; mean σ 23.0→20.8), exactly
§2's dynamic. **Situation/security borrows the player_signal trust axis** — the Sleeper `security` tier +
`direction`/`reliability`, carried as structured evidence (not fused into a grade; the AI narrative + 1-10
roll-up is Phase 6). New `data_layer.write/read_ros_outcome_shape` (mirrors the Production VOR tall block).
**Gate** (`backtest_ros_outcome_shape.py`, exit 0, imports the shipped `_ros_sigma`/`_outcome_band`):
(1) **calibration** — freeze-wk actual ROS lands in [bear, bull] at **0.835** (target 0.80 ± 0.05; answer key =
Σ realised PPR over remaining weeks); `--sweep` tuned **BULL_Z → 1.645**, a real finding — it sits *above* the
normal-theory 1.28 for 80% because a player's weekly residuals are **positively autocorrelated** over a season
(a bust persists), so realised ROS is more dispersed than the independent sum and the band must widen to stay
honest. (2) **decision-relevant** — actual ROS rises monotonically by `ros_bull` tercile (dead 58 < mid 126 <
stud 206). **Bonus:** the situation axis carries signal — non-stable players broke their bear floor **15.9%** vs
stable **9.8%**. Symmetric-by-design (no ROS-level skew term — a documented deferral; the §3 per-week band
already carries the skew this sums over). No-regression: reads-only of production_vor/consensus/player_signal
(untouched). No UI (data + gate). **Next — remaining Phase 4:** manager dossiers (§7 — **reshaped 2026-07-10
into a cross-league, Claude-API-key-gated AI read; design + locked params + buildable facts recorded in
`DECISION_READS.md` §7** for the next build session, phased A = cross-league acquisition + behavioral
features, B = the gated Haiku dossier writer) and the **front-end surfacing** of the now-six gated forward
reads (Spread/VOR/True Rank/Positional Depth/Bracket Odds/ROS Outcome Shape).

> earlier build
**Any-league pieces 2 & 3 — roster-shape/superflex generalization + division-aware seeding (project complete).**
Finishes the "any league" project (piece 1 = the custom-scoring engine, prior build). Both are
**generalizations** with no real-data answer key (the real league is standard 1QB PPR, no divisions), so
both are gated like piece 1: **no-regression on the real league + synthetic-config correctness.**
**Piece 2 (roster-shape/superflex, fully gated).** Two hardcodes assumed "1QB + standard flex" and
mis-handled superflex/2QB: VOR's `_pool_of` matched only a slot literally named `FLEX` (missed
`SUPER_FLEX`), and leakage's `_cls` was `QB`-vs-`FLEX`. Both now derive the swap/replacement pools from
the league's declared `lineup_slots` via one shared helper **`_analytics.position_pools`** (positions
sharing a multi-position slot are pooled; pool key = the broadest inducing slot name, so the standard
config reproduces the old QB/'FLEX' partition **and labels** byte-identically, while superflex pools QB
with the flex). `expand_slots`/`optimal_lineup` were already general — untouched. **Gate**
(`backtest_roster_shape.py`, exit 0): (A) no-regression — `production_vor`/`team_leakage`/`true_rank`/
`positional_depth` all **frame-equal** to on-disk for the real league; (B) synthetic superflex — pools
QB with RB/WR/TE, VOR measures QB against the flex waiver line, and a benched QB is a legal `SUPER_FLEX`
swap for a started RB. **Piece 3 (division/tiebreaker seeding — synthetic-gated latent).** `_seed_table`
extracted from the bracket sim's `_simulate` and made division-aware: with a roster→division map (≥2
divisions) division winners are seeded ahead of wildcards (Sleeper default), else the flat (wins,
points-for) seed — **proven identical to the old inline formula**, so the no-division real league is
unchanged. `sleeper.py fetch-league-config` now persists `settings.divisions`; the per-roster division
map (`_division_map`) reads a `division` column when persisted (None today — the teams entity carries
none; populating it from the rosters endpoint is the **deferred** follow-up). **Explicitly NOT validated
on a real division league** — revisit when one is onboarded. **Also fixed a pre-existing latent:** the
fixed `SEED` didn't reproduce run-to-run (polars `group_by` order is unstable and zero-score bye-week
ties flipped with row order) — sorting the schedule pairings + each roster's player list restores
determinism, without touching the shared `optimal_lineup`. **Gate** (`backtest_bracket_sim.py` extended,
exit 0): Brier 0.224 / Spearman 0.756 unchanged, plus NEW determinism (two runs frame-equal), invariant
(Σ playoff_odds = playoff_teams every as-of week), and synthetic 2-division correctness (a low-record
division winner is seeded into the top slots and makes the bracket where flat seeding drops it).
**Next — the "any league" project is done; remaining Phase 4:** §2 ROS outcome-shape skeleton, manager
dossiers (§7), and front-end surfacing of the gated forward reads. *(Update 2026-07-10: the §2 skeleton
has since shipped — see the most recent build. Remaining Phase 4 is now §7 + front-end surfacing.)*

> earlier build
**Custom-scoring recompute engine — the "any league" project's first piece (fills the stub).**
The last build left `_scoring.recompute_custom_points()` as a stub that **raised**: standard PPR/half/std
leagues ran, any custom scoring hard-failed. This builds the engine. **Design — delta on the canned
baseline, not from-scratch:** the data settled it — RotoWire's `proj_pts_ppr` is **not** reconstructable
from the 7 exposed projection components (off by up to ~2 pts; it bakes in projected turnovers/minor
bonuses the components don't expose). So the engine takes the **standard canned baseline**
(`proj_pts_std` / `fantasy_points`) and adds, per component, only the *delta* between the league's weight
and standard: `points_league = std_baseline + Σ(w_custom−w_std)·component`. **Exact for a standard league
by construction** (all deltas 0 ⇒ the canned column), robust to whatever the vendor baked in, and it
touches only the components that changed — applied with the **same weights on both sides** (`proj_*` and
`nfl_stats`) so residuals stay matched. **Supported:** any PPR value (incl. 0.75), any TD/yardage rate
(6-pt pass TD), and **position-conditional reception bonuses** (`bonus_rec_te`/`_rb`/`_wr`/`_qb` = TE
premium) as `bonus·receptions` gated on position. **Rejected — raises naming the key, never silently
mis-scores (law 2):** first-down (`pass_fd`/`rush_fd`/`rec_fd`) and threshold/yardage bonuses
(`bonus_rush_yd_100`, …) — the projections carry no component, so the *center* can't be scored faithfully;
they unlock when a component-carrying projection source lands in-season (ffanalytics/FantasyPros).
Turnovers/2pt are carried in the baseline at the standard rate (tolerance, as before). **Interface:**
`recompute_custom_points(scoring, side)` now returns a `pl.Expr` (the delta engine); `projection_column`
→ `projection_points_expr(profile, scoring)`; `actual_points_expr` gains `scoring`; the sole call site
`compute_projection_consensus.compute(season, scoring=None)` is now **injectable** (defaults to the
persisted settings) so the gate can exercise custom profiles without touching the parquet. **Gate**
(`backtest_scoring_recompute.py`, exit 0, reconciliation-style — the "answer key" is the canned columns):
(A) **equivalence** — custom path reproduces the canned columns on standard inputs (actuals **exact 0.0**,
projections **~0.01** = 2-dp component rounding); (B) **custom deltas exact** — 6-pt pass TD Δ = +2·pass_td,
TE premium Δ = +0.5·rec **TE-only**, 0.75-PPR Δ = −0.25·rec; (C) **rejection** raises naming the key;
(D) **end-to-end** — consensus runs under a real custom profile (0.75-PPR + 6-pt pass TD + TE premium),
**100% of QB centers rise**. **Verified no-regression:** recompute with the real (ppr) settings equals the
on-disk `projection_consensus_2025.parquet` **frame-for-frame**, so VOR/True Rank/Positional Depth/Bracket
gates (which read it) are unaffected; and **VOR runs on a custom consensus** in-memory (the downstream
seam proven). **Custom leagues now run the whole read spine.** **Next in the "any league" project:**
seeding tiebreakers/divisions in the bracket sim; roster-shape/superflex generalization (the leakage
miss-attribution + VOR superflex latents); richer custom scoring (first-down/threshold) when the
projection source carries the component.

> built
    - nflreadpy fetcher
    - sleeper fetcher (includes fetch_players() for Sleeper player registry)
    - nfl_sleeper join (left join, Sleeper-authoritative)
    - audit_join (resolves unknown-position remainders post-join)
    - front-end skeleton (React + Vite + DuckDB-WASM, reads live parquet) — Power Rankings panel
    - leaguelogs fetcher (daily market-value snapshots, all profiles) + launchd 4am-ET scheduler
    - sleeper teams fetch (fetch_teams → teams_2025.parquet) — real team names on Power Rankings cards
    - roster_positions fetch + derive_lineup_slots transform — declared starting-lineup config (lineup_slots_2025.parquet)
    - Power Rankings team drill-down drawer — all-play true record, lineup efficiency, weekly scoring, consistency + positional-shape spectrums
    - tab nav shell (League | Team) — App.jsx shell + LeaguePanel/TeamPanel split
    - Team tab foundation — your-team resolver (loadTeams + MY_USERNAME), team switcher, Overview/Players sub-tabs (stubbed)
    - Team Overview sub-view — vitals + "how this team is built": rate-based depth chart, league-relative star dependence, auto-surfaced lineup/hole signals; loadTeamRosters(), shared posColors.js [Overview lenses 1–2 of 4]
    - Team Overview — Form / trajectory lens: direction headline (heating up/cooling off/steady), league-relative Fading↔Surging spectrum, weekly column chart (beat/below median); last-half vs first-half scoring swing in loadTeamRosters() [Overview lens 3 of 4]
    - Team Overview — Where-you-leave-points lens: season points-left + efficiency % on a league-relative Leaky↔Optimal spectrum, per-week leak chart, biggest specific start/sit misses (eligibility-aware pairing); shared optimalLineup()/expandSlots() helpers + computeLeakage() [Overview lens 4 of 4 — Overview complete]
    - Team Overview refinement — Form lens → recency-weighted EWMA slope (half-life 2wk, ±4%/wk direction band, recency-faded weekly bars); computeForm() rewritten [backlog item 2]
    - Team Overview refinement — Lens-4 reframe (retrospective → improvement): efficiency-led, season points-left split into variance vs coachable (repeatable >10% bench-over-starter fix, sum-exact), named-miss list replaced by one rate-gap fix; computeLeakage() takes season role+rate map [backlog item 1]
    - Architecture refactor — form + leakage analytics extracted from queries.js → Python transforms (compute_team_form.py + compute_team_leakage.py → snapshots/derived/), tuning constants moved with them; queries.js slimmed to a thin read+assemble seam (−253 lines); loadTeamDetails efficiency consolidated to read the leakage parquet. View components untouched.
    - Phase 1 spike signal-quality engine — compute_player_signal.py → derived/player_signal_{season}.parquet (opportunity-vs-efficiency decomposition, regression_risk, sample-gated read); backtest_player_signal.py validates the shipped function against the full-2025 answer key (beats naive recent-points 13% on MAE; spike group regresses ~3.9 pts/g while sticky holds). First decision-critique slice; data + backtest only, no UI yet.
    - Phase 1 Players sub-view — sortable table surfacing the signal read per player (recent /g, directional verdict, volume rank, TD share); loadTeamPlayers(rosterId) seam reads player_signal.parquet (no JS math); direction-not-projection, question-framed (laws 2+4), sample-gated. The front end's first decision-coach surface.
    - Phase 1 per-panel readiness gate — readiness.jsx (assessReadiness + Gate): per-panel regime (structural/point-in-time/trend) → ready/building/tooEarly, with a "too early" fallback slot (accepts preseason content later) and an early-read note when building; wired into the Team tab (?weeksOverride=N for QA). Closes Phase 1.
    - leaguelogs snapshot reliability — snapshot() rewritten to write incrementally (cumulative today's-rows persisted after each profile) so a mid-run API failure leaves a recoverable partial day instead of discarding the whole run; idempotent re-run replaces a partial day (dedup on snapshot_date). 2026-06-18 captured (5 profiles, 3,409 rows; history → 14 dates). Follow-up still open: retry/backoff + off-laptop host.
    - Season-replay backend (Session A; parts 1–3) — `as_of_week` first-class column on the three derived analytics; tall grain `(season, as_of_week, entity)` materialized N=1..maxweek (each transform loops, filtering input to `week ≤ N`). Roster-as-of-N correctness fix falls out of that filter (`arg_max(week)` → "latest week ≤ N"). Per-analytic windowing framework: injected EWMA half-life via shared `_weighted_rates`; `backtest_player_signal.py --sweep` tunes the opportunity half-life on the 2025 answer key → ships cumulative (tested, not guessed). `data_layer` reads take optional `as_of_week` (default latest); `queries.js` default-latest guard keeps the front end on week 4. **Front-end week selector is Session B.**
    - Season-replay front-end (Session B; part 4 — grouping COMPLETE) — global "As of" week dropdown in the App shell (`App.jsx`); one selection drives League + Team and persists across tabs. `queries.js` threads `asOfWeek` via `asOfSlice(table, n)` (pick the week-N slice of the tall derived parquets) + `weekCutoff(n)` (bound inline `season.parquet` reads to `week ≤ N`, including `SQL_CURRENT_TEAM`'s `arg_max(roster_id, week)` → front-end roster-as-of-N); `n == null` ⇒ latest, so defaults are unchanged. New `loadWeeks()` feeds the dropdown (weeks 1..latest, default = latest = current week; travels back only). Readiness gate now runs off the selected week (`weeksElapsed = asOfWeek`); the temporary `?weeksOverride` QA param is retired. Verified live across weeks 1–4 (cutoff reshuffles rankings; trend panels degrade to too-early; roster-as-of-N departed flags; no console errors).
    - Phase 1 refinement — Opportunity to spec (`quality_rate`, `direction`/`reliability`, `security`, `point_correlation`) — see "most recent build" above for the full breakdown. `nfl_stats.py` gains a PBP-derived quality signal (`xtd`/`redzone_touches`); `sleeper.py`'s `fetch_players()` carries injury/depth-chart fields through. 2025 backtest gate unchanged (PASS/PASS, 13.2% MAE cut).
    - Data-layer I/O consistency — all fetcher parquet I/O routed through `data_layer.py` (Option-A coverage gap from a Phase 1 build audit). Added write_player_id_map / write_sleeper_players (+exists/age) / write_nfl_stats(week=) / write_sleeper_matchups / read+write_sleeper_transactions; rewired nfl_stats.py, sleeper.py (`_write_parquet_from_list` → `_rows_to_df` + `_snapshot_list`), audit_join.py. Raw JSON cache dumps kept as a documented fetcher exception. TECHNICAL_ARCHITECTURE truthed-up (fetchers in the I/O rule; LeagueLogs collect-only exception; MIN_GAMES 2→3 places). Behavior-preserving (byte-identical player_signal reproduction; backtest PASS/PASS).
    - Phase 2 projection substrate, source #1 (Sleeper) — multi-source `projections` entity in data_layer (write/read_projections; `source` a column on one growing snapshots/projections/projections_{season}.parquet; snapshot/append, dedup on (season,week,source)); `sleeper.py projections <season> [week]` mode pulls the NFL skill pool's weekly projections from api.sleeper.com (RotoWire), native sleeperPlayerId, QB/RB/WR/TE. 2025 backfilled wks 1–18 (54,594 rows); 100% coverage of rostered skill players at W1–4. FantasyPros joins later in-season via the same seam.
    - Phase 2 projection consensus + spread band — compute_projection_consensus.py → derived/projection_consensus_{season}.parquet (per week×player over the whole skill pool): borrowed consensus center + p25/p50/p75 band from the player's residual std (actual−proj) shrunk toward a full-pool positional prior, BAND_Z-scaled, floored at 0; disagreement_ppr column null under one source. Calibration-gated (backtest_projection_consensus.py, exit 0): 25–75 coverage 51.4% on the 2025 answer key, BAND_Z=0.6 swept-tuned; per-player shrink beats a naive one-size band on stratum uniformity. New _analytics.stdev + data_layer write/read_projection_consensus. 2nd source scouted: ffanalytics (in-season live disagreement), ESPN (deferred historical).
    - Phase 2 archetype skew (§3 c3) — completes the spread band to full 3-component spec. compute_projection_consensus.py gains a Cornish-Fisher skew shift (SKEW_GAIN·(g/6)·(BAND_Z²−1)) on p25/p75 driven by the player's residual skewness shrunk to a positional prior (new _analytics.skewness, SKEW_SHRINK_K=8); p50 stays the borrowed center. Design fork resolved by the answer key: the projection's TD-dependence archetype does NOT track residual skew (measured), the player's own residual 3rd moment does. Because BAND_Z<1 the shift moves both breakpoints down (center sits above realized median). Gate extended to per-tail calibration + joint BAND_Z×SKEW_GAIN sweep → (0.55, 1.5): coverage 0.493, tails 0.247/0.261 (tail error cut 5×), exit 0. No schema change to data_layer (new skew_ppr/resid_skew columns pass through).
    - Phase 2 Production VOR (§4) — compute_production_vor.py → derived/production_vor_{season}.parquet, the first read that consumes the substrate. Per rostered player: ROS value = sum of borrowed weekly consensus centers over remaining weeks; anchored waiver line=0, normalized by pool spread (top−waiver); QB its own pool, flex-eligible RB/WR/TE share a pooled waiver line (from lineup_slots). Tall over as_of_week (roster-as-of-N, roster frozen wks 1–4, projection horizon wk 18). New data_layer write/read_production_vor. Gate (backtest_production_vor.py, exit 0): projected ROS tracks actual at corr 0.944 QB / 0.955 FLEX, VOR tiers monotonic (dead<mid<stud). Simplifications documented: pooled flex line ignores dedicated-slot scarcity; superflex latent; Market VOR + trade gap V4.
    - Phase 3 True Rank (§5, first half) — compute_true_rank.py → derived/true_rank_{season}.parquet, the first league-level read consuming the substrate. Per team: roster_strength = sum of the optimal-lineup ros_value (fill QB/RB/WR/TE+FLEX from the roster by ros_value, most-constrained slot first) → record-independent roster-strength rank + league-relative spectrum_pos + bench_value. Re-aggregates Production VOR (no new engine); the optimal-lineup greedy lifted from compute_team_leakage into _analytics as shared expand_slots/optimal_lineup (leakage imports them, behavior-preserving). Tall over as_of_week (roster-as-of-N inherited from the VOR slice). New data_layer write/read_true_rank; _as_of_slice gains an "all" sentinel for whole-frame re-aggregation through the seam. Slot-aware: a 2-elite-QB roster ranks by its one startable QB (verified — roster 9 holds a 310-pt QB, ranks 9th of 10). Gate (backtest_true_rank.py, exit 0): projected strength tracks the actual ROS ceiling (mgmt-independent optimal lineup on realized points) at Pearson 0.802 / Spearman 0.842 (freeze wk4, n=10, floor 0.60); strong half +261.7 ROS over weak. No UI (data+gate, like VOR).
    - Phase 3 Positional Depth (§6) — compute_positional_depth.py → derived/positional_depth_{season}.parquet, the 4th and last Phase-3 cash-in read (3rd VOR re-aggregation). Per (as_of_week, roster_id, fine position QB/RB/WR/TE): re-slices the borrowed ros_value/vor net of the position's dedicated starter_need (from lineup_slots; shared FLEX excluded → flex-worthy depth = surplus). Carries starter_value, surplus_value + surplus_startable (beyond-need vor>0), marginal_vor (last dedicated starter's VOR = gap indicator), spectrum_pos within each position cohort, advisory surplus/adequate/gap shape (evidence-first). One row per (team, position) even at zero count (body-count gaps visible). Tall over as_of_week (roster-as-of-N from VOR). New data_layer write/read_positional_depth. Lossless re-slice (per-pos rostered_value sums to team VOR ros_value). Gate (backtest_positional_depth.py, exit 0): per position, projected starter_value tracks actual ROS ceiling (top-need by realized pts) at QB 0.792 / RB 0.867 / WR 0.855 / TE 0.928, mean 0.861 (freeze wk4, n=10/pos, floor 0.50); top half +85.3 over bottom. No UI (data+gate). Closes the Phase-3 read set (4/4).
    - Phase 4 Bracket Odds (§5 bracket-math) — compute_bracket_sim.py → derived/bracket_odds_{season}.parquet, the bracket-math half of Posture (with True Rank = §5 complete). Per team weekly score dist (μ = optimal-lineup Σ center_ppr, σ = √Σ band_ppr²; starters independent), analytic per-matchup win prob Φ((μA−μB)/√(σA²+σB²)) via math.erf; standings as-of-N from actual results; Monte Carlo (numpy, fixed seed, 10k) over the real remaining schedule → playoff_odds, proj_wins/points, avg_seed, magic_wins. Enabled by raw Sleeper matchups existing for all 18 wks. Playoff config (REG_SEASON_END_WEEK=15, PLAYOFF_TEAMS=6) inferred from schedule — documented latent. New data_layer write/read_bracket_odds + read_season_matchups. Verified wk4: Σ playoff_odds=6.00 (hard invariant); deterministic. Gate (backtest_bracket_sim.py, exit 0, config-light): Brier 0.224 beats coin-flip; expected wins vs actual Spearman 0.756; top-6 by odds = 6/6 actual playoff teams. numpy is the one compute dep. Simplifications: starter independence, Normal draw (no §3 skew), frozen-roster byes reduce μ. **[Superseded: the playoff config REG_SEASON_END_WEEK/PLAYOFF_TEAMS is now read from real league settings — 4 teams, not the wrong inferred 6 — see the league-settings build.]**
    - League settings (scoring + playoff) persisted + consumed — sleeper.py fetch-league-config pulls scoring_settings + playoff config from the /league object → data_layer write/read_league_settings (tall section/key/value) + read_scoring_settings/read_playoff_settings. transforms/_scoring.py dispatcher: scoring_profile ppr/half/std/custom; standard selects the canned projection column + nfl_stats actual expr; custom → recompute_custom_points() stub (raises; engine is the next project). Wired into compute_projection_consensus (scoring, byte-identical for this ppr league) + compute_bracket_sim/backtest (playoff via _playoff_config, injected, no hardcoded fallback). Real league: playoff_teams=4, playoff_week_start=16, profile=ppr. Corrects the sim's playoff cut 6→4 (Σ playoff_odds=4.00); all gates green. Standard PPR/half/std leagues now supported; foundation for the "any league" project.
    - Custom-scoring recompute engine ("any league" piece 1) — fills `_scoring.recompute_custom_points()` (was a stub that raised) with a **delta-on-canned-baseline** engine: `points_league = std_baseline (proj_pts_std/fantasy_points) + Σ(w_custom−w_std)·component`, exact for standard by construction. Same weights on `proj_*` + `nfl_stats` so residuals stay matched. Supports non-{0,.5,1} PPR, 6-pt pass TD, non-standard yardage/TD, position-conditional reception bonuses (TE premium `bonus_rec_te`/`_rb`/`_wr`/`_qb`); rejects (raises, names key) first-down / threshold-yardage bonuses (no projection component); turnovers/2pt carried in baseline (tolerance). `recompute_custom_points(scoring, side)` → `pl.Expr`; `projection_column`→`projection_points_expr`; `actual_points_expr` gains scoring; `compute_projection_consensus.compute(season, scoring=None)` injectable. New `backtest_scoring_recompute.py` (exit 0): equivalence (custom==canned on standard: actuals exact, proj ~0.01 rounding), exact custom deltas, rejection, end-to-end custom consensus (100% QB centers rise under 6-pt pass TD). No-regression: real-ppr recompute == on-disk consensus parquet frame-for-frame (downstream gates unaffected); VOR runs on a custom consensus. Custom leagues now run the whole read spine.
    - Any-league pieces 2 & 3 (project complete) — **roster-shape/superflex:** new shared `_analytics.position_pools(slot_rows)` derives swap/replacement pools from `lineup_slots` (positions sharing a multi-position slot pooled; key = broadest inducing slot). `compute_production_vor._pool_of` + `compute_team_leakage._cls` now use it (fixes the `SUPER_FLEX` latent + generalizes leakage swap classes); standard config byte-identical, superflex pools QB with flex. `backtest_roster_shape.py` (exit 0): no-regression frame-equal on vor/leakage/true_rank/positional_depth + synthetic superflex. **Division seeding (synthetic-gated latent):** `_seed_table` extracted from `compute_bracket_sim._simulate`, division-aware when a roster→division map is present (winners seeded ahead of wildcards) else flat (proven identical); `sleeper.py fetch-league-config` persists `settings.divisions`; `_division_map` None today (teams entity has no `division` col — rosters-endpoint population deferred). NOT validated on a real division league. **Also fixed:** the fixed-SEED bracket sim wasn't reproducible (polars group_by order + zero-score bye ties) — sorting schedule pairings + roster player lists restores determinism (shared `optimal_lineup` untouched). `backtest_bracket_sim.py` extended (exit 0): Brier 0.224/Spearman 0.756 unchanged + determinism + Σ-invariant + synthetic 2-division correctness.
    - ROS Outcome Shape (§2 quantitative skeleton — completes the player-read backend §1–§4) — compute_ros_outcome_shape.py → derived/ros_outcome_shape_{season}.parquet, tall over (as_of_week, roster_id, player). Bull/bear = the borrowed ROS centre (Production VOR ros_value, reused directly) ± BULL_Z·ros_sigma, floored at 0, where ros_sigma = √(Σ band_ppr² over the remaining schedule) — the §3 weekly band summed under weekly independence (compute_bracket_sim's documented assumption). New pure `_ros_sigma` (mirrors `_ros_values`, aggregates band²) + `_outcome_band`; ros_cv = sigma/centre (fragility), per-position spectrum_pos on the bull ceiling. Time decay emergent (shrinking horizon → tighter band; 0/142 σ grew wk1→wk4). Situation/security borrows the player_signal trust axis (security tier + direction/reliability) as structured evidence — the AI narrative + 1-10 roll-up is Phase 6. New data_layer write/read_ros_outcome_shape (mirrors the Production VOR tall block). Gate (backtest_ros_outcome_shape.py, exit 0): calibration — freeze-wk actual ROS in [bear, bull] = 0.835 (target 0.80±0.05), BULL_Z swept to 1.645 (above the normal 1.28 because weekly residuals are positively autocorrelated → realised ROS more dispersed than the independent sum); decision-relevant — actual ROS monotonic by ros_bull tercile (dead 58 < mid 126 < stud 206); bonus — non-stable players broke their bear floor 15.9% vs stable 9.8%. Symmetric-by-design (ROS-level skew deferred). No-regression (reads-only of the three source parquets). No UI (data + gate).

> not yet built
    >> backend
        - The Odds fetcher
        - FantasyPros fetcher
        - weather fetcher
    >> frontend
        - production front-end — React + DuckDB decided; Power Rankings panel built + deepened
          (team drill-down drawer with all-play, efficiency, weekly scoring, two spectrums).
          Remaining: more panels (per the Build Order below), deployment.

## Current build target
**Phase 1 (the spike signal-quality slice) is COMPLETE** — all four parts shipped:
(1) the engine (`compute_player_signal.py`), (2) the backtest gate (beats naive
recent-points −13% MAE on the full-2025 answer key), (3) the Players sub-view surface
(sortable table, direction-not-projection, question-framed), and (4) the per-panel
readiness gate (`readiness.jsx` — regimes + fallback slot). The descriptive dashboard
(Phase 0) plus the first decision-critique engine are both done; the project has made
the leap from *showing team state* to *grading a decision against a prior*. Still
frozen at Week 4 of 2025 for building. **The `READ_BUILD_ORDER.md` § Phase 1 "refine to
spec" delta is now also closed** — `quality_rate`/`direction`/`reliability`/`security`/
`point_correlation` bring the shipped engine's Opportunity read up to the full
`DECISION_READS.md` §1 definition (see "most recent build"). No UI surfaces these new
fields yet — that's a front-end follow-up, not blocking Phase 2.

**The Season-replay build grouping is COMPLETE (both sessions shipped).** Session A (the
`as_of_week` backend — parts 1–3) and Session B (the front-end week selector — part 4) are
both done (see the build log): the three derived analytics are tall snapshots over weeks
1–4, roster-as-of-N is fixed (backend + front-end), windowing is declared+tuned per analytic,
and a **global "As of" week dropdown** in the App shell threads the selected week through
`queries.js` (derived reads pick the matching slice; inline SQL reads filter `WHERE week ≤ N`),
drives the readiness gate, and retired the `?weeksOverride` param. Default = latest week
(today week 4); the selector travels back only.

**The Phase-2 substrate is DONE and Phase 3 (cash in the projection) is COMPLETE — all 4 cash-in
reads shipped** — per `READ_BUILD_ORDER.md`'s phase map (the authority the roadmap docs sync to).
Source #1 (Sleeper weekly projections) + the consensus/spread band with **its archetype-skew 3rd
component** (§3), **Production VOR** (§4, the first roster-management read), **True Rank** (§5 first
half, the first league-level read), **and now Positional Depth** (§6) have all landed (see "most
recent build"): the borrowed center + a **calibration-gated, fully-3-component band** is the forward
prior every read leans on; VOR proves the substrate cashes into a real add/drop surface (projected ROS
tracks actual at corr ~0.95); True Rank aggregates that VOR up into a record-independent roster-strength
rank (Pearson 0.802 / Spearman 0.842); Positional Depth re-slices it per position into surplus/gap
(per-position corr mean 0.861). **All four are answer-key gated, data + gate only (no UI yet).**
**Phase 4 is now UNDERWAY** — the **§5 bracket-math Monte Carlo** (`compute_bracket_sim.py`) ships the
posture integration point: team weekly score distributions (μ from the optimal-lineup projection, σ
from the §3 band) → analytic per-matchup win prob → a 10k-sim season over the real remaining schedule
→ **playoff odds** + projected wins/seed + magic number. With **True Rank** it **completes the §5
Posture read**. Gated config-light on actual 2025 results (Brier 0.224 beats coin-flip; expected-wins
Spearman 0.756; top-6 by odds = 6/6 actual playoff teams). **Source scouting settled the 2nd source**
— no clean historical-2025 projection source exists but Sleeper, so the **cross-source disagreement**
half (the Phase-2 substrate's other ingredient) comes **in-season via ffanalytics**; ESPN historical
is deferred (cookie-gated + `espn_id` join). **The §2 ROS outcome-shape skeleton is now DONE** (bull/bear/
situation, calibration-gated — see the most recent build), which **completes the player-read backend
(§1–§4).** **Next — remaining Phase 4:** **manager dossiers** (§7 — reshaped 2026-07-10 into a cross-league,
Claude-API-key-gated AI read; design recorded in `DECISION_READS.md` §7), and the deliberate **front-end
surfacing** of the now-six gated forward
reads (Spread/VOR/True Rank/Positional Depth/Bracket Odds/ROS Outcome Shape) — including the posture
*presentation* (True Rank + odds shown adjacent, the risk-appetite lens). **Blocked, not next:** cross-source
disagreement (Phase 2, needs the live 2nd source). Python/data-layer + front-end work.

## Version Roadmap
→ **Source of truth: `scope docs/PRODUCT_ROADMAP.md`** — phase detail, the four
design laws (grade process not outcome; speak only when confident; borrow the
substrate; consultation not autopilot), sequencing logic, and the scope filter.
Summary only here:

- **Phase 0 — Descriptive dashboard** *(done)* — team overview, league standings,
  power rankings. Frozen at Week 4 of 2025.
- **Phase 1 — Spike signal-quality slice** *(current; kickoff target)* — "is this
  production real or noise?" on usage data already fetched; validated against the
  full-2025 answer key before going live.
- **Phase 2 — Projections substrate** *(substrate done; disagreement blocked)* —
  the forward prior (the hinge everything credible depends on). **Source #1 = Sleeper**
  weekly projections + the consensus/spread band shipped; **cross-source disagreement**
  is blocked at the freeze and fills in-season via ffanalytics. Odds/Vegas optional add.
- **Phase 3 — Cash in the projection: the quantitative forward reads** *(COMPLETE —
  §3, §4, §5-half, §6 all done)* — the reads that consume the prior (per `READ_BUILD_ORDER.md`):
  Weekly Spread (§3 ✅), Production VOR (§4 ✅), True rank (half of §5 ✅), Positional Depth
  (§6 ✅). The leakage coachable-fix (backlog #1, regress-to-prior — law 1) lands in
  VOR; the shared-engines generalization is the cross-cutting *how*, not a separate gate.
- **Phase 4 — Integration + go live + opponent modeling** *(UNDERWAY — §5 bracket
  math + §2 ROS skeleton done)* — the §5 posture read (bracket-math Monte Carlo ✅ + True Rank = complete),
  §2 ROS outcome-shape skeleton (✅ bull/bear/situation, calibration-gated), manager dossiers (§7 — next);
  front-end surfacing of the gated forward reads; in-season weekly refresh; waiver and trade surfaces.
- **Phase 5 — Model of YOU** — graded decisions compound into a per-manager
  tendency profile that personalizes guidance.
- **Phase 6 — Forward advisory + AI layer (later)** — real-time "better call now";
  AI interpretation over the engines; draft & streaming surfaces.

> **Old V# → phase map** (so version references elsewhere in this doc still resolve):
> V1 dashboard → Phase 0; V1.5 scheduler + V2 waivers → Phase 4; V3 start/sit →
> Phase 3 (projections = Phase 2); V4 trades → Phase 4; V5 AI → Phase 6.

## Known Scope Exclusions
→ Source of truth: **TECHNICAL_ARCHITECTURE.md § Known Scope Exclusions** (DST/K, waiver
wire / full player pool, IR roster overages, zero-stat rows). One product note kept here:
**Market value (V1)** is snapshotted daily now to bank the time-series, but the features
that consume it (trade analysis, value-aware rankings) are V4; any UI showing it must
carry the "Powered by LeagueLogs API" attribution.

## Season-replay build grouping — COMPLETE (design record)

**One build grouping, two sessions, done before Phase 2.** Lets the user view the dashboard
*as of any past week N* — the tool exactly as it would have looked through week N, every
analytic recomputed on weeks ≤ N. A real product feature (the week selector), the in-season
"now advances each week" mechanism, and the QA instrument for every future engine. We are
**still frozen at week 4** — this did NOT expand the data; it lets us inspect weeks 1–3 states.

> **STATUS (2026-06-18):** ✅ **DONE — both sessions shipped & merged.** Session A (parts
> 1–3, the `as_of_week` backend + roster-as-of-N + windowing framework) and Session B (part
> 4, the front-end week selector) are complete and verified. The parts 1–4 text below is kept
> as the design record. **Next is Phase 2 (projections substrate)** — see "The step after".

> **Decided design (built reasons in chat 2026-06-18):**

**Part 1 — `as_of_week`, a temporal-snapshot dimension (backend).** Add `as_of_week`
as a first-class **column** on the three derived analytics (`player_signal`,
`team_form`, `team_leakage`). Grain becomes `(season, as_of_week, entity)` — one tall
table per analytic, NOT a file-per-week. This is the warehouse-correct modelling
(survives the eventual DuckDB→SQLite→server migrations) and matches the project's
existing append-snapshot pattern (leaguelogs by `snapshot_date`, the join by `week`) —
the column is *right*, not just convenient; file-per-week is the parquet-tied choice
that a SQLite layer would force you to undo. Each transform gains an as-of-week param:
filter the join to `week ≤ N` **before** computing, emit rows tagged `as_of_week = N`,
materialize all N=1..maxweek (cheap). data_layer read fns take an optional `as_of_week`
(default = latest). Current behavior = `WHERE as_of_week = max(as_of_week)` — nothing
existing breaks.

**Part 2 — windowing, per-analytic, decoupled from the cutoff.** `as_of_week` ⊥
window: the cutoff is *what data exists*; the window is *how data inside the cutoff is
weighted*. Each analytic declares its window by the **stationarity principle** (a
window is a bet about how fast the measured quantity actually drifts):
  - **Cumulative** (all weeks ≤ N, equal weight) → accounting/ledger metrics (leakage
    season points-left; record/all-play) and **structural baselines** (the league
    efficiency mean the spike signal regresses toward — ~stationary, wants max sample).
  - **Decayed (EWMA / half-life)** → state & trend reads: form (already EWMA, half-life
    2wk) and the spike signal's **player role/opportunity** component (role drifts).
  Where decayed, use a **half-life, not a hard rolling window** (smooth, no edge
  discontinuity, uses all data, graceful early-season). Half-life is a per-transform
  injected tuning constant (like `HALF_LIFE_WK`). The decayed windows are
  **backtest-tunable** — extend `backtest_player_signal.py` to sweep the opportunity
  half-life against the 2025 answer key and pick the best; don't guess. (At N ≤ ~2,
  cumulative and decayed converge anyway; the window mostly matters mid/late season.)

**Part 3 — roster-as-of-N (correctness fix; latent bug even today).** The transforms
currently resolve "current team" as `arg_max(roster_id, week)` = the *latest* week (4)
— that's "latest", not "as-of". Under `as_of_week`, roster membership must be "the
roster a player belonged to in their latest week **≤ N**." Thread the cutoff through
**roster resolution**, not just stat aggregation — it changes *who is even on the team*
at week N (trades/adds), not just their numbers. This is the cleanest proof `as_of_week`
is a true dimension; fix it as part of this work.

**Part 4 — the week selector (front-end product feature). ✅ BUILT (Session B).** A
selector that sets the active `as_of_week`, threaded through `queries.js` — derived reads
pick the matching `as_of_week` slice (`asOfSlice`), the still-in-JS SQL reads (power
rankings, construction, vitals, all-play) filter `WHERE week ≤ N` (`weekCutoff`, including
`SQL_CURRENT_TEAM` for front-end roster-as-of-N). Folded into the **readiness gate**
(`weeksElapsed = asOfWeek`) so past-week views render the real `building`/`tooEarly` states;
the temporary `?weeksOverride` QA param is **retired**. Default = latest week; travels back
only. **Resolved decisions:** placement = **global header** (App-shell dropdown, applies
across League + Team, editable from every tab); control = **dropdown** (weeks 1..latest).

**Suggested sequencing (respect the 3-commit cap):**
- ✅ **Session A — backend (DONE 2026-06-18):** parts 1–3 shipped. `as_of_week` in the
  three transforms + roster-as-of-N + windowing framework + data_layer; materialized all
  weeks; extended the backtest with `--sweep` to tune the opportunity half-life (→
  cumulative, tested). Verified per-week parquet contents (week-N slice carries only weeks
  ≤ N; N≤2 all `too_early`; roster = as-of-N for the 7 traded players). For Session B: the
  parquets are now **tall**, and `queries.js` already has a default-latest guard
  (`WHERE as_of_week = (SELECT max …)`) on the three derived reads — the selector
  parameterises that inner `max(as_of_week)`.
- ✅ **Session B — front-end (DONE 2026-06-18):** part 4. Global "As of" dropdown in `App.jsx`
  + threaded the week through `queries.js` (`asOfSlice`/`weekCutoff` + `loadWeeks()`) + panels;
  folded into the readiness gate (`weeksElapsed = asOfWeek`); retired `?weeksOverride`. Verified
  live across weeks 1–4 (week-2 trend panels "too early"; rankings reshuffle to the cutoff;
  roster-as-of-N departed flags; week persists across tabs; no console errors). **Preview
  gotcha (confirmed):** point the worktree's `.claude/launch.json` at a free port (`--port 5273`)
  — a stray 5173 server serves *main's* frontend, not this source.

**Non-goals:** not expanding past week 4; not Phase 2. This is the replay/inspection
layer that precedes Phase 2.

## Refinement backlog — Team Overview (deferred, not blocking)

These refine shipped lenses; pick up alongside or after the Players sub-view.

> ✅ **Done (2026-06-07):** Lens-4 reframe (retrospective → improvement) and the Form
> lens EWMA switch both shipped. ✅ **Done (2026-06-17):** item 2 (per-panel readiness
> gate) shipped as `readiness.jsx` — see the maintenance log. **One backlog item remains:**

1. **Reframe the Lens-4 "coachable" fix from confident imperative → advisory question
   (and own its predictive weakness).** The shipped coachable fix says *"start X over Y
   going forward — +N/g on the season,"* which silently converts a tiny realized sample
   into a forward claim it can't support. **Worked example that exposes it:** at the wk-4
   freeze, Cousin 'Chilling's roster fired *"start Keenan Allen (16.3/g) over A.J. Brown
   (8.8/g) at WR going forward."* Pulling the *actual* rest-of-season from
   `nfl_stats_2025.parquet`: **Brown W5+ = 16.8/g, Allen W5+ = 9.0/g** — a near-total
   reversal; Brown won 7 of the next 10 head-to-heads by +67.7 pts. The call would have
   been backwards. Mechanism: 4 games, equal-weighted, **no talent prior** — Brown's two
   near-zero early games were noise a prior would discount; stars are the *worst* case for
   realized-rate reads. The leakage total is descriptively true (you did leave those
   points in wks 1–3); only the **forward language** overreaches. Directions:
   - **Language (near-term, cheap):** drop the imperative + "+N/g going forward." Pose it
     as a **question the manager adjudicates**, per the project mission (consultation, not
     autopilot): *"Is it time to pivot off Brown? He's scored 8.8/g to Allen's 16.3 over
     4 weeks — past fluke territory; decide if you still believe in him."* Surfaces the
     decision point; defers the call to the user.
   - **Trade-timing angle (V4):** a sustained underperformance isn't only a start/sit
     question — even if you *don't* believe the player rebounds, selling while perceived
     value is high (≈$0.85 on the dollar) beats holding until the market reprices
     (≈$0.35). Ties to the **LeagueLogs market-value** layer (V4). The signal's real job
     is to flag "make a call here," not to make it.
   - **Real fix (V3):** regress realized rate toward a forward prior (FantasyPros
     projections / ADP) before calling anything coachable; gate the language on sample
     size (see item 2). Until then, keep coachable **retrospective**, not predictive.

2. ✅ **DONE (2026-06-17) — Per-panel readiness gate.** Shipped as `readiness.jsx`:
   `assessReadiness(regime, weeks)` + a `Gate` wrapper. Regimes — **structural** (ready at
   roster lock), **point-in-time** (ready week 1, confidence grows), **trend** (ready
   ~week 3–4) — map to ready / building / tooEarly; a **"too early" fallback slot** accepts
   custom children (the preseason-content hook, no rework) and a *building* note calibrates
   language on thin samples. Wired into the Team tab (construction = structural, Form +
   leakage = trend, Players = point-in-time). Frozen at week 4 → all ready; `?weeksOverride=N`
   drives the clock for QA. The deeper "calibrate to a forward prior" half is **Phase 2**
   (projections) — the gate is the seam; the prior that sharpens it comes next.

## Phase 2 — the projections substrate (substrate DONE; disagreement blocked) → Phase 3 COMPLETE

> **Phase labels follow `READ_BUILD_ORDER.md`** (the authority STATUS + PRODUCT_ROADMAP sync
> to): the **substrate** (consensus + spread band) is Phase 2; the reads that **consume** it —
> Weekly Spread §3, VOR §4, True rank half-§5, Positional Depth §6 (**all done**) — are
> Phase 3 "cash in the projection." This section covers the substrate + its progress; the
> Progress list below spans both.

The hinge — **the forward prior** every later decision slice rests on. Delivered as a
**multi-source `projections` entity** (all I/O through `data_layer.py`; keyed on
`sleeperPlayerId`; `source` a column so providers combine/select without a schema change),
plus a transform producing a **consensus + disagreement (spread)** read. Two payoffs: (a) the
spread is the law-2 confidence signal — tight consensus = act, wide = coin-flip; (b) it gives
the spike read a *forward* prior to regress toward, fixing the one honest blind spot the
backtest surfaced (Kamara: usage looked fine, the player declined — usage alone can't see
talent/situation change). It also lets the readiness gate *calibrate* early-season language
rather than merely gate it. Do **not** use prior-season carryover as the prior (biased by
age/injury/scheme).

**Progress:**
- ✅ **Source #1 — Sleeper weekly projections (DONE).** `sleeper.py projections <season> [week]`
  → `write_projections(source="sleeper")`. Historical (works with the frozen-2025 world),
  native `sleeperPlayerId`. See the build log.
- ✅ **Consensus + spread band, all 3 components (DONE).** `compute_projection_consensus.py` →
  `derived/projection_consensus_{season}.parquet`: borrowed consensus **center** + a percentile band
  whose **width** is the player's residual std shrunk to a positional prior + **archetype skew**
  (§3 c3) via a Cornish-Fisher shift from the player's residual *skewness* shrunk to a positional
  prior. Calibration-gated (`backtest_projection_consensus.py`, exit 0) — extended to **per-tail**
  (below-p25/above-p75 ≈ 0.25 each), joint `BAND_Z × SKEW_GAIN` sweep → (0.55, 1.5): coverage 0.493,
  tails 0.247/0.261. Skew driver resolved by the answer key (residual 3rd moment, not the
  TD-dependence archetype §3 names — see "most recent build"). The **cross-source disagreement**
  ingredient stays null under one source, additive when a 2nd lands.
- ✅ **Production VOR (§4) — first substrate-consuming read (DONE).** `compute_production_vor.py` →
  `derived/production_vor_{season}.parquet`: ROS value (borrowed centers summed over remaining weeks)
  over the waiver line, normalized by pool spread; QB pool + pooled flex line from `lineup_slots`;
  tall over as_of_week. Gate (`backtest_production_vor.py`, exit 0): projected ROS tracks actual at
  corr 0.944 QB / 0.955 FLEX, VOR tiers monotonic in realized production. Market VOR + trade gap V4.
- ✅ **True Rank (§5, first half) — first league-level substrate-consuming read (DONE).**
  `compute_true_rank.py` → `derived/true_rank_{season}.parquet`: per team, optimal-lineup ros_value
  sum → record-independent roster-strength rank + spectrum_pos + bench_value; re-aggregates
  Production VOR over the lineup rules (optimal-lineup greedy lifted into `_analytics` as shared
  `expand_slots`/`optimal_lineup`); tall over as_of_week. Gate (`backtest_true_rank.py`, exit 0):
  projected strength tracks the actual ROS ceiling at Pearson 0.802 / Spearman 0.842 (freeze wk4,
  n=10, floor 0.60); strong half +261.7 ROS over weak. Slot-aware (a 2-QB roster ranks by its one
  startable QB). No UI (data+gate). Bracket-math Monte Carlo (§5 full) is Phase 4.
- ✅ **Positional Depth (§6) — the last Phase-3 cash-in read (DONE).** `compute_positional_depth.py` →
  `derived/positional_depth_{season}.parquet`: per (as_of_week, roster_id, fine position QB/RB/WR/TE),
  re-slices VOR net of the position's dedicated `starter_need` (from `lineup_slots`; shared FLEX
  excluded → depth = surplus); carries starter_value, surplus_value/surplus_startable, marginal_vor
  (gap indicator), spectrum_pos per position cohort, advisory surplus/adequate/gap shape; one row per
  (team, position) even at zero count. New `data_layer.write/read_positional_depth`. Lossless re-slice.
  Gate (`backtest_positional_depth.py`, exit 0): per position, projected starter_value tracks the
  actual ROS ceiling at QB 0.792 / RB 0.867 / WR 0.855 / TE 0.928, mean 0.861 (floor 0.50); top half
  +85.3 over bottom. **Closes Phase 3 (4/4).**
- **2nd source — scouted, resolved:** no clean historical-2025 weekly projection source but Sleeper
  (ffanalytics = live-scrape + R; fantasyfootballdatapros = 2019/20 ESPN snapshot + actuals; ESPN =
  cookie-gated + `espn_id` join). Plan: **ffanalytics for the in-season live cross-source
  disagreement** (2026); ESPN historical only if we later want to backtest disagreement against 2025.
- ✅ **§5 bracket-math Monte Carlo (DONE — Phase 4 begun).** `compute_bracket_sim.py` → playoff odds
  from the forward reads; with True Rank = §5 Posture complete. Gated config-light (Brier 0.224 beats
  coin-flip; expected-wins Spearman 0.756; 6/6 actual playoff teams). See "most recent build".
- ✅ **§2 ROS Outcome Shape skeleton (DONE — Phase 4).** `compute_ros_outcome_shape.py` → bull/bear (borrowed
  ROS centre ± BULL_Z·√Σband², floored, emergent time decay) + situation/security (player_signal trust axis).
  Calibration-gated (coverage 0.835; BULL_Z swept to 1.645; monotonic by bull tercile). **Completes the
  player-read backend (§1–§4).** See "most recent build".
- **Next — remaining Phase 4:** **manager dossiers** (§7 — reshaped into a cross-league, Claude-API-key-gated
  AI read; design recorded in `DECISION_READS.md` §7) and the **front-end surfacing** of the six gated
  forward reads (incl. posture presentation).
  **Blocked, not next:** cross-source **disagreement** (in-season, needs the live 2nd source).
- **Optional cheap add:** Vegas game totals via an `odds.py` fetcher (game environment).

(Older note, lower priority: continue the V1 Dashboard Build Order — standings with
trajectory; manager dossiers; positional strength vs. league average; head-to-head
matchup breakdown — now reframed under the phase roadmap below.)

## V1 Dashboard Build Order

Dashboard build structure:
Build first
    - Power rankings league overview
        What it shows: Composite team strength score with positional breakdown (QB/RB/WR/TE) as a detail layer.
        Data needed: nflreadpy weekly stats + Sleeper roster data + weekly data from the season join (nfl_sleeper_weekly_joined transform → season_{season}.parquet).
    - Points scored + consistency league overview
        What it shows: Average weekly points per team and a consistency signal — stable vs. high-variance output.
        Data needed: Sleeper matchup snapshots only. No join required.

Build second
    - Standings with trajectory lens league overview
        What it shows: Record + points for/against, past strength of schedule, remaining schedule difficulty, historical league baseline for wins needed to reach playoffs.
        Data needed: Sleeper matchup history + Sleeper league schedule + prior season backfill data.
    - Manager dossiers league overview
        What it shows: Static AI-generated profile per manager — waiver tendencies, trade behavior, roster construction patterns, positional preferences.
        Data needed: Sleeper transaction + waiver history. One-time AI synthesis pass per manager, output stored as static JSON or markdown.
    - Positional strength vs. league average team overview
        What it shows: Your team's output by position compared to league average. Identifies tradeable surplus and gaps to address.
        Data needed: weekly data from the season join (nfl_sleeper_weekly_joined transform → season_{season}.parquet).
    - Head-to-head position breakdown matchup overview
        What it shows: Your lineup vs. opponent's lineup by position — where's the edge, where's the risk.
        Data needed: Sleeper current roster + weekly data from the season join (season_{season}.parquet).

Build third
    - Production consistency per player team overview
        What it shows: Week-to-week variance per player. Who's reliable, who's boom/bust.
        Data needed: nflreadpy weekly stats.
    - Key player matchups + narrative read matchup overview
        What it shows: The 1-3 decisive spots in the matchup — who could swing the week, whether you're ahead or at risk.
        Data needed: Sleeper live scoring + nflreadpy historical context. Natural candidate for AI layer in V5.
