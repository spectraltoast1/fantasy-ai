# The League Corpus — Spec

**Created:** 2026-07-12 · **Status:** proposed (design only)
**Companions:** [`IMPROVEMENT_LOOP.md`](./IMPROVEMENT_LOOP.md) · [`PILOT_2026.md`](./PILOT_2026.md) ·
[`LLM context/712_BACKEND_AUDIT.md`](../LLM%20context/712_BACKEND_AUDIT.md)

---

## The idea in one line

> **A completed league-season is a fully-resolved answer key.** Harvesting them is a *backfill*
> operation, not a *recruitment* operation — which means the statistical power problem in the audit
> (S2.2: every league-level gate runs at n=10) can be solved **before 2026 kicks off**, with **zero
> users, zero support burden, and zero live-serving risk.**

This changes the shape of the whole project. It cleanly separates the two axes:

| Axis | Operation | When | Cost |
|---|---|---|---|
| **Leagues** | `add_league(league_id, seasons)` — backfill + grade | any time, idempotent | **O(league)** |
| **Weeks** | `advance_week(season, week)` — all registered leagues | live, 2026 | O(leagues) |

---

## Keystone dependency — **VERIFIED**

The entire corpus rests on one question: *does Sleeper serve **historical** weekly projections?*
Everything downstream of `projection_consensus` needs them:

```
projections → projection_consensus → production_vor → { true_rank, positional_depth, bracket_odds }
                                                     → ros_outcome_shape
```

**Probed 2026-07-12:** `GET api.sleeper.com/projections/nfl/2021/5?season_type=regular&position[]=RB&order_by=pts_ppr`
returns a **full populated board** — `pts_ppr` 22.2 / 20.41 / 19.15 / 18.94 … descending, ~83 KB.

**Historical projections exist back to at least 2021.** So the **entire read spine is backfillable**, not
just the transaction-only reads.

> **Open (2-minute check, worth ~20% more corpus):** probe **2020**. Your `nfl_stats` backfill already
> covers **2020–2024 + 2025**, so if 2020 projections exist the corpus window is *exactly* the window you
> already hold NFL stats for — six seasons, no extra fetching.

---

## You already own most of the harvester

The §7 Manager Dossiers work built the crawl primitives without meaning to:

| Existing | Does |
|---|---|
| `sleeper._manager_leagues(owner_id, season, seasons_back)` | every league a manager played, across N seasons |
| `_manager.classify_league(league)` | the full comparability signature — `scoring_profile` / `num_teams` / `qb_structure` / `league_format` / `waiver_budget` — **from the `/user/{id}/leagues` payload, with no extra API call** |
| `_manager.is_comparable` / `select_comparables` | filter by profile |
| `fetchers/_http.py` | retry / backoff / **throttle** / per-item isolation |

**Your "6 degrees of separation" crawl is a breadth-first search over functions that already exist:**

```
seed leagues → /league/{id}/rosters → owner_ids
             → _manager_leagues(owner_id, season, seasons_back)   ← already built
             → classify_league()                                   ← already built, free
             → keep those matching the target matrix
             → recurse to depth D
```

The new code is the **BFS driver, a corpus registry, and de-duplication.** That's small.

*Walk a single league backwards through seasons via the league object's `previous_league_id` edge
(verify the field on a real payload — a redraft league gets a fresh `league_id` each year).*

---

## Harvest the corpus as a **matrix**, not a pile

> **This is the most important strategic point in this doc.**

Your any-league generalisations — `_analytics.position_pools` (superflex), `_scoring` (custom /
TE-premium), `compute_bracket_sim._seed_table` (divisions) — are **gated on synthetic configs only.**
`backtest_roster_shape.py` builds `_SF_SLOTS` by hand; TECHNICAL_ARCHITECTURE explicitly states division
seeding is *"synthetic-gated only … NOT validated on a real division league."*

**The corpus is the first time real league shapes hit that code. It will find bugs.** That is a *feature* —
infinitely better in a backfill in July than in a stranger's live league in week 6. But only if you
**harvest for coverage, not convenience.**

Target the crawl to fill cells, not to collect volume:

| Axis | Values to cover | Why |
|---|---|---|
| **Scoring** | PPR · half · std · **≥1 custom / TE-premium** | exercises `_scoring.recompute_custom_points` (rejects first-down/threshold bonuses — find out now) |
| **QB structure** | 1QB · **superflex** | `position_pools` superflex path has **never seen a real league** |
| **Teams** | 10 · 12 · **≥1 at 8 or 14** | pool lines, waiver line, playoff cut |
| **Playoff shape** | flat · **≥1 division league** | `_seed_table` division path is **unvalidated on real data**; `_division_map` currently returns `None` |
| **Lineup shape** | standard · **≥1 with 2-TE or 3-WR/2-FLEX** | the remaining `lineup_slots` latent |

A corpus of 10 leagues that fills this matrix is worth more than 30 that are all copies of yours.

---

## Prioritise **seasons × leagues** — not league count

> **The one place your instinct could mislead you.** Leagues in the *same* NFL season are **not
> independent**: they share the same underlying player performances.

| Read family | What extra **leagues** (same season) buy | What extra **seasons** buy |
|---|---|---|
| §1 signal · §2 band · §3 consensus — **player-level** | **≈ nothing.** Same player-weeks, re-used. Only *scoring-variant coverage*. | **everything** |
| §5 true rank / bracket · §6 depth — **team-level** | real, but **correlated** (shared NFL season; different rosters + schedules) | more, and cleaner |
| §7 manager features — **behavioural** | **the most** — genuinely independent people | some |

**⇒ 8 leagues × 6 seasons ≫ 20 leagues × 1 season**, for far less crawling. Sleeper keeps the history;
seasons are nearly free once you have the league. **Depth of history beats breadth of leagues.**

---

## What the corpus **cannot** give you *(this is the pilot's entire remaining job)*

Be precise about the boundary — it's what keeps the pilot honest and small.

| Not backfillable | Why | Consequence |
|---|---|---|
| **Situation news** | `team_news_raw` is **forward-only RSS**. You cannot retrieve 2021 beat-writer feeds. | **§2's whole AI half (`ros_synthesis`) is un-backtestable.** Its grades can only ever be graded *forward*, in 2026. |
| **Market values** | LeagueLogs daily snapshots begin **2026-05-31**. | **§4 Market VOR + `trade_gap` un-backtestable** (STATUS already flags this as "un-backdatable"). |
| **Live collector reliability** | 65% coverage is a *live-host* problem. | Only the live loop can measure it. |
| **Served-decision behaviour** | decision-touch, divergence, who-was-right. | Needs actual humans making actual moves. |

Everything else — **§1, §3, §4-production, §5, §6, §7 — is fully gradeable offline, today.** Six of seven
reads.

---

## Splits (the fix for the in-sample problem, done properly)

With a corpus you finally get **two independent holdout dimensions** instead of zero:

- **Season-wise:** fit 2021–2023 · dev 2024 · **test 2025** *(never touched until the end)*
- **League-wise:** fit on leagues A–M · **holdout leagues N–T** — the honest test of the any-league
  generalisations, since a held-out superflex league is a genuinely unseen shape

Audit S2.1 said the five tuned constants (`BAND_Z` 0.55, `SKEW_GAIN` 1.5, `BULL_Z` 1.44, `ANCHOR_W` 0.25,
`OPP_HALF_LIFE` None) were **fit and certified on the same 2025 data**. The corpus lets you **retune all
of them out-of-sample before 2026 ever starts** — and, for the first time, tune the *league-level*
constants too, which a single 10-team league could never support.

---

## What the numbers become

| | today | 10 leagues × 5 seasons |
|---|---|---|
| team-seasons | 10 | **~500–600** |
| regular-season matchups | 75 | **~3,750** (reliability bins of ~750, vs ~15) |
| distinct managers | 10 | **~100–120**, each fanning to their own comparable leagues |
| league shapes exercised | 1 | the whole matrix |

**That is the difference between *certifying* a read and *tuning* one.**

It also dissolves §7's documented weakness — *"depth honestly thin (recurring-league friend group)"* —
outright.

---

## Risks

1. **The corpus is what finally trips the O(n²) write** (710 audit #2, the acknowledged migration
   trigger). 50–100 league-seasons written incrementally into one file is exactly the pathological case.
   **Mitigation is free and you're doing it anyway: partition derived parquet by `league_id`** (L0 keying
   gives you this). Don't hand-optimise the writers; just don't put 100 league-seasons in one file.
2. **Selection bias — name it, then accept it.** A 6-degrees crawl from your leagues is a
   friend-of-a-friend-of-a-friend sample of Sleeper, not a random one. For **engine mechanics** (NFL
   players, lineup math, playoff odds) the bias doesn't reach — those are properties of the NFL and the
   rules. For **§7 manager behaviour**, and for any future claim about "typical manager error rates," it
   absolutely does. **Let §7 tell you what *these* managers do, not what "managers" do.**
3. **Sleeper API load.** ~10 leagues × 6 seasons × (rosters + 18 wks matchups + transactions). Route
   everything through `_http` and use `set_throttle` (already built for the §7 fan-out). Persist
   incrementally + idempotently, per league — the `leaguelogs.snapshot()` precedent.
4. **Real shapes will break real code.** Restating deliberately: this is the *point*, not a risk to
   avoid. Budget a session for "the corpus found bugs in the any-league work."

---

## Decision this forces: **retire the 2025-wk4 freeze**

The app currently simulates "the present" at **2025 week 4**. If 2025 becomes fully-resolved corpus, that
freeze stops being a useful scaffold and becomes an obstacle — you'd be holding out data you now own.

**Proposed clean line:**

> **2020/21 → 2025 = CORPUS** (offline, resolved, `served=false`, the tuning + certification ground).
> **2026 = LIVE** (forward, `served=true`, the ledger).

That *is* the leagues/weeks separation you asked for, stated as a data contract.
