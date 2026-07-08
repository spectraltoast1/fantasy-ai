# Technical Architecture

> Engineering context document for Claude Code. Describes the stack, folder structure, data layer design, and technical principles. Updated regularly as the project evolves.

**Last reviewed:** 2026-07-08

---

## Project Summary

A fantasy football analytics dashboard (v1) and AI advisor (v2+). V1 is a pure analytics dashboard - no AI component. The data layer is shared between the dashboard and the future AI advisor. All fetchers write to a common data layer that both halves read from.

Winning a redraft fantasy football championship is about more than just collecting all of the best players. It is about how you manage your specific team in your specific league. Knowing when you need to act - or not act - as a team manager is as valuable as knowing which individual players to target or avoid. This tool focuses on helping you navigate your league using real data signals: how your team is trending, where your real weaknesses are, and what your opponents look like. The goal is fewer decisions driven by anxiety or noise, and more decisions made on league-winning signal.

---

## Tech Stack

- **Language:** Python for the data layer/pipeline; JS/React in the front-end
- **Data manipulation:** polars (not pandas) - nflreadpy returns polars DataFrames; use polars syntax throughout
- **NFL stats:** nflreadpy (successor to deprecated nfl_data_py) - returns polars DataFrames
- **Front-end:** React + Vite + DuckDB (decided). Original plan was Dash + Plotly; switched after a vertical slice in the real stack validated it and proved easier to iterate than a chat artifact.
- **Data delivery (V1):** client-side DuckDB-WASM — the browser reads parquet and runs SQL; no server, static hosting only. A server/API was **deliberately deferred, not ruled out** — switch to one when warranted (multiple users, data too large to ship to the browser, or secrets to protect). The swap point is the front-end data-access layer `src/queries.js`; the view components never call data access directly, so moving "read files" → "call API" won't touch them.
- **Query layer:** DuckDB — SQL directly over parquet. Adopted as the query layer (in use now in the front-end); carries into the production app.
- **Market values:** LeagueLogs API (keyed on sleeperPlayerId; QB/RB/WR/TE only; visible attribution required)
- **Scheduling:** launchd (macOS) for daily fetchers
- **Storage:** JSON (cache), parquet (snapshots), JSONL (advisor log - future)
- **HTTP:** requests library

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
- **Standard lineup shape.** `compute_team_leakage.py`'s swap-class split (`QB` vs
  `FLEX`=RB/WR/TE) assumes QB-dedicated + standard flex; **superflex/2QB or TE-premium
  leagues mis-pair misses.** The optimal-lineup/efficiency calc (`_expand_slots`) is
  general; only the leakage miss-attribution carries this. (Moved with the analytics —
  this assumption now lives in the Python transform, not the JS seam.)
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

```
fantasy-ai/
├── project_management/
│   ├── TECHNICAL_ARCHITECTURE.md   (this file)
    ├── STATUS.md
    ├── PRODUCT_ROADMAP.md
    ├── PROJECT_OVERVIEW.md
│   ├── data_sources.txt
│   └── journal/
└── application/
    ├── frontend/                   # production front-end — React + Vite + DuckDB-WASM (Node)
    │   ├── src/                     #   App.jsx (tab shell), LeaguePanel/TeamPanel.jsx (views), queries.js (data-access layer), db.js (DuckDB-WASM loader), readiness.jsx (per-panel readiness gate), posColors.js
    │   └── public/data/             #   symlinks → season_2025 + teams_2025 + lineup_slots_2025 + team_form_2025 + team_leakage_2025 + player_signal_2025 parquet (gitignored)
    ├── data/
        ├── data_layer.py           # ✅ built — centralized read/write module
    │   ├── fetchers/               # one Python script per source (tracked in git)
    │   │   ├── nfl_stats.py        # ✅ built
    │   │   ├── sleeper.py          # ✅ built
    │   │   ├── leaguelogs.py       # ✅ built — daily market-value snapshots
    │   │   └── scheduler/          #   tracked launchd plist + README for the daily snapshot job
    │   │       ├── com.fantasyai.leaguelogs-snapshot.plist
    │   │       └── README.md
    │   ├── cache/                  # current state (gitignored)
    │   │   ├── player_id_map.parquet  # gsis_id → sleeperPlayerId mapping
    │   │   └── sleeper/
    │   │       └── players.parquet    # Sleeper /players/nfl registry, refreshed ≤ once/day — 10 cols incl. injury_status/depth_chart_order/practice_participation (Phase 1 refinement)
    │   └── snapshots/              # time-series parquet (gitignored)
            ├── derived/                                 # pre-computed analytics (compute_*.py output); tall, grain (season, as_of_week, entity)
            │   ├── team_form_2025.parquet               # per (as_of_week, team) trajectory: slope, direction, spectrum, weekly series
            │   ├── team_leakage_2025.parquet            # per (as_of_week, team) leakage: efficiency %, coachable/variance, named fixes
            │   └── player_signal_2025.parquet           # per (as_of_week, team, player) spike signal: opp vs efficiency split, regression_risk, read
            ├── leaguelogs/
            │   └── market_values.parquet            # daily market-value history, all profiles
            └── nfl_sleeper_weekly_joined/
                ├── season_2025.parquet                  # join output, all weeks appended (one file per season)
                └── 2025/
                    └── remainders_2025_w{week}.parquet      # unresolved players; empty = clean join
    │       └── nflreadpy/
    │           └── nfl_stats_2025.parquet  # 18,539 rows × 123 cols, weeks 1-18 (+xtd, redzone_touches — PBP quality signal, Phase 1 refinement)
            └── sleeper/
                └── 2025/
                    ├── teams_2025.parquet            # roster_id → team/owner names
                    ├── roster_positions_2025.parquet # raw league starting-lineup slot list
                    ├── lineup_slots_2025.parquet     # derived starting skill-slot requirements (optimal-lineup config)
                    └── ... # matchup and transaction parquet files for each week of the 2025 season
    ├── shared/                     # league detection, config loaders
    ├── transforms/ # one Python script per join/transform
        ├── _analytics.py              # shared pure helpers (round1, mean, median, spectrum_positions)
        ├── join_nfl_sleeper_weekly.py # ✅ built
        ├── audit_join.py              # ✅ built — resolves unknown-position remainders
        ├── derive_lineup_slots.py     # ✅ built — roster_positions → lineup_slots (starting skill slots)
        ├── compute_team_form.py       # ✅ built — EWMA trajectory analytics → derived/team_form
        ├── compute_team_leakage.py    # ✅ built — lineup-leakage analytics → derived/team_leakage
        ├── compute_player_signal.py   # ✅ built — spike signal-quality read (Phase 1) → derived/player_signal
        └── backtest_player_signal.py  # ✅ built — validates the shipped signal vs naive baseline on the full-2025 answer key
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
  write_sleeper_matchups, write_sleeper_players, write_player_id_map); they do not
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
| Sleeper | cache/ + snapshots/ | Matchup/roster/transaction state to snapshots/ (weekly history); player registry to cache/ (current state only, refreshed ≤ once/day) |
| nflreadpy | snapshots/ only | Weekly player stats - trend visualization requires history |
| LeagueLogs | snapshots/ only | Daily market-value snapshot of all profiles (redraft + dynasty). API serves only "now" (no history endpoint), so the value time-series exists only if we snapshot it. Keyed on sleeperPlayerId. |
| Odds API | cache/ only | Current week lines only needed for v1 |
| FantasyPros | cache/ only | Current projections and news only needed for v1 |

- internal
| nfl_sleeper_weekly_joined transform | snapshots/nfl_sleeper_weekly_joined/ | Joined output — one file per season (season_{season}.parquet), each week appended with a (season, week) dedup guard
| derive_lineup_slots transform | snapshots/sleeper/{season}/ | lineup_slots_{season}.parquet — starting skill-slot requirements (slot, count, eligible) derived from the league's raw roster_positions; declares the QB/RB/WR/TE + FLEX config so the front-end "perfect lineup" / efficiency calc is exact, not inferred |
| compute_team_form transform | snapshots/derived/ | team_form_{season}.parquet — **tall, grain (as_of_week, roster_id)** (Season-replay): per as-of week N=1..maxweek, one row per roster_id with the EWMA scoring slope, direction, recent record, league-relative spectrum pos, per-week series — all recomputed on weeks ≤ N. Pre-computed so the front-end seam just reads it (no JS trajectory math) |
| compute_team_leakage transform | snapshots/derived/ | team_leakage_{season}.parquet — **tall, grain (as_of_week, roster_id)**: per as-of week N, lineup efficiency %, season points-left, coachable/variance split, named fixes, per-week leak, spectrum pos — cumulative ledger over weeks ≤ N. Roster-as-of-N: a player's "current team" resolves to his latest week ≤ N. Feeds both the Team Overview leakage lens and the League drawer's efficiency read |
| compute_player_signal transform | snapshots/derived/ | player_signal_{season}.parquet — **tall, grain (as_of_week, roster_id, player)**: per as-of week N, one row per rostered skill player with the spike signal-quality read (Phase 1), recomputed on weeks ≤ N (roster-as-of-N applies). Decomposes recent production into sticky opportunity (opp_g, EWMA-windowed via injected half-life — ships cumulative, backtest-tuned) vs fragile efficiency (ppo, shrunk toward the league positional mean); headline regression_risk + a sample-gated read (too_early/spike/mixed/sticky), td_share as evidence, per-week series. The first decision-critique engine slice; not a forward projection. **Phase 1 refinement (2026-07-08):** four added fields close the DECISION_READS.md §1 gap — quality_rate (xtd_g/opp_g, the Quality axis from PBP td_prob), direction/reliability (Trust axis, from the player's own opportunity series), security (Trust's context flag, from Sleeper injury/depth-chart data), point_correlation (pearson(xtd, td_pts)). Kept separate from the validated core read, not fused in |

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
- `sleeper.py` - backfills + refresh modes
- `odds.py` - does not exist
- `fantasypros.py` - does not exist
- `weather.py` - does not exist
- `nfl_stats.py` - backfill + refresh modes, polars, player ID map
- `leaguelogs.py` - built; daily market-value snapshots (all profiles), scheduled by launchd at 4am ET

## nflreadpy Notes

Package version: 0.1.5
Key functions: load_player_stats(), load_snap_counts(),
load_team_stats(), load_ff_playerids()
All functions return polars DataFrames
player_id in load_player_stats() is gsis_id format ("00-0023459")
Snap count join path: load_snap_counts().pfr_player_id →
load_ff_playerids().pfr_id → gsis_id
Join coverage on nfl_sleeper_weekly_joined targets 100% of rostered skill-position players per week. The join is left-joined from Sleeper (authoritative), so players without nflreadpy stats that week (injured, inactive) appear with 0-stat rows rather than being dropped. The audit step resolves any remaining unknowns via the Sleeper player registry.

**PBP quality signal (added 2026-07-08, Phase 1 refinement):** `nfl_stats.py._load_pbp_quality(year)` calls `nflreadpy.load_pbp(year)` (a new function on the same package — not a new dependency) and aggregates nflfastR's per-play `td_prob` (expected-TD probability given down/distance/yardline/score/time) into per-(gsis_id, week) `xtd` (sum of td_prob over the player's rush attempts, targets, and pass attempts) and `redzone_touches` (yardline_100 ≤ 20). PBP player-id columns (`rusher_player_id`/`receiver_player_id`/`passer_player_id`) are already gsis_id format, matching every other join in this fetcher — no new id mapping needed. Filtered to `season_type == "REG"` (playoffs excluded), consistent with `_load_player_stats`. This is the Quality axis (DECISION_READS.md §1) feeding `compute_player_signal.py`'s `quality_rate`.

## sleeper.py Notes

Player IDs are strings (e.g. "2307") throughout - never cast to int. This is the sleeperPlayerId join key.
Offseason-safe week logic: season_type == "offseason" returns 18 completed weeks, not 0. season_type == "pre" is the only state that returns 0.
Cache files are JSON (league/user/roster state) or parquet (players registry). Snapshot files are parquet partitioned by season: snapshots/sleeper/<year>/
league_resolver.py is the only file that touches SLEEPER_USERNAME. The fetcher accepts league_id as a parameter only.
refresh() current-week snapshot writes will silently skip with an explicit log message during offseason - this is expected behavior.

players_points in matchup snapshots is stored as a serialized JSON string (map of sleeperPlayerId → points). Parse with json.loads before joining. Same applies to starters (JSON array of starter IDs).

fetch_players() caches the full Sleeper /players/nfl endpoint to cache/sleeper/players.parquet. Skips the network call if the cache is less than 24 hours old; pass force=True to override. Called automatically by refresh() and by audit_join.py when the cache is stale or missing. Can also be triggered standalone: python fetchers/sleeper.py fetch-players. Position values in this endpoint use Sleeper's internal codes: QB/RB/WR/TE for skill, K for kicker, DEF for defense.

**Injury/depth-chart fields (added 2026-07-08, Phase 1 refinement):** fetch_players() now also carries injury_status, injury_body_part, depth_chart_order, depth_chart_position, and practice_participation through to the cache — the endpoint already returns them, previously discarded. Feeds compute_player_signal.py's `security` read. **Gotcha:** these fields are null for most players in the sampled prefix polars uses for schema inference, which can pin the wrong dtype for a column that's stringy/numeric further down — fetch_players() passes `infer_schema_length=None` to pl.DataFrame() to force a full scan. This is "now" data only (no history), so the same value applies across every as_of_week slice for a given player — a documented simplification, not a bug.

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

**Next move (resilience + host migration):** add per-request retry/backoff so a transient timeout doesn't abort a run, and move the schedule off the laptop to an always-on host (Raspberry Pi or cloud cron). Laptop-sleep coalescing also costs days, so retry alone isn't sufficient — host migration is the other half of the real fix.

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
  normaliser — the Python mirror of the front-end's old `attachSpectrumPos` — and
  `pearson`, added for the Phase 1 point-correlation refinement) live once in
  **`transforms/_analytics.py`** rather than being copy-pasted per transform.

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

  **Phase 1 refinement (2026-07-08):** closes the DECISION_READS.md §1 delta between the
  shipped engine and the full Opportunity spec — four fields added, kept separate from
  the validated core read ("don't collapse the axes"). `quality_rate` (`xtd_g/opp_g`,
  the Quality axis — expected TDs per touch, independent of Volume) is computed inside
  `_player_signal` from the new `xtd` PBP aggregation (see nflreadpy Notes), so the
  backtest exercises it too. `direction`/`reliability` (the Trust axis) and
  `point_correlation` are computed in `_compute_as_of` from the raw per-week series —
  `direction` mirrors `compute_team_form.py`'s weighted-least-squares-slope +
  `DIRECTION_BAND` pattern (own constant `DIRECTION_HALF_LIFE_WK`, independent of
  `OPP_HALF_LIFE_WK`); `reliability` is `1/(1+cv)` on the weekly opportunity series;
  `point_correlation` is `pearson(xtd, td_pts)` (new shared helper in `_analytics.py`),
  read against `quality_rate` per the spec (low correlation + high quality = unlucky;
  low + low = correctly cheap). `security` is a categorical context flag (not a
  numeric trend) from a new `_security_map()` built once per `compute(season)` call
  from `data_layer.read_sleeper_players()` — "now" data, so it's constant across every
  as_of_week slice for a given player. None of this touches `expected_ppg`/
  `regression_risk` — the 2025 backtest gate is unchanged (PASS/PASS, 13.2% MAE cut).

- `backtest_player_signal.py` — **the validation gate Phase 1 must clear before any
  engine ships live.** Imports the *same* pure `_player_signal` the transform ships
  (no parallel re-derivation that could drift) and tests it against the full-2025
  answer key: input = a recent window (default wks 1–4), truth = rest-of-season
  per-game PPR. Two verdicts — *predictive* (does the signal beat a naive
  "recent-points-carry-forward" baseline on MAE/RMSE/corr?) and *decision-relevant*
  (among hot players, which the naive read can't tell apart, does the `spike` group
  regress more than the `sticky` group?). Exits 0 only if both pass. Current 2025
  result: signal cuts rest-of-season MAE ~13% at the W4 freeze (PASS at every freeze
  W3–W8); hot `spike` group regressed ~3.9 pts/g while `sticky` held flat. This
  backtest-against-the-answer-key pattern is the template for every future engine slice.
  **`--sweep`** tunes the opportunity EWMA half-life against the answer key at any freeze
  (and `--opp-half-life` overrides the verdict run); the 2025 sweep across W4/W6/W8 chose
  **cumulative** (short half-lives hurt rest-of-season MAE — opportunity is sticky enough
  that max sample wins), which is why `OPP_HALF_LIFE_WK` ships `None`.

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