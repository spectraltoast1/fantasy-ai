# STATUS

**Last updated:** 2026-07-13 (**GRIDIRON FRONT-END — FOUNDATION + PLAYERS SLICE SHIPPED: the first
front-end surfacing of the gated backend reads.** Recreates the Claude-Design `Gridiron` handoff (in
`scope docs/`, its `DATA_CONTRACT.md` mapping every visual → a backend entity) in the real React + Vite +
DuckDB-WASM app — Web-first, new-shell-with-placeholders migration. **Commit 1** the violet/posture design
system + 4-surface app chrome (brand + real derived league meta `10-tm · PPR · 1QB · 3-1` from teams/
league_settings/lineup_slots, segmented League/Matchups/Teams/Players tabs, the existing week selector
reused, coming-soon placeholders for the 3 unbuilt surfaces; new `icons.jsx`/`Placeholder.jsx`, `styles.css`
rewritten to the token set). **Commit 2** the **Players table** — `queries.loadPlayers()`: ONE read joining
`production_vor` (PROD VOR, default sort) + `market_vor` (MKT VOR, cross-time) + `ros_synthesis` (bull/bear/
situation 1-10 grades) + season identity, ALL on `sleeper_player_id`; VOR-anchored sortable table + position
filter, is_me YOU badges. **Commit 3** the **Player card** — `loadPlayerCard()` + shared `charts.jsx`
(Sparkline/TrendLine/GradeBar/RangeGauge): Value·VOR (Production + Market weekly series + value/delta) + a
BUY/HOLD/SELL trade lean off `trade_gap` (POC-GATED — cross-time, never a live call), Opportunity from
`player_signal` (quality_rate / opp_pct / direction+reliability / recent-vs-expected), ROS Outcome Shape
(grades + prose notes + confidence, prior-season flagged), all with honest empty states. **Honest gaps:**
rostered-only (no free-agent VOR entity → the Available filter + waiver strip are deferred, a backend
follow-up); `ros_synthesis` is sparse (~16 players → grades shown where present, full coverage needs a
roster-wide AI batch ~$0.75); MKT/trade-gap cross-time (2026 market × 2025 roster) so gated POC. All new
front-end data access is through the `queries.js` seam (loadPlayers/loadPlayerCard/loadLeagueMeta); the old
League/Team panels are retired from the shell (files kept, unimported). Verified live 1280px: real players
sorted by PROD VOR, MKT + negatives, is_me badges, PROD/MKT re-sort, QB filter, row→card→back; Player card
full (Gibbs honest ROS-empty; Hurts full ROS 8/6/6 + MED confidence + prior-season flag), no console errors.
**Next — Manager Dossier slice (trivial 1:1 map), then Teams/Team-detail → League → Matchups per the
contract build order.** — Prior backend: **§4 MARKET VOR + PRODUCTION−MARKET TRADE GAP SHIPPED — the primary
remaining backend read, and the one un-backdatable piece built on CURRENT (2026) data.** The market-value
twin of Production VOR: the same waiver=0 ÷ pool-spread VOR (reusing the shared `position_pools` /
`_pool_lines` / `_vor` engine — no new math, law 3) on the borrowed LeagueLogs `value` for the
format-matched `redraft-1qb-12t-ppr1` profile. New `data_layer` `market_vor` entity
(`derived/market_vor_{season}.parquet`, tall over the market's `snapshot_date` axis); `compute_market_vor.py`
(position from the Sleeper registry); the Production−Market **gap folded in** (`trade_gap`). The app is
frozen at 2025 wk4 but the LeagueLogs series is current 2026 and can't be backdated, so the gap is
**cross-time by construction** — every row carries `is_cross_time` + `market_season` + `has_production_vor`
as first-class columns (never fused — the `anchor_is_prior_season` precedent), and it's **POC/architecture
validation, not a live trade call** until the season rolls to 2026. **Purely additive — nothing reads it
yet, so the current-vs-2025 split does NOT affect app functioning.** Internal-consistency gate
`check_market_vor.py` (no answer key at the freeze). Verified live: 31 snapshots → 5270 rows, 170/171
frozen roster priced, gate exit 0, Production VOR gate unaffected. **Next = front-end surfacing of the
gated reads.** — Prior: **§2 ROS SYNTHESIS SHIPPED (QUEUED #2 done) — the AI interpretation
layer, completing the §2 read.** The last mile `compute_ros_outcome_shape.py` deferred ("the AI
narrative + 1-10 grade roll-up is Phase 6") now exists: a **per-player Claude call** (`application/ai/
write_ros_synthesis.py`, reusing the `ai/client.py` seam) that **fuses** the quantitative anchor
(`ros_outcome_shape`) with the situation news (`player_news_slice`) + Sleeper facts into the three §2
scores as **1-10 grades — bull / bear / situation — each with a prose note**, **consolidated headlines**
(grounded in the cited article ids), and a **confidence flag**. Graceful per-input degradation makes
the gaps FIRST-CLASS columns (`has_ros_anchor` / `has_news` / `anchor_is_prior_season` + confidence):
full-set → fully-anchored; news-only → news-led, confidence capped; nothing → a hardcoded "insufficient
data" row, **API skipped**. This is how the 2026-news × 2025-anchor **time-world mismatch** is handled
HONESTLY (the anchor is flagged prior-season, never silently fused). Output is a **structured parquet**
(`ros_synthesis_{season}`, replace-by (season,week,player)) — every grade / note / confidence is its
own column, extractable apart. The **prompt is a pure editable module** (`ai/ros_synthesis_prompt.py`)
with **no-AI iteration tooling** in the writer (`--render` prints the exact assembled prompt, `--replay`
runs a canned reply through validation — both need no API key / no cost). Gate
(`ai/check_ros_synthesis.py`) is internal-consistency (no answer key): coverage / schema / **grounding**
(headlines trace to the slice) / **confidence honesty** (thin/no-anchor ⇒ not 'high') / data-flag
honesty + a soft prose-leak scan. Verified live 2026 wk0: 16 players across all regimes (~$0.07,
grades spread bull 3-9), gate PASS, guard tests (run-once / locked-key / partial / zero-signal) all
clean. **Front-end surfacing + the browser-triggered on-demand runtime stay deferred with the
deployment/server decision** (no server exists; API key is server-side; the `news_content_hash` column
is laid down now as the future cache seam). **The prompt TEXT is expected to keep evolving — it lives in
that one pure module, and `--render`/`--replay` make tweaking it AI-free.** **Prior — Daily-collector
reliability SHIPPED — shared `_http` layer + collector
registry/dispatcher + coverage gate (QUEUED #1 done).** Separation of concerns: retry / backoff /
throttle / per-item isolation now live ONCE in `fetchers/_http.py`, and all three HTTP callers
(`sleeper` / `news` / `leaguelogs`) route through it — **leaguelogs gains the missing retry + per-item
isolation** (the fix for the audit's ~7 transient-fail + "dynasty profiles drop first" days).
`fetchers/run.py` is a declarative collector **REGISTRY + `run <name>` dispatcher** (cadence declared
per collector; the **meter stays external** — launchd → GitHub Actions, which will call this same
dispatcher, so nothing is wasted). `fetchers/check_collectors.py` **certifies** the banked series
(leaguelogs strict daily coverage; news recency), hard-gating a recent window so permanent powered-off
gaps don't fail forever; `--today` monitoring. The **off-laptop host** (the ~8 powered-off days) stays
**deferred to the deployment decision**. Verified: network-free retry/4xx self-test, live no-regression
on all three fetchers, isolation proof (a dead profile no longer aborts the run), gate reproduces the
audit (65% complete / 72% any-data) + flags the real recent gap. **Next = QUEUED #2** (§2 ROS synthesis
call — the news input `player_news_slice` now exists). **Prior — §2 news pipeline COMPLETE (Stage C):**
per-player slice by inheritance (`player_news_slice`) + thinness tripwire + retention; deterministic
reshape, hard gate, verified live 2026 wk0 (967 players → 3058 rows; prune kept all 5021 raw rows,
nulled 1243 old bodies). **Prior detail — Stage B (`application/ai/news_prompt.py`
+ `write_team_news_dossier.py` + `check_team_news_dossier.py`, reusing the `ai/client.py` seam + the
retained resolver) distills each team's recent `team_news_raw` window into a compact, **situation/security-
focused, attributed** set of **scope-tagged claims** (player / position_group / unit) a downstream AI reads
next to the numeric analytics. Per claim: `scope` / `subject` / `claim_type` / **`basis`** (official /
reported / opinion — so an opinion is never mistaken for fact) / `note` (one attributed cliffs-note) /
`direction` (positive / negative / neutral / **mixed** = cross-pressured) / `salience` / cited
`source_article_ids` + `source_types` (clustered across the 3 sources; diversity = trust). **Skill-only
(V1):** player claims are QB/RB/WR/TE and resolve to a Sleeper id via a **team-restricted** index (never a
cross-team id); all defensive news is condensed into ONE `defense` unit note (game-script context now,
pre-banked for later). Verified live: **32/32 teams, 317 claims, 1 Haiku call/team (~$0.46 total)**;
internal-consistency gate PASS (coverage / schema / grounding / on-team resolution / zero-signal honesty);
168/186 player claims resolved. Off-season window is thin by nature; richness ramps into camp.
**Design record — Stage A (still current):** `fetchers/news.py`
collects per-NFL-team from **3 native RSS sources per team** — SB Nation (grounded analysis), FanSided
(player-flavored, noisier), and the official team site (authoritative/PR) — into the new **`team_news_raw`**
entity (one row per article, **stores feed-provided content** so the extraction has text; feed-provided
only, no scraping). National desks dropped (league-level, not team); **SI/FanNation ruled out** (no native
per-team RSS — tested: zero autodiscovery, all team paths 404). Player resolution moved out of collection
into Stages B/C (the resolver is retained). Per-feed isolation + backoff + resilience-floor flag; per-team
volume reported (the Stage-C thinness-tripwire input); append-only-of-new by `article_id` (idempotent).
Verified live: **96/96 feeds across 32 teams, 5021 articles**; 0 duplicate titles; dead-feed isolation;
resolver `check` PASS; content + provenance (`published_at` 100%, url) stored. **Supersedes** the v1
`player_news` collector (left as legacy). **Design record (sparred + researched with the PM):** the value
is *interpretation + salience* (facts come from Sleeper), so trust = source diversity, not fake
corroboration; `source_type` stored for downstream weighting; the "no bodies" v1 rule was reversed because
extraction needs the text. **Prior build:** the v1 player-news collector (national feeds → `player_news`) —
now reworked.)
**Retention (Stage C — SHIPPED):** collection runs **daily** (append-only-of-new; first run was a
5021-article backfill). `news.py prune` (`RETENTION_DAYS=28`, safely > the 14d synthesis window) nulls raw
article **content** older than the cutoff while keeping the row + link + derived claims; idempotent,
`--dry-run` first. Verified: 5021 rows kept, 1243 old bodies nulled. **Scheduling deferred to QUEUED #1**
(wire `prune` into the daily job — it's a data-maintenance step, cheap + idempotent).
**Post-merge operator action: install the `com.fantasyai.news-snapshot` launchd plist** into
`~/Library/LaunchAgents/` + `launchctl bootstrap` (5am ET daily; the job now does **team** collection) —
see `scheduler/README.md`. (`feedparser` already installed in the framework Python on this machine.)
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
**Gridiron front-end — Foundation + Players slice (first front-end surfacing of the gated reads; 3 commits).**
Recreates the Claude-Design `Gridiron` handoff in the real React + Vite + DuckDB-WASM app per its
`DATA_CONTRACT.md` (Web-first; new-shell-with-placeholders migration). **(1) Foundation:** `styles.css`
rewritten to the Gridiron token set (violet brand accent + reserved 5-color posture palette, Archivo/IBM
Plex Mono), a new top-bar shell (`App.jsx`) — brand + league switcher (real derived `10-tm · PPR · 1QB · 3-1`
via new `queries.loadLeagueMeta` off teams/league_settings/lineup_slots, nothing hardcoded), centered
segmented tabs with SVG glyphs (`icons.jsx`), the existing week selector reused, avatar; `Placeholder.jsx`
coming-soon slot for League/Matchups/Teams. The old League/Team panels are retired from the shell (files
kept, unimported). **(2) Players table:** `queries.loadPlayers(asOfWeek)` — ONE read joining `production_vor`
(as-of slice → PROD VOR, default sort), `market_vor` (latest snapshot → MKT VOR + trade_gap, cross-time),
`ros_synthesis` (latest week → bull/bear/situation grades, sparse), and season identity (name + NFL team),
ALL on `sleeper_player_id`; `Players.jsx` renders a VOR-anchored sortable table (PROD/MKT/BULL/BEAR/SIT) +
position filter + is_me YOU badges, wrapped in the point-in-time readiness `Gate`. Available/waiver filter
DEFERRED (no free-agent VOR entity in V1). **(3) Player card:** shared `charts.jsx` (Sparkline/TrendLine/
GradeBar/RangeGauge) + `queries.loadPlayerCard(sleeperId, asOfWeek)` → `PlayerCard.jsx`: Value·VOR
(Production + Market weekly series + value/delta) with a BUY/HOLD/SELL lean off `trade_gap` **POC-gated**
(is_cross_time — never a live call), Opportunity from `player_signal` (quality_rate/opp_pct/direction+
reliability/recent-vs-expected + read), ROS Outcome Shape (`ros_synthesis` grades + prose notes + confidence,
prior-season flagged); honest empty states where a read is absent. `db.js` registers production_vor/
market_vor/ros_synthesis/league_settings (public/data symlinks added). **Seam discipline kept** — all new
data access is in `queries.js`; views are pure renderers consuming plain objects. Verified live at 1280px
(browser preview): real players sorted by PROD VOR (Josh Allen/McCaffrey…), MKT cross-time incl. negatives,
QB filter + MKT re-sort, is_me badges, row→card→back; Player card full — Gibbs (honest ROS-empty) and Hurts
(full ROS BULL 8 / BEAR 6 / SITUATION 6 + AI prose + MED confidence + prior-season flag); no console errors.
**Next — Manager Dossier slice (trivial 1:1 to `manager_dossiers`), then Teams/Team-detail → League →
Matchups; plus mobile-responsive pass + the free-agent value backend read that unblocks Available/waivers.**

> earlier build
**§4 Market VOR + Production−Market trade gap — the market-value twin of Production VOR (completes the
§4 read; the un-backdatable POC piece built on CURRENT 2026 data).** The primary remaining backend read.
Per design law 3 it borrows the LeagueLogs market value and adds only the decision layer — the SAME
anchoring + normalisation as Production VOR, reusing the shared engine (`_analytics.position_pools`,
`compute_production_vor._pool_lines`/`_vor`/`_roster_as_of`, `round1`) with **no new VOR math**. **New
`data_layer` `market_vor` entity** (`snapshots/derived/market_vor_{season}.parquet`; grain one row per
(snapshot_date, rostered skill player); **tall over the market's `snapshot_date` axis** — the analog of
Production VOR's `as_of_week`, banking the un-backdatable market series in derived form; `read_market_vor(
season, snapshot_date=None)` defaults to the latest banked day). **`compute_market_vor.py`:** filters the
market to the **format-matched** profile `redraft-1qb-12t-ppr1` (redraft ✓ 1QB ✓ full-PPR ✓ — resolves
the §4 open prereq flag; LeagueLogs only publishes 12-team profiles vs our 10-team, a documented non-issue
because the waiver line is computed from OUR league's roster/available split, not the profile), joins
**position from the Sleeper registry** (the feed carries only `position_rank`, no label), resolves the
frozen-2025 roster/available split (`_roster_as_of` at the freeze week), and per pool sets waiver = best
**available** value / top = best value → `market_vor = (value − waiver) / (top − waiver)` (waiver=0,
top≈1, negative = below the best freely-available player). **Pools identical to Production VOR** (QB pool
+ pooled flex line from `lineup_slots`). **The Production−Market gap folded in:** joins the frozen
Production VOR slice (latest `as_of_week`) → `trade_gap = market_vor − production_vor` (Market ≫ Production
→ sell; Production ≫ Market → buy/hold; the gap ≈ the speculation premium). **Time-world honesty (the
crux):** the app is frozen at 2025 wk4 but the LeagueLogs market is **current 2026 and can't be backdated**,
so the gap is **cross-time by construction** — `is_cross_time` + `market_season` + `production_as_of` +
`has_production_vor` ride as **first-class columns**; the market number is never silently fused with the
production number (the `ros_synthesis.anchor_is_prior_season` precedent). At the freeze the gap is
**POC/architecture validation, NOT a live trade call** (the biggest gaps are cross-time + 1QB-pool-
compression artifacts — "sell all your QBs" is noise, exactly what the flag warns against); it becomes a
real signal once the season rolls to 2026 and production is recomputed there. **Purely additive** — a new
derived parquet + `data_layer` fns + a gate; **nothing in the front end or any existing transform reads
it**, so the current-vs-2025 split does NOT touch app functioning (front-end surfacing is the next work).
**Internal-consistency gate `check_market_vor.py`** (no answer key at the 2026-offseason freeze — the
market has no future truth to grade against here, the `backtest_manager_features`/`check_ros_synthesis`
regime): recompute-match (persisted == shipped `compute()` frame-for-frame) / VOR algebra (waiver≤top,
market_vor reproduces (value−waiver)/spread within a spread-aware rounding tol ⇒ monotonic + negatives
below waiver, top≈1.0) / pool integrity (= Production VOR's pools) / profile+coverage (single profile, no
picks, ≥95%) / gap honesty (all cross-time flagged; `trade_gap` null iff no production row else exactly
market−production). Verified live 2026 offseason: **31 snapshots → 5270 rows**, 170/171 frozen roster
priced (99.4%), 248 no-production rows null (law 2), gate exit 0; Production VOR gate unaffected (corr
0.944 QB / 0.955 FLEX). No UI (data + gate). **Next — front-end surfacing of the gated forward reads
(Phase 4).**

> earlier build
**§2 ROS Synthesis — the per-player AI interpretation call (QUEUED #2; §2 read COMPLETE).** The last
mile the ROS Outcome Shape skeleton deferred to Phase 6. The project's 3rd AI-layer read, reusing the
`ai/client.py` isolation seam. **New `application/ai/` trio:** `ros_synthesis_prompt.py` (pure, editable
prompt — `system_prompt()`/`user_prompt(ctx)` + `SYNTHESIS_KEYS` + the zero-signal fallback + the
plain-language translations of the internal role signals); `write_ros_synthesis.py` (gathers a player's
inputs → one `generate_dossier` Haiku call → validate → row); `check_ros_synthesis.py` (internal-
consistency gate). **New `data_layer` `ros_synthesis` entity** (`snapshots/derived/ros_synthesis_
{season}.parquet`; grain one row per (season, week, player); replace-by-(season,week,player) so a
single-player re-run overwrites just his row — the per-player cache-friendly grain the on-demand runtime
will use). Per player it **fuses** the quantitative anchor (`ros_outcome_shape`: caliber bucket + bull/
bear band + security/trend), the situation news (`player_news_slice`), and Sleeper injury/depth facts
into: **bull/bear/situation 1-10 grades (each with a prose note)** + **consolidated headlines** (each
citing the article ids that back it) + a **confidence** flag. **Grade convention** (decided with the
PM): all three 1-10 with 10 best, INDEPENDENT axes (no ordering) — bull = ceiling height (hard-anchored
to a caliber bucket so elites hit 9-10 and the full range is used), bear = floor safety, situation =
how smooth/settled. **Prose discipline:** notes are natural manager-facing language — the substrata
(percentiles/tiers/projection points/trend flags) drive the grades but are BANNED from the prose;
attributed news stays. **Graceful per-input degradation** with the gaps as first-class columns
(`has_ros_anchor`/`has_news`/`anchor_is_prior_season`); a player with neither anchor nor news gets a
hardcoded row, **API skipped**. **No-AI prompt iteration** (self-serve, no session, no key, no cost):
`write_ros_synthesis.py --render` prints the exact assembled prompt; `--replay` runs a canned reply
through validation. **Season/time-world honesty:** output keyed by the NEWS (season, week); the ros
anchor is a by-id lookup from `--anchor-season`, flagged PRIOR-SEASON when it differs — never silently
fused (the STATUS caveat). Gate checks coverage / schema / grounding / confidence honesty / data-flag
honesty + a soft prose-leak scan. Verified live 2026 wk0: 16 players across all regimes (Chase bull 9 …
Kraft/Rodriguez 3-4; ~$0.07), gate exit 0, guard tests (run-once superset / locked-key refusal /
partial run calls the API only for the new player / zero-signal skips it) all clean; the persisted
parquet carries every grade/note/confidence as its own column. **Deferred with deployment:** front-end
wiring + the browser-triggered on-demand runtime (no server; the key is server-side; `news_content_hash`
is the future staleness-cache seam) + validated same-season live fusion. **Next — front-end surfacing
of the gated forward reads** (Phase 4).

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
    - leaguelogs snapshot reliability — snapshot() rewritten to write incrementally (cumulative today's-rows persisted after each profile) so a mid-run API failure leaves a recoverable partial day instead of discarding the whole run; idempotent re-run replaces a partial day (dedup on snapshot_date). 2026-06-18 captured (5 profiles, 3,409 rows; history → 14 dates). Follow-up still open: retry/backoff + off-laptop host. **(2026-07-11 audit: over the full 41-day series 05-31→07-10 coverage is 63% complete / 71% any-data — ~8 laptop-off + ~7 no-retry days, all permanent. This follow-up is now specced as the generalized "Daily-collector reliability" item in `READ_BUILD_ORDER.md`, covering both `leaguelogs.py` and `news.py` via one shared `fetchers/_http.py` + a `check_*` coverage gate + an off-laptop host merged with Deployment.)**
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
    - 710 backend-audit fixes (structural #1 + hygiene #5/#6/#7) — `application/` made a proper Python package: `__init__.py` in the 6 dirs + root `pyproject.toml`; every bare sys.path-dependent import rewritten to absolute package form and all 56 `sys.path.insert` lines across 31 files deleted (zero remain); scripts run as `python3 -m application.<pkg>.<module>` from the repo root (`-m` puts cwd on the path — no editable install); lazy `_import_manager_helpers` → top-level package import; ~30 usage strings + the two doc call-sites + the launchd plist (`-m` module, WorkingDirectory=repo root) + README updated. Hygiene: config.example gains SLEEPER_LEAGUE_ID + drops dead LEAGUE_TYPES/EXCLUDED_LEAGUES; requirements sheds unused pandas/nfl_data_py; bracket figure reconciled to top-4=3/4. Behavior-preserving (all backtest gates pass via -m, identical numbers; byte-compiles clean). Deferred: #2 scaling (no-op migration trigger), #3 §1 quality axis (net-new empirical-weighting transform), #4 §2 preseason anchor (blocked — no ADP source fetched). Post-merge: reinstall the launchd plist.
    - 710 audit #4 (§2 ROS preseason anchor) — overturns session-1's "#4 blocked on data": the ADP source was `nflreadpy.load_ff_rankings` (already a dependency). `fetchers/adp.py` fetches the historical FantasyPros preseason redraft-overall board (latest full-skill-board pre-kickoff snapshot/season; ecr/best/worst/sd + positional rank; id-bridged `fantasypros_id`→sleeper via ff_playerids, cbs/yahoo all-null; `adp_preseason` entity, 2020–2025, top-150 150/150). `compute_adp_points_curve.py` fits per-position `pos_ecr_rank → realized-points` floor/center/ceiling (P10/P50/P90 over a rolling ±3-rank window, isotonic non-increasing; drafted-never-produced = 0.0 floor signal; trained 2020–24, 2025 held out = leak-free; `adp_points_curve` entity; +`_analytics.quantile`). Historical realized points via existing `nfl_stats` backfill 2020–24 (sanctioned data-layer path — no transform hits nflreadpy). Anchor blended into `compute_ros_outcome_shape` bull/bear via horizon-decaying `w_N = ANCHOR_W·(remaining/total)`; `ros_center` stays borrowed (law 3); undrafted/uncovered degrade to the pure-projection band; +adp/anchor evidence cols. Joint `BULL_Z×ANCHOR_W` re-sweep (gate imports shipped `_preseason_anchor`/`_blended_band`; objective |cov−tgt|+|tail imbalance|) → (1.44, 0.25): freeze coverage 0.744→0.817, tails 0.195/0.061→0.091/0.091, gate exit 0, ros_bull terciles 58<127<205. Limitation: freeze bounds tested cutoffs to N=1..4 (early/prior-heavy) — decay's late tail by construction. Also re-scoped #3 (§1 quality) smaller: `load_ff_opportunity` ships the empirical expected-points model → consume-and-re-score, not fit-your-own-weights.
    - 710 audit #3 (§1 Quality axis) — CLOSES the 710 audit (7/7). `quality_rate` was `xtd_g/opp_g` (nflfastR `td_prob`, TD-only, ungated); now = **expected fantasy points per opportunity** from ffverse's `ff_opportunity` component model. `nfl_stats._load_ff_opportunity` joins the `*_exp` components (gsis-keyed, null-id rows filtered; REG weeks); `xtd` retired, `redzone_touches` kept as companion; latent bare `import audit_join` (package-refactor #1 miss) fixed. New `_scoring.expected_points_expr` re-scores the components from-scratch under league settings — exact (all components exposed), reproduces ffverse's `total_fantasy_points_exp` under PPR to ±0.02, scores first-down leagues too. `compute_player_signal`: `quality_rate = exp_pts_g/opp_g` (value per chance, separate from Volume), `point_correlation` → weekly actual-vs-expected full points, new `luck` = recent − expected ppg; scoring applied at the consumption layer. Gate (`backtest_player_signal.py`, exit 0): new 3rd verdict — quality_rate (exp_ppo) forecasts ROS realized efficiency at MAE 0.311 vs 0.506 recent-realized; core still beats naive 13.2%, spike<sticky. **Core-engine upgrade tested & REJECTED by the answer key**: shrinking the spike forecast toward exp_ppo lost to the positional mean at every SHRINK_K (K=6: 2.699 vs 2.599) — points-forecasting regresses to the *population*, exp_ppo (same recent weeks) too correlated with realized ppo to pull that way; kept the validated positional-mean prior (the model serves the §1 axis, not the forecast). No UI (data + gate).
    - §2 Player-News Collector (aggregation half of the ROS AI-interpretation layer, Phase 6) — `fetchers/news.py`, a live/scheduled RSS collector → new `player_news` entity (`snapshots/news/player_news.parquet`; grain = one row per news-item × resolved player; writer append-only-of-new by `item_id`, idempotent; compact items only — headline/summary/url + `collected_at`, never article bodies → url+date = Wayback recall path). National feed registry (source_type stored so team beats drop in later); `_get_feed` timeout+backoff; **resolution** = exact full-name match vs the 967 active-rostered (`team`-not-null) skill players (0 collisions) + defensive team-mention disambiguation (`match_confidence` exact_full/disambiguated; ambiguous skipped — law 2); incremental per-feed snapshot with per-feed isolation; entry points snapshot/feeds/resolve-test/check (synthetic resolver self-check). +feedparser dep + `com.fantasyai.news-snapshot` launchd plist (5am ET). Live-acquired like manager_activity (forward pipeline, NOT tied to frozen-2025). Verified live: 5/5 feeds, 151 entries→48 items→66 rows, idempotent, dead-feed isolation, check PASS, 0 false positives. Next: the §2 on-demand AI synthesis (one lazy cached per-player call → headlines + bull/bear blurb + confidence).
    - §2 News pipeline REWORK — team-centric collection (Stage A), supersedes the v1 player-news collector — `fetchers/news.py` reworked to collect per-NFL-team from **3 native RSS sources/team** (SB Nation `/rss/index.xml` grounded + FanSided `/feed/` player-flavored/noisier + official `<team>.com/rss/news` authoritative/PR); all **96 feeds (32×3) validated live** (96/96 ok, 5021 articles). Nationals dropped (league-level); SI/FanNation ruled out (no native per-team RSS — 0 autodiscovery, all paths 404). New data_layer **`team_news_raw`** entity (grain = one row per **article**; **stores feed-provided content** for the extraction — reverses v1's headline-only rule; feed-provided only, no scraping; append-only-of-new by `article_id`, idempotent). Player resolution moved out of collection into Stages B/C (resolver retained: `build_index`/`resolve_players`/`_TEAM_ALIASES`). Per-feed isolation + backoff + per-team volume report (Stage-C thinness-tripwire input) + resilience-floor flag; `source_type` per article for weighting; `player_news` left as legacy. Verified: 96/96 feeds / 32 teams / 5021 articles, 0 dup titles, dead-feed isolation, resolver `check` PASS, `published_at` 100%. Stage A of the 3-stage pipeline (B = weekly AI claim-extraction → `team_news_dossier`; C = per-player slice + thinness tripwire + retention).
    - §2 News pipeline Stage B — weekly per-team AI news synthesis → `team_news_dossier` (the interpretation half; the project's 2nd AI-layer read after §7 dossiers) — new `application/ai/`: `news_prompt.py` (pure; situation/security schema + cluster-across-sources + attribution guardrails), `write_team_news_dossier.py` (windows the raw store `WINDOW_DAYS`=14/cap 60 → 1 Haiku call/team → validate → deterministic on-team id resolution; run-once-per-week, `--force`, `--team`), `check_team_news_dossier.py` (internal-consistency gate). `client.py` refactored (`_raw_call` shared seam + `generate_claims` array path; `generate_dossier` behavior-identical). New data_layer **`team_news_dossier`** (one growing file; grain = one claim row per (season,week,team); replace-by-(season,week,team), idempotent). Per claim: scope (player/position_group/unit) / subject / claim_type / **`basis`** (official/reported/opinion — opinion never laundered into fact) / attributed `note` / direction (positive/negative/neutral/**mixed**) / salience / cited `source_article_ids` + `source_types` (clustered; source diversity = trust). Skill-only (V1): player claims QB/RB/WR/TE resolved via a **team-restricted** index (gate caught + fixed a cross-team-id bug); all defensive news condensed into ONE `defense` unit note (game-script context; pre-banked for later). Verified live 2026 wk0: 32/32 teams, 317 claims, ~$0.46; gate PASS (coverage/schema/grounding/on-team-resolution/zero-signal); 168/186 player claims resolved. Next — Stage C (per-player slice by inheritance + thinness tripwire + raw-content retention).
    - §2 News pipeline Stage C — per-player slice by inheritance + thinness tripwire + raw-content retention (COMPLETES the 3-stage news pipeline A→B→C) — a **deterministic reshape** (no AI), so the gate is **hard**. New data_layer **`player_news_slice`** entity (`snapshots/news/player_news_slice.parquet`; grain = one inherited-claim row per (season,week,player,claim); write replace-by-(season,week)). `transforms/compute_player_news_slice.py`: each on-team skill player (whole NFL skill pool ~967, forward/league-agnostic) inherits his **own** resolved `player` claims + his **position_group** claims (subject normalized to his skill position, OR team-wide offensive context — `offense`/`offensive line`/coaching-scheme → all skill players; unmapped subjects dropped + reported as Stage-B drift) + his team's **unit** claims (`offense` + the condensed `defense` note) from `team_news_dossier`. Thinness tripwire as columns: `signal_tier` (rich=≥1 own / thin=only inherited / none=nothing) + `n_own_claims`/`n_inherited_claims`/`team_news_volume`; a player who inherits nothing gets ONE `is_empty` honest-zero row (like positional_depth's zero-count rows). `transforms/check_player_news_slice.py`: HARD gate — **independently recomputes** each player's expected inherited set from the dossier+registry (does NOT call the compute) and demands an exact multiset match incl. inheritance tag + provenance; + coverage/identity/thinness-honesty/zero-signal/retention-safety. **Retention:** `data_layer.prune_team_news_raw_content` + `fetchers/news.py prune [--dry-run]` (`RETENTION_DAYS=28` > the 14d synthesis window) nulls raw article `content` older than the cutoff, KEEPS the row + `article_id`/`title`/`url`/`published_at` + the derived claims (which cite `article_id`, never the text); idempotent. Verified live 2026 wk0: 967 players → 3058 rows (own 168 = the resolved player claims / pg 626 / unit 2264; tiers rich 160 / thin 807 / none 0); eyeballed a TE inheriting his own claim + team offense but NOT the WR-room claim + a team-wide o-line claim reaching all 4 positions; slice gate exit 0. Prune: dry-run 1243/5021 rows → live kept all 5021 rows (0 null id/url), nulled all old content, kept the 28d window (3748 with content), idempotent; both gates exit 0 post-prune. The §2 synthesis (QUEUED #2) now has its news input: a player's inherited `player_news_slice`. No UI (data + gate). Next — QUEUED #1 (Daily-collector reliability).
    - Daily-collector reliability — shared `_http` resilience layer + collector registry + coverage gate (QUEUED #1) — separation of concerns: retry/backoff/throttle/per-item isolation now live ONCE in `fetchers/_http.py`, so every collector shares a consistent resilient fetch process. **3 commits.** (1) `_http.py`: `get`/`get_json` (bounded timeout + exponential-backoff-with-jitter retry on TRANSIENT failures — timeouts/conn-errors/5xx; a 4xx raises immediately) + `set_throttle` (process min-gap; the manager-activity fan-out raises it) + `isolate` (per-item catch+log+continue). All three HTTP callers migrated: `sleeper._get_json` → behaviour-identical thin wrapper (`set_throttle` re-exported); `news._get_feed` → `_http.get` + `_http.isolate`; **`leaguelogs._get` → `_http.get_json` (ADDS retry) + `snapshot()` per-item isolation** (ADDS it — the fix for the audit's ~7 transient-fail + "dynasty profiles drop first" days). (2) `fetchers/run.py`: declarative collector REGISTRY (leaguelogs + news — the banked daily series; NOT sleeper = on-demand) with cadence + coverage-shape per collector, + a `run <name>|--all|--list` dispatcher (uniform process → post-run freshness); the **meter stays external** (launchd → GitHub Actions calls this same dispatcher — nothing wasted). `fetchers/check_collectors.py`: network-free coverage/health gate — leaguelogs STRICT daily coverage (per-day distinct profiles vs max-seen full day), news RECENCY (append-only); HARD criterion is a recent window (default 7d, excl. today) so permanent powered-off gaps don't fail forever; `--today` monitoring; UTC-dated to match the collectors. (3) Docs. The **off-laptop host** (the ~8 powered-off days — a host problem retry can't fix) stays **deferred to the deployment decision** (GitHub Actions the lead: collects + publishes). Verified: network-free retry/4xx/isolate self-test (PASS); live no-regression on all 3 fetchers; isolation proof (2 forced-dead leaguelogs profiles → the 3 good ones collected + the run COMPLETED reporting "2/5 failed (isolated)" instead of aborting); gate reproduces the audit (leaguelogs full-span 28 complete / 65% / 72% any-data — matches the documented 63%/71%) + flags the real recent gap (07-05 partial → FAIL/exit 1; `--since 3` clean → PASS/exit 0). Next — QUEUED #2 (§2 ROS synthesis call).
    - §2 ROS Synthesis — the per-player AI interpretation call (QUEUED #2; completes the §2 read, the last mile compute_ros_outcome_shape deferred to Phase 6) — the project's 3rd AI-layer read, reusing the `ai/client.py` seam. New `application/ai/` trio + a `data_layer` entity. (1) **`ros_synthesis_prompt.py`** — the pure, editable prompt (`system_prompt()` + `user_prompt(ctx)` + `SYNTHESIS_KEYS` + `zero_signal_synthesis()` + plain-language translations of the internal security/direction labels). (2) **`write_ros_synthesis.py`** — per player: `assemble_player` gathers his `player_news_slice` claims + `ros_outcome_shape` anchor (by id, from `--anchor-season`) + Sleeper injury/depth facts → one `client.generate_dossier` Haiku call → `_validate` (grades 1-10, notes non-empty, headline ids ⊆ the slice, confidence vocab) → row. Modes: `run` (write, run-once superset guard by (season,week,player), `--force`), `--preview` (print output), and the **no-AI** `--render` (print the exact assembled prompt) / `--replay REPLY.json` (run a canned reply through validation) — both need no key/no cost, the prompt-iteration loop. Zero-signal (no anchor AND no news) → hardcoded row, API skipped. (3) **`check_ros_synthesis.py`** — internal-consistency gate (no answer key): coverage / schema / grounding (headlines trace to the slice) / confidence honesty (thin or no-anchor ⇒ not 'high'; zero rows are clean fallbacks) / data-flag honesty + a soft high-precision prose-leak scan. New **`data_layer` `ros_synthesis`** entity (`snapshots/derived/ros_synthesis_{season}.parquet`; grain one row per (season,week,player); replace-by-(season,week,player)). Output columns fully separable: `bull_grade`/`bear_grade`/`situation_grade` (Int, independent axes — no ordering) each with its `*_note`, `headlines` (List(Struct{text, source_article_ids})), `confidence`/`confidence_note`, availability flags (`has_ros_anchor`/`has_news`/`signal_tier`/`n_news_claims`), anchor carries + `anchor_is_prior_season`, `news_content_hash` (future on-demand-cache seam), provenance. **Grade convention (with the PM):** 10=best on all three; bull hard-anchored to a caliber bucket (elite→9-10 … fringe→1-2, full range) and decoupled from downside (that lives in bear/situation). **Prose discipline:** notes are natural manager language; the substrata (percentile/tier/projection/trend) drive the grades but are banned from the prose; attributed news stays. **Season/time-world honesty:** keyed by the news (season,week); a differing anchor season is flagged PRIOR-SEASON, never silently fused (the STATUS caveat — 2026 news × 2025 anchor). Verified live 2026 wk0: 16 players across all regimes (Chase bull 9 … Kraft/Rodriguez 3-4; ~$0.07), gate exit 0, guard tests (run-once / locked-key refusal / partial run hits the API only for the new player / zero-signal skip) all clean. Front-end wiring + the browser on-demand runtime + validated same-season fusion deferred with deployment (no server; key server-side). No UI (data + gate + prompt tooling).
    - §4 Market VOR + Production−Market trade gap — the market-value twin of Production VOR (completes §4; the primary remaining backend read, and the un-backdatable POC piece built on CURRENT 2026 data). Per law 3 borrows the LeagueLogs market value + adds only the decision layer, reusing the shared engine (`_analytics.position_pools`, `compute_production_vor._pool_lines`/`_vor`/`_roster_as_of`, `round1`) — **no new VOR math**. **2 code commits + docs.** (1) New `data_layer` **`market_vor`** entity (`snapshots/derived/market_vor_{season}.parquet`; grain one row per (snapshot_date, rostered skill player); **tall over the market's `snapshot_date` axis** — the analog of Production VOR's `as_of_week`, banking the un-backdatable series; `read_market_vor(season, snapshot_date=None)` → latest banked day) + `compute_market_vor.py`: filters to the format-matched profile **`redraft-1qb-12t-ppr1`** (redraft/1QB/full-PPR — resolves the §4 open prereq flag; 12t-vs-our-10t a documented non-issue since the waiver line is from OUR roster/available split), joins **position from the Sleeper registry** (feed carries only `position_rank`), resolves the frozen-2025 roster (`_roster_as_of` at the freeze week), per pool sets waiver=best-available / top=best value → `market_vor=(value−waiver)/(top−waiver)`; QB pool + pooled flex line identical to Production VOR. The **Production−Market gap folded in**: joins the frozen Production VOR slice → `trade_gap=market_vor−production_vor` + `is_cross_time`/`market_season`/`production_as_of`/`has_production_vor` as **first-class columns** (the market is CURRENT 2026, rosters/production are 2025 → cross-time by construction, never fused — the `anchor_is_prior_season` precedent; POC/architecture validation, NOT a live trade call, until the season rolls to 2026). **Purely additive** — nothing in the front end or any existing transform reads it, so the current-vs-2025 split does NOT affect app functioning. (2) **Internal-consistency gate `check_market_vor.py`** (no answer key at the 2026-offseason freeze — the `backtest_manager_features`/`check_ros_synthesis` regime): recompute-match (persisted == shipped `compute()`) / VOR algebra (waiver≤top, reproduces (value−waiver)/spread within a spread-aware rounding tol, top≈1.0) / pool integrity (= Production VOR's pools) / profile+coverage (single profile, no picks, ≥95%) / gap honesty (all cross-time flagged; `trade_gap` null iff no production row else exactly market−production). Verified live 2026 offseason: **31 snapshots → 5270 rows**, 170/171 frozen roster priced (99.4%), 248 no-production rows null (law 2), gate exit 0; Production VOR gate unaffected (0.944/0.955). No UI (data + gate). Next — front-end surfacing of the gated forward reads (Phase 4).
    - Manager Dossiers — removed the API-key gate (now an **included AI run**, not opt-in) — the §7 dossier run is cheap (~10 Haiku calls / ~$0.025 / once per season) and now ships as a standard product AI read using the app owner's key (in the gitignored `config.py`, never user-supplied). Dropped the `client.api_available()` LOCKED early-return in `write_manager_dossiers.run()` so the writer always executes; the **shared `client.api_available()` seam is untouched** and the other two AI writers (`write_team_news_dossier`, `write_ros_synthesis`) stay key-gated. Unrelated guards unchanged (run-once-per-season, zero-signal API skip). Docstring + `TECHNICAL_ARCHITECTURE.md`/`READ_BUILD_ORDER.md` reworded from "API-key-gated / key-gate clean exit". No key-storage change (key stays out of git). Docs-and-one-writer change; `check_manager_dossiers.py` gate unaffected.
    - Gridiron front-end — Foundation + Players slice (first front-end surfacing of the gated reads; 3 commits) — recreates the Claude-Design `Gridiron` handoff (`scope docs/`, `DATA_CONTRACT.md`) in the real React+Vite+DuckDB-WASM app, Web-first, new-shell-with-placeholders. (1) Gridiron design system (`styles.css` tokens — violet brand + reserved 5-color posture palette, Archivo/IBM Plex Mono) + 4-surface app chrome (`App.jsx`: brand + league switcher via new `queries.loadLeagueMeta` deriving `10-tm · PPR · 1QB · 3-1` from teams/league_settings/lineup_slots, segmented tabs with `icons.jsx` glyphs, week selector reused, `Placeholder.jsx` for League/Matchups/Teams; old League/Team panels retired from the shell). (2) Players table — `queries.loadPlayers(asOfWeek)` joins `production_vor` (PROD VOR, default sort) + `market_vor` (MKT VOR, cross-time) + `ros_synthesis` (bull/bear/situation grades, sparse) + season identity on `sleeper_player_id`; `Players.jsx` VOR-anchored sortable table + position filter + is_me badges + point-in-time `Gate`; Available/waiver DEFERRED (no FA-pool entity). (3) Player card — shared `charts.jsx` (Sparkline/TrendLine/GradeBar/RangeGauge) + `queries.loadPlayerCard()` → `PlayerCard.jsx`: Value·VOR series + BUY/HOLD/SELL lean off `trade_gap` (POC-gated cross-time), Opportunity from `player_signal`, ROS Outcome Shape from `ros_synthesis` (grades/notes/confidence, prior-season flagged); honest empty states. `db.js` registers production_vor/market_vor/ros_synthesis/league_settings (public/data symlinks added). All new data access through the `queries.js` seam. Verified live 1280px (browser preview): real players + sort/filter/is_me, full Player card (Gibbs ROS-empty; Hurts full ROS 8/6/6 + confidence + prior-season flag), no console errors. Next — Manager Dossier slice, then Teams/League/Matchups; + mobile pass + free-agent value read (unblocks Available/waivers) + roster-wide ros_synthesis batch.

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

> **✅ §4 Market VOR + Production−Market trade gap — DONE (2026-07-12).** The **primary remaining backend
> read** and the only one buildable NOW rather than blocked at the freeze. The market-value twin of
> Production VOR: the same waiver=0 ÷ pool-spread VOR (reuses the shared `position_pools` / `_pool_lines`
> / `_vor` engine — no new math, law 3) computed on the borrowed LeagueLogs `value` for the
> **format-matched** profile `redraft-1qb-12t-ppr1` (resolves the §4 open prereq flag; 10-vs-12-team is a
> documented non-issue — the waiver line comes from our own roster/available split, not the profile).
> New `data_layer` `market_vor` entity (`derived/market_vor_{season}.parquet`, **tall over the market's
> `snapshot_date` axis** — banks the un-backdatable series in derived form); `compute_market_vor.py`
> (position joined from the Sleeper registry — the feed carries only `position_rank`); the
> Production−Market **gap folded in** (`trade_gap = market_vor − production_vor`). **Time-world honesty
> (the crux):** the app is frozen at 2025 wk4 but the market is **current (2026 offseason)** and can't be
> backdated, so the gap is **cross-time by construction** — every row carries `is_cross_time` +
> `market_season` + `has_production_vor` as first-class columns, never silently fused (the
> `anchor_is_prior_season` precedent). **Purely additive** — nothing in the front end or any existing
> transform reads it, so the current-vs-2025 split does NOT affect app functioning; it's the trade layer
> banked/wired for the eventual surface. Internal-consistency gate `check_market_vor.py` (no answer key
> at the freeze — the market has no future truth to grade against here): recompute-match / VOR algebra /
> pool integrity / profile+coverage / gap honesty. Verified live: 31 snapshots → 5270 rows, 170/171
> frozen roster priced (99.4%), gate exit 0, Production VOR gate unaffected (0.944/0.955). **The gap is
> POC/architecture validation, NOT a live trade call** until the season rolls to 2026 and production is
> recomputed there (at the freeze the largest gaps are cross-time + 1QB-pool-compression artifacts —
> e.g. "sell all your QBs" is noise, exactly what `is_cross_time` warns against). **Next — front-end
> surfacing of the gated backend reads** (Phase 4).
>
> ---
>
> **✅ §2 team-news pipeline (rework) — COMPLETE (2026-07-11).** All three stages shipped:
> **A collection** (`team_news_raw`) → **B weekly AI synthesis** (`team_news_dossier`) → **C per-player
> slice by inheritance** (`player_news_slice` — each skill player inherits his own `player` claims + his
> `position_group` claims + his team's `unit`/`defense` claims; + a **thinness tripwire** `signal_tier`
> for law-2 confidence honesty; + **raw-content retention** — `news.py prune`, `RETENTION_DAYS=28`, nulls
> old `team_news_raw.content` keeping row+link+claims). Deterministic reshape, **hard** round-trip gate
> (exit 0). The §2 synthesis (QUEUED #2) now has its news input. **Scheduling handoff (now deferred with
> the host):** QUEUED #1 built the `run.py` dispatcher + resilience layer, but wiring `news.py prune` +
> the weekly `write_team_news_dossier`/`compute_player_news_slice` into the meter (launchd → GitHub
> Actions) lands with the deployment/off-laptop-host decision.
>
> ---
>
> **✅ QUEUED #1 — Daily-collector reliability — DONE (2026-07-12).** Shipped the **portable** resilience
> layer (nothing wasted by the later hosting call): **`fetchers/_http.py`** — one shared
> retry/backoff/throttle/**isolation** path; all three HTTP callers routed through it (`sleeper` behaviour-
> identical, `news`, and **`leaguelogs` gained the missing retry + per-item isolation** — the fix for the
> audit's 63%/71% coverage). **`fetchers/run.py`** — a collector REGISTRY + `run <name>` dispatcher
> (cadence declared per collector; the **meter stays external**). **`fetchers/check_collectors.py`** —
> the coverage/health gate (leaguelogs strict daily coverage, news recency, `--today` monitoring;
> reproduces the audit + flags recent gaps). See the most-recent build for the full record.
>
> **Deferred — decide WITH web hosting (NOT done here):** the **off-laptop host** that closes the ~8
> powered-off days (a host problem retry can't fix) + where the canonical parquet lives. A static web
> deploy has no compute, so a scheduled runner — **GitHub Actions the lead** — both collects *and*
> publishes the parquet, **calling the `run.py` dispatcher**: the collector host is the same decision as
> Deployment. **Interim (cheap, still open — operator action):** install the written-but-unloaded
> `com.fantasyai.news-snapshot` plist + multi-fire both launchd jobs so the laptop only needs to be awake
> once. (Also still to wire into the meter: the weekly `write_team_news_dossier` + `compute_player_news_slice`
> + daily `news.py prune`.)
>
> **✅ QUEUED #2 — §2 ROS Synthesis — DONE (2026-07-12).** The AI interpretation half of §2 (Phase 6),
> completing the §2 read. Per-player Claude call (`application/ai/write_ros_synthesis.py`, reusing
> `ai/client.py`) fusing the `ros_outcome_shape` anchor + the `player_news_slice` news + Sleeper facts
> → bull/bear/situation 1-10 grades (each with a prose note) + grounded headlines + a confidence flag,
> persisted to the structured `ros_synthesis` entity; pure editable prompt (`ai/ros_synthesis_prompt.py`)
> + no-AI `--render`/`--replay` iteration tooling; internal-consistency gate (`ai/check_ros_synthesis.py`).
> Verified live 2026 wk0 (16 players, gate exit 0). See the most-recent build for the full record. The
> shipped shape differs from the original sketch below in three PM-decided ways: **(a)** it is a
> **batch-capable CLI writer → parquet + gate** (matching how every AI read shipped), NOT the live
> lazy/cached on-demand runtime — that (and front-end wiring) is **deferred with deployment** (no server
> exists; the key is server-side; `news_content_hash` is laid down now as the future cache seam);
> **(b)** the three §2 scores are **three independent 1-10 grades** (bull/bear/situation), not a single
> roll-up, each with its own note (extractable columns); **(c)** the 2026-news × 2025-anchor mismatch is
> handled by **graceful per-input degradation + a prior-season flag** (run on whatever resolves, make
> the gaps first-class), honoring the time-world caveat below. **The original design sketch (kept as the
> design record):**
>
> The §2 AI layer was decomposed (sparred with the PM) into
> **aggregation** (the news layer — REBUILT as the 3-stage team-news pipeline, now **COMPLETE**) and
> **interpretation** (this synthesis). The quantitative skeleton
> (`compute_ros_outcome_shape.py`: bull/bear band + preseason ADP anchor + situation/security evidence)
> exists and the news layer has **landed**; the synthesis reads them. **Note:** the
> news input is the team-pipeline **player-slice** — `player_news_slice` (Stage C output — a player's
> inherited scope-tagged claims + `signal_tier`), not the retired `player_news`.
>
> **The synthesis design (decided):** a **single lazy, cached, per-player** Claude call — NOT a batch
> pre-compute of all rostered players (you'd pay for players nobody views). It fires **on demand** when a
> user opens a player, reads his inherited `player_news_slice` (scope-tagged claims + `signal_tier`) + the Sleeper factual
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
