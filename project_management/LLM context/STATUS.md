# STATUS

**Last updated:** 2026-07-11 (**§2 Player-News Collector shipped — the aggregation half of the ROS
Outcome Shape AI-interpretation layer (Phase 6).** The §2 AI layer's one missing input — no news feed
was fetched anywhere — now exists. `fetchers/news.py` is a live, scheduled RSS collector that banks
current NFL player news as a de-duplicated, player-resolved, source-attributed time-series (the new
`player_news` entity) for the future on-demand AI synthesis to read. Mirrors the leaguelogs collector
(incremental per-feed writes, dedup guard in the writer, launchd plist). Nationals-only source list
(team beats deferred; every item stores `source_type` so the national/beat blend is preserved when
beats land); resolves against the **967 active-rostered skill players** (team-not-null → **0 name
collisions** → exact-full-name matching, with defensive team-mention disambiguation for the rare
collision the mutating registry will eventually surface); **compact items only** — headline / summary /
url + `collected_at`, never article bodies (url + date are the Wayback recall path; sidesteps
copyright/ToS). **Live-acquired like `manager_activity`** — the FORWARD pipeline, deliberately NOT tied
to the frozen-2025 league. Verified live: 5/5 national feeds, 151 entries → 48 items → 66 (item×player)
rows, idempotent (66 after two runs), dead-feed isolation, synthetic resolver `check` PASS, zero
false positives on eyeball. **Design record (sparred with the PM):** aggregation is separated from
interpretation; the synthesis step — **next session** — is a single **lazy, cached, per-player** Claude
call returning consolidated headlines **and** the ROS bull/bear blurb **and** confidence in one pass
(the headlines are the receipts for the blurb — one pass = guaranteed consistent). Prior build: **710
audit CLOSED (7/7)** — §1 Quality axis on the empirical expected-points model + §2 ROS preseason ADP
anchor + the `application/` package refactor + hygiene; all backtest gates green.)
**Post-merge operator action (one thing): install the new `com.fantasyai.news-snapshot` launchd plist**
into `~/Library/LaunchAgents/` + `launchctl bootstrap` (runs 5am ET daily) — see `scheduler/README.md`.
(`feedparser` is already installed in the framework Python on this machine, and the leaguelogs plist is
already on the `-m` invocation and running cleanly — verified — so no leaguelogs action is needed; the
710-era "reinstall leaguelogs" note was already actioned.)
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
**§2 Player-News Collector — the aggregation half of the ROS Outcome Shape AI-interpretation layer (Phase 6).**
The §2 AI layer (`DECISION_READS.md §2`) needs a news feed and none was fetched anywhere — the "primary
blocker." This ships the **collector** (aggregation), separated from the AI **interpretation** (a later
session), mirroring §7's `manager_activity → features → dossiers` tiering. **Three commits.** (1)
**Entity + pipeline:** new `data_layer` `player_news` (one growing file `snapshots/news/player_news.parquet`;
grain = one row per news-item × resolved player; writer is **append-only-of-new by `item_id`** so
re-polling is idempotent) + `feedparser` dep + `fetchers/news.py` — a national RSS feed registry,
`_get_feed` (timeout + backoff retry), player **resolution** (exact full-name match against the **967
active-rostered skill players**, `team`-not-null → **0 collisions**), **incremental per-feed snapshot**
with **per-feed isolation** (one dead feed never kills the run), entry points `snapshot`/`feeds`/
`resolve-test`. Only **compact items** stored (headline/summary/url + `collected_at` — never article
bodies; url+date = Wayback recall path; sidesteps copyright/ToS). (2) **Resolution hardening + feed
validation:** defensive same-name **team-disambiguation** (`match_confidence` exact_full / disambiguated;
ambiguous → skipped, never guessed — law 2), richer `resolve-test` report, a credit-free synthetic
`check` subcommand; all 5 national feeds validated live (no pruning). (3) **Scheduling + docs:** a
`com.fantasyai.news-snapshot` launchd plist (5am ET daily) + README. **Live-acquired like
`manager_activity`** — the FORWARD pipeline, deliberately NOT tied to the frozen-2025 league (a live
news feed can't map to a 2025 roster; fusing news into the frozen bull/bear grade is dishonest and
deferred). Verified live: 5/5 feeds, 151 entries → 48 items → **66 (item×player) rows**, idempotent (66
after two runs), dead-feed isolation, `check` PASS, **zero false positives** on eyeball (incl. "Amon-Ra
St. Brown", "D.J.→DJ Moore", multi-player fan-out, rookie "Sam Roush" across 3 feeds). No AI/credits/UI.
**Next — the §2 synthesis session:** a single **lazy, cached, per-player** Claude call over recent
`player_news` + Sleeper factual fields + the `ros_outcome_shape` anchors → consolidated headlines + the
bull/bear blurb + confidence in **one pass**. **Also still remaining Phase 4:** front-end surfacing of
the six §1–§6 forward reads + dossiers.

> earlier build
**710 audit #3 — §1 Quality axis on the empirical expected-points model (+ core-upgrade tested & rejected).**
The audit's last spec item, closing the whole 710 backlog. `quality_rate` was `xtd_g/opp_g` — a
hand-rolled sum of nflfastR `td_prob`, TD-only and ungated. Now it's **expected fantasy points per
opportunity** from ffverse's `ff_opportunity` model. **Four commits.** (1) **Data + scoring:**
`fetchers/nfl_stats.py` gains `_load_ff_opportunity` (the `*_exp` component expectations, gsis-keyed,
joined like the PBP signal; null-id "dupes" filtered), the old `xtd` TD-proxy retired (`redzone_touches`
kept as companion). New `_scoring.expected_points_expr` re-scores the components **from-scratch** under
the league's settings — exact here (every component exposed), reproducing ffverse's
`total_fantasy_points_exp` under PPR to ±0.02, and it even scores first-down leagues. Also fixed a latent
bare `import audit_join` the package refactor (#1) missed. (2) **Quality axis:** `compute_player_signal`
sets `quality_rate = exp_pts_g/opp_g` (value per chance, kept separate from Volume), `point_correlation`
now correlates weekly **actual vs expected** full points, and a new `luck` = recent − expected ppg. (3)
**Gate:** `backtest_player_signal` adds a third verdict — `quality_rate` (exp_ppo) forecasts ROS realized
efficiency at **MAE 0.311 vs 0.506** recent-realized; exit 0 (predictive 13.2% MAE cut, spike<sticky,
quality). The **optional core-engine upgrade** (shrink the spike forecast toward exp_ppo instead of the
positional mean) was implemented and **rejected by the answer key** — lost at every SHRINK_K (K=6: 2.699
vs 2.599). Points-forecasting is regression toward the *population*; exp_ppo (same recent weeks) is too
correlated with realized ppo to pull that way. **Not a contradiction:** exp_ppo beats *recent-realized*
as an efficiency forecaster but loses to the *population mean* as a shrink target — so the core keeps its
validated positional-mean prior; the model serves the §1 Quality axis, not the forecast. (4) docs
closedown. **The 710 audit is now fully closed (7/7).** No UI (data + gate). **Next — remaining Phase 4:**
front-end surfacing of the six §1–§6 reads + dossiers.

> earlier build
**710 audit #4 — §2 ROS bull/bear preseason anchor (ADP, historical curve).**
Closed the last spec-completeness gap: the shipped band was purely `centre ± z·σ` off the in-season
projection, with no preseason limits. The audit filed #4 as "blocked on data — no ADP source fetched";
that was **wrong** — `nflreadpy.load_ff_rankings` (already a dependency) carries historical FantasyPros
consensus rankings the whole time. **Five commits.** (1) **`fetchers/adp.py`** pulls the latest
full-skill-board pre-kickoff redraft-overall snapshot per season (ecr/best/worst/sd + positional rank),
id-bridged FantasyPros→sleeper via `ff_playerids.fantasypros_id` (the cbs/yahoo columns are all-null);
new `adp_preseason` entity, backfilled 2020–2025 (top-150 matched 150/150 every year). (2)
**`compute_adp_points_curve.py`** fits the empirical anchor — per position, `pos_ecr_rank →
realized-points floor/center/ceiling` (P10/P50/P90 over a rolling ±3-rank window, isotonic-smoothed
non-increasing), a drafted-but-never-produced player realizing 0.0 (the floor's bust signal); trained
2020–2024, 2025 held out = leak-free; historical realized points via the existing `nfl_stats` backfill
(the sanctioned data-layer path — no transform hits nflreadpy). New `_analytics.quantile` +
`adp_points_curve` entity. (3) **anchor blend** in `compute_ros_outcome_shape`: each drafted player's
curve floor/ceiling, scaled to the remaining schedule, blended into bull/bear with weight
`w_N = ANCHOR_W·(remaining/total)` (prior-driven early → evidence-driven late — §2's dynamic, explicit);
`ros_center` stays the borrowed projection (law 3); undrafted/uncovered degrade to the pure-projection
band; additive evidence columns (adp_ecr/best/worst, anchor_floor/ceiling, anchor_applied). (4) **joint
`BULL_Z×ANCHOR_W` re-sweep** (gate imports the shipped `_preseason_anchor`/`_blended_band`; objective =
|cov−target| + |tail imbalance| so the pick is calibrated AND centred) → **(1.44, 0.25)**: the anchor
lifts freeze coverage 0.744→0.817 and rebalances the projection's lopsided miss tails 0.195/0.061 →
0.091/0.091; gate exit 0, ros_bull terciles monotonic (58 < 127 < 205). (5) **docs closedown.** Honest
limitation: the roster freeze bounds tested cutoffs to N=1..4 (early / prior-heavy), so the decay's
late/evidence-heavy tail is by construction, not exercised. Byte-compiles clean; no-regression
(ros_outcome_shape is a leaf; schema additive). #3 (§1 quality) re-scoped smaller — `load_ff_opportunity`
ships the empirical model, so it's consume-and-re-score. **Next — remaining Phase 4:** front-end
surfacing of the six §1–§6 reads + dossiers (unchanged by this build).

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
    - Phase 4 Bracket Odds (§5 bracket-math) — compute_bracket_sim.py → derived/bracket_odds_{season}.parquet, the bracket-math half of Posture (with True Rank = §5 complete). Per team weekly score dist (μ = optimal-lineup Σ center_ppr, σ = √Σ band_ppr²; starters independent), analytic per-matchup win prob Φ((μA−μB)/√(σA²+σB²)) via math.erf; standings as-of-N from actual results; Monte Carlo (numpy, fixed seed, 10k) over the real remaining schedule → playoff_odds, proj_wins/points, avg_seed, magic_wins. Enabled by raw Sleeper matchups existing for all 18 wks. Playoff config (REG_SEASON_END_WEEK=15, PLAYOFF_TEAMS=6) inferred from schedule — documented latent. New data_layer write/read_bracket_odds + read_season_matchups. Verified wk4: Σ playoff_odds=6.00 (hard invariant); deterministic. Gate (backtest_bracket_sim.py, exit 0, config-light): Brier 0.224 beats coin-flip; expected wins vs actual Spearman 0.756; top-6 by odds = 6/6 actual playoff teams (at the originally-inferred 6-team cut). numpy is the one compute dep. Simplifications: starter independence, Normal draw (no §3 skew), frozen-roster byes reduce μ. **[Superseded: the playoff config REG_SEASON_END_WEEK/PLAYOFF_TEAMS is now read from real league settings — 4 teams, not the wrong inferred 6; at the corrected 4-team cut the gate reports Σ playoff_odds=4.00 and top-4 by odds = 3/4 — see the league-settings build.]**
    - League settings (scoring + playoff) persisted + consumed — sleeper.py fetch-league-config pulls scoring_settings + playoff config from the /league object → data_layer write/read_league_settings (tall section/key/value) + read_scoring_settings/read_playoff_settings. transforms/_scoring.py dispatcher: scoring_profile ppr/half/std/custom; standard selects the canned projection column + nfl_stats actual expr; custom → recompute_custom_points() stub (raises; engine is the next project). Wired into compute_projection_consensus (scoring, byte-identical for this ppr league) + compute_bracket_sim/backtest (playoff via _playoff_config, injected, no hardcoded fallback). Real league: playoff_teams=4, playoff_week_start=16, profile=ppr. Corrects the sim's playoff cut 6→4 (Σ playoff_odds=4.00); all gates green. Standard PPR/half/std leagues now supported; foundation for the "any league" project.
    - Custom-scoring recompute engine ("any league" piece 1) — fills `_scoring.recompute_custom_points()` (was a stub that raised) with a **delta-on-canned-baseline** engine: `points_league = std_baseline (proj_pts_std/fantasy_points) + Σ(w_custom−w_std)·component`, exact for standard by construction. Same weights on `proj_*` + `nfl_stats` so residuals stay matched. Supports non-{0,.5,1} PPR, 6-pt pass TD, non-standard yardage/TD, position-conditional reception bonuses (TE premium `bonus_rec_te`/`_rb`/`_wr`/`_qb`); rejects (raises, names key) first-down / threshold-yardage bonuses (no projection component); turnovers/2pt carried in baseline (tolerance). `recompute_custom_points(scoring, side)` → `pl.Expr`; `projection_column`→`projection_points_expr`; `actual_points_expr` gains scoring; `compute_projection_consensus.compute(season, scoring=None)` injectable. New `backtest_scoring_recompute.py` (exit 0): equivalence (custom==canned on standard: actuals exact, proj ~0.01 rounding), exact custom deltas, rejection, end-to-end custom consensus (100% QB centers rise under 6-pt pass TD). No-regression: real-ppr recompute == on-disk consensus parquet frame-for-frame (downstream gates unaffected); VOR runs on a custom consensus. Custom leagues now run the whole read spine.
    - Any-league pieces 2 & 3 (project complete) — **roster-shape/superflex:** new shared `_analytics.position_pools(slot_rows)` derives swap/replacement pools from `lineup_slots` (positions sharing a multi-position slot pooled; key = broadest inducing slot). `compute_production_vor._pool_of` + `compute_team_leakage._cls` now use it (fixes the `SUPER_FLEX` latent + generalizes leakage swap classes); standard config byte-identical, superflex pools QB with flex. `backtest_roster_shape.py` (exit 0): no-regression frame-equal on vor/leakage/true_rank/positional_depth + synthetic superflex. **Division seeding (synthetic-gated latent):** `_seed_table` extracted from `compute_bracket_sim._simulate`, division-aware when a roster→division map is present (winners seeded ahead of wildcards) else flat (proven identical); `sleeper.py fetch-league-config` persists `settings.divisions`; `_division_map` None today (teams entity has no `division` col — rosters-endpoint population deferred). NOT validated on a real division league. **Also fixed:** the fixed-SEED bracket sim wasn't reproducible (polars group_by order + zero-score bye ties) — sorting schedule pairings + roster player lists restores determinism (shared `optimal_lineup` untouched). `backtest_bracket_sim.py` extended (exit 0): Brier 0.224/Spearman 0.756 unchanged + determinism + Σ-invariant + synthetic 2-division correctness.
    - ROS Outcome Shape (§2 quantitative skeleton — completes the player-read backend §1–§4) — compute_ros_outcome_shape.py → derived/ros_outcome_shape_{season}.parquet, tall over (as_of_week, roster_id, player). Bull/bear = the borrowed ROS centre (Production VOR ros_value, reused directly) ± BULL_Z·ros_sigma, floored at 0, where ros_sigma = √(Σ band_ppr² over the remaining schedule) — the §3 weekly band summed under weekly independence (compute_bracket_sim's documented assumption). New pure `_ros_sigma` (mirrors `_ros_values`, aggregates band²) + `_outcome_band`; ros_cv = sigma/centre (fragility), per-position spectrum_pos on the bull ceiling. Time decay emergent (shrinking horizon → tighter band; 0/142 σ grew wk1→wk4). Situation/security borrows the player_signal trust axis (security tier + direction/reliability) as structured evidence — the AI narrative + 1-10 roll-up is Phase 6. New data_layer write/read_ros_outcome_shape (mirrors the Production VOR tall block). Gate (backtest_ros_outcome_shape.py, exit 0): calibration — freeze-wk actual ROS in [bear, bull] = 0.835 (target 0.80±0.05), BULL_Z swept to 1.645 (above the normal 1.28 because weekly residuals are positively autocorrelated → realised ROS more dispersed than the independent sum); decision-relevant — actual ROS monotonic by ros_bull tercile (dead 58 < mid 126 < stud 206); bonus — non-stable players broke their bear floor 15.9% vs stable 9.8%. Symmetric-by-design (ROS-level skew deferred). No-regression (reads-only of the three source parquets). No UI (data + gate).
    - Manager Dossiers Phase A (§7 — cross-league acquisition + deterministic behavioral features; the credit-free substrate the Phase-B AI writer consumes) — 3 commits. (1) sleeper.py: fetch_teams persists owner_id (the user_id identity key it dropped; teams_2025 regenerated, additive); new _get_json (timeout + backoff-retry on transient/5xx, 4xx raise, optional throttle), all bare requests.get routed through it. (2) transforms/_manager.py (pure comparability + attribution helpers, reuses _scoring.scoring_profile; shared by fetch mode + transform + gate) + sleeper.py fetch-manager-activity <season> [--me] [--limit N] [--throttle S]: per manager, fan out to their comparable other leagues (same scoring/size/QB-structure/format — redraft-only V1, format tagged), ≤5 across current+2-prior biased to prior; classifies off the /user/.../leagues payload (carries scoring_settings+roster_positions+settings, verified) so no per-candidate fetch; persists incrementally per manager (replace-by-owner_id, recoverable/idempotent). New manager_activity_{season} — the FIRST cross-league/user-keyed entity (owner_id key; source_league_id/source_season as columns; league-marker + txn row kinds). (3) compute_manager_features.py → manager_features_{season} (per manager: FAAB aggression/budget-spent [completed waivers only], waiver/FA mix, success rate, churn, trade freq, positional lean of adds, signal-depth counts + depth_tier + is_primary); pure manager_features (injected constants); rate/lean features null when undefined (law 2, never fabricated 0). Gate (backtest_manager_features.py, exit 0 — internal consistency, behaviour has no answer key): comparability invariant (0 leaked, grounded on persisted target facts) + accounting round-trip (independent re-aggregation; fractions ∈[0,1]; shares sum 1) + signal-depth honesty (all profiled; zero-signal → null). Verified live 2025: 10 managers, 431 activity rows, real differentiation; depth honestly thin (recurring-league friend group). No AI/credits/UI. Phase B (Haiku dossier writer) next.
    - Manager Dossiers Phase B (§7 — the API-key-gated Haiku dossier writer; §7 COMPLETE) — the project's FIRST AI-layer code. New application/ai/ module (distinct from the polars transforms; parquet I/O still via data_layer, the Anthropic call is external like a fetcher's HTTP). (1) ai/client.py — the isolation seam: api_available() gates on a real config.ANTHROPIC_API_KEY (absent/placeholder/non-sk-ant → locked, no anthropic import to check); generate_dossier() is the ONE place that knows how a request reaches the model (synchronous messages.create, Haiku 4.5, no thinking/effort, tolerant json.loads NOT messages.parse — SDK-version-safe; returns (dossier, usage)) — a Batch path swaps here only. ai/dossier_prompt.py — pure: stable system prefix (fixed 7-key JSON schema + tendencies-not-verdicts guardrails) + per-manager user prompt (blindspot framing for is_primary / exploitable-edge for opponents) + hardcoded zero-signal "no intel" dossier. (2) ai/write_manager_dossiers.py (compute/run/--season/--force) → manager_dossiers_{season} (first AI-written entity; one row per owner_id: structured fields + is_primary + signal-depth echo + model/generated_at/is_zero_signal): per manager, zero comparable leagues ⇒ hardcoded (no API); else prompt→generate→validate schema; synchronous sequential (caching off — ~347-token prefix below Haiku's 4096 min); run-once-per-season guard; key-gate clean exit. New data_layer write/read_manager_dossiers. (3) ai/check_manager_dossiers.py — internal-consistency gate (no API, reads persisted only): coverage + schema completeness + depth-echo-matches-features + zero-signal honesty (exit 0). Design decision: synchronous not Batch (≤16 managers once/season → 50% batch discount is noise; concurrent batch can't share a prompt cache; seam lets Batch swap in later). Verified live 2025: 10 dossiers, 10 Haiku calls, ~$0.025, gate exit 0; primary=blindspot, opponents=exploitable-edge, 10/10 confidence notes cite the real txn count. Guards unit-tested credit-free (zero-signal skips API; locked-key refuses even with --force). No UI.
    - 710 backend-audit fixes (structural #1 + hygiene #5/#6/#7) — `application/` made a proper Python package: `__init__.py` in the 6 dirs + root `pyproject.toml`; every bare sys.path-dependent import rewritten to absolute package form and all 56 `sys.path.insert` lines across 31 files deleted (zero remain); scripts run as `python -m application.<pkg>.<module>` from the repo root (`-m` puts cwd on the path — no editable install); lazy `_import_manager_helpers` → top-level package import; ~30 usage strings + the two doc call-sites + the launchd plist (`-m` module, WorkingDirectory=repo root) + README updated. Hygiene: config.example gains SLEEPER_LEAGUE_ID + drops dead LEAGUE_TYPES/EXCLUDED_LEAGUES; requirements sheds unused pandas/nfl_data_py; bracket figure reconciled to top-4=3/4. Behavior-preserving (all backtest gates pass via -m, identical numbers; byte-compiles clean). Deferred: #2 scaling (no-op migration trigger), #3 §1 quality axis (net-new empirical-weighting transform), #4 §2 preseason anchor (blocked — no ADP source fetched). Post-merge: reinstall the launchd plist.
    - 710 audit #4 (§2 ROS preseason anchor) — overturns session-1's "#4 blocked on data": the ADP source was `nflreadpy.load_ff_rankings` (already a dependency). `fetchers/adp.py` fetches the historical FantasyPros preseason redraft-overall board (latest full-skill-board pre-kickoff snapshot/season; ecr/best/worst/sd + positional rank; id-bridged `fantasypros_id`→sleeper via ff_playerids, cbs/yahoo all-null; `adp_preseason` entity, 2020–2025, top-150 150/150). `compute_adp_points_curve.py` fits per-position `pos_ecr_rank → realized-points` floor/center/ceiling (P10/P50/P90 over a rolling ±3-rank window, isotonic non-increasing; drafted-never-produced = 0.0 floor signal; trained 2020–24, 2025 held out = leak-free; `adp_points_curve` entity; +`_analytics.quantile`). Historical realized points via existing `nfl_stats` backfill 2020–24 (sanctioned data-layer path — no transform hits nflreadpy). Anchor blended into `compute_ros_outcome_shape` bull/bear via horizon-decaying `w_N = ANCHOR_W·(remaining/total)`; `ros_center` stays borrowed (law 3); undrafted/uncovered degrade to the pure-projection band; +adp/anchor evidence cols. Joint `BULL_Z×ANCHOR_W` re-sweep (gate imports shipped `_preseason_anchor`/`_blended_band`; objective |cov−tgt|+|tail imbalance|) → (1.44, 0.25): freeze coverage 0.744→0.817, tails 0.195/0.061→0.091/0.091, gate exit 0, ros_bull terciles 58<127<205. Limitation: freeze bounds tested cutoffs to N=1..4 (early/prior-heavy) — decay's late tail by construction. Also re-scoped #3 (§1 quality) smaller: `load_ff_opportunity` ships the empirical expected-points model → consume-and-re-score, not fit-your-own-weights.
    - 710 audit #3 (§1 Quality axis) — CLOSES the 710 audit (7/7). `quality_rate` was `xtd_g/opp_g` (nflfastR `td_prob`, TD-only, ungated); now = **expected fantasy points per opportunity** from ffverse's `ff_opportunity` component model. `nfl_stats._load_ff_opportunity` joins the `*_exp` components (gsis-keyed, null-id rows filtered; REG weeks); `xtd` retired, `redzone_touches` kept as companion; latent bare `import audit_join` (package-refactor #1 miss) fixed. New `_scoring.expected_points_expr` re-scores the components from-scratch under league settings — exact (all components exposed), reproduces ffverse's `total_fantasy_points_exp` under PPR to ±0.02, scores first-down leagues too. `compute_player_signal`: `quality_rate = exp_pts_g/opp_g` (value per chance, separate from Volume), `point_correlation` → weekly actual-vs-expected full points, new `luck` = recent − expected ppg; scoring applied at the consumption layer. Gate (`backtest_player_signal.py`, exit 0): new 3rd verdict — quality_rate (exp_ppo) forecasts ROS realized efficiency at MAE 0.311 vs 0.506 recent-realized; core still beats naive 13.2%, spike<sticky. **Core-engine upgrade tested & REJECTED by the answer key**: shrinking the spike forecast toward exp_ppo lost to the positional mean at every SHRINK_K (K=6: 2.699 vs 2.599) — points-forecasting regresses to the *population*, exp_ppo (same recent weeks) too correlated with realized ppo to pull that way; kept the validated positional-mean prior (the model serves the §1 axis, not the forecast). No UI (data + gate).
    - §2 Player-News Collector (aggregation half of the ROS AI-interpretation layer, Phase 6) — `fetchers/news.py`, a live/scheduled RSS collector → new `player_news` entity (`snapshots/news/player_news.parquet`; grain = one row per news-item × resolved player; writer append-only-of-new by `item_id`, idempotent; compact items only — headline/summary/url + `collected_at`, never article bodies → url+date = Wayback recall path). National feed registry (source_type stored so team beats drop in later); `_get_feed` timeout+backoff; **resolution** = exact full-name match vs the 967 active-rostered (`team`-not-null) skill players (0 collisions) + defensive team-mention disambiguation (`match_confidence` exact_full/disambiguated; ambiguous skipped — law 2); incremental per-feed snapshot with per-feed isolation; entry points snapshot/feeds/resolve-test/check (synthetic resolver self-check). +feedparser dep + `com.fantasyai.news-snapshot` launchd plist (5am ET). Live-acquired like manager_activity (forward pipeline, NOT tied to frozen-2025). Verified live: 5/5 feeds, 151 entries→48 items→66 rows, idempotent, dead-feed isolation, check PASS, 0 false positives. Next: the §2 on-demand AI synthesis (one lazy cached per-player call → headlines + bull/bear blurb + confidence).

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

> **⭐ NEXT BUILD (chosen 2026-07-11 for the next session): §2 ROS Outcome Shape — the AI SYNTHESIS
> call (Phase 6, the interpretation half).** The §2 AI layer was decomposed (sparred with the PM) into
> **aggregation** (the news collector — **now BUILT**, see the most-recent build: `fetchers/news.py` +
> the `player_news` entity) and **interpretation** (this next build). The quantitative skeleton
> (`compute_ros_outcome_shape.py`: bull/bear band + preseason ADP anchor + situation/security evidence)
> and the news feed both now exist; what's left is the synthesis that reads them.
>
> **The synthesis design (decided):** a **single lazy, cached, per-player** Claude call — NOT a batch
> pre-compute of all rostered players (you'd pay for players nobody views). It fires **on demand** when a
> user opens a player, reads recent `player_news` (relevance/independence-gated) + the Sleeper factual
> fields (injury/depth/practice) + the `ros_outcome_shape` structured anchors (`ros_bull`/`bear`/`cv`,
> `spectrum_pos`, `adp_*`, `anchor_floor`/`ceiling`, `security`/`direction`/`reliability`), and returns
> in **one pass**: (1) consolidated **news headlines** (the receipts), (2) the **bull/bear narrative**,
> (3) a **confidence-flagged grade**. One call, so the headlines and the blurb can't drift; cache keyed on
> (player + news-content-hash + week), invalidated when either changes. Guardrails (from `DECISION_READS
> §2`): **anchor to the structured inputs** so grades aren't free-floating, **always show the narrative
> with the grade**, and **flag confidence** (law 2 — qualitative + AI = the least provable read; thin/no
> news → explicitly tentative, the zero-signal-dossier move).
>
> **Reuse, don't rebuild:** `ai/client.py` is a generic isolation seam (`api_available()` API-key gate +
> one model-call point, Haiku, SDK-version-safe `json.loads`); mirror `ai/dossier_prompt.py` (a §2 prompt
> anchored to the news + anchors) and `ai/write_*` (the writer). **Gate = internal-consistency** (no
> answer key — it's live/qualitative): faithfulness (narrative only cites the clustered headlines),
> anchoring (grades consistent with the quantitative band/spectrum), confidence honesty. **Time-world
> caveat (design record):** live-2026 news can't be validly fused onto a frozen-2025 bull/bear number, so
> the grade *fusion with the band* is a live-season integration — the provable-now deliverable is the
> collect→synthesize chain over current players; don't staple a 2026 injury note onto a 2025 roster.

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
Spearman 0.756; top-4 by odds = 3/4 actual playoff teams). **Source scouting settled the 2nd source**
— no clean historical-2025 projection source exists but Sleeper, so the **cross-source disagreement**
half (the Phase-2 substrate's other ingredient) comes **in-season via ffanalytics**; ESPN historical
is deferred (cookie-gated + `espn_id` join). **The §2 ROS outcome-shape skeleton is now DONE** (bull/bear/
situation, calibration-gated — see the most recent build), which **completes the player-read backend
(§1–§4).** **§7 Manager Dossiers is now COMPLETE** (Phase A cross-league features + Phase B the
API-key-gated Haiku dossier writer — the project's first AI-layer code, `application/ai/`; see the two
most recent builds). **Next — remaining Phase 4:** the deliberate **front-end
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
  math + §2 ROS skeleton + §7 dossiers all done)* — the §5 posture read (bracket-math Monte Carlo ✅ +
  True Rank = complete), §2 ROS outcome-shape skeleton (✅ bull/bear/situation, calibration-gated),
  manager dossiers (✅ §7 COMPLETE — Phase A cross-league features + Phase B the API-key-gated Haiku AI
  writer); front-end surfacing of the gated forward reads; in-season weekly refresh; waiver and trade surfaces.
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
  coin-flip; expected-wins Spearman 0.756; top-4 by odds = 3/4 actual playoff teams). See "most recent build".
- ✅ **§2 ROS Outcome Shape skeleton (DONE — Phase 4).** `compute_ros_outcome_shape.py` → bull/bear (borrowed
  ROS centre ± BULL_Z·√Σband², floored, emergent time decay) + situation/security (player_signal trust axis).
  Calibration-gated (coverage 0.835; BULL_Z swept to 1.645; monotonic by bull tercile). **Completes the
  player-read backend (§1–§4).** See "most recent build".
- ✅ **§7 Manager Dossiers COMPLETE (Phase A + B — Phase 4).** Phase A: cross-league acquisition
  (`fetch-manager-activity` → `manager_activity_{season}`, first cross-league/user-keyed entity) +
  deterministic features (`compute_manager_features.py` → `manager_features_{season}`). Phase B: the
  project's first AI-layer code — `application/ai/` writes one API-key-gated Claude-Haiku dossier per
  manager (`manager_dossiers_{season}`, first AI-written entity) from those features; synchronous calls
  behind a swappable seam, run-once, tendencies-not-verdicts, blindspot/edge framing, internal-consistency-
  gated. Both live-verified 2025 (Phase B: 10 dossiers, ~$0.025, gate exit 0). See the two most recent builds.
- **Next — remaining Phase 4:** the **front-end surfacing** of the six gated forward reads (incl. posture
  presentation) + the dossiers.
  **Blocked, not next:** cross-source **disagreement** (in-season, needs the live 2nd source).
- **Optional cheap add:** Vegas game totals via an `odds.py` fetcher (game environment).

> **V1 Dashboard Build Order — moved.** The dashboard build order, plus the full
> Built / Unbuilt breakdown (Built Backend · Built Frontend · Unbuilt+Blocked), now lives in
> `scope docs/READ_BUILD_ORDER.md`. Single source of truth — not duplicated here. The backend
> hygiene backlog is in `LLM context/710_AUDIT.md`.
