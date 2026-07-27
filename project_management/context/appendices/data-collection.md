# Appendix: Data Collection

**Scope:** the fetchers, the collection cadence, and the reliability story. Referenced from `ARCHITECTURE.md`.
Making collection reliable off-laptop is V1 project **P1**.

## Sources & fetchers (one fetcher per source, `application/data/fetchers/`)

| Source | Fetcher | Provides |
|---|---|---|
| **Sleeper** | `sleeper.py` | Rosters, matchups, transactions, weekly projections, league config, cross-league manager activity |
| **nflreadpy** | `nfl_stats.py` | Weekly player box scores + ff_opportunity expected-points components + preseason ADP |
| **LeagueLogs** | `leaguelogs.py` | Daily market-value snapshots (the trade-value signal) |
| **NFL team news RSS** | `news.py` | 96 feeds (32 teams × 3 sources) — the situation-news input for the AI ROS read |
| The Odds · FantasyPros · weather | — | **Not built yet** (overlay sources; in-season adds) |

**Primary sources:** nflreadpy, Sleeper, LeagueLogs. **Overlay (future):** The Odds, FantasyPros, weather,
NextGen.

## Two storage patterns

- **`cache/`** — current state, overwritten each fetch.
- **`snapshots/`** — append-only time-series. These are **"bank it or lose it"** — the APIs don't serve their
  history, so a missed day is a permanent hole.

## Cadence

- **Daily collectors** (must be banked): LeagueLogs market values ~4am ET, news RSS ~5am ET.
- **On demand** (not scheduled): Sleeper + nflreadpy are pulled when a build runs, then frozen into the
  derived store.

## The reliability problem (why P1 exists)

The daily collectors run on **the owner's laptop via macOS launchd**. Over the audited window that yielded
**~63% complete / ~71% any-data** coverage — roughly 8 laptop-off days + 7 no-retry days. Because the daily
series can't be backfilled, every off day is unrecoverable. The cache also **doesn't record a fetch
timestamp** — a `metadata.json` sidecar is needed before in-season use.

**Fix (V1 P1):**

- **S1 — built + locally verified.** An env-selected storage backend in `data_layer` (`SNAPSHOT_BACKEND`:
  `local` for the laptop, `supabase` for CI) lets the *same* collectors write to a durable **Supabase Storage**
  bucket (S3-compatible, via `boto3`) on a diskless runner; a **GitHub Actions** workflow
  (`.github/workflows/collectors.yml`) runs the two collectors through the `run.py` dispatcher on independent
  daily crons. Neither collector needs auth (open LeagueLogs API + public RSS) — the *only* secret is the
  storage-scoped S3 credential. **Go-live is gated on creating the bucket + setting the CI secrets + proving one
  hosted run**; the laptop `launchd` jobs retire only after that (no gap) — cutover runbook in
  `application/data/fetchers/scheduler/README.md`.
- **S2 — remaining.** The `metadata.json` fetch-timestamp sidecar, retry/backoff, a daily coverage alert, and a
  2-week soak to prove **≥95%** coverage.

This is a pilot go/no-go gate and gates the live market read (P2) and the live AI outlook (P4).
