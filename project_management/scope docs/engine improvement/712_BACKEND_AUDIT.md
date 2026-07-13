# 712 Backend Audit — "Can this engine get better over time?"

**Created:** 2026-07-12 · Scope: the whole backend engine (fetchers → data_layer → transforms → ai),
audited against **one question**: *what stops the engine's output from improving as more users, NFL
weeks and leagues run through it?*

This is **not** a code-quality audit (the 710 audit did that; all 7 items are closed). The code is in
good shape. This audit is about a **capability the system does not have**, and about three latents
that will fire the moment you add league #2.

Companions: [`scope docs/IMPROVEMENT_LOOP.md`](../scope%20docs/IMPROVEMENT_LOOP.md) (the architecture)
and [`scope docs/PILOT_2026.md`](../scope%20docs/PILOT_2026.md) (the test plan).

---

## The one-paragraph verdict

The engine is **well-built and unable to learn**. Every read is validated once, offline, against a
single frozen answer key (2025), by a gate that prints to stdout and remembers nothing. Every derived
parquet is a **full-season overwrite**, so the moment you re-tune a constant, the engine's own history
is rewritten — there is no record of *what the engine actually said, at the time it said it, under the
code that was running*. Without that record you cannot measure improvement, cannot detect a regression
you caused yourself, and cannot honestly tell a user how much to trust a read. **The missing piece is
not an algorithm. It is a ledger.** And the ledger has a deadline: anything week 1 of 2026 produces
that you don't record is gone for good.

---

## What's genuinely strong (build on it, don't rebuild it)

Stated plainly because the architecture below is an *extension* of this discipline, not a correction:

- **Gates import the shipped pure function.** Every `backtest_*` imports `_player_signal`,
  `_projection_band`, `_win_prob` etc. from the production transform — what's validated is exactly
  what serves. No parallel re-derivation that can drift. This is the single best decision in the
  codebase and the whole loop leans on it.
- **Leak discipline is real.** Input windows are strictly before truth windows; `adp_points_curve`
  holds out the target season; the `as_of_week` tall grain is an honest reconstruction.
- **Honesty columns are first-class**, not comments: `is_cross_time`, `anchor_is_prior_season`,
  `has_ros_anchor` / `has_news`, `signal_tier`, `is_zero_signal`, null-when-undefined (law 2). The
  ledger design below reuses this idiom directly.
- **Two entities are already append-only ledgers** — `leaguelogs/market_values` (101,292 rows,
  dedup-by-`snapshot_date`) and `news/team_news_raw` (append-only-of-new by `article_id`). The
  pattern the engine needs already exists in the codebase; it just was never applied to *the engine's
  own output*.
- **`fetchers/run.py`'s "the meter stays external"** is exactly the right host-agnosticism. The loop's
  jobs register in the same place.

---

## S1 — Blocks the loop entirely · *unrecoverable if not fixed before 2026 week 1*

### S1.1 — There is no prediction ledger. Derived reads are overwrites.

Every `data_layer.write_*` for a derived read is documented `(overwrite)`. Verified across all 14
derived parquets.

The `as_of_week` tall axis **looks** like a point-in-time record and is not one. It answers *"what
would **today's** code say about week 5?"* — a **reconstruction**. It does not answer *"what did the
code that was **running** in week 5 actually say?"* — a **record**. Both are needed and only the first
exists:

| | reconstruction (`as_of_week`) | record (missing) |
|---|---|---|
| Answers | what would today's engine have said | what the engine did say |
| Survives a re-tune | **no** — it's recomputed | yes — immutable |
| Use | backtest a candidate change | measure improvement, detect self-inflicted regressions, report honest accuracy to a user |

Consequences, concretely:

- Re-tune `BAND_Z` → `projection_consensus_2025.parquet` is rewritten end-to-end. The numbers the user
  saw last week no longer exist anywhere.
- "Is the engine better than it was in September?" is **unanswerable**, because September's engine
  output has been overwritten by October's engine.
- A regression you introduce is invisible: nothing compares run N to run N−1.

**This is the critical path item.** Weeks are not recoverable.

### S1.2 — No code/constant provenance on any derived row.

Of 14 derived parquets, **12 carry zero provenance**. The two AI ones carry `model` + `generated_at`
and nothing else. There is no git sha, no constants hash, no prompt version, anywhere.

So even if history were preserved, a metric move could not be **attributed** — you'd see the number
change and not know whether the cause was new data, a constant you changed, a prompt you edited, or a
degraded feed.

### S1.3 — Single-league keying. League #2 silently overwrites league #1.

`config.SLEEPER_LEAGUE_ID` is one string. Every league-scoped entity is keyed by **season only**:

```
derived/production_vor_{season}.parquet      ← no league_id
derived/true_rank_{season}.parquet           ← no league_id
sleeper/{season}/teams_{season}.parquet      ← no league_id
nfl_sleeper_weekly_joined/season_{season}.parquet
```

Scope split as it stands today (verified against the persisted columns):

| Layer | Entities | Today |
|---|---|---|
| **NFL-global** (shared by every league) | `nfl_stats`, `projections`, `adp_preseason`, `adp_points_curve`, `market_values`, `team_news_raw`, `team_news_dossier`, `player_news_slice` | correct as-is |
| **Scoring-scoped** (one per distinct scoring profile) | `projection_consensus`, `ros_synthesis` | **stored as if global — see S3.1/S3.2** |
| **League-scoped** (one per league) | `player_signal`, `production_vor`, `market_vor`, `ros_outcome_shape`, `true_rank`, `positional_depth`, `bracket_odds`, `team_form`, `team_leakage`, `manager_features`, `manager_dossiers`, `manager_activity` | **no `league_id` key — collides** |

Your stated 2026 plan (several of your own leagues + a friendly test group) breaks the store on day
one. This blocks the ledger too — a ledger row with no `league_id` is worthless.

---

## S2 — Makes the numbers dishonest · *fix before you trust or publish them*

### S2.1 — Every tuned constant is fit and certified on the same data.

Five constants were swept on the 2025 answer key and gated on the 2025 answer key. **In-sample.**

| Constant | Value | Fit on | Certified on |
|---|---|---|---|
| `BAND_Z` (§3 band width) | 0.55 | 2025 | 2025 |
| `SKEW_GAIN` (§3 skew) | 1.5 | 2025 | 2025 |
| `BULL_Z` (§2 ROS width) | 1.44 | 2025 | 2025 |
| `ANCHOR_W` (§2 preseason anchor) | 0.25 | 2025 | 2025 |
| `OPP_HALF_LIFE_WK` (§1 window) | `None` (cumulative) | 2025 | 2025 |

Your headline gate figures — band coverage 0.493, ROS coverage 0.817 with 0.091/0.091 tails, signal
MAE −13.2% vs naive — are therefore **optimistic by an unknown margin**. That's not a criticism of the
method (the sweeps are principled and the comments are scrupulous); it's a statement about what a
single-season fit can prove, which is less than the gate output implies.

**And the fix is free and available today.** `nfl_stats` is already backfilled **2020–2024**. Every
player-level read (§1 signal, §3 consensus band, §2 ROS shape) can be cross-validated season-wise —
fit on 2020–2023, certify on 2024 — *before 2026 kicks off*. If a constant collapses out-of-sample,
you want to know that in July, not in October. **This is the highest-value, lowest-cost item in the
entire audit.**

### S2.2 — Every league-level gate is n=10.

`true_rank` (Pearson 0.802, n=10 teams), `positional_depth` (n=10 per position), `bracket_odds`
(Brier 0.224 over **70 independent matchups** — verified: 75 regular-season matchups exist in
weeks 1–15; the gate scores weeks 2–15, and pools them across as-of weeks 1–4, which *nests* the same
matchup up to 4× rather than adding independent evidence). These are directionally encouraging and
statistically thin: a reliability curve over 70 events gives bins of ~15 — enough to see a shape, not
enough to trust one.

**RESOLUTION PATH (added 2026-07-12): backfill, not recruitment.** A *completed* league-season is a
fully-resolved answer key, and Sleeper serves historical projections (**verified**: 2021 wk5 returns a
full populated `pts_ppr` board) — so the whole read spine is backfillable. Harvesting ~10 leagues × 5
seasons takes n from **10 team-seasons / 75 matchups** to **~500 / ~3,750**, offline, before kickoff,
with zero users. See [`scope docs/LEAGUE_CORPUS.md`](../scope%20docs/LEAGUE_CORPUS.md). This retires
S2.2 *and* most of S2.1 before the season starts.

### S2.3 — The AI layer is never graded against outcomes.

`check_ros_synthesis` / `check_manager_dossiers` / `check_team_news_dossier` are **internal-consistency**
gates: coverage, schema, grounding, confidence-honesty-vs-*inputs*, prose-leak. They are good at what
they do. **None of them asks whether the grade was right.**

But `bull_grade` / `bear_grade` / `situation_grade` **are predictions** — ordinal claims about ROS
ceiling, floor and stability. They're gradeable against the same 2025-style answer key as everything
else, and nothing grades them. There is also **no `prompt_version` column**, so you cannot A/B a prompt
even if you wanted to — and the STATUS doc explicitly expects the prompt text "to keep evolving."

### S2.4 — Confidence is the project's spine and the one thing with no metric.

Law 2 is *"speak only when confident."* The engine emits confidence in at least five forms —
`confidence` (ros_synthesis), band width (§3), `ros_cv` (§2), `signal_tier` (news), `depth_tier` (§7),
`reliability` (§1). **Not one of them is ever checked against realized error.**

A confidence signal that does not sort by error is worse than no confidence signal: it launders noise
as caution. This should be the **first metric the loop computes** and the one that gates whether a read
is allowed to speak at all.

---

## S3 — Correctness latents that multi-league will expose

### S3.1 — `projection_consensus` is scoring-dependent, stored scoring-agnostically.

`compute_projection_consensus.compute(season, scoring=None)` defaults to the league's real
`read_scoring_settings(season)`, and the custom-scoring engine re-scores the centers. The output goes
to `derived/projection_consensus_{season}.parquet` — **no scoring key in the path or the columns**.

Add a half-PPR league and it overwrites the PPR league's consensus. Silent wrong output for whichever
ran first — no error, no flag. Everything downstream (VOR → true rank → depth → bracket → ROS shape)
inherits it.

### S3.2 — `ros_synthesis` fuses a league-scoped anchor into an NFL-global entity.

`ros_synthesis` is keyed `(season, week, sleeper_player_id)` — no `roster_id`, i.e. one row per player
league-wide. But its anchor carries (`ros_bull`, `ros_bear`, `ros_cv`, `spectrum_pos`, `security`) come
from `ros_outcome_shape`, which **is** league-scoped (roster membership, league pools from
`lineup_slots`, league scoring).

One player, one row, two leagues, two different valid anchors. Harmless at n=1 league; silently wrong
at n=2. **Fix shape:** split `ros_outcome_shape` into a *scoring-scoped player band* (center / bull /
bear / sigma / cv — needs no roster) and a *league-scoped VOR view* (spectrum vs league pools, roster
membership). Then `ros_synthesis` reads the scoring-scoped half and legitimately stays shared — which
also keeps its API cost **flat as leagues grow** (see below).

### S3.3 — Doc/code drift on a tuned constant (the registry's raison d'être).

`STATUS.md`'s built log states *"BULL_Z swept to 1.645."* The code says `BULL_Z = 1.44` — re-swept
jointly with `ANCHOR_W` during the ADP-anchor build; the log entry wasn't updated. Harmless today. It
is also **exactly** the failure the constant registry (IMPROVEMENT_LOOP §4) exists to prevent: a
tunable with no single source of truth, no `fitted_on`, no `last_tuned`.

---

## S4 — Operational

- **Collector coverage is 65%.** `check_collectors.py` reproduces it over the 41-day LeagueLogs series
  (~8 laptop-off days, ~7 pre-retry failures). Retry is fixed; **the host is not.** Every accuracy
  metric computed over a degraded week is uninterpretable — which is why coverage is a **precondition
  layer** in the architecture, not a fourth improvement channel. A trust report that says "calibration
  fell in week 9" while the real cause was three missing market days is a report that teaches you the
  wrong lesson.
- **No test suite, no CI.** The 10 gates *are* the test suite — but they are hand-invoked, print to
  stdout, and **persist nothing**. There is no gate history, so a regression introduced three sessions
  ago is invisible today.
- **Known O(n²) read-modify-write** (710 audit #2, consciously deferred as the migration trigger). Note
  precisely: **the prediction ledger is the entity that will trip it** — append-only, growing every
  week, multiplied by N leagues. Design it behind `data_layer` so the parquet → DuckDB/SQLite swap is
  an internal change and nothing upstream notices.

---

## Cost note (good news, worth knowing before the pilot)

Measured from the shipped runs: `ros_synthesis` ≈ **$0.0044/player** (16 players ≈ $0.07);
`team_news_dossier` ≈ **$0.46 per full 32-team week**; `manager_dossiers` ≈ **$0.025 per league-season**.

Extrapolated to a full NFL skill pool (~967 players in the news slice):

| Item | Per week | Per 18-wk season | Scales with |
|---|---|---|---|
| ros_synthesis (full pool) | ~$4.25 | ~$77 | **weeks only** (scoring-scoped) |
| team_news_dossier | ~$0.46 | ~$8 | **weeks only** (NFL-global) |
| manager_dossiers | — | ~$0.03/league | leagues |
| **Total** | **~$5** | **~$85 + $0.03/league** | |

**The AI layer is essentially free to scale across leagues** — provided S3.2 is fixed so it stays
scoring-scoped. Even a champion/challenger prompt A/B (2× cost) is ~$170/season. Cost is not a
constraint on the pilot; it should not shape any decision.

---

## The finding in one line

> You have built an engine that can be *validated*. You have not built one that can *learn*. The
> difference is a ledger, and the ledger has a kickoff deadline.
