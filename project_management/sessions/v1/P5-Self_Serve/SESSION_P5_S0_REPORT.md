# P5 · S0 — The cold-league latency spike — report

**Ran:** 2026-07-31 · **Brief:** `SESSION_P5_S0_LATENCY_SPIKE.md` · **Commits:** 3 ·
**Harness:** `application/data/serve/bench_cold_league.py` (re-run it unchanged on the worker in S3)

---

## The verdict in one paragraph

**Connecting a league is cheap; building its Manager Dossier is not.** A cold, never-before-seen
league goes from nothing to loadable in **10.3 seconds** (full 2025 regular season) or **~3.8
seconds** for a Week-1 2026 shape — but the Manager Dossier's cross-league fan-out adds **80.3
seconds and 248 more Sleeper calls**, eight times the entire rest of the pipeline. So the answer to
"spinner or notification" is neither: **ship the four fast surfaces on a spinner in ~10s, and fill
the dossier in behind its own progress state.** The whole chain is **network-bound, not
compute-bound** — the only CPU-bound stage is the spine, and it costs 0.6s. **Buy RAM, not CPU:**
a 1 GB `shared-cpu-1x` worker with a 1 GB volume, ~$7/month, and it stays ~$7/month at 200 leagues.

---

## What was measured

Two genuinely cold leagues — real strangers' 2025 PPR 1QB 12-team redraft leagues, drawn from the
2,451 leagues `corpus_discovery` found but never harvested, each asserted absent from
`leagues.parquet`, `demo_manifest.parquet` and all three on-disk league directories before the clock
started.

| | Run A — full season | Run B — capped at week 1 |
|---|---|---|
| league | `1266907939122200576` | `1258181662160719872` |
| weeks | 1–14 (whole regular season) | 1 |
| **total wall** | **10.35 s** | **8.43 s** |
| total CPU | 3.64 s | 1.92 s |
| peak RSS | 382.7 MB | 214.9 MB |
| store growth | 0.76 MB | 0.38 MB |
| Sleeper calls | 41 | 41 |

### Per step (Run A, the pessimistic bound)

| stage | wall s | cpu s | cpu/wall | verdict |
|---|---|---|---|---|
| fetch | 6.97 | 1.53 | 0.22 | **I/O-bound** — 41 calls, 6.78 s of network |
| join | 0.25 | 0.65 | 2.64 | CPU, parallel, negligible (14 weeks) |
| band | 0.00 | 0.00 | — | skipped: 2025 < `FIRST_HONEST_BAND_SEASON` |
| spine | 0.62 | 1.11 | 1.79 | **the only CPU-bound stage** |
| schedule | 0.01 | 0.01 | — | negligible |
| load | 2.50 | 0.34 | 0.14 | **I/O-bound** — 15,230 rows to Supabase |
| **total** | **10.35** | **3.64** | | |

Spine split: `bracket_odds` 0.32 s · `player_signal` 0.22 s · `production_vor` 0.06 s ·
`positional_depth` 0.01 s · `true_rank` 0.01 s. The 10,000-sim Monte-Carlo everyone expected to
dominate is fully vectorised and costs **0.02 s per as-of week**.

### How it scales with season depth

The spine is the only thing that grows with weeks, and it grows at **~0.038 s per week** (0.62 s at
14 weeks vs 0.13 s at 1). Fetch is 5 fixed calls (0.68 s) + 2 calls per week (0.68 s/week). So:

- **A Week-1 2026 connect — the actual launch case — is ~3.8 s**: 1.4 fetch + 0.06 join + ~0.2 band
  + 0.13 spine + 0.01 schedule + 2.0 load. (`sleeper.backfill` has no week cap, so Run B's measured
  fetch pulled all 18 weeks anyway; the 1.4 s is derived from the per-call log, not assumed.)
- **A mid-season connect is ~10 s.** Depth is not the cost driver anyone feared.

### The Manager Dossier chain — the finding that changes S4

`compute_spine._compute_league` produces five reads and **four** of the app's five surfaces. The
Manager Dossier needs a separate cross-league fan-out that no one had costed:

| stage | wall s | cpu/wall | calls |
|---|---|---|---|
| `manager_activity` | **80.34** | 0.12 | **248** |
| `manager_features` | 0.01 | — | 0 |
| dossier AI write | *not run* | — | **12 Haiku calls** (one per manager — counted, not spent) |

50 s of those 80 s are the deliberate 0.2 s politeness throttle across 248 calls. **A bigger machine
buys exactly nothing here** (cpu/wall 0.12). The lever is the throttle and Sleeper's patience, not Fly.

---

## The three recommendations

### 1 · Machine size — 1 GB `shared-cpu-1x` + a 1 GB volume

- **RAM: 1 GB.** Peak RSS was 383 MB, driven by the load stage's polars frames, not the simulation.
  512 MB would work today with no headroom for a deeper league or a concurrent read; 1 GB is one
  step up and ~$5/month.
- **CPU: shared, 1×.** Total CPU for a whole cold league is 3.6 s. Nothing here justifies dedicated
  cores; the two heaviest stages are both waiting on a network.
- **Volume: 1 GB** (Fly's minimum, and ~4× what is needed). A league costs **0.76 MB** all in. The
  working set under the P5 brief's store-ownership rule is ~245 MB; 200 leagues adds ~150 MB.
- **Separate Fly app from the API**, per the P5 brief — the API is scale-to-zero and 256 MB, and it
  ships an image with no `data/` package and no polars. The worker is a different image, and the
  volume pins it to one host anyway.

### 2 · Spinner or notification — **both, staged**

Against the brief's thresholds (<~90 s spinner · ~90 s–10 min leave-and-return · >10 min
notification):

| what the user is waiting for | time | verdict |
|---|---|---|
| Players / Teams / League / Matchups (Week-1 shape) | **~3.8 s** | **spinner** |
| the same, mid-season | **~10 s** | **spinner** |
| \+ Manager Dossier | **~91 s** | straddles the line — **its own progress state** |
| \+ P4's AI outlook (not yet wired) | unmeasured | re-measure when P4 lands |

The measurement argues for a **staged connect** rather than one bar: the dashboard is usable in ten
seconds, and the dossier — which is an enrichment, not the product — arrives behind a "still
gathering manager history" state. That is both the better UX and the honest one: a single 91-second
spinner would be a progress bar that spends 88% of its life on one surface the user did not ask for
first. It also means the connect flow never sits in the awkward 90-second band where a spinner lies
and a notification is overkill.

### 3 · Compute caps — honestly, this is a rounding error

Fly: ~$5/GB RAM/month, $0.15/GB/month volume.

| connected leagues | onboarding compute | weekly refresh | worker cost |
|---|---|---|---|
| 10 | 15 min one-off | ~2 min/week | **~$7/mo** |
| 50 | 76 min one-off | ~13 min/week | **~$7/mo** |
| 200 | 5 h one-off | ~50 min/week | **~$7/mo** |

One always-on 1 GB machine is ~$5 RAM + ~$1.94 base + $0.15 volume ≈ **$7/month flat**, and the
work is so far under the machine's duty cycle that league count does not move it. **The bill does
not become a real number until several hundred leagues** — and even then the next constraint is
Sleeper's API and the single volume-pinned worker, not money. Recommended caps, set for blast
radius rather than cost:

- **Per user: 5 connected leagues.** Not a cost control — a bound on the dossier fan-out, which is
  the only expensive thing a single user can trigger.
- **Global: 100 jobs/day.** 200 full connects is 5 hours of a 24-hour worker; 100/day keeps the
  queue drainable inside a day even at the 91-second full-dossier cost.
- **Sleeper burst: no extra limiter needed yet.** A full connect is 289 calls against Sleeper's
  ~1000/min ask, and S4's design (one worker, one job leased at a time) already caps the process at
  ~5 calls/second. The rate limit becomes real only if the worker ever goes concurrent.
- **AI: 12 Haiku calls per league at dossier time**, one per manager. Cap it there; it is the only
  per-league cost that is metered per token rather than per second.

---

## Shared substrate — verified, not assumed

**It is genuinely shared.** After both cold leagues ran end to end, all **133** watched files —
`leagues.parquet`, `demo_manifest.parquet`, and every file under `derived/scoring/` and
`derived/adp_points_curve/` — were **byte-identical** to their pre-session sha256. Two leagues
consumed the ppr substrate without rebuilding a byte of it.

**Building it costs 0.42 s** for 2026 ppr + half together. So the "first league on a new scoring
key" penalty is *not* an order of magnitude — it is under half a second, and it does not need a
product decision. Onboarding a league on an unseen `cust-…` key is a fraction of a second of extra
work, though the harness currently refuses it rather than building it inline (see finding 3).

**One caveat, fully chased down.** Rebuilding the 2026 substrate changed the *bytes* of
`projection_consensus_2026.parquet` for both keys — the harness's own guard caught it. It is **row
order only, and the values are unchanged**:

- twice-run rebuilds are **sorted-equal** on `(season, week, sleeper_player_id)`, which is a unique
  key (0 duplicate rows), so sorted equality *is* value equality;
- `ros_player_band_2026.parquet` — which is **computed from** the consensus — is **byte-identical**
  for both keys across the entire session;
- all 8 consensus inputs are unchanged in the tree comparison;
- `check_forward_substrate` **passes**.

Nothing serves 2026 yet, so the blast radius is nil. But it matters for **S3**: a checksum-based
sync of `derived/scoring` to the worker volume will re-upload `projection_consensus` on every run
even when nothing changed. Compare sorted content, or accept the re-upload (it is 110 KB).

---

## Findings for later sessions

1. **There is no cold-onboard entry point — S4 has to build one.** `weekly_refresh.refresh_league`
   *advances* a league that already exists: its fetch stage calls `sleeper.refresh`/`backfill` and
   never `fetch_league_config` / `fetch_roster_positions` / `derive_lineup_slots` / `fetch_teams`.
   The cold half lives in `corpus/harvest._pull_raw`, a corpus-batch module. The connect flow needs
   a real one; this harness composes the same steps in the same order meanwhile.
2. **`weekly_refresh._resolve_scoring_key` would silently mis-score a stranger's league**
   ([weekly_refresh.py:42](application/data/serve/weekly_refresh.py:42)). A league absent from
   `demo_manifest` falls back to `data_layer._active_league(season)[1]` — *the owner's* key. Every
   user's league is absent from `demo_manifest` until S4 catalogs it, so this is on the live path.
   The fix is the one the harness uses: derive from the league's own settings via
   `_keys.scoring_key_from_settings`. **S4/S5.**
3. **`build_db.load_league` hard-exits without a `demo_manifest` row, and there is no unload.**
   ([build_db.py:433](application/data/serve/build_db.py:433)) So S4's connect flow must write the
   catalog row *before* it can load, and S6's failure drills need a teardown path — the harness's
   `--teardown` covers the store side but not Postgres.
4. **`sleeper.backfill` has no week cap.** A preseason or Week-1 connect still pulls all 18 weeks
   (41 calls instead of 7). Harmless today, trivially wasteful at cohort scale — a cheap S4 fix.
5. **The pipeline cone imports without `config.py`.** The only `from application import config` in
   everything this harness touches is inside `sleeper.py`'s `__main__` CLI dispatch, unreachable
   from library use. Good news for S3: no config plumbing needed on the worker.

---

## What this measurement is not

**It was taken on a laptop.** It licenses an order of magnitude and — more usefully — the *shape* of
the split: which stage dominates, what scales with what, and what a bigger machine would and would
not fix. It is not a number that transfers to Fly. Two things will move there: Supabase network
latency from `iad` (probably *down* — the load stage is 2.5 s of network from a home connection),
and single-core throughput (probably *up* in wall-clock, but the spine is 0.6 s so it will not
matter). **S3 re-runs `bench_cold_league.py` unchanged on the worker** and the two JSON reports
diff directly.

Also unmeasured, deliberately: the `COMMIT` of the load (the transaction is rolled back — sub-second
for 15 k rows), `nfl_stats.refresh()` (shared, not per-league), the AI dossier write (counted at 12
calls, not spent), and P4's ROS synthesis (not wired for live news yet).

---

## The store was left as it was found

| check | result |
|---|---|
| both scratch leagues removed | ✓ 109 files removed; `assert_cold` re-passes for both |
| snapshots + cache tree | ✓ **15,254 files before → 15,254 after**, all sizes identical except the two below |
| Postgres | ✓ **all 15 table row counts identical** — the load transaction was rolled back, never committed |
| registry + catalog | ✓ `leagues.parquet` and `demo_manifest.parquet` sha256 unchanged |
| frozen corpus | ✓ untouched — `--substrate` refuses any season below `FIRST_HONEST_BAND_SEASON`; no `corpus/`, `ledger` or `_constants` change in the diff |
| `derived/scoring` | 131 of 133 files byte-identical; **2 changed by the deliberate 2026 rebuild, values proven unchanged** (above) |

### Both new guards were proven to bite

- `--substrate --season 2025` → *"refusing to rebuild substrate for 2025: below FIRST_HONEST_BAND_SEASON
  (2026) is the FROZEN CORPUS…"*
- `--league <the demo is_mine league>` → *"is NOT cold — present in: leagues.parquet,
  demo_manifest.parquet, raw_sleeper…, joined…, derived…"*

And the cold/warm distinction the headline rests on is evidenced, not asserted: re-running Run A's league
with `--allow-warm` gave **fetch 0.00 s and join 0.00 s** against 6.97 s / 0.25 s cold. The gates are what
a warm re-run measures — which is exactly why the brief insisted on a cold league.
