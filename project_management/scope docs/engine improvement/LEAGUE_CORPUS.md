# The League Corpus — Spec

**Created:** 2026-07-12 · **Status:** **VALIDATED (Session 0) → REGISTRY BUILT (Session 0.5) → FINAL/harvest-ready
(Session 2.5) → RAW HARVESTED (Session 3a, 2026-07-15): 271 leagues' raw + per-league `join_season` persisted
league-keyed → MEASUREMENT SPINE COMPUTED (Session 3b, 2026-07-15): the 5 graded reads (`production_vor`,
`true_rank`, `positional_depth`, `bracket_odds`, `player_signal`) threaded league-keyed + computed for the 221
matched leagues (220 computed + 1 flagged-degenerate; `check_spine` green). The narrative reads
(`ros_league_view`, `manager_features`) are DESCOPED from the corpus (no answer key). → EXPECTED-POINTS
BACKFILL (Session 3c, 2026-07-15): the 14 ff_opportunity `*_exp` components **additively backfilled** into
`nfl_stats` 2020–24 + the matched `join_season`s (every pre-existing column byte-identical), and
`player_signal` re-run over the 160 non-degenerate matched 2020–24 leagues — so **§1 Quality (`quality_rate`
/ `luck` / `point_correlation`) now spans the whole matched corpus** (was TEST-only: 100% null 2020–24), the
rest of the 3b spine byte-identical; `check_expected_points` green with teeth. Session 3d (renumbered from
3c) = the 48 `never_tune` generalization leagues through the same spine — it inherits the `*_exp` fix for
free (`nfl_stats` already carries the components) and additively backfills its own joins the same way
(scoped, not started); then the L2 ledger.**
**Companions:** [`IMPROVEMENT_LOOP.md`](./IMPROVEMENT_LOOP.md) · [`PILOT_2026.md`](./PILOT_2026.md) ·
[`SESSION_0_5_CORPUS_SELECTION.md`](./SESSION_0_5_CORPUS_SELECTION.md) ·
[`LLM context/SPIKE_CORPUS_FINDINGS.md`](../LLM%20context/SPIKE_CORPUS_FINDINGS.md) ·
[`LLM context/712_BACKEND_AUDIT.md`](../LLM%20context/712_BACKEND_AUDIT.md)

> **Session 0 (spike) verified the assumptions with real API responses; Session 0.5 built the selected
> league registry (`corpus_manifest`).** What changed vs. this doc's original prose:
> - **Discovery is not the constraint — selection is.** ≥3,003 foreign league-seasons found (a lower
>   bound); ~87% pass the inclusion filter. Window **2020–2025** confirmed (projections reach 2019).
> - **The neighbourhood is the near-inverse of the product** — 72% custom scoring (pure `std` = 0),
>   superflex (1,667) > 1QB, dynasty > redraft, sizes 4→32. **⇒ Product decision: stay NARROW
>   (PPR/half · 1QB · redraft); exotic leagues are a robustness *test* set, never a tuning input.**
>   Pooling everything and tuning on it would import a distribution shift.
> - **Stale player IDs: cleared** — 100% of skill players on a 2020 roster resolve to a `gsis_id`.
> - **New caveats:** custom-scoring dominance meets `_scoring`'s first-down/threshold-bonus rejection
>   (~28% of custom leagues unscoreable — a roadmap number, not a corpus blocker); FAAB features apply
>   only to the FAAB-league subset.
>
> **⚠️ Corrected (Session 0.6, 2026-07-13):** the "72% custom / pure `std` = 0" split above was **inflated
> by a float32-tolerance bug** in `_scoring.scoring_profile` (a drifted standard PPR league was tagged
> `custom`). True custom pool **1,765 not 2,045 (−13.7%)**; unscoreable rate **45.4% not 39.2%** (802
> genuine, corrected denominator); matched-eligible **six seasons, not four** (2020:10 / 2021:19 were the
> bug's "clean zero", total 261→320). The narrow-corpus decision stands; the split is now **TRAIN 2020–2023 ·
> DEV 2024 · TEST 2025**. The bug was **live engine code** (§7 comparability), not just a corpus artefact —
> see `SESSION_0_6_SCORING_TOLERANCE_FIX.md` + `STATUS.md`.

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

> **RESOLVED (Session 0, 2026-07-13):** projections come back **to 2019** — full populated week-5 boards
> every season 2019→2025. The corpus window is confirmed **2020–2025 (six seasons)**, exactly the window
> the `nfl_stats` backfill already covers. See `LLM context/SPIKE_CORPUS_FINDINGS.md` §A.

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

## The unit is the **league-SEASON** · harvest by **manager**, not by league

> **Leagues churn. A five-season continuous league is uncommon — do not go looking for one.**

The corpus row is a **`(league_id, season)` pair**. A league that existed only in 2023 is a perfectly
good corpus row: 10–12 team-seasons, ~75 matchups, a dozen managers' transaction histories, one roster
shape. **Nothing downstream needs continuity** — season-wise splits, league-wise splits, and every
team-level read work fine on disjoint leagues. **§7 explicitly *wants* different leagues** (cross-league
comparability is its entire premise).

So `previous_league_id` chaining is a **nice-to-have, not the spine.**

**The durable entity is the manager.** Leagues die; people don't. And `_manager_leagues(owner_id, season,
seasons_back)` — already built — returns *every league a manager played, per season*. One manager active
since 2021 hands you five league-seasons across five possibly-different leagues. **That's better than
chaining**, because people play in different formats, so the crawl *naturally* diversifies scoring and
roster shape.

**Discovery is abundant.** Depth-1 alone — ten leaguemates × ~2–4 leagues each × 5 seasons — is on the
order of 100+ league-seasons before you recurse. **Discovery is not the constraint; quality filtering is
(see Risks).**

### Still true: spread across **NFL seasons**, not just league count

The independence axis that matters is the **NFL season** — leagues in the *same* season share the same
underlying player performances.

| Read family | Extra **leagues, same NFL season** | Extra **NFL seasons** |
|---|---|---|
| §1 signal · §2 band · §3 consensus — **player-level** | **≈ nothing.** Same player-weeks, re-used. Only *scoring-variant coverage*. | **everything** |
| §5 true rank / bracket · §6 depth — **team-level** | real, but **correlated** (shared NFL season; different rosters + schedules) | more, and cleaner |
| §7 manager features — **behavioural** | **the most** — genuinely independent people | some |

**⇒ Target a roughly even spread of league-seasons across 2021–2025**, rather than piling them all into
2025. 50 league-seasons at 10/10/10/10/10 ≫ 50 all in one year.

> **Expect a recency skew anyway.** Sleeper adoption grew across the window, so 2021–22 leagues are both
> rarer *and* likelier to be dead or incomplete. You will probably end up with a fat 2023–25 and a thin
> 2021–22. That's fine — still transformative versus n=1 — but plan for a lopsided split rather than
> being surprised by one.

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

## ⚠️ The inclusion filter — **the binding constraint**

> **Dead leagues are the *best* corpus material. Half-dead ones will silently poison it.**

A league that folded after 2022 is **fully resolved** — no ambiguity, no partial season, nobody using
it. Ideal. **Do not skip defunct leagues; prefer them.**

But leagues also die **mid-season**: managers stop setting lineups, teams go inactive, the commissioner
bails in week 9. A team fielding an empty lineup in week 10 wrecks `optimal_lineup`, wrecks the matchup
outcome, wrecks `true_rank` and `team_leakage` — **and throws no error.** It is the same silent-failure
class as the stale-player-ID risk, and it is why the corpus needs a gate, not just a crawler.

**Every league-season must pass before it enters the corpus:**

| Check | Reject if | Protects |
|---|---|---|
| **Season complete** | any regular-season week missing matchups, or all-zero points | everything |
| **No abandonment** | any team with ≥3 weeks of empty/zero `starters` after week 2 | §5 · §6 · leakage |
| **Roster integrity** | `len(rosters) != settings.num_teams`; teams far under a full roster | VOR pools |
| **Transactions present** | zero transactions all season → **exclude from §7 only**, keep for §5/§6 | §7 |
| **ID resolution** | skill-player resolution below threshold | the join — *see the stale-ID risk* |

**This filter — not discovery — is what sizes the corpus.** The crawl will likely surface 100+
league-seasons; the open question is what fraction survive. **Nobody knows that number yet, and
everything downstream is sized by it.** It is probe H of
[`SESSION_0_CORPUS_SPIKE.md`](./SESSION_0_CORPUS_SPIKE.md) and the single most important output of that
session.

---

## Risks

1. **Stale player IDs (the silent one).** The corpus joins Sleeper rosters from e.g. 2021 to nflreadpy
   stats from 2021 through `player_id_map.parquet` and the Sleeper registry — **both built from
   current-state data.** A player who retired in 2022 may not resolve to a position or a `gsis_id`. If a
   meaningful share of old rosters can't map, `join_nfl_sleeper_weekly` dumps them into `remainders` and
   **every league-scoped read silently loses roster mass.** No error. Just wrong. May require a
   historical-ID reconciliation step before any of the corpus is trustworthy. **Probe F.**
2. **The corpus is what finally trips the O(n²) write** (710 audit #2, the acknowledged migration
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
