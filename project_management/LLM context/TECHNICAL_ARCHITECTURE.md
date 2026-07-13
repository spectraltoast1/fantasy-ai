# Technical Architecture

> Engineering context document for Claude Code. Describes the stack, folder structure, data layer design, and technical principles. Updated regularly as the project evolves.

**Last reviewed:** 2026-07-13 (**Gridiron front-end — Teams cluster shipped** — the 2nd front-end slice
against the `DATA_CONTRACT` (§4.4/§4.5/§4.8): **Teams standings + Team detail + Manager Dossier.** New pure
**`src/posture.js`** = the contract §5 posture rule (`derivePosture`, `BAND=9`/`LEVEL_CUT=60`, `POSTURE_TONE`)
in ONE home, reused by the Teams chips now and the League posture MAP later. New `queries.js` reads —
`loadStandings` (record + all-play "true record" + `bracket_odds` playoff %/weekly-series + posture),
`loadTeamDetail` (4 stat blocks + `positional_depth` + roster Production/Market VOR series), `loadManagerDossier`
(the 1:1 `manager_dossiers` map). New views `Teams.jsx` / `TeamDetail.jsx` / `Dossier.jsx` + a `DepthBar`
chart mark; `db.js` registers `bracket_odds`/`positional_depth`/`manager_dossiers`. `App.jsx` gains a **detail
nav-stack** (push/pop) so multi-level drills (team → player, team → dossier) get a correct one-level "‹ Back";
tab-switch clears it. The Team-detail **this-week matchup bar is deferred** to the Matchups slice (needs
`bracket_sim`). Seam discipline intact (all data access in `queries.js`; views pure). **Prior front-end —
Foundation + Players slice shipped** — the first front-end surfacing of the gated reads. The Claude-Design
`Gridiron` handoff (`scope docs/`, its
`DATA_CONTRACT.md` mapping visual → backend entity) recreated in the real React + Vite + DuckDB-WASM app,
Web-first, new-shell-with-placeholders. New `src/`: Gridiron design system (`styles.css` tokens), a 4-surface
app shell (`App.jsx`) + `icons.jsx`/`Placeholder.jsx`, the **Players** table (`Players.jsx`) + **Player card**
(`PlayerCard.jsx`) + shared chart primitives (`charts.jsx`). New `queries.js` reads — `loadLeagueMeta`,
`loadPlayers`, `loadPlayerCard` — join `production_vor`/`market_vor`/`ros_synthesis`/`player_signal`/`season`
on `sleeper_player_id`; `db.js` registers those parquets + `league_settings`. Seam discipline intact (all
data access in `queries.js`; views pure). Rostered-only (FA/waiver deferred — no free-agent VOR entity);
`ros_synthesis` sparse; MKT/trade-gap POC-gated (cross-time). Old League/Team panels retired from the shell.
**Prior — §4 Market VOR + Production−Market trade gap shipped** — the market-value twin of Production VOR and the primary remaining backend read. Same waiver=0 ÷ pool-spread VOR (reusing `position_pools`/`_pool_lines`/`_vor`/`_roster_as_of` — no new math) on the borrowed LeagueLogs `value` (format-matched profile `redraft-1qb-12t-ppr1`); position from the Sleeper registry; new `data_layer` **`market_vor`** entity (`derived/market_vor_{season}.parquet`, tall over the market's `snapshot_date` axis), `compute_market_vor.py` + internal-consistency gate `check_market_vor.py`. The Production−Market **gap** folded in (`trade_gap`); since the app is frozen at 2025 wk4 but the LeagueLogs market is current 2026 and can't be backdated, the gap is **cross-time by construction** — `is_cross_time`/`market_season`/`has_production_vor` are first-class columns, never fused (POC/architecture validation, not a live trade call). **Purely additive — nothing reads it yet, so the current-vs-2025 split does not affect app functioning.** **Prior — §2 ROS Synthesis shipped** — the AI interpretation half of §2 (Phase 6), the project's 3rd AI-layer read: new `application/ai/` trio (`ros_synthesis_prompt.py` pure editable prompt / `write_ros_synthesis.py` per-player Haiku writer reusing `client.py`, with no-AI `--render`/`--replay` iteration modes / `check_ros_synthesis.py` internal-consistency gate) + new `data_layer` **`ros_synthesis`** entity (`derived/ros_synthesis_{season}.parquet`, replace-by-(season,week,player)). Fuses the `ros_outcome_shape` anchor + `player_news_slice` news + Sleeper facts → bull/bear/situation 1-10 grades (independent axes) each with a prose note + grounded headlines + confidence, all separable columns; graceful per-input degradation + a prior-season flag for the time-world mismatch. Front-end wiring + the on-demand runtime deferred with deployment. **Prior — Daily-collector reliability shipped**: shared **`fetchers/_http.py`** resilience layer — one path for retry/backoff/throttle/per-item isolation that all three HTTP callers (`sleeper`/`news`/`leaguelogs`) route through (leaguelogs gained the missing retry + isolation) — + **`fetchers/run.py`** collector REGISTRY/dispatcher (cadence declared, meter external) + **`fetchers/check_collectors.py`** coverage/health gate. Off-laptop host deferred to Deployment. Prior: §2 news pipeline **COMPLETE — Stage C shipped**: per-player slice by inheritance → `player_news_slice` entity + `transforms/compute_player_news_slice.py` / `check_player_news_slice.py` (a deterministic reshape — no AI — so the gate is a HARD inheritance round-trip), + **raw-content retention** (`data_layer.prune_team_news_raw_content` + `fetchers/news.py prune`, `RETENTION_DAYS=28`). The 3-stage pipeline A→B→C is now the whole news layer)

---

## Project Summary

A fantasy football analytics dashboard (v1) and AI advisor (v2+). V1 is a pure analytics dashboard - no AI component. The data layer is shared between the dashboard and the future AI advisor. All fetchers write to a common data layer that both halves read from.

Winning a redraft fantasy football championship is about more than just collecting all of the best players. It is about how you manage your specific team in your specific league. Knowing when you need to act - or not act - as a team manager is as valuable as knowing which individual players to target or avoid. This tool focuses on helping you navigate your league using real data signals: how your team is trending, where your real weaknesses are, and what your opponents look like. The goal is fewer decisions driven by anxiety or noise, and more decisions made on league-winning signal.

---

## Tech Stack

- **Language:** Python for the data layer/pipeline; JS/React in the front-end
- **Data manipulation:** polars (not pandas) - nflreadpy returns polars DataFrames; use polars syntax throughout
- **Numerical/Monte Carlo:** numpy — the one compute dependency, for vectorized simulation math only (the §5 bracket-math sim in `compute_bracket_sim.py`). **Not** for data I/O (that stays polars, through data_layer). `math.erf` (stdlib) covers the analytic normal CDF.
- **NFL stats:** nflreadpy (successor to deprecated nfl_data_py) - returns polars DataFrames
- **Front-end:** React + Vite + DuckDB (decided). Original plan was Dash + Plotly; switched after a vertical slice in the real stack validated it and proved easier to iterate than a chat artifact.
- **Data delivery (V1):** client-side DuckDB-WASM — the browser reads parquet and runs SQL; no server, static hosting only. A server/API was **deliberately deferred, not ruled out** — switch to one when warranted (multiple users, data too large to ship to the browser, or secrets to protect). The swap point is the front-end data-access layer `src/queries.js`; the view components never call data access directly, so moving "read files" → "call API" won't touch them.
- **Query layer:** DuckDB — SQL directly over parquet. Adopted as the query layer (in use now in the front-end); carries into the production app.
- **Market values:** LeagueLogs API (keyed on sleeperPlayerId; QB/RB/WR/TE only; visible attribution required). **Consumed by Market VOR (§4)** via the format-matched profile `redraft-1qb-12t-ppr1` — the market-value twin of Production VOR, on the current (2026) market
- **Scheduling:** launchd (macOS) for daily fetchers
- **Storage:** JSON (cache), parquet (snapshots), JSONL (advisor log - future)
- **HTTP:** requests library, wrapped by the shared **`fetchers/_http.py`** resilience layer (bounded timeout / exponential-backoff-with-jitter retry on transient failures / process throttle / per-item isolation) — every fetcher's network I/O routes through it (Daily-collector reliability)
- **AI layer:** `anthropic` SDK (0.97.0), model `claude-haiku-4-5` — the project's first AI-layer code (`application/ai/`, §7 Manager Dossiers Phase B). Opt-in + API-key-gated (`config.ANTHROPIC_API_KEY`); the single Anthropic call is isolated behind one function (`ai/client.generate_dossier`) so it can swap to the Batch API later without touching callers. Synchronous today (see the AI-layer note below); parquet I/O still routes through `data_layer` — the LLM call is external, like a fetcher's HTTP.

---

## Client/Server Seam — Invariants

V1 runs client-side (DuckDB-WASM in the browser, no server). Going server-side
(a Python API) one day is **expected, not hypothetical** — the goal is to keep
that switch boring. This is a bounded, ~5-item surface, not a sprawling one. Keep
these invariants true and the switch stays a localized swap rather than a rewrite:

1. **All data access lives in `src/queries.js`.** It is the single seam. Going
   server-side means rewriting the bodies of its functions ("read parquet" → "call
   API") and nothing else in the data path. This is the one that makes everything
   below cheap.
2. **View components never touch data access directly.** `App.jsx` and future
   panels call `queries.js` functions and consume plain JS values/objects — never
   SQL, never DuckDB handles, never file paths. If a view knows it's reading a
   parquet file, the seam has leaked.
3. **No DuckDB-WASM specifics outside `queries.js`/`db.js`.** SQL strings, DuckDB
   quirks, and `.parquet` awareness stay behind the seam. A server build would
   change `db.js` (how data is located/loaded) without touching views.
4. **Data addressing is config-level, not scattered.** Today: symlinks in
   `public/data/` + `db.js` registering files. A server serves these instead. Keep
   "where the data is" in `db.js`, so the answer changes in one place.
5. **Don't bake in "no auth / no secrets / whole dataset fits in the browser."**
   These are the conditions that *trigger* the server decision (multiple users,
   data too large to ship, secrets to protect) — not things to pre-engineer now.
   Just don't write code that assumes their absence is permanent.

This is a one-time checklist, not a living log: if these hold, the migration is a
swap. It is intentionally kept here (single source of truth) rather than in a
separate decisions doc.

---

## Version Roadmap
→ Source of truth: **`scope docs/PRODUCT_ROADMAP.md`** (the full phase-based path
forward). STATUS.md carries a summary + current build target. Phases are referenced
here for scope tagging only; the canonical list lives in PRODUCT_ROADMAP.

> **Doc roles** (single source of truth per fact — principle #7): **STATUS.md** =
> current state, recent build history, and immediate upcoming work. **PRODUCT_ROADMAP.md**
> = the full path forward (phases, design laws, sequencing). **TECHNICAL_ARCHITECTURE.md**
> (this doc) = under-the-hood stack, data layer, and technical principles.

## Known Scope Exclusions
**DST/K (V1):** Excluded from all V1 transforms and dashboard work. DSTs are stripped at join time via team abbreviation detection (Sleeper represents DSTs as all-uppercase team codes in matchup data). Kickers are removed by the SKILL_POSITIONS filter applied after the join. All joins and visualizations assume skill positions only: QB, RB, WR, TE.

**Waiver wire / full player pool (V1):** The Sleeper player registry is now cached via fetch_players() in sleeper.py (cache/sleeper/players.parquet, max once per 24 hours). This cache is used by the auditor at join time to resolve unknown-position players. Full player pool analysis against all available (non-rostered) players remains V2 scope.

**IR roster overages:** Managers using IR slots can carry more than the standard 17 roster spots. The join reconciliation handles this correctly — it counts whatever Sleeper reports. Expect 18-player rosters from 1–2 teams per week in-season.

**Zero-stat row context:** Rostered players who did not play (injured, suspended, inactive, not yet activated) appear in the join output with all stat columns at 0.0. No signal is provided for why they scored 0. Requires a separate Sleeper injury/status endpoint fetch to resolve. Treat 0-stat rows as "rostered, did not contribute" without assuming a specific reason.

---

## Front-end shaping — portability & latent assumptions

The heaviest analytics (trajectory + lineup leakage) now live in **Python transforms**
that pre-compute parquet (`compute_team_form.py` / `compute_team_leakage.py` → `derived/`);
`src/queries.js` is the thin seam that reads them and the lighter construction/consistency
shaping it still computes inline (depth, star dependence, lineup/hole signals, all-play,
spectrums). Panels stay pure renderers. Three classes of portability to keep straight:

**Data-driven, portable (self-correcting — needs no code change):** scoring (baked into
`sleeper_points` upstream), team count, week count, and lineup-slot config all come from
the parquets (`season`, `teams`, `lineup_slots`), not code. Week-windowed reads (EWMA
form, leakage) derive `n` dynamically and widen as weeks append; a new standard Sleeper
league means new parquets + a transform re-run, not new logic.

**Season-replay seam (`as_of_week`):** the three derived parquets are **tall** — one slice
per as-of week N. A global "As of" **week selector** lives in the App shell (`App.jsx`):
`App.jsx` owns the `asOfWeek` state and passes it to both panels, so one active week applies
across League + Team and persists across tab switches. It threads through `queries.js` via two
helpers — `asOfSlice(table, n)` parameterises the derived reads' inner `max(as_of_week)` (pick
week N's slice; `n == null` ⇒ latest, the default), and `weekCutoff(n)` adds `WHERE week ≤ N`
to the still-in-JS SQL reads (power rankings, construction, vitals, all-play — including
`SQL_CURRENT_TEAM`'s `arg_max(roster_id, week)`, the front-end half of roster-as-of-N).
`loadWeeks()` feeds the dropdown (weeks 1..latest; default = latest, travels back only). The
selector drives the readiness gate (`weeksElapsed = asOfWeek`) and replaced the temporary
`?weeksOverride` QA param. This is the one place "which week am I viewing" lives behind the seam.

**Latent assumptions (won't self-correct — silent wrong output, not an error):**
- ~~**Standard lineup shape.**~~ **RESOLVED (any-league piece 2).** `compute_team_leakage.py`'s
  swap-class split and `compute_production_vor.py`'s replacement pools now derive from the league's
  `lineup_slots` via shared `_analytics.position_pools` (superflex pools QB with the flex; standard is
  byte-identical). Gated by `backtest_roster_shape.py`. *(The remaining shape latent is **TE-premium
  lineup shape** beyond scoring — but TE-premium **scoring** is handled by the any-league scoring
  engine; a dedicated 2-TE slot config already flows through `lineup_slots` + `position_pools`.)*
- **Division playoff seeding is synthetic-gated only** (any-league piece 3). `compute_bracket_sim`
  seeds division winners ahead of wildcards when a roster→division map is present, but no real division
  league exists in the answer key, and the per-roster division map isn't persisted yet (`_division_map`
  returns None → flat seeding). Revisit against a real division league; populate the map from the
  rosters endpoint onto the teams entity when one is onboarded.
- **`MY_USERNAME` identity hardcode** (still in `queries.js`) resolves "your team" —
  replace by baking an `is_me` flag into the teams parquet at fetch time.
- **Single-season file addressing in `db.js`** — multi-season/league requires
  parameterizing the registered parquet names, now including the two `derived/` parquets
  (this is the one place to change it).

**Tuning constants → future config seed:** league-agnostic **magic numbers** kept as named
constants near the logic that uses them. The form/leakage constants moved into their
transforms (`HALF_LIFE_WK`, `DIRECTION_BAND` in `compute_team_form.py`; `MIN_GAMES`,
`COACHABLE_RATE_MARGIN`, `HABITUAL_STARTER_THRESHOLD` in `compute_team_leakage.py`;
`compute_player_signal.py` owns its own signal set — `SHRINK_K`, `MIN_GAMES`,
`SPIKE_BAND`/`STICKY_BAND`, `POS_MEAN_MIN_OPP`, `OPP_HALF_LIFE_WK`,
`DIRECTION_HALF_LIFE_WK`/`DIRECTION_BAND`); `queries.js` still holds its own `MIN_GAMES` and
the 10%/15% construction-signal thresholds for the inline depth/signals read. Candidates to
become league/user-configurable one day — document the seam, don't build the config now
(premature flexibility is its own debt). Lift to a shared config object when that seam is
built. (Note: `MIN_GAMES` is currently defined in **three** places for three independent
consumers — `compute_player_signal.py` (=3, the per-player games gate),
`compute_team_leakage.py` (=2), and `queries.js` (=2, the inline construction read) — same
name, independent values and semantics; fold into shared config when it exists.)

---

## Folder Structure

> **`application/` is a Python package** (2026-07-10 710-audit fix): every dir has an
> `__init__.py`, a root `pyproject.toml` declares it, and modules import each other by absolute
> package path (`from application.data import data_layer`,
> `from application.data.transforms._analytics import …`) — **no `sys.path` manipulation anywhere**.
> Run scripts as **`python3 -m application.<pkg>.<module>` from the repo root** (`-m` puts the cwd on
> `sys.path`, so the package resolves without an editable install; `pip install -e .` is available
> for IDE/tooling). The launchd scheduler invokes the fetcher the same way (`-m` module,
> `WorkingDirectory` = repo root).

```
fantasy-ai/
├── pyproject.toml                 # package declaration (deps ← application/requirements.txt)
├── project_management/
│   ├── TECHNICAL_ARCHITECTURE.md   (this file)
    ├── STATUS.md
    ├── PRODUCT_ROADMAP.md
    ├── PROJECT_OVERVIEW.md
│   ├── data_sources.txt
│   └── journal/
└── application/
    ├── frontend/                   # production front-end — React + Vite + DuckDB-WASM (Node). Being recreated to the Gridiron design (Web-first); new-shell-with-placeholders migration
    │   ├── src/                     #   App.jsx (Gridiron 4-surface shell: brand + league switcher, segmented tabs, week selector, detail routing via a push/pop nav-stack), Players.jsx + PlayerCard.jsx (Players surface + its detail — wired), Teams.jsx + TeamDetail.jsx + Dossier.jsx (Teams surface + team detail + manager dossier — wired), Placeholder.jsx (coming-soon slot for League/Matchups), icons.jsx (SVG glyphs), charts.jsx (Sparkline/TrendLine/GradeBar/RangeGauge/DepthBar), posture.js (the §5 posture rule — derivePosture/POSTURE_TONE), queries.js (data-access seam — loadLeagueMeta/loadPlayers/loadPlayerCard/loadStandings/loadTeamDetail/loadManagerDossier + prior team reads), db.js (DuckDB-WASM loader — registers production_vor/market_vor/ros_synthesis/bracket_odds/positional_depth/manager_dossiers + season/teams/slots/league_settings), readiness.jsx (per-panel gate), posColors.js, styles.css (Gridiron tokens). LeaguePanel.jsx/TeamPanel.jsx = retired from the shell (kept, unimported) until their data re-homes
    │   └── public/data/             #   symlinks → season_2025 + teams_2025 + lineup_slots_2025 + league_settings_2025 + team_form_2025 + team_leakage_2025 + player_signal_2025 + production_vor_2025 + market_vor_2025 + ros_synthesis_2026 parquet (gitignored)
    ├── data/
        ├── data_layer.py           # ✅ built — centralized read/write module
    │   ├── fetchers/               # one Python script per source (tracked in git)
    │   │   ├── _http.py            # ✅ built — SHARED HTTP resilience layer (Daily-collector reliability): get/get_json (timeout + exponential-backoff-with-jitter retry on transient failures/5xx; a 4xx raises immediately) + set_throttle (process min-gap) + isolate (per-item catch/log/continue). ALL fetcher network I/O routes through it
    │   │   ├── nfl_stats.py        # ✅ built (uses nflreadpy, not _http)
    │   │   ├── sleeper.py          # ✅ built — on-demand Sleeper API; _get_json wraps _http (set_throttle re-exported for the manager-activity fan-out)
    │   │   ├── leaguelogs.py       # ✅ built — daily market-value snapshots; _get → _http.get_json (ADDS retry) + snapshot() per-item isolation (ADDED — the reliability fix)
    │   │   ├── news.py             # ✅ built — daily TEAM-news RSS collector (§2 pipeline Stage A): 3 native sources/team → team_news_raw; _get_feed → _http.get, snapshot() → _http.isolate; also `prune` (Stage C retention: null content older than RETENTION_DAYS=28, keep row+link+claims) + the retained resolver (build_index/resolve_players, imported by Stages B/C)
    │   │   ├── run.py              # ✅ built — collector REGISTRY (leaguelogs + news = banked daily series; NOT sleeper = on-demand) + `run <name>|--all|--list` dispatcher; cadence declared per collector, the meter (launchd → GitHub Actions) calls this. Post-run freshness check
    │   │   ├── check_collectors.py # ✅ built — coverage/health gate (network-free): leaguelogs STRICT daily coverage, news RECENCY, --today monitoring; hard-gates a recent window so permanent powered-off gaps don't fail forever
    │   │   └── scheduler/          #   tracked launchd plists + README for the daily snapshot jobs
    │   │       ├── com.fantasyai.leaguelogs-snapshot.plist
    │   │       ├── com.fantasyai.news-snapshot.plist
    │   │       └── README.md
    │   ├── cache/                  # current state (gitignored)
    │   │   ├── player_id_map.parquet  # gsis_id → sleeperPlayerId mapping
    │   │   └── sleeper/
    │   │       └── players.parquet    # Sleeper /players/nfl registry, refreshed ≤ once/day — 10 cols incl. injury_status/depth_chart_order/practice_participation (Phase 1 refinement)
    │   └── snapshots/              # time-series parquet (gitignored)
            ├── derived/                                 # pre-computed analytics (compute_*.py output); team/player analytics + production_vor + true_rank + positional_depth are tall, grain (season, as_of_week, entity); projection_consensus is per (season, week, player)
            │   ├── team_form_2025.parquet               # per (as_of_week, team) trajectory: slope, direction, spectrum, weekly series
            │   ├── team_leakage_2025.parquet            # per (as_of_week, team) leakage: efficiency %, coachable/variance, named fixes
            │   ├── player_signal_2025.parquet           # per (as_of_week, team, player) spike signal: opp vs efficiency split, regression_risk, read
            │   ├── projection_consensus_2025.parquet    # per (week, player) forward prior: borrowed center + p25/p50/p75 spread band (width = residual std, skew = residual skewness, both shrunk to positional prior — §3's 3 components); disagreement_ppr null till a 2nd source
            │   ├── production_vor_2025.parquet          # per (as_of_week, roster, player) §4 read: ROS value (borrowed centers summed over remaining weeks) over the waiver line, normalized by pool spread; QB pool + pooled flex line
            │   ├── market_vor_{season}.parquet          # per (snapshot_date, roster, player) §4 read: the MARKET-value twin of production_vor — same waiver=0 ÷ pool-spread VOR on the borrowed LeagueLogs `value` (format-matched profile redraft-1qb-12t-ppr1), reusing the same position_pools/_pool_lines/_vor engine (no new math). Position joined from the Sleeper registry (feed carries only position_rank). Tall over the market's `snapshot_date` axis (banks the un-backdatable series). Production−Market GAP folded in: trade_gap = market_vor − production_vor + is_cross_time/market_season/production_as_of/has_production_vor first-class cols. TIME-WORLD: rosters frozen-2025 but market current-2026 → gap cross-time by construction, never fused (the ros_synthesis anchor_is_prior_season precedent); POC/architecture validation, not a live trade call until the season rolls to 2026. Written by compute_market_vor.py; gated by check_market_vor.py (internal-consistency — no answer key at the freeze)
            │   ├── true_rank_2025.parquet               # per (as_of_week, team) §5-half read: optimal-lineup ROS strength (production_vor re-aggregated over lineup slots) → record-independent rank + spectrum_pos + bench_value
            │   ├── positional_depth_2025.parquet        # per (as_of_week, team, position) §6 read: production_vor re-sliced per position net of starting need → starter/surplus value, marginal_vor (gap), spectrum_pos vs league, surplus/adequate/gap shape
            │   ├── bracket_odds_2025.parquet            # per (as_of_week, team) §5 bracket-math: Monte Carlo playoff odds from team weekly score dists (μ optimal-lineup projection, σ from §3 band) over the real remaining schedule → playoff_odds, proj_wins/seed, magic_wins
            │   ├── ros_outcome_shape_2025.parquet      # per (as_of_week, roster, player) §2 read: bull/bear rest-of-season range = borrowed ros_value centre ± BULL_Z·√Σband², then blended toward the preseason ADP anchor (adp_points_curve floor/ceiling, weight w_N = ANCHOR_W·remaining/total, horizon-decaying) + ros_cv fragility + situation/security (player_signal trust axis) + adp/anchor evidence cols; the ROS-horizon analog of the §3 weekly band
            │   ├── adp_points_curve.parquet            # season-agnostic §2 anchor curve: per (position, pos_ecr_rank) the historical realized-points floor/center/ceiling (P10/P50/P90, rolling-window + isotonic non-increasing), fit by compute_adp_points_curve.py over prior seasons (target held out); consumed by compute_ros_outcome_shape
            │   ├── manager_features_2025.parquet       # per manager (owner_id) §7 read (Phase A): cross-league behavioral profile — FAAB aggression/budget-spent, waiver/FA mix, waiver success rate, churn, trade freq, positional lean of adds + signal-depth counts (n_leagues/n_seasons/n_transactions) + depth_tier + is_primary; rate/lean features null when undefined. The credit-free AI input for the Phase-B Haiku dossier writer
            │   ├── manager_dossiers_2025.parquet       # per manager (owner_id) §7 read (Phase B): the AI-written qualitative dossier — the FIRST AI-written entity. Fixed 7-key schema (headline/waiver_faab/trade_tendency/positional_lean/roster_construction/edge_or_blindspot/confidence_note) + is_primary + signal-depth echo + provenance (model/generated_at/is_zero_signal). Written by application/ai/write_manager_dossiers.py from manager_features via Claude Haiku (never raw logs); zero-signal managers get a hardcoded "no intel" row (AI skipped)
            │   └── ros_synthesis_{season}.parquet      # per (season, week, player) §2 AI interpretation read: fuses ros_outcome_shape (anchor) + player_news_slice (news) + Sleeper facts → bull/bear/situation 1-10 grades (INDEPENDENT axes) each with a prose note + headlines (List(Struct{text, source_article_ids}), grounded in the slice) + confidence/confidence_note; availability flags (has_ros_anchor/has_news/signal_tier/n_news_claims) + anchor carries + anchor_is_prior_season + news_content_hash (future cache seam) + is_zero_signal/model/generated_at — every field its own column. Keyed by the NEWS (season,week); replace-by-(season,week,player). Written by application/ai/write_ros_synthesis.py via Claude Haiku; no-anchor+no-news → hardcoded row (AI skipped)
            ├── leaguelogs/
            │   └── market_values.parquet            # daily market-value history, all profiles
            ├── news/
            │   ├── team_news_raw.parquet           # §2 pipeline Stage A: per-team article store — 3 native sources/team (SB Nation + FanSided + official); grain = one row per article; STORES feed-provided content (extraction input; no scraping); append-only-of-new by article_id. RETENTION (Stage C): `content` older than RETENTION_DAYS (28) is nulled by `news.py prune` — the row + article_id/title/url/published_at + the derived claims survive
            │   ├── team_news_dossier.parquet       # §2 pipeline Stage B: weekly per-team AI news sheet — grain = one scope-tagged claim per (season,week,team); situation/security-focused, attributed (basis official/reported/opinion), skill-only + one condensed defense note; written by application/ai/write_team_news_dossier.py via Haiku; replace-by-(season,week,team)
            │   ├── player_news_slice.parquet       # §2 pipeline Stage C: per-player inheritance view of the dossier — grain = one inherited-claim row per (season,week,player,claim); each on-team skill player (whole NFL pool) inherits his own player claims + his position_group claims (his position + team-wide offensive context) + his team's unit (offense/defense) claims; + thinness tripwire (signal_tier rich/thin/none + counts); honest-zero is_empty row for a player who inherits nothing. Deterministic reshape (transforms/compute_player_news_slice.py); replace-by-(season,week). The §2-synthesis (QUEUED #2) input
            │   └── player_news.parquet              # LEGACY (v1 national player-news collector, superseded by team_news_raw)
            ├── projections/
            │   └── projections_2025.parquet         # multi-source forward prior (Sleeper now, FantasyPros in-season); `source` a column; snapshot/append, grain (season, week, source, player)
            └── nfl_sleeper_weekly_joined/
                ├── season_2025.parquet                  # join output, all weeks appended (one file per season)
                └── 2025/
                    └── remainders_2025_w{week}.parquet      # unresolved players; empty = clean join
    │       └── nflreadpy/
    │           ├── nfl_stats_2025.parquet  # per player-week, weeks 1-18. Carries the ff_opportunity `*_exp` expected-points components (the §1 Quality basis, re-scored at the consumption layer) + redzone_touches (PBP companion). `xtd` (the old TD-proxy) retired. 2020–2024 also backfilled (realized-points source for the §2 ADP curve)
    │           └── adp_preseason.parquet   # historical preseason ADP (FantasyPros via load_ff_rankings): one tall file, season a column; per (season, player) ecr/best/worst/sd + pos_ecr_rank, latest full-board pre-kickoff redraft-overall snapshot/season, id-bridged fantasypros_id→sleeper. The §2 preseason-anchor source (fetchers/adp.py)
            └── sleeper/
                └── 2025/
                    ├── teams_2025.parquet            # roster_id → team/owner names
                    ├── roster_positions_2025.parquet # raw league starting-lineup slot list
                    ├── lineup_slots_2025.parquet     # derived starting skill-slot requirements (optimal-lineup config)
                    ├── league_settings_2025.parquet  # real Sleeper scoring_settings + playoff config (tall section/key/value) — drives the scoring dispatcher + bracket-sim playoff cut
                    ├── manager_activity_2025.parquet # §7 (Phase A) FIRST cross-league / user-keyed entity: per manager (owner_id), their transactions across their *comparable* other leagues; source_league_id/source_season as columns; "league" marker + "txn" row kinds; incremental replace-by-owner_id
                    └── ... # matchup and transaction parquet files for each week of the 2025 season
    ├── shared/                     # league detection, config loaders
    ├── transforms/ # one Python script per join/transform
        ├── _analytics.py              # shared pure helpers (round1, mean, median, quantile, stdev, skewness, pearson, spectrum_positions, expand_slots/optimal_lineup — the slot-aware greedy lineup engine; position_pools — swap/replacement pools from lineup_slots, shared by VOR + leakage for superflex/any-shape generalization)
        ├── _scoring.py                # scoring dispatcher + custom-scoring recompute engine — scoring_profile (ppr/half/std/custom); standard selects canned columns, custom recomputes via recompute_custom_points(scoring, side) as a delta on the std canned baseline (built; supports PPR variants / non-std TD-yardage / TE-premium reception bonuses; raises on first-down/threshold bonuses). Also **expected_points_expr(scoring)** — the §1 Quality engine: a from-scratch weighted sum of the ff_opportunity `*_exp` component expectations under league scoring (exact — every component exposed; reproduces ffverse's total under PPR to ±0.02; scores first-down leagues too)
        ├── _manager.py                # §7 shared pure helpers (no I/O, no polars) — comparability: classify_league (reuses _scoring.scoring_profile), is_comparable (scoring/size/QB-structure/format), select_comparables (≤5, prior-season biased); attribution: manager_in_transaction, manager_moves; feature math: manager_features (FAAB/waiver/trade/churn/positional-lean + signal-depth, null when undefined). Shared by the sleeper.py fetch mode + the transform + the backtest (one source of truth)
        ├── join_nfl_sleeper_weekly.py # ✅ built
        ├── audit_join.py              # ✅ built — resolves unknown-position remainders
        ├── derive_lineup_slots.py     # ✅ built — roster_positions → lineup_slots (starting skill slots)
        ├── compute_team_form.py       # ✅ built — EWMA trajectory analytics → derived/team_form
        ├── compute_team_leakage.py    # ✅ built — lineup-leakage analytics → derived/team_leakage
        ├── compute_player_signal.py   # ✅ built — spike signal-quality read (Phase 1) → derived/player_signal
        ├── backtest_player_signal.py  # ✅ built — validates the shipped signal vs naive baseline on the full-2025 answer key
        ├── compute_projection_consensus.py  # ✅ built — projection consensus + spread band, all 3 §3 components incl. archetype skew (Phase 2) → derived/projection_consensus
        ├── backtest_projection_consensus.py # ✅ built — calibration gate: 25–75 band coverage ~50% AND both tails ~25% on the full-2025 answer key
        ├── compute_production_vor.py        # ✅ built — Production VOR §4 (first substrate-consuming read) → derived/production_vor
        ├── backtest_production_vor.py        # ✅ built — VOR gate: projected ROS tracks actual (corr ~0.95), VOR tiers monotonic on the 2025 answer key
        ├── compute_market_vor.py            # ✅ built — Market VOR §4 (the market-value twin of Production VOR): same waiver=0 ÷ pool-spread VOR on the borrowed LeagueLogs value (profile redraft-1qb-12t-ppr1), reusing position_pools/_pool_lines/_vor/_roster_as_of (no new math); position from the Sleeper registry; tall over snapshot_date; the Production−Market trade_gap folded in with is_cross_time honesty cols → derived/market_vor
        ├── check_market_vor.py              # ✅ built — Market VOR gate (INTERNAL-CONSISTENCY, not answer-key — no future truth at the 2026-offseason freeze): recompute-match (persisted == shipped compute()) / VOR algebra (waiver≤top, reproduces (value−waiver)/spread, top≈1.0) / pool integrity (= Production VOR's pools) / profile+coverage (≥95%) / gap honesty (cross-time flagged; trade_gap null iff no production row else market−production) (exit 0)
        ├── compute_true_rank.py             # ✅ built — True Rank §5-half (first league-level read): production_vor re-aggregated over optimal lineup → record-independent roster-strength rank → derived/true_rank
        ├── backtest_true_rank.py            # ✅ built — True Rank gate: projected strength tracks actual ROS ceiling (Pearson 0.802 / Spearman 0.842, n=10) on the 2025 answer key
        ├── compute_positional_depth.py      # ✅ built — Positional Depth §6 (last Phase-3 read): production_vor re-sliced per position net of starting need → surplus/gap vs league → derived/positional_depth
        ├── backtest_positional_depth.py     # ✅ built — Positional Depth gate: per-position projected starter_value tracks actual ROS ceiling (mean corr 0.861, n=10/pos) on the 2025 answer key
        ├── compute_bracket_sim.py           # ✅ built — §5 bracket-math Monte Carlo (Posture, Phase 4): team weekly score dists → analytic win prob → 10k-sim season over the real schedule → playoff odds → derived/bracket_odds
        ├── backtest_bracket_sim.py          # ✅ built — Bracket Odds gate (config-light): win-prob Brier 0.224 beats coin-flip + expected-wins Spearman 0.756 vs actual + determinism (two runs frame-equal) + Σ-odds invariant + synthetic 2-division seeding correctness (exit 0)
        ├── backtest_scoring_recompute.py    # ✅ built — custom-scoring recompute gate (reconciliation): custom path == canned columns on standard inputs + exact custom deltas + rejects unscoreable keys + end-to-end custom consensus (exit 0)
        ├── backtest_roster_shape.py         # ✅ built — roster-shape (superflex) gate: no-regression frame-equal on vor/leakage/true_rank/positional_depth (standard league) + synthetic superflex correctness via position_pools (exit 0)
        ├── compute_adp_points_curve.py      # ✅ built — §2 preseason-anchor curve: per (position, pos_ecr_rank) historical realized-points floor/center/ceiling (P10/P50/P90, rolling ±3-rank window, isotonic non-increasing) over prior seasons (target held out = leak-free) → derived/adp_points_curve. Realized points read from nfl_stats (no transform hits nflreadpy)
        ├── compute_ros_outcome_shape.py     # ✅ built — ROS Outcome Shape §2 (quantitative skeleton, completes the player-read backend): bull/bear = borrowed ros_value ± BULL_Z·√Σband², blended toward the preseason ADP anchor (adp_points_curve, weight w_N=ANCHOR_W·remaining/total) + situation/security from the player_signal trust axis → derived/ros_outcome_shape
        ├── backtest_ros_outcome_shape.py    # ✅ built — ROS Outcome Shape gate (exercises the shipped anchored path): freeze-wk bull/bear coverage 0.817 (target 0.80; joint BULL_Z×ANCHOR_W sweep → (1.44, 0.25), objective |cov−tgt|+|tail imbalance|) + monotonic realised ROS by bull tercile on the 2025 answer key (exit 0); anchor lifts coverage 0.744→0.817 + balances tails vs pre-anchor
        ├── compute_manager_features.py      # ✅ built — Manager Dossiers §7 Phase A: cross-league behavioral features per manager (owner_id) from manager_activity → derived/manager_features. Pure manager_features (injected constants); every league manager gets a row incl. zero-signal (null features)
        ├── backtest_manager_features.py     # ✅ built — Manager features gate (internal consistency — behaviour has no answer key): comparability invariant (0 leaked, grounded on persisted target facts) + accounting round-trip (independent re-aggregation; fractions ∈[0,1]; shares sum 1) + signal-depth honesty (all profiled; zero-signal → null) (exit 0)
        ├── compute_player_news_slice.py     # ✅ built — §2 news pipeline Stage C: per-player inheritance slice of team_news_dossier → news/player_news_slice (a deterministic reshape, no AI). Each on-team skill player inherits own player claims + position_group (his position + team-wide offensive context) + team unit (offense/defense) claims; + thinness tripwire signal_tier + counts; honest-zero is_empty row when nothing inherited. position_group_positions() is the shared subject→position mapper
        └── check_player_news_slice.py       # ✅ built — §2 Stage C gate (HARD — Stage C is deterministic): independently recomputes each player's expected inherited claim set from the dossier+registry and demands an exact multiset match incl. inheritance tag + provenance; + coverage / identity / thinness honesty / zero-signal / retention safety (cited ids survive) (exit 0)
    ├── ai/                         # the AI layer — distinct from the deterministic polars transforms. Parquet I/O still via data_layer; the Anthropic call is external (like a fetcher's HTTP). Three reads now: §7 Manager Dossiers (Phase B) + §2 Team News Dossier (news pipeline Stage B) + §2 ROS Synthesis (the interpretation half of §2)
        ├── client.py                  # ✅ built — the isolation seam: api_available() key gate (locked on absent/placeholder/non-sk-ant) + the ONE synchronous call point _raw_call (Haiku 4.5, no thinking/effort; THE swap point for a Batch path); generate_dossier() parses a JSON object, generate_claims() parses a JSON ARRAY (Stage B) — both tolerant json.loads NOT messages.parse
        ├── dossier_prompt.py          # ✅ built — §7 pure prompt construction: system_prompt (fixed 7-key JSON schema + tendencies-not-verdicts guardrails) + user_prompt (blindspot framing for is_primary / exploitable-edge for opponents) + zero_signal_dossier (hardcoded "no intel")
        ├── write_manager_dossiers.py  # ✅ built — §7 writer (compute/run/--season/--force): an included AI run (ungated); per manager, zero comparable leagues ⇒ hardcoded (no API) else prompt→generate→validate schema; synchronous sequential; run-once-per-season guard → derived/manager_dossiers
        ├── check_manager_dossiers.py  # ✅ built — §7 dossiers gate (internal consistency, no API, reads persisted only): coverage + schema completeness + depth-echo-matches-features + zero-signal honesty (exit 0)
        ├── news_prompt.py             # ✅ built — §2 Stage B pure prompt: system_prompt (situation/security claim schema — scope/subject/claim_type/basis/note/direction[+mixed]/salience/source_article_ids; cluster-across-sources; ATTRIBUTE-don't-assert per basis; skill-only + one condensed defense note) + user_prompt (windowed article list). Controlled vocabularies (SCOPES/CLAIM_TYPES/DIRECTIONS/SALIENCES/BASES) the writer + gate validate against
        ├── write_team_news_dossier.py # ✅ built — §2 Stage B writer (run/--season/--week/--team/--force): per team, windows team_news_raw (WINDOW_DAYS=14, cap 60) → one Haiku generate_claims call → validate enums + ground cited ids + resolve player subjects via a TEAM-restricted resolver index (on-team ids only; off-team → null, law 2) → team_news_dossier; run-once-per-week guard; replace-by-(season,week,team); key-gate clean exit
        ├── check_team_news_dossier.py # ✅ built — §2 Stage B gate (internal consistency, no API): consistency (no empty+claims mix) + schema/enum + grounding (cited ids exist AND on-team; provenance matches) + player resolution (ids only on player claims, each an on-team skill player) + zero-signal honesty (exit 0)
        ├── ros_synthesis_prompt.py    # ✅ built — §2 ROS Synthesis pure prompt (the editable text lives here): system_prompt (three 1-10 grades bull/bear/situation as INDEPENDENT axes — bull hard-anchored to a caliber bucket, full range; PROSE RULES banning internal substrata from the notes; confidence honesty) + user_prompt(ctx) (renders anchor + Sleeper facts + inherited news claims; translates the internal security/direction labels to plain language) + SYNTHESIS_KEYS + zero_signal_synthesis
        ├── write_ros_synthesis.py     # ✅ built — §2 ROS Synthesis writer: assemble_player gathers ros_outcome_shape (by id, --anchor-season) + player_news_slice + Sleeper facts → one client.generate_dossier Haiku call → _validate (grades 1-10, notes, headline ids ⊆ slice, confidence vocab) → row. Modes: run (write, run-once superset guard by (season,week,player), --force), --preview, and the NO-AI --render (print the exact assembled prompt) / --replay REPLY.json (canned reply through validation) — both need no key/no cost. Graceful degradation: no-anchor/no-news → hardcoded row, API skipped. Keyed by the NEWS (season,week); anchor flagged PRIOR-SEASON when --anchor-season differs
        └── check_ros_synthesis.py     # ✅ built — §2 ROS Synthesis gate (internal consistency, no API): coverage + schema (grades in range w/ notes; nulls only on zero rows) + grounding (headline ids trace to player_news_slice) + confidence honesty (thin/no-anchor ⇒ not 'high'; zero rows clean fallbacks) + data-flag honesty (has_ros_anchor/has_news/n_news_claims match inputs) + soft prose-leak scan (exit 0)
    ├── config.example.py
    └── requirements.txt
```

---

## Data Layer

### Concept

Two storage patterns:

- **cache/** - current state only. Overwritten on every refresh. Use for data where only "right now" matters (roster state, injury status, current odds, current projections).
- **snapshots/** - time-series, append-only. Each refresh adds a new record without overwriting prior ones. Use for data where trend history matters (weekly stats, market values over time).

## I/O Architecture

All reads from and writes to the data layer (cache/, snapshots/) 
must go through application/data/data_layer.py. This is a 
non-negotiable architectural rule.

**What this means in practice:**
- Transform scripts import data_layer and call its functions — 
  they do not construct file paths or call polars read/write directly
- Dashboard components read via data_layer functions only
- Fetchers write through data_layer too — they build the DataFrame from the source
  API, then persist it via a data_layer writer (e.g. write_nfl_stats,
  write_sleeper_matchups, write_sleeper_players, write_player_id_map,
  write_projections); they do not
  construct snapshot/cache paths or call polars write directly
- Any new data entity requires a read and write function added 
  to data_layer.py before the consuming script is written

**data_layer.py organization:**
- Organized by data entity with a comment header per section
- Read and write functions for the same entity live together
- Section header naming matches the corresponding transform 
  script name (e.g. # --- Join: NFL + Sleeper Weekly ---)

**What never belongs in a transform, dashboard, or fetcher script:**
- pathlib.Path construction pointing at snapshots/ or cache/
- pl.read_parquet() or df.write_parquet() called directly
- Hardcoded file path strings

**One documented exception — raw JSON cache dumps.** `sleeper.py`'s `refresh()` writes the
league / users / rosters / bracket JSON responses straight to `cache/` through its own
`_write_json` helper. These are current-state API captures (overwritten each run), not
analytics entities, and data_layer has no JSON support — so they stay in the fetcher for
now. Everything in **parquet** goes through data_layer.

### Current source assignments

| Source | Storage | Rationale |
|---|---|---|
- external
| Sleeper | cache/ + snapshots/ | Matchup/roster/transaction state **and weekly projections** (the forward prior — `source="sleeper"` in the shared `projections` entity, from the `api.sleeper.com` stats host) to snapshots/; player registry to cache/ (current state only, refreshed ≤ once/day) |
| nflreadpy | snapshots/ only | Weekly player stats - trend visualization requires history. Also: the **§1 Quality basis** (`load_ff_opportunity` → the `*_exp` expected-points components joined onto nfl_stats); the **preseason ADP** source (`load_ff_rankings` → `adp_preseason` entity) feeding the §2 ROS anchor; and the realized-points basis for its curve (`load_player_stats`, 2020–2024 backfilled) |
| LeagueLogs | snapshots/ only | Daily market-value snapshot of all profiles (redraft + dynasty). API serves only "now" (no history endpoint), so the value time-series exists only if we snapshot it. Keyed on sleeperPlayerId. |
| Odds API | cache/ only | Current week lines only needed for v1 |
| FantasyPros | snapshots/ (`projections` entity) | Weekly projected points (PPR/half/std). Routes through the shared **multi-source `projections` entity** (`source="fantasypros"`), snapshotted like Sleeper — **supersedes the earlier "cache/ only" note.** Added in-season; key in config. |
| NFL team news (RSS) | snapshots/ only (`team_news_raw`) | Public **native** RSS, **3 sources per team** (SB Nation + FanSided + official team site; 96 feeds), via `fetchers/news.py` + `feedparser`. Live now-stream, snapshotted forward (bank it or lose it, like leaguelogs). No API key. Stores feed-provided article **content** (the extraction input; no scraping). Stage A of the §2 team-news pipeline (weekly AI extraction + per-player slice downstream). Supersedes the v1 national `player_news`. |

- internal
| nfl_sleeper_weekly_joined transform | snapshots/nfl_sleeper_weekly_joined/ | Joined output — one file per season (season_{season}.parquet), each week appended with a (season, week) dedup guard
| derive_lineup_slots transform | snapshots/sleeper/{season}/ | lineup_slots_{season}.parquet — starting skill-slot requirements (slot, count, eligible) derived from the league's raw roster_positions; declares the QB/RB/WR/TE + FLEX config so the front-end "perfect lineup" / efficiency calc is exact, not inferred |
| compute_team_form transform | snapshots/derived/ | team_form_{season}.parquet — **tall, grain (as_of_week, roster_id)** (Season-replay): per as-of week N=1..maxweek, one row per roster_id with the EWMA scoring slope, direction, recent record, league-relative spectrum pos, per-week series — all recomputed on weeks ≤ N. Pre-computed so the front-end seam just reads it (no JS trajectory math) |
| compute_team_leakage transform | snapshots/derived/ | team_leakage_{season}.parquet — **tall, grain (as_of_week, roster_id)**: per as-of week N, lineup efficiency %, season points-left, coachable/variance split, named fixes, per-week leak, spectrum pos — cumulative ledger over weeks ≤ N. Roster-as-of-N: a player's "current team" resolves to his latest week ≤ N. Feeds both the Team Overview leakage lens and the League drawer's efficiency read |
| compute_player_signal transform | snapshots/derived/ | player_signal_{season}.parquet — **tall, grain (as_of_week, roster_id, player)**: per as-of week N, one row per rostered skill player with the spike signal-quality read (Phase 1), recomputed on weeks ≤ N (roster-as-of-N applies). Decomposes recent production into sticky opportunity (opp_g, EWMA-windowed via injected half-life — ships cumulative, backtest-tuned) vs fragile efficiency (ppo, shrunk toward the league positional mean); headline regression_risk + a sample-gated read (too_early/spike/mixed/sticky), td_share as evidence, per-week series. The first decision-critique engine slice; not a forward projection. **Phase 1 refinement + §1 Quality axis (710 #3, 2026-07-10):** added fields close the DECISION_READS.md §1 gap, kept separate from the validated core read (not fused) — **quality_rate = expected fantasy points per opportunity** (`exp_pts_g/opp_g`) from ffverse's ff_opportunity component model re-scored under league settings (`_scoring.expected_points_expr`), the full multi-component EV read §1 specifies (was the TD-only `xtd` proxy); **point_correlation** = pearson(weekly actual, weekly expected full points); **luck** = recent − expected ppg (over/under-performance residual); plus direction/reliability (Trust axis) + security (Sleeper injury/depth-chart). The core forecast (regression_risk) still shrinks efficiency toward the positional mean — the exp_ppo shrink target was tested and rejected by the answer key (see backtest) |
| compute_projection_consensus transform | snapshots/derived/ | projection_consensus_{season}.parquet — **per (season, week, player)** over the whole skill pool. **NOT tall over as_of_week** (unlike the three above): a projection for week W is a fixed forward statement whose band uses only weeks < W, so it's keyed on `week` like the projections entity it reads — read via `read_projection_consensus(season, week=None)`. Borrowed consensus center (median `proj_pts_ppr` across sources) + a p25/p50/p75 spread band — **all three §3 components**: center (borrowed), **width** = the player's residual std (actual − proj) shrunk toward a full-pool positional prior (`SHRINK_K`), and **archetype skew** = a Cornish-Fisher quantile shift `SKEW_GAIN·(g/6)·(BAND_Z²−1)` on p25/p75 from the player's residual *skewness* `g` shrunk to a positional prior (`SKEW_SHRINK_K`); p50 stays the borrowed center, floored at 0. **Skew driver resolved by the answer key, not §3's literal wording:** the projection's TD-dependence archetype does *not* track residual skew (measured 2026-07-09); the player's own residual 3rd moment does — the exact parallel to the width's 2nd moment. Because `BAND_Z<1`, a right-skewed residual shifts both breakpoints *down* (the borrowed center sits above the realized median), giving a slightly longer *lower* gap — reversing §3's right-skew illustration (pre-data intuition about raw scores). `disagreement_ppr` (cross-source std) is null under a single source. The Phase-2 forward prior / law-2 confidence band (DECISION_READS §3), calibration-gated by backtest_projection_consensus.py — **per-tail** (25–75 coverage ~0.50 AND below-p25/above-p75 ~0.25 each); `BAND_Z × SKEW_GAIN` swept jointly → (0.55, 1.5) on the 2025 answer key. **Coverage nuance:** a null `proj_pts_ppr` (Sleeper doesn't project a player who's OUT/inactive — components are null too) means no band and no residual for that player-week, by design — so the pool is projected-and-playing players, not every roster spot. Consumed by Production VOR (below) and later ROS reads; the front end reads the current week's slice and filters to rostered players |
| compute_true_rank transform | snapshots/derived/ | true_rank_{season}.parquet — **tall, grain (as_of_week, roster_id)**: per as-of week N, one row per team with the DECISION_READS §5 (first half) True Rank read. **roster_strength** = the sum of each team's **optimal-lineup** ros_value — fill the declared starting slots (QB/RB/WR/TE + FLEX) from the roster by ros_value, most-constrained slot first, sum the optimal starters. **Record-independent** (reads no wins/standings): it measures how good the roster *is*. **No new engine** — it re-aggregates `production_vor` over the lineup rules (`read_production_vor(season, as_of_week="all")`), reusing the shared `_analytics.expand_slots`/`optimal_lineup` (the slot-aware greedy lifted out of compute_team_leakage). Also carries **bench_value** (rostered ros_value not in the optimal lineup — a §6 depth/trade-capital hint, evidence not folded into the rank), a within-cohort dense **rank** (1 = strongest), and a league-relative 0–1 **spectrum_pos**. Roster-as-of-N is inherited free from the VOR slice (already resolved there). **Slot-aware, not a roster-sum:** a roster hoarding two elite QBs ranks by its one *startable* QB (the 2nd rides the bench), so True Rank rewards a balanced startable lineup over capped-position hoarding. Calibration-gated by backtest_true_rank.py (projected strength tracks the actual ROS ceiling — management-independent optimal lineup on realized points — at Pearson 0.802 / Spearman 0.842, freeze wk4, n=10 teams; exit 0). The **integration precursor** the Phase-4 bracket-math Monte Carlo (§5 full) sits on; **value, not WAR** — roster_strength is in ROS-projected-points units, the rank is ordinal roster quality, no wins conversion here |
| compute_positional_depth transform | snapshots/derived/ | positional_depth_{season}.parquet — **tall, grain (as_of_week, roster_id, position)** (position = **fine** QB/RB/WR/TE, not VOR's QB/FLEX pool): per as-of week N, one row per team per position with the DECISION_READS §6 read. **No new engine** — it re-slices `production_vor` (`read_production_vor(season, as_of_week="all")`) per position, **net of the position's dedicated starting requirement**. `starter_need` from `lineup_slots` (`_starter_needs`: QB1/RB2/WR2/TE1; the shared FLEX×2 is *excluded*, so flex-worthy depth surfaces as **surplus** — which is what makes it trade capital). Fields: **starter_value** (top-`starter_need` ros_value), **surplus_value** + **surplus_startable** (beyond-need players clearing the waiver line, vor>0 = real depth), **marginal_vor** (the last dedicated starter's VOR — the **gap indicator**, ≤0 = starting replacement level; null when the roster can't fill the slots), **spectrum_pos** (league-relative 0–1 of starter_value **within that position's cohort** — the spec's "vs league" benchmark), and an **advisory** `shape` ∈ {surplus, adequate, gap} off marginal_vor + spectrum_pos (evidence-first: numbers lead, the manager adjudicates — per the advisory-framing principle). **One row per (team, position) even at zero roster count**, so a body-count gap isn't invisible in a rostered-only frame. Roster-as-of-N inherited from the VOR slice. The re-slice is **lossless** (per-position rostered_value sums to the team's total VOR ros_value). Calibration-gated by backtest_positional_depth.py (per position, projected starter_value tracks the actual ROS ceiling — top-need by realized points — mean corr 0.861 across QB/RB/WR/TE, freeze wk4 n=10/pos; exit 0). Decision homes: trade shape + waiver/FAAB. Closes the Phase-3 read set |
| compute_bracket_sim transform | snapshots/derived/ | bracket_odds_{season}.parquet — **tall, grain (as_of_week, roster_id)**: per as-of week N, one row per team with the DECISION_READS §5 **bracket-math** read (the second half of Posture; True Rank is the first). A **Monte Carlo season simulation**: each team's weekly score distribution — mean μ from the optimal-lineup borrowed projection (`projection_consensus.center_ppr`), std σ from the §3 band (`band_ppr`) — drives analytic per-matchup win probabilities Φ((μA−μB)/√(σA²+σB²)); `SIMS`=10k runs draw weekly scores ~N(μ,σ²), pair by the **real remaining schedule** (matchup_id from the all-18-weeks matchup snapshots, read via `read_season_matchups`), accumulate onto the actual as-of-N standings, and seed the top-`PLAYOFF_TEAMS` (`_seed_table` — **division-aware**: division winners seeded ahead of wildcards when a roster→division map is present, else the flat wins/points-for seed; synthetic-gated latent, see below) → **playoff_odds** (Σ across the league = exactly `PLAYOFF_TEAMS`, a hard invariant), **proj_wins/proj_points**, **avg_seed**, **magic_wins** (a clinch proxy), plus current wins/points. **numpy** (fixed seed) is the one compute dependency — **now truly deterministic** run-to-run (any-league piece 3 sorted the schedule pairings + roster player lists; polars group_by order + zero-score bye ties had made the fixed seed non-reproducible). **Playoff config** (reg-season-end + playoff-teams) is read from the persisted `league_settings` via `_playoff_config` (`playoff_week_start−1`, `playoff_teams`) — **not** hardcoded; the sim raises if settings are absent. For this league that's a **4-team** playoff starting wk16 (reg season ends wk15), which corrected an earlier wrong schedule-inferred "6". The gate is config-light (independent of the cut). Calibration-gated by backtest_bracket_sim.py (win-prob Brier 0.224 beats the 0.25 coin-flip; expected-wins Spearman 0.756 vs actual; top-4 by odds = 3/4 actual playoff teams; exit 0). **Simplifications:** starter independence (no covariance), Normal draw (no §3 skew), frozen-roster byes reduce μ. Decision home: posture + urgency (shown adjacent to True Rank — the front-end presentation is the deferred half) |
| compute_production_vor transform | snapshots/derived/ | production_vor_{season}.parquet — **tall, grain (as_of_week, roster_id, player)**: per as-of week N, one row per rostered skill player with the DECISION_READS §4 Production VOR read. **ros_value** = sum of the borrowed weekly consensus centers (projection_consensus.center_ppr) over the *remaining* schedule (weeks > N) — borrows the projection (law 3), builds only the anchor+normalization. **vor** = (ros_value − waiver_line) / (pool_top − waiver_line): waiver line = 0, pool top ≈ 1, negative = dead weight; §4's settled normalization (divide by pool spread, not the waiver value). **Pools from lineup_slots** via shared `_analytics.position_pools` (not hard-coded): dedicated QB slot = its own pool, flex-eligible RB/WR/TE = one pooled waiver line (§4 flex reconciliation); **superflex pools QB with the flex automatically** (any-league piece 2 — the old `_pool_of` matched only a slot named `FLEX`). Roster-as-of-N (latest team ≤ N, the shared arg_max idiom); roster frozen wks 1–4 so N bounded there, projection horizon → wk 18. Calibration-gated by backtest_production_vor.py (projected ROS tracks actual at corr ~0.95 per pool; VOR tiers monotonic in realized production — exit 0); superflex pooling gated by backtest_roster_shape.py. **Documented simplification:** the pooled flex line doesn't model dedicated-slot scarcity (a scarce TE is measured vs the flex replacement). **Market VOR (LeagueLogs) + the Production−Market trade gap are now BUILT** — see the `market_vor_{season}.parquet` row above (same engine on the borrowed market value; cross-time gap) |
| compute_ros_outcome_shape transform | snapshots/derived/ | ros_outcome_shape_{season}.parquet — **tall, grain (as_of_week, roster_id, player)**: per as-of week N, one row per rostered skill player with the DECISION_READS §2 ROS Outcome Shape read (**quantitative skeleton**; the AI narrative + 1-10 roll-up is Phase 6). **Bull/bear is the ROS-horizon analog of the §3 weekly spread:** **ros_center** = Production VOR's `ros_value` **reused directly** (`read_production_vor(season, as_of_week="all")` — the borrowed Σ weekly centres over remaining weeks, so it can't drift from §4); **ros_sigma** = √(Σ `band_ppr`² over the *same* remaining weeks) — the §3 shrunk weekly residual std combined under **weekly independence** (the assumption `compute_bracket_sim`'s team σ documents); the pure-projection extremes are ros_center ± `BULL_Z`·ros_sigma, then **blended toward the §2 preseason anchor**. **Preseason anchor (710 #4):** each drafted player's empirical floor/center/ceiling from `adp_points_curve` (keyed on his `adp_preseason.pos_ecr_rank`; the curve = historical realized-points P10/P50/P90 by positional ADP rank, fit on prior seasons, target held out), scaled to the remaining schedule and blended in with weight **w_N = ANCHOR_W·(remaining_weeks/total)** — **prior-driven early, evidence-driven late** (§2's dynamic, now explicit, not only emergent). `ros_center` stays the borrowed projection (law 3 — only the extremes are anchored); an undrafted / curve-uncovered player degrades to w=0 (the pure-projection band), so the read never breaks. **Backtest-tuned jointly**: `(BULL_Z, ANCHOR_W) = (1.44, 0.25)` (the anchor corrects the projection's floor-overprojection, so BULL_Z drops from the pre-anchor 1.645). Also **ros_cv** = ros_sigma/ros_center (fragility proxy), a per-position **spectrum_pos** on the bull ceiling, and **adp_ecr/best/worst + anchor_floor/ceiling + anchor_applied** evidence columns. **Situation/security** carries the structured `security` tier + `direction`/`reliability` from `player_signal` (the forward face of the Opportunity Trust axis) as evidence, not fused. New pure `_ros_sigma` + `_outcome_band` + `_preseason_anchor` + `_blended_band`; reads production_vor/projection_consensus/player_signal + adp_preseason/adp_points_curve. Calibration-gated by backtest_ros_outcome_shape.py, which exercises the shipped anchored path (freeze-wk coverage 0.817 vs target 0.80, balanced tails 0.091/0.091; joint BULL_Z×ANCHOR_W sweep on objective |cov−tgt|+|tail imbalance|; actual ROS monotonic by ros_bull tercile; exit 0). **Documented limitation:** the roster freeze bounds tested cutoffs to N=1..4 (early/prior-heavy) — the decay's late/evidence-heavy tail is by construction, not exercised. Decision home: hold/upside reads; the risk-appetite lens (§5 posture) sets how bull/bear is read |
| sleeper.py fetch-manager-activity mode | snapshots/sleeper/{season}/ | manager_activity_{season}.parquet — **the FIRST cross-league / user-keyed entity** (every other store is single-league, per-season). The DECISION_READS §7 acquisition (Phase A): for each target-league manager, their behaviour across their *comparable* other Sleeper leagues (same **scoring_profile + num_teams + qb_structure + format** — the four axes of `_manager.is_comparable`; **redraft↔redraft only** for V1, format tagged so dynasty turns on later). `owner_id` (Sleeper user_id) is the identity key; **`source_league_id` / `source_season` are COLUMNS** (the projections "source-as-a-column" idiom) so one tall file spans every manager/league/season. Two row **kinds**: `league` markers (one per searched comparable league, so a league a manager was inactive in still counts toward signal depth) + `txn` rows (one per that manager's transaction; adds/drops as JSON, waiver_bid, status, week). Comparables classified **straight off the `/user/.../leagues` payload** (it carries scoring_settings + roster_positions + settings — verified), so no per-candidate `/league` fetch. Selection: ≤5 leagues across {season, −1, −2}, biased to the prior season (`_manager.select_comparables`). **Written INCREMENTALLY per manager** (`write_manager_activity(df, season, owner_id)` = replace-by-owner_id) so a mid-fan-out failure leaves completed managers on disk and a re-run is idempotent (the leaguelogs reliability lesson). Acquired live (public Sleeper data, at most once/season) — a deliberate departure from the frozen-2025 world since the read is about the manager's *other* leagues. Consumed by compute_manager_features |
| compute_manager_features transform | snapshots/derived/ | manager_features_{season}.parquet — **per manager (owner_id)**, the DECISION_READS §7 Phase-A behavioral profile — the deterministic, **credit-free** AI input for the Phase-B Haiku dossier writer (never raw transaction logs — credit optimization, principle #5). Re-aggregates `manager_activity`: **FAAB aggression** (avg/max bid as fraction of that bid's league budget — normalises 200 vs 1000 budgets — + budget-spent fraction counting **only completed waivers**), **waiver/free-agent mix**, **waiver success rate** (complete/attempted), **add/drop churn** (moves per league), **trade frequency**, **positional lean of adds** (QB/RB/WR/TE shares, skill only — team-abbrev DST + K adds drop out), plus the **signal-depth counts** (n_leagues / n_seasons / n_transactions) + a coarse `depth_tier` (none/thin/moderate/deep) Phase B gates AI confidence on, + `is_primary` (the primary user gets a **blindspot**-scoped dossier). **No new engine** — pure `_manager.manager_features` with injected constants; **every league manager gets a row** (a zero-comparable-league manager included, depth 0). **Rate/lean features are null when their denominator is 0 — never a fabricated 0** (law 2 / the `_analytics` None convention), so Phase B can trust the depth counts. Internal-consistency-gated by backtest_manager_features.py (behaviour has no answer key): comparability invariant + accounting round-trip + signal-depth honesty (exit 0). The **"model of YOU" infrastructure** (Phase 5) pointed outward |
| application/ai/write_manager_dossiers.py | snapshots/derived/ | manager_dossiers_{season}.parquet — **per manager (owner_id)**, the DECISION_READS §7 Phase-B read and the **FIRST AI-written entity**. `application/ai/` (the AI layer, distinct from the polars transforms) turns `manager_features` into one **Claude-Haiku** dossier per manager — **never raw logs** (the deterministic features are the pre-filtered AI input, credit optimization principle #5). **Opt-in + API-key-gated:** `ai/client.api_available()` locks the read when `config.ANTHROPIC_API_KEY` is absent/placeholder/non-`sk-ant` (the writer exits cleanly, nothing written). **Fixed 7-key schema** (`headline`/`waiver_faab`/`trade_tendency`/`positional_lean`/`roster_construction`/`edge_or_blindspot`/`confidence_note`) so dossiers read side by side; **tendencies-not-verdicts** (laws 2+4); **blindspot framing for the primary user** (`is_primary`), exploitable-edge for opponents; confidence gated hard on signal depth. A **zero-comparable-league manager skips the AI** and gets a hardcoded "no intel" row (`is_zero_signal=True`). **Synchronous sequential** calls, isolated behind `ai/client.generate_dossier` (the ONE swap point for a future Batch path); JSON-in-prompt + `json.loads` (not `messages.parse` — SDK-version-safe). **Run-once-per-season** (overwrite; `--force` to regenerate). Rows carry the structured fields + `is_primary` + a signal-depth echo + provenance (`model`, `generated_at`, `is_zero_signal`). New `data_layer.write/read_manager_dossiers`. Internal-consistency-gated by check_manager_dossiers.py (no API, reads persisted only): coverage + schema completeness + depth-echo-matches-features + zero-signal honesty (exit 0). **Decision:** synchronous not Batch — at ≤16 managers once/season the 50% batch discount is noise, a concurrent batch can't share a prompt cache, and the seam lets Batch swap in if this ever becomes a high-volume hosted sweep. Decision home: opponent scouting (trade targeting, waiver competition) + the primary user's self-blindspot |
| fetchers/news.py (collector) | snapshots/news/ | team_news_raw.parquet — **Stage A of the §2 team-news pipeline** (collection → weekly AI extraction → per-player slice). A live, scheduled RSS collector banking per-NFL-team article coverage from **3 native sources per team** — SB Nation (grounded), FanSided (player-flavored/noisier), the official team site (authoritative/PR); **96 feeds (32×3) validated live**. **One growing file**; grain = **one row per article** (team-tagged; player resolution moved downstream to Stages B/C). Stores the feed-provided **article content** (`content:encoded` else summary, tag-stripped, ≤12k chars) — the extraction needs the text; **feed-provided only, no scraping** (reverses the v1 "no bodies" rule; product surfaces derived claims + link; raw prunable after the extraction window). Columns: article_id / team / **source_type** (team_official / team_blog_sbn / team_blog_fansided — for downstream weighting) / title / content / url / published_at / **collected_at** / season / week. Writer (`write_team_news_raw`) is **append-only-of-new by `article_id`** (sha1(url)) — re-polls add nothing (idempotent). National desks dropped (league-level); SI/FanNation ruled out (no native per-team RSS — tested). **Reliability** (leaguelogs lesson): `_get_feed` timeout + backoff, **per-feed isolation**, **incremental per-feed persistence**; per-team volume reported (the Stage-C thinness-tripwire input) + a <2/3 resilience-floor flag. The resolver (`build_index`/`resolve_players`/`_TEAM_ALIASES`) is **retained** for Stage B (claim-subject resolution) + Stage C (slice). Scheduled by launchd at 5am ET (`com.fantasyai.news-snapshot`). Verified live: 96/96 feeds, 32 teams, 5021 articles, idempotent, dead-feed isolation. `player_news` (v1) left as legacy. |
| application/ai/write_team_news_dossier.py | snapshots/news/ | team_news_dossier.parquet — **Stage B of the §2 team-news pipeline** (the interpretation half; the project's **2nd AI-written entity** after §7 dossiers). Once a week, per NFL team, distills that team's recent `team_news_raw` window (`WINDOW_DAYS`=14, cap 60 articles, newest first) into a compact, **situation/security-focused** news sheet a downstream AI reads next to the numeric analytics. Grain = **one scope-tagged claim row** per (season, week, team); one growing file, replace-by-(season, week, team) (idempotent; `--team` verify-runs touch only that team). Per claim: **scope** (player / position_group / unit) — the Stage-C inheritance key — / subject / claim_type / **basis** (`official`/`reported`/`opinion` — the epistemic status, so a downstream model never mistakes an opinion for fact) / **note** (ONE attributed cliffs-note — "SB Nation analysts argue…", not a flat assertion) / **direction** (positive/negative/neutral/**mixed** = cross-pressured, both good and bad) / salience / cited **source_article_ids** + **source_types** + n_sources (the model **clusters** one story across the 3 sources → source diversity = trust). **Skill-only (V1):** player claims are QB/RB/WR/TE, resolved to a `sleeper_player_id` via the retained resolver against a **team-restricted index** (an id attaches only for a player on THAT team — an opponent / former player / trade target → null id, never a cross-team id; law 2). **Defense condensed:** no individual defensive-player claims — the whole defense folds into ONE `unit`/`defense_strength` note (game-script context for the offense now; the signal pre-banked for when defensive positions are added). **Opt-in + API-key-gated** (`ai/client.api_available()`); synchronous sequential Haiku calls behind `ai/client.generate_claims` (the array analog of `generate_dossier`; the ONE Batch swap point); run-once-per-week (`--force`). A quiet team-week → one explicit `is_empty` row. New `data_layer.write/read_team_news_dossier` + `team_news_dossier_exists`. Internal-consistency-gated by `check_team_news_dossier.py` (no answer key — live/qualitative): consistency + schema/enum + grounding (cited ids exist AND on-team) + on-team player resolution + zero-signal honesty (exit 0). Verified live 2026 wk0: 32/32 teams, 317 claims, ~$0.46, gate PASS, 168/186 player claims resolved. **Next — Stage C:** per-player slice by inheritance + thinness tripwire + raw-content retention. Decision home: the §2 ROS Outcome Shape AI synthesis (reads a player's inherited slice next to the bull/bear anchors) |

**Projections entity (multi-source forward prior — Phase 2).** A single normalized,
source-agnostic file (`snapshots/projections/projections_{season}.parquet`) that any projection
provider writes into via `data_layer.write_projections(df, season, week, source)`. **`source` is
a column, not a directory** — so combining providers into a consensus + disagreement spread is a
group-by across `source`, and "pick a provider" is a filter; adding a new source (FantasyPros
in-season) is a new `source` value, **not a schema change**. Snapshot/append (dedup on
`(season, week, source)`), keyed on `sleeperPlayerId`, QB/RB/WR/TE only, `pts_ppr/half/std` +
component evidence. Source #1 = Sleeper (RotoWire); FantasyPros next. This is the borrowed forward
prior every Phase-2 read (§2/§3/§4/§5-bracket) depends on.

**Projection scoring is matched to the league via the scoring dispatcher (`transforms/_scoring.py`) —
standard + custom both built.** The entity stays *generic* (`pts_ppr`/`pts_half`/`pts_std` + component
stats), and scoring is applied at the **consumption layer** (`compute_projection_consensus`) so the same
projections serve any league. `scoring_profile(read_scoring_settings(season))` classifies the league:
  - **Standard (ppr/half/std) — built.** `rec` ∈ {1, .5, 0} with the shape-defining offensive keys at
    their standard values and no bonuses/TE-premium/first-down scoring → select the matching canned
    projection column + the matching nfl_stats actual expr (`fantasy_points_ppr`; `fantasy_points` for
    std; their mean for half). This closes the old "projection must match league" latent for the vast
    majority of leagues; `League of Random People 2.0` is profile=ppr so output is byte-identical.
  - **Custom — built (delta-on-canned-baseline engine).** Any scoring the canned columns can't express →
    `recompute_custom_points(scoring, side)` returns a `pl.Expr` that adds, to the **standard canned
    baseline** (`proj_pts_std` / `fantasy_points`), only the *delta* between the league's weight and the
    standard weight per component: `points = std_baseline + Σ(w_custom−w_std)·component`. **Not** a
    from-scratch sum — RotoWire's `proj_pts_ppr` embeds unexposed contributions (off ~2 pts if rebuilt);
    the delta form is **exact for standard by construction** and robust to what the vendor baked in. Same
    weights applied to the `proj_*` and `nfl_stats` columns so the projection center and the realized
    actual stay matched (residual = actual − center). **Supported:** non-{0,.5,1} PPR, non-standard
    TD/yardage rates (6-pt pass TD), position-conditional reception bonuses (`bonus_rec_te`/`_rb`/`_wr`/
    `_qb` = TE premium, scored `bonus·receptions` gated on position). **Rejected — raises naming the key
    (law 2):** first-down (`pass_fd`/`rush_fd`/`rec_fd`) and threshold/yardage bonuses — the projections
    carry no component, so the center can't be scored faithfully; unlock when a component-carrying
    projection source lands in-season. Reconciliation-gated by `backtest_scoring_recompute.py` (custom ==
    canned on standard inputs; exact custom deltas; rejection; end-to-end custom consensus — exit 0). The
    stored components (`proj_pass_yd/td`, …) enable it. `projection_column` was renamed
    `projection_points_expr`; `actual_points_expr` + `compute()` gained an injectable `scoring`.
  Turnover penalties (`pass_int`, `fum_lost`) and 2-pt conversions are carried in the std baseline at the
  standard rate (tolerance — the projections have no component to adjust them, and they move skill scoring
  only marginally), so they don't force or reshape the custom path. Note the consensus output columns
  still carry the `*_ppr` suffix (they now hold *league* points — a documented naming wart; the rename is
  deferred to the any-league project). Ties to the "league scoring settings" cross-cutting input in
  DECISION_READS §1/§3/§4.

These assignments reflect current v1 decisions, not permanent rules. Future versions may snapshot additional sources (e.g., odds history for post-hoc analysis).

Cache files do not currently track fetch timestamp. Add a metadata.json sidecar file to each cache write before in-season use.

Data sources are subject to change.

### Player ID join

Each data source uses a different player identifier. The canonical join key for this project is `sleeperPlayerId`.

- nflreadpy uses `gsis_id`
- LeagueLogs uses `sleeperPlayerId` natively
- FantasyPros uses `fantasypros_id`

Use nflreadpy's `import_ids()` to maintain a mapping table at `application/data/cache/player_id_map.parquet`. Refresh this mapping on every nflreadpy fetch run.

nfl_stats_{year}.parquet already includes sleeper_player_id as a column — this join is performed during the fetch step in nfl_stats.py. Transform scripts that read from the nflreadpy snapshot do not need to re-join via player_id_map.parquet.

---

## Fetchers

One script per data source in `application/data/fetchers/`. Each fetcher has a single concern - one source, one cache file, one snapshot stream where applicable.

Current fetcher state:
- `sleeper.py` - backfill + refresh + **projections** + **fetch-league-config** + **fetch-manager-activity** modes (projections: whole NFL skill pool's weekly forward prior via the `api.sleeper.com` stats host → shared `projections` entity, `source="sleeper"`; fetch-league-config: persists the `/league` object's `scoring_settings` + playoff config → `league_settings` entity, so scoring/playoff behavior is settings-driven not hardcoded; **fetch-manager-activity** `<season> [--me] [--limit N] [--throttle S]`: §7 cross-league fan-out — per target-league manager, their transactions across their *comparable* other leagues → `manager_activity` entity, incremental per manager). **All HTTP now routes through `_get_json`** — bounded timeout + exponential-backoff retry on transient failures (timeouts/resets/5xx; 4xx raise immediately) + an optional module-level throttle (`set_throttle`) the fan-out raises; behaviour-preserving for the existing single-shot callers.
- `odds.py` - does not exist
- `fantasypros.py` - does not exist (Phase 2 next source; writes the same `projections` entity, `source="fantasypros"`, in-season)
- `weather.py` - does not exist
- `nfl_stats.py` - backfill + refresh modes, polars, player ID map. Joins the ff_opportunity `*_exp` expected-points components (`_load_ff_opportunity`, the §1 Quality basis) + `redzone_touches` (`_load_redzone_touches`) onto each player-week; the old `xtd` td_prob proxy is retired
- `adp.py` - built; **preseason ADP** (`backfill [season]`) — FantasyPros historical consensus ranks via `nflreadpy.load_ff_rankings('all')`, latest full-skill-board pre-kickoff redraft-overall snapshot/season, id-bridged `fantasypros_id`→sleeper (the `id` column; cbs/yahoo are all-null) → `adp_preseason` entity. The §2 ROS preseason-anchor source
- `leaguelogs.py` - built; daily market-value snapshots (all profiles), scheduled by launchd at 4am ET
- `news.py` - built; **team-news collector** (§2 pipeline Stage A) — `snapshot [--team]`/`feeds`/`check`. A live RSS collector over a **per-team registry of 3 native sources/team** (SB Nation + FanSided + official; 96 feeds validated: `feedparser` + `_get_feed` timeout/backoff; per-feed isolation; incremental per-feed writes) → `team_news_raw` (one row per article; stores feed-provided content; append-only-of-new by article_id). Per-team volume reported (thinness-tripwire input). The resolver (`build_index`/`resolve_players`) is retained for Stages B/C (player resolution moved out of collection). Scheduled by launchd 5am ET. **Next: Stage B** (weekly per-team AI extraction → `team_news_dossier`) + **Stage C** (per-player slice + thinness tripwire + retention). v1 `player_news` collector superseded (legacy)

## nflreadpy Notes

Package version: 0.1.5
Key functions: load_player_stats(), load_snap_counts(),
load_team_stats(), load_ff_playerids()
All functions return polars DataFrames
player_id in load_player_stats() is gsis_id format ("00-0023459")
Snap count join path: load_snap_counts().pfr_player_id →
load_ff_playerids().pfr_id → gsis_id
Join coverage on nfl_sleeper_weekly_joined targets 100% of rostered skill-position players per week. The join is left-joined from Sleeper (authoritative), so players without nflreadpy stats that week (injured, inactive) appear with 0-stat rows rather than being dropped. The audit step resolves any remaining unknowns via the Sleeper player registry.

**§1 Quality axis — expected-points components (710 #3, 2026-07-10; supersedes the 2026-07-08 PBP td_prob proxy):** `nfl_stats.py._load_ff_opportunity(year)` calls `nflreadpy.load_ff_opportunity(year, stat_type="weekly")` (ffverse's expected-points model, same package) and joins its per-(gsis_id, week) `*_exp` component expectations (`receptions_exp`, `rec/rush/pass yards/TD/2pt/first-down _exp`, `pass_interception_exp`) onto nfl_stats — gsis-keyed like every other source (non-null ids, REG weeks ≤ 18, 1 row/gsis×week after filtering the null-id rows). The read re-scores these under the league's settings at the **consumption layer** (`_scoring.expected_points_expr` in `compute_player_signal`), so the fetcher stores raw scoring-agnostic components. This retired the old hand-rolled `xtd = Σ td_prob` TD-proxy; `_load_redzone_touches(year)` still derives `redzone_touches` (yardline_100 ≤ 20) from `load_pbp` as the legible companion. The empirical Quality axis (DECISION_READS.md §1): expected value per chance, not just TD probability.

## sleeper.py Notes

Player IDs are strings (e.g. "2307") throughout - never cast to int. This is the sleeperPlayerId join key.
Offseason-safe week logic: season_type == "offseason" returns 18 completed weeks, not 0. season_type == "pre" is the only state that returns 0.
Cache files are JSON (league/user/roster state) or parquet (players registry). Snapshot files are parquet partitioned by season: snapshots/sleeper/<year>/
league_resolver.py is the only file that touches SLEEPER_USERNAME. The fetcher accepts league_id as a parameter only.
refresh() current-week snapshot writes will silently skip with an explicit log message during offseason - this is expected behavior.

players_points in matchup snapshots is stored as a serialized JSON string (map of sleeperPlayerId → points). Parse with json.loads before joining. Same applies to starters (JSON array of starter IDs).

fetch_players() caches the full Sleeper /players/nfl endpoint to cache/sleeper/players.parquet. Skips the network call if the cache is less than 24 hours old; pass force=True to override. Called automatically by refresh() and by audit_join.py when the cache is stale or missing. Can also be triggered standalone: python3 -m application.data.fetchers.sleeper fetch-players. Position values in this endpoint use Sleeper's internal codes: QB/RB/WR/TE for skill, K for kicker, DEF for defense.

**Injury/depth-chart fields (added 2026-07-08, Phase 1 refinement):** fetch_players() now also carries injury_status, injury_body_part, depth_chart_order, depth_chart_position, and practice_participation through to the cache — the endpoint already returns them, previously discarded. Feeds compute_player_signal.py's `security` read. **Gotcha:** these fields are null for most players in the sampled prefix polars uses for schema inference, which can pin the wrong dtype for a column that's stringy/numeric further down — fetch_players() passes `infer_schema_length=None` to pl.DataFrame() to force a full scan. This is "now" data only (no history), so the same value applies across every as_of_week slice for a given player — a documented simplification, not a bug.

**Projections mode (added 2026-07-08, Phase 2 source #1):** `sleeper.py projections <season> [week]` fetches the whole NFL skill-position pool's weekly projections and writes the shared multi-source `projections` entity (`source="sleeper"`). **Gotcha — different host:** projections live on `api.sleeper.com` (the stats host, `_SLEEPER_STATS_BASE`, **no `/v1`**), not the `api.sleeper.app/v1` league API the rest of the fetcher uses. Endpoint: `/projections/nfl/{season}/{week}?season_type=regular&position[]=QB…`. **The scoring is already computed by the source** (`pts_ppr`/`pts_half_ppr`/`pts_std` in each row's `stats`) — no re-derivation. `position` lives at the nested `player.position` (the top-level `position` is null); the payload includes FB/CB rows filtered out by `SKILL_POSITIONS`. Under the hood the projections are RotoWire's (carried as the `company` column). **Key fact — it serves historical weekly projections** (past seasons return real per-week values, one row per player, 0 dupes), which is why Sleeper is Phase 2's *first* source: the prior lines up with the frozen-2025 world and is backtestable, whereas a live FantasyPros pull today would only serve 2026. League-agnostic (no league_id), so its CLI branch runs before the league_resolver import.

## leaguelogs.py Notes

`snapshot` pulls every profile (discovered dynamically from /v1/market — the API contract is additive) and appends to snapshots/leaguelogs/market_values.parquet via data_layer.write_leaguelogs_market_snapshot(), idempotent with dedup on snapshot_date. `profiles` lists the current profile keys. Read history via data_layer.read_leaguelogs_market().

**Status — collect-only (exception).** This fetcher runs on its own launchd schedule purely
to **bank market-value history** the API can't backfill (it serves only "now"). **No
transform or dashboard consumes its output yet** — market-value reads (trade / value VOR)
are V4. It is therefore an explicit exception to the scope filter's "everything traces to a
current consumer" expectation, kept solely to accumulate the time-series until then. Note it
is **not** an I/O-rule exception — it already writes through
data_layer.write_leaguelogs_market_snapshot(); the gap is a missing *consumer*, not missing
data-layer routing. Revisit when V4 wires in the market-value reads.

**Snapshot reliability (diagnosed & partially fixed 2026-06-18):** the daily snapshot had been silently dropping days. Root cause was *not* power/sleep — it was transient API failures (ReadTimeout / connection reset / ChunkedEncodingError against developer.leaguelogs.com) combined with a fragile write path: `snapshot()` collected all 5 profiles in memory and wrote once at the very end, so any single failed request discarded every profile already fetched that day (e.g. 2026-06-14 fetched 2 of 5, saved 0). **Fix applied:** `snapshot()` now writes incrementally — it persists the cumulative set of today's rows after each profile, so a later failure leaves a *partial* day on disk (more recoverable) instead of total loss. Because the writer dedupes on snapshot_date and treats `df` as the full set for that day, a re-run cleanly replaces a partial day with the complete one (no duplicates). 2026-06-18 was captured this way (5 profiles, 3,409 rows; history now 14 dates). **Caveat:** until retry/resilience lands, downstream analysis should treat any day with fewer than the expected profile count (5) as incomplete. Historical gaps 2026-06-03, -05, -06, -10, -14 are permanent — the API serves only "now" and they were never snapshotted.

**Update (2026-07-11 audit — full 41-day series 05-31→07-10):** the incremental-write fix held (no total-loss-from-fragile-write days since), but coverage is still only **26/41 complete · 29/41 any-data (63% / 71%)**. The fuller sample **corrects the root-cause read above — it is *both*:** ~7 days lost to transient errors (retry still hasn't landed — `leaguelogs._get` is a bare `requests.get`; the error log shows `ReadTimeout` + `ConnectionResetError(54)`, and the dynasty profiles, fetched last, drop first) **and ~8 days the job never fired** (laptop powered off at 04:00 — launchd skips a powered-off run, no catch-up). Full permanent gap list: missing 06-03/-05/-06/-10/-14/-19/-21/-26, 07-01/-02/-03/-04; partial 06-23 (3/5), 06-24 (2/5), 07-05 (4/5).

**Next move (resilience + host migration) — now generalized across collectors:** `news.py` is a second banking collector with identical needs, so the retry belongs in **one shared `fetchers/_http.py`** every fetcher calls (folding in `sleeper._get_json` + `news._get_feed`, which already retry, and fixing `leaguelogs._get`) + per-item isolation (news isolates each feed; leaguelogs doesn't isolate profiles) + a `check_*` coverage gate that certifies each series. The off-laptop host closes the ~8 powered-off days (retry alone can't) and **merges with the Deployment decision** — a static web deploy has no compute, so a scheduled runner (GitHub Actions the lead) both collects and publishes the parquet. Specced as the **"Daily-collector reliability"** item in `READ_BUILD_ORDER.md`.

Dynasty profiles include rookie-pick rows (synthetic ids like "PICK#2026#01"), flattened into pick_* columns with is_pick=true. Redraft profiles have players only.

Market value is a black-box signal (methodology not published) — use for ranking/trend, not as ground truth. Mandatory attribution: any UI displaying the data must show "Powered by LeagueLogs API" (https://leaguelogs.com).

Scheduler: launchd agent `com.fantasyai.leaguelogs-snapshot` runs `snapshot` daily at 04:00 America/New_York. Canonical plist + README are tracked in application/data/fetchers/scheduler/; the live copy lives at ~/Library/LaunchAgents/. **Gotcha:** launchd cannot open log files inside ~/Documents (TCC-protected) → it fails with EX_CONFIG/78 and empty logs. Logs therefore live at ~/Library/Logs/fantasy-ai/. The launchd-spawned python can still read/write parquet under ~/Documents — only the log-file open is blocked, so no Full Disk Access is needed. This applies to any future launchd job in this repo.

---

## Transforms

One script per join in `application/data/transforms/`. Each transform reads 
via data_layer.py, performs a single join, and writes via data_layer.py.

- `join_nfl_sleeper_weekly.py` — joins nflreadpy weekly stats + Sleeper matchup data on sleeperPlayerId. Sleeper is the authoritative left table — all rostered skill-position players appear in the output regardless of whether nflreadpy has stats for them that week. DSTs are stripped at parse time; kickers are removed by the SKILL_POSITIONS filter after the join. Inactive/injured players appear with 0-stat rows. Appends the week's rows to the single season_{season}.parquet (replacing any existing rows for that (season, week) combo) and writes a remainders file. Calls audit_join automatically on completion. Accepts --season and --week as required CLI args.

- `audit_join.py` — audits and repairs the weekly join output for unresolved players. Reads the remainders file, checks the Sleeper player registry (refreshing it if stale), classifies each remainder as skill (appended to joined file with 0 stats), K/DEF (confirmed and discarded), or truly unknown (left in remainders for manual review). Idempotent — safe to re-run. Called automatically by join_nfl_sleeper_weekly.py; can also be run standalone with --season and --week args.

- **Season-replay `as_of_week` dimension (all three derived transforms).** Each
  `compute(season)` loops N=1..maxweek, filters its input join slice to `week ≤ N`, and
  emits rows tagged `as_of_week = N` — one tall table per analytic at grain
  `(season, as_of_week, entity)`, the dashboard as it would have read through each week N.
  That single `week ≤ N` filter does double duty: it is the cutoff (Part 1) **and** the
  roster-as-of-N correctness fix (Part 3) — the `arg_max(roster_id, week)` "current team"
  resolution becomes "latest week ≤ N", so a mid-season trade/add changes *who is on the
  team* at week N, not just the numbers. League-relative spectra (and the player-signal
  positional efficiency mean) are recomputed within each N cohort. **Windowing (Part 2)
  is per-analytic, decoupled from the cutoff, by the stationarity principle:** leakage
  cumulative (ledger), form EWMA half-life 2wk (trend), player-opportunity through an
  injected EWMA half-life (`OPP_HALF_LIFE_WK`, shared `_weighted_rates`) — backtest-tuned
  and shipping **cumulative** (the 2025 sweep showed recency hurts rest-of-season MAE).
  `data_layer.read_team_form/leakage/player_signal` take an optional `as_of_week`
  (default = latest), and `queries.js` carries a default-latest guard, so existing
  callers and the front end are unchanged until the Session-B week selector lands.

- `compute_team_form.py` / `compute_team_leakage.py` — **derived-analytics transforms.** They read the season join (+ lineup_slots for leakage) and write one pre-computed row per (as_of_week, roster_id) to `snapshots/derived/`. These promote the heaviest Team Overview math out of the front-end seam (`queries.js`): the EWMA trajectory read and the optimal-lineup / leakage read, respectively, plus the tuning constants and signal thresholds they own (`HALF_LIFE_WK`/`DIRECTION_BAND`; `MIN_GAMES`/`COACHABLE_RATE_MARGIN`/`HABITUAL_STARTER_THRESHOLD`). Rationale: a Python server is the eventual architecture, so the analytics live in Python now — the front end reads pre-shaped parquet, and the server migration becomes "transform → API serves same parquet" rather than "rewrite JS math in Python." Re-run with `--season` after a join refresh. Faithful ports of the prior JS; output reconciles exactly. Accept `--season` as a required CLI arg.

  **SOLID shape (per principle #9):** each per-team analytic is a pure function
  (`_team_form`, `_team_leakage`) that **receives its tuning constants as injected
  keyword args** — `compute(season)` is the composition root that owns the module
  constants and passes them down (DIP: the pure logic depends on parameters, not
  globals, so it tests in isolation at any parameterisation). Shared numeric helpers
  (`round1`, `mean`, `median`, the league-relative `spectrum_positions`
  normaliser — the Python mirror of the front-end's old `attachSpectrumPos` — `pearson`,
  added for the Phase 1 point-correlation refinement, and the slot-aware greedy lineup
  engine `expand_slots`/`optimal_lineup`, lifted here when True Rank became its 2nd
  consumer) live once in **`transforms/_analytics.py`** rather than being copy-pasted per transform.

- `compute_player_signal.py` — **the first decision-critique engine slice (Product
  Roadmap Phase 1): the spike signal-quality read.** Reads the (frozen) season join,
  emits one row per rostered skill player to `snapshots/derived/player_signal_`. It
  characterizes recent production as "real or noise" — *not* a forward projection
  (design law 3) — by decomposing it into **sticky opportunity** (`opp_g`,
  position-specific: targets / carries+targets / pass-att+carries, carried forward as
  the anchor) and **fragile efficiency** (`ppo` = points per opportunity, shrunk
  toward the league-wide positional mean by sample size, `SHRINK_K` games of prior).
  Headline `regression_risk = 1 − expected_ppg/recent_ppg`; a sample-gated categorical
  `read` (`too_early`/`spike`/`mixed`/`sticky`) keeps the language honest (law 2), and
  `td_share` is carried as the most legible evidence. Same SOLID shape as the team
  transforms: pure `_player_signal` with injected constants (`SHRINK_K`, `MIN_GAMES`,
  `SPIKE_BAND`/`STICKY_BAND`, `POS_MEAN_MIN_OPP`, and the `OPP_HALF_LIFE_WK` window),
  `compute()` the composition root, helpers from `_analytics`. The positional efficiency
  mean is computed over the full NFL stat pool (the borrowed substrate), not just this
  league's rostered players. Per-game rates come from the shared pure
  `_weighted_rates(weeks, half_life)` (EWMA window), so the windowing choice is a single
  injected parameter and the backtest validates the exact shipped path.

  **§1 Quality axis (710 #3, 2026-07-10; refines the 2026-07-08 slice):** the §1 fields, kept
  separate from the validated core read ("don't collapse the axes"). **`quality_rate` is now
  expected fantasy points per opportunity** (`exp_pts_g/opp_g`) — `compute()` derives `exp_pts`
  once at the consumption layer via `_scoring.expected_points_expr(scoring)` over the joined
  ff_opportunity `*_exp` components, and the weekly series carries `exp_pts` alongside actual pts
  (replacing the old TD-only `xtd`), so `_weighted_rates` yields `exp_pts_g` and the backtest
  exercises the exact path. `point_correlation` is now `pearson(weekly actual, weekly expected
  full points)` — do the valuable chances convert? — and a new **`luck`** = recent − expected ppg
  (over/under-performance residual). `direction`/`reliability` (Trust axis, from the raw per-week
  series) and `security` (Sleeper injury/depth-chart "now" flag) are unchanged. **The core forecast
  (`expected_ppg`/`regression_risk`) still shrinks efficiency toward the positional mean** — the
  710 #3 upgrade to shrink toward the model-expected efficiency (`exp_ppo`) was implemented and
  **rejected by the answer key** (lost to the positional mean at every `SHRINK_K`; points-forecasting
  is regression toward the *population*, and `exp_ppo` on the same recent weeks is too correlated
  with realized `ppo` to pull that way). So the 2025 core gate is unchanged (13.2% MAE cut); the
  model serves the Quality axis, not the forecast.

- `backtest_player_signal.py` — **the validation gate Phase 1 must clear before any
  engine ships live.** Imports the *same* pure `_player_signal` the transform ships
  (no parallel re-derivation that could drift) and tests it against the full-2025
  answer key: input = a recent window (default wks 1–4), truth = rest-of-season
  per-game PPR. **Three verdicts** — *predictive* (does the signal beat a naive
  "recent-points-carry-forward" baseline on MAE/RMSE/corr?), *decision-relevant*
  (among hot players, which the naive read can't tell apart, does the `spike` group
  regress more than the `sticky` group?), and **§1 Quality axis (710 #3)** (does
  `quality_rate` = `exp_ppo` forecast a player's rest-of-season realized efficiency
  pts/opp better than his recent realized `ppo`?). Exits 0 only if all pass. Current 2025
  result: signal cuts rest-of-season MAE 13.2% at the W4 freeze; hot `spike` group
  regressed ~3.7 pts/g while `sticky` held flat; quality_rate forecasts ROS efficiency at
  MAE 0.311 vs 0.506 recent-realized (decisively better). This backtest-against-the-answer-key
  pattern is the template for every engine slice — it's also what **rejected the 710 #3
  core-prior upgrade** (shrink toward `exp_ppo`): it lost to the positional mean at every
  `SHRINK_K`, so the core forecast kept its validated prior.
  **`--sweep`** tunes the opportunity EWMA half-life against the answer key at any freeze
  (and `--opp-half-life` overrides the verdict run); the 2025 sweep across W4/W6/W8 chose
  **cumulative** (short half-lives hurt rest-of-season MAE — opportunity is sticky enough
  that max sample wins), which is why `OPP_HALF_LIFE_WK` ships `None`.

- `compute_projection_consensus.py` — **the Phase-2 forward prior: the weekly projection
  consensus + spread band (DECISION_READS §3).** Reads the multi-source `projections` entity
  + `nfl_stats` actuals, emits one row per (week, player) over the whole skill pool. Per law 3
  it **borrows the center** (median `proj_pts_ppr` across sources) and **builds only the band**;
  per law 2 the band width *is* the confidence signal. Band width = the player's **residual std**
  `std(actual − proj)` over his weeks < W (out-of-sample), **shrunk toward a full-pool positional
  prior** by `SHRINK_K` games — thin early samples lean on the position, sharpen as history
  accrues (the shrink idiom from `compute_player_signal.py`, applied to a variance instead of a
  rate; the pure `_analytics.stdev` added for it). **Archetype skew (§3 c3, added 2026-07-09)** is
  the 3rd component: a Cornish-Fisher quantile shift `SKEW_GAIN·(g/6)·(BAND_Z²−1)` applied to both
  breakpoints from the player's **residual skewness** `g` shrunk to a positional prior (`SKEW_SHRINK_K`
  — larger than `SHRINK_K` since a 3rd moment is noisier; pure `_analytics.skewness` added for it). p50
  stays the borrowed center; p25/p75 = center + band·(∓`BAND_Z` + shift), floored at 0. **The skew
  driver was resolved by the answer key, not §3's literal wording:** §3 names the projection's
  archetype (TD-dependence) as the driver, but that was *measured* not to track residual skew (high-TD
  players skew 0.64, low-TD 0.89 — backwards); the player's own residual 3rd moment does. Because
  `BAND_Z<1`, a right-skewed residual (the universal case) shifts both breakpoints *down* — the
  borrowed center sits above the realized median (projections lean mildly optimistic) — so honest
  25/25 tails want a slightly longer *lower* gap, reversing §3's right-skew illustration (documented in
  the transform docstring). Same SOLID shape: pure `_projection_band`/`_consensus` with injected
  constants, `compute()` the composition root, but **not** the as_of_week loop — it's per-week forward
  (band uses weeks < W), so the output is keyed on `week` and read without `_as_of_slice`.
  `disagreement_ppr` (cross-source std) is a scaffolded column, null under one source, additive when
  ffanalytics adds a live second source in-season — a value change, not a schema change.

- `backtest_projection_consensus.py` — **the calibration gate for the spread band.** Imports the
  same pure `_projection_band`/`_consensus_frame`/`_residuals` the transform ships (no re-derivation).
  Validates DECISION_READS §3's calibration on the full-2025 answer key: for every projected-and-played
  (player, week), the band from weeks < W (out-of-sample) — does the actual land in [p25, p75] ~50% of
  the time, **and each tail (below-p25 / above-p75) near 25%**? The per-tail split is what the skew
  term is graded on (a symmetric band can hit 50% overall while missing low on one side — 2025 was
  0.278/0.208). **`--sweep`** tunes `BAND_Z × SKEW_GAIN` **jointly** against the answer key (2025 chose
  (0.55, 1.5) — coverage 0.493, tails 0.247/0.261, tail error cut 5× vs symmetric). Exit 0 iff combined
  coverage within tol of 0.50, both tails within tol of 0.25, AND the skew improves tail balance vs a
  re-tuned symmetric band. Also reports the per-player shrink vs a naive position-only band across
  volatility strata. Same backtest-against-the-answer-key template as `backtest_player_signal.py`.

- `compute_production_vor.py` — **the first read that consumes the projection substrate (DECISION_READS
  §4): Production VOR.** Reads `projection_consensus` (the borrowed centers) + the season join (roster)
  + `lineup_slots` (pool config); emits one row per (as_of_week, rostered player). Per law 3 it borrows
  the projection and builds only the decision layer: `ros_value` = sum of the borrowed weekly centers
  over the remaining schedule (weeks > N); `vor` = (ros_value − waiver_line) / (pool_top − waiver_line),
  anchoring waiver = 0 and normalizing by the **pool spread** (§4's settled choice — stable where a
  waiver denominator collapses). Pools derive from `lineup_slots` (`_pool_of` → shared `_analytics.position_pools`): a dedicated QB slot is
  its own pool, flex-eligible RB/WR/TE share **one pooled waiver line** (§4 flex reconciliation), and
  **superflex pools QB with the flex automatically** (any-league piece 2). SOLID
  shape: pure `_ros_values`/`_pool_lines`/`_vor`/`_roster_as_of`, `compute()` the composition root.
  **Tall over as_of_week** like the three team/player analytics (roster-as-of-N via the shared arg_max
  idiom); roster (season join) is frozen at wks 1–4 so N is bounded there, projection horizon → wk 18.
  **Documented simplifications:** the pooled flex line doesn't model dedicated-slot scarcity (a scarce
  TE is measured against the flex replacement, usually a WR/RB — §4's deliberate settled choice).
  **Superflex is now handled** (QB joins the flex pool via `position_pools`; any-league piece 2, gated by
  backtest_roster_shape.py) — no longer a latent. **Market VOR (LeagueLogs) + the Production−Market trade
  gap are now BUILT** (`compute_market_vor.py` — the market-value twin; same engine on the borrowed
  market value; the gap folded in with cross-time honesty columns since the market is current-2026 while
  rosters/production are frozen-2025).

- `compute_market_vor.py` — **the market-value twin of Production VOR (§4).** Same waiver=0 ÷ pool-spread
  VOR on the borrowed LeagueLogs `value` (format-matched profile `redraft-1qb-12t-ppr1`), reusing the
  shipped pure functions (`position_pools`/`_pool_lines`/`_vor`/`_roster_as_of`, `round1`) — no new math
  (law 3). Position joined from the Sleeper registry (the feed carries only `position_rank`). **Tall over
  the market's `snapshot_date` axis** (banks the un-backdatable series). The **Production−Market gap**
  folded in — `trade_gap = market_vor − production_vor` — with `is_cross_time`/`market_season`/
  `production_as_of`/`has_production_vor` as first-class columns: the app is frozen at 2025 wk4 but the
  market is current 2026, so the gap is cross-time by construction and never fused (POC/architecture
  validation, not a live trade call, until the season rolls to 2026). Gated by `check_market_vor.py`
  (internal-consistency — no answer key exists at the 2026-offseason freeze).

- `backtest_production_vor.py` — **the validation gate for Production VOR.** Imports the same pure
  functions the transform ships. Two verdicts on the full-2025 answer key (exit 0 iff both): (1)
  *predictive* — per pool, does projected `ros_value` correlate with **actual** ROS production (realized
  points over the same remaining weeks)? 2025: corr 0.944 (QB) / 0.955 (FLEX), floor 0.60. (2)
  *decision-relevant* — sort rostered players by VOR into terciles and confirm actual production rises
  monotonically (dead 70.7 < mid 138.7 < stud 220.7), with below-waiver (vor<0) clearly under
  at-or-above. Same backtest-against-the-answer-key template as the other two gates.

- `compute_true_rank.py` — **the first league-level read that consumes the substrate (DECISION_READS
  §5, first half): True Rank.** Reads `read_production_vor(season, as_of_week="all")` (the whole tall
  frame — a new `_as_of_slice` `"all"` sentinel lets a re-aggregating consumer read every week's slice
  through the seam) + `lineup_slots`; emits one row per (as_of_week, team). Per law 3 it borrows
  nothing new — it **re-aggregates** the already-shipped Production VOR over the league's lineup rules:
  pure `_team_strength` feeds each rostered player's ros_value in as the shared `optimal_lineup`'s
  `pts`, so the greedy most-constrained-first fill maximises summed ROS value → `roster_strength`;
  `_rank_cohort` attaches the dense rank + shared `spectrum_positions`. SOLID shape: pure helpers +
  `compute()` composition root looping as_of_week. **The optimal-lineup engine (`expand_slots`/
  `optimal_lineup`) was lifted from `compute_team_leakage` into `_analytics`** (pure, points-agnostic,
  now two consumers — the "shared helper has one home" move); leakage imports them aliased, so its
  behavior is unchanged. Record-independent (no wins read); slot-aware so a capped-position stud
  surplus doesn't inflate the rank. Consumed by the Phase-4 bracket-math Monte Carlo (§5 full); no UI
  yet (data + gate, like VOR).

- `backtest_true_rank.py` — **the validation gate for True Rank.** Imports the same pure functions the
  transform ships (`_team_strength`, `expand_slots`, `optimal_lineup`). Two verdicts on the full-2025
  answer key (exit 0 iff both): (1) *predictive* — freeze-week corr(projected `roster_strength`, each
  team's **actual ROS ceiling**) ≥ 0.60, reported Pearson AND Spearman (the read is a *ranking*).
  Actual ceiling = the *management-independent* optimal lineup set each week on **realized** nfl_stats
  points over the remaining weeks, so it isolates roster quality from lineup-setting skill (leakage's
  domain). 2025: Pearson 0.802 / Spearman 0.842 (n=10 teams @ wk4). (2) *decision-relevant* — the
  strong half by projected rank out-produces the weak half on actual ceiling (+261.7 ROS). **Small-
  sample honesty:** the freeze snapshot is the gate (10-team league); the pooled-over-weeks corr is
  reported as evidence only (the same team at N=1..4 isn't independent). Same template as the other gates.

- `compute_positional_depth.py` — **the last of the four Phase-3 reads (DECISION_READS §6): Positional
  Depth.** Reads `read_production_vor(season, as_of_week="all")` + `lineup_slots`; emits one row per
  (as_of_week, team, **fine position** QB/RB/WR/TE). Per law 3 it borrows nothing — it **re-slices** the
  borrowed ros_value/vor per position, **net of the position's dedicated starting requirement**
  (`_starter_needs` reads QB1/RB2/WR2/TE1 off lineup_slots; the shared FLEX is excluded so flex-worthy
  depth reads as **surplus** = trade capital). Pure `_position_depth` computes starter_value /
  surplus_value / surplus_startable (beyond-need vor>0) / marginal_vor (the gap indicator); a per-cohort
  `spectrum_positions` pass benchmarks each team **within its position** vs the league; `_shape` buckets
  an **advisory** surplus/adequate/gap off marginal_vor + spectrum_pos (named thresholds `GAP_VOR`,
  `SURPLUS_SPECTRUM` — league-agnostic config seeds). Emits a row for **every (team, position)** even at
  zero roster count so a body-count gap is visible. SOLID shape: pure helpers + `compute()` composition
  root looping as_of_week. Roster-as-of-N inherited from the VOR slice; the re-slice is lossless. No UI
  yet (data + gate). Decision homes: trade shape + waiver/FAAB (§6).

- `backtest_positional_depth.py` — **the validation gate for Positional Depth.** Imports the same pure
  functions the transform ships (`_position_depth`, `_starter_needs`). §6 is a finer re-slice of
  already-gated VOR, so the gate proves the **per-position** claim carries signal (not just that VOR
  does). Two verdicts on the full-2025 answer key (exit 0 iff both): (1) *predictive* — per position,
  corr(projected `starter_value`, each team's **actual ROS ceiling** at that position = top-`need`
  players by *realized* points over the remaining weeks, the management-independent True-Rank style);
  gate on the **mean across positions** ≥ 0.50 (each position n≈10, so per-position is noisy — the mean
  is the honest aggregate; per-position printed). 2025 @ wk4: QB 0.792 / RB 0.867 / WR 0.855 / TE 0.928,
  mean 0.861. (2) *decision-relevant* — within each (position, week) the top half by projected
  starter_value out-produces the bottom half on actual ceiling (+85.3 pooled). Small-sample honesty:
  freeze week is the gate, pooled Pearson (0.971) is evidence. Same template as the other gates.

- `compute_bracket_sim.py` — **the bracket-math half of the Posture read (DECISION_READS §5): a Monte
  Carlo season simulation → playoff odds** (Phase 4). With `compute_true_rank` (§5 first half) it
  completes §5. Per law 3 it borrows the forward prior and builds only the simulation layer. Reads
  `read_projection_consensus` (per-week `center_ppr` + `band_ppr`), the season join (roster-as-of-N via
  the shared `_roster_as_of`), `lineup_slots` (shared `expand_slots`/`optimal_lineup`), and
  `read_season_matchups` (the new data_layer reader stacking all per-week matchup snapshots → schedule +
  actual results). **Score-distribution model** (pure `_team_week_dist`): per team × remaining week, the
  optimal lineup by that week's borrowed centre → μ = Σ starter centres, σ = √(Σ starter `band_ppr`²)
  (band_ppr is the §3 shrunk residual std; **starters independent — documented**). **Analytic win prob**
  `_win_prob` = Φ((μA−μB)/√(σA²+σB²)) via `math.erf`. **Standings as-of-N** (`_standings_as_of`) from
  the actual results (wins, then points-for). **Monte Carlo** (`_simulate`, numpy, fixed `SEED`, `SIMS`
  =10k): draw weekly scores ~N(μ,σ²), pair by the real remaining schedule, accumulate onto the as-of-N
  standings, seed top-`PLAYOFF_TEAMS` → per-team `playoff_odds`, `proj_wins`/`points`, `avg_seed`,
  `magic_wins`. **Playoff config** (`reg_season_end`, `playoff_teams`) is read from the persisted
  `league_settings` via `_playoff_config` (`playoff_week_start−1`, `playoff_teams`), injected as params;
  the sim raises if settings are absent (no hardcoded fallback). For this league that's a **4-team**
  playoff starting wk16 (reg season ends wk15) — correcting an earlier wrong schedule-inferred "6".
  Tall over as_of_week. **Documented simplifications:** independence across starters
  (no covariance); Normal weekly draw (the §3 skew isn't carried into the sample — a refinement);
  frozen-roster bye weeks reduce μ (no streaming — shared with VOR/True Rank). numpy is the one compute
  dependency; no UI yet (data + gate). The posture *presentation* (True Rank + odds adjacent, the
  risk-appetite lens) is the deferred front-end half of §5.

- `backtest_bracket_sim.py` — **the validation gate for the bracket sim.** Imports the same pure
  functions the transform ships (`_team_week_dist`, `_win_prob`, `_standings_as_of`). Deliberately
  **config-light** — both verdicts use only actual matchup results, so a wrong playoff-config default
  can't fake a pass (exit 0 iff both): (1) *win-probability calibration* — the analytic `P(win)` over
  every actual matchup wks N+1..15 scored with the **Brier score**, must beat the 0.25 coin-flip
  baseline by ≥ 0.02 (2025: **0.224** — single-game FF is near-coin-flip by nature, so the honest edge
  is modest); (2) *standings prediction* — expected wins (analytic base + Σ remaining P(win), the
  backbone the MC approximates) vs actual wins, freeze-week **Spearman ≥ 0.50** (2025: **0.756**). Also
  reports (not gated) that the top-`PLAYOFF_TEAMS` by `playoff_odds` = **3/4** actual playoff teams —
  the season aggregate is where the modest per-game edge accumulates. Same answer-key template as the
  other gates.

- `compute_adp_points_curve.py` — **the §2 preseason-anchor curve (710 #4).** Answers "what does a
  player drafted at positional ADP rank *r* actually produce over a full season?" by pairing
  `read_adp_preseason(season)`'s `pos_ecr_rank` with realized season-total `fantasy_points_ppr`
  (`read_nfl_stats` — so no transform touches nflreadpy directly) over the training seasons, then per
  position fitting floor/center/ceiling = P10/P50/P90 (`_analytics.quantile`) over a **rolling ±3-rank
  window** (per-rank samples are one player/season — too thin alone), each series **isotonic-smoothed**
  non-increasing (weighted PAVA — the monotone fit without a running-min's downward bias). A
  drafted-but-never-produced player realizes 0.0 — kept, as the floor's bust/injury signal. The
  freeze/target season is **held out** of the fit (default = latest) so the anchor it feeds is leak-free.
  → `derived/adp_points_curve` (season-agnostic, overwrite). No answer-key gate of its own — validated
  through the ROS gate that consumes it.

- `compute_ros_outcome_shape.py` — **the forward player read (DECISION_READS §2): ROS Outcome Shape,
  the quantitative skeleton.** Reads `read_production_vor(season, as_of_week="all")` (the borrowed ROS
  centre), `read_projection_consensus(season)` (the §3 weekly band), `read_player_signal(season,
  as_of_week="all")` (situation/security), and — for the preseason anchor — `read_adp_preseason(season)`
  + `read_adp_points_curve()`; emits one row per (as_of_week, rostered player). Per law 3 it borrows the
  centre and the band and builds **only** the ROS-horizon aggregation + the anchor blend. **Bull/bear is
  the rest-of-season analog of the §3 weekly spread:** pure `_ros_sigma` aggregates the weekly band's
  *variance* (`band_ppr²`) → `ros_sigma = √(Σ band²)` (weekly independence); pure `_outcome_band` forms
  the pure-projection extremes `ros_center ± BULL_Z·ros_sigma`. **Preseason anchor (710 #4):** pure
  `_preseason_anchor` looks the player's `pos_ecr_rank` up in the curve (deep ranks clamp to the deepest
  fitted rank) → floor/center/ceiling scaled to the remaining schedule; pure `_blended_band` blends the
  projection extremes toward it with weight **w_N = ANCHOR_W·(remaining/total)** — prior-driven early,
  evidence-driven late (§2's dynamic, explicit). `ros_center` stays borrowed (law 3); an undrafted /
  uncovered player degrades to w=0 (the pure-projection band, `_load_anchor_inputs` returns empty maps if
  the ADP pipeline hasn't run). SOLID shape: pure helpers with injected `BULL_Z`/`ANCHOR_W`, `compute()`
  the composition root. **Situation/security** carries the player_signal trust axis as structured
  evidence — not fused; the AI narrative + 1-10 roll-up is Phase 6. **Documented simplifications:**
  symmetric projection band (no ROS-level skew term); weekly-independence σ (autocorrelation absorbed
  into the tuned `BULL_Z`). No UI yet (data + gate). Completes the player-read backend (§1–§4).

- `backtest_ros_outcome_shape.py` — **the calibration gate for ROS Outcome Shape.** Imports the same pure
  `_ros_sigma`/`_preseason_anchor`/`_blended_band`/`_load_anchor_inputs` the transform ships, so it
  validates exactly the anchored band that serves the read (no re-derivation). The per-player realised ROS
  answer key is Σ actual PPR over the remaining weeks (a player read, no `optimal_lineup`); the band's
  forward inputs never see the actuals (no leakage). Two verdicts on the 2025 answer key (exit 0 iff
  both): (1) *calibration* — freeze-week coverage within `COVERAGE_TOL` of `TARGET_COVERAGE`=0.80 (2025:
  **0.817**), tails balanced 0.091/0.091. **`--sweep`** tunes **`BULL_Z × ANCHOR_W` jointly** (the anchor
  reshapes the band, so width and anchor weight interact) on objective `|cov−target| + |tail imbalance|`
  → **(1.44, 0.25)** — calibrated *and* centred, where coverage-only would chase a lopsided band. The
  gate reports the pre-anchor (ANCHOR_W=0) vs anchored freeze-week tails so the anchor's contribution is
  visible: it lifts coverage 0.744→0.817 and rebalances the projection's lopsided miss tails
  (0.195/0.061 → 0.091/0.091). (2) *decision-relevant* — actual ROS rises monotonically by `ros_bull`
  tercile (2025: dead 58 < mid 127 < stud 205). **Documented limitation:** the roster freeze bounds
  tested cutoffs to N=1..4 (early/prior-heavy), so the horizon-decay's late/evidence-heavy tail is
  asserted by construction, not exercised — tuned where the anchor matters most.

## Technical Principles

These do not change without an explicit architectural decision:

1. **polars only** - no pandas anywhere in the codebase, use polars until the project advances to a SQL backend
2. **One fetcher per source** - no combined fetchers
3. **The data layer is shared** - dashboard and AI advisor read from the same cache/snapshots; no parallel data paths
4. **Separation of concerns** - focus scripts around a single action, i.e. analysis scripts never read from cache or snapshots directly. All data access goes through dedicated read functions. These are the only code that knows where data lives or what format it's in.
5. **Pre-filter data before any API call** - do not send the LLM more context than it needs (cost control)
6. **The strategy doc is markdown** - not vector-embedded; rules must be auditable and human-readable
7. **Single source of truth per fact** - constitution docs hold current state; never duplicate across docs
8. **Skill positions only in V1** — QB, RB, WR, TE. DST and K are explicitly out of scope until a future version. Do not write V1 code that attempts to handle them.
9. **adhere to SOLID programming design principles** - Single Responsibility Principle, a function/class/module should have only one reason to change, meaning it should have only one responsibility (separation of concerns); Open/Closed Prinicple, software entities (classes, modules, functions, etc.) should be open for extension, but closed for modification; Liskov Substitution Principle, subtypes must be substitutable for their base types without altering the correctness of the program, for a non-OOP context, this translates to predictable behavior and strict adherence to data contracts; Interface Segregation Principle, avoid depending on things you don't use; Dependency Inversion Principle, high-level modules should depend on abstractions, not concrete details, apply this using techniques like dependency injection (passing configuration or services into functions)