# Session 0 — Corpus Spike: Findings

> ## ⚠️ Correction (Session 0.6, 2026-07-13) — do not silently trust the `custom`/`std` splits below
> The classifier `_scoring.scoring_profile` compared weights at `_TOL = 1e-9`, but Sleeper serves them at
> **float32** (a "0.1" arrives as `0.10000000149…`, drift ~1.5e-9), so **every float32-drifted standard
> league was misclassified `custom`.** This inflated the `custom` counts and the "pure `std` = 0" claim in
> the shape matrix (§D/§5). Measured against the persisted discovery, **280 leagues were wrongly `custom`**;
> the true custom pool is **1,765, not 2,045 (−13.7%)**, and the unscoreable rate among *genuine* customs
> is **45.4%, not 39.2%** (same 802 numerator, corrected denominator). This is *the* bug this doc's own
> "suspiciously clean zero" (0 matched in 2020 **and** 2021) pointed at. Fixed in §0.6; corrected corpus
> numbers live in `STATUS.md`. **The discovery totals (≥3,003 league-seasons, ~87% pass, ID resolution,
> matchup completeness) are unaffected** — they don't depend on scoring classification. Left below as
> written, per "mark corrected, don't rewrite."

**Run:** 2026-07-13 · **Type:** throwaway de-risking spike (code deleted; only this doc merges)
**Brief:** [`scope docs/SESSION_0_CORPUS_SPIKE.md`](../scope%20docs/SESSION_0_CORPUS_SPIKE.md) ·
**Feeds:** [`scope docs/LEAGUE_CORPUS.md`](../scope%20docs/LEAGUE_CORPUS.md)
**Method:** standalone `spike/` scripts, plain `requests`/`json`, read-only public Sleeper endpoints,
0.1s throttle. Classification via the production-identical pure helpers
(`transforms/_manager.classify_league`); no `data_layer`, no entities, no fetchers touched.

---

## 1. Verdict

> ## ✅ **Corpus viable — and materially *bigger and richer* than the spec assumed.** Proceed to the L0 keying sessions.

Every plan-killing assumption cleared, most of them emphatically:

- **Projections go back to 2019** (spec only needed 2021; hoped for 2020). The corpus window can be the
  full **2020–2025 (six seasons)** — an exact match to the existing `nfl_stats` backfill.
- **Old player IDs resolve cleanly** (probe F, the "most likely to be false"): a 2020 dynasty roster
  resolved **100% to position and 100% of skill players to a `gsis_id`.** The silent join-loss risk did
  not materialise.
- **Discovery is not the constraint, as predicted** — an exhaustive-strategy crawl, **capped for
  politeness** with its frontier still full (6,784 managers unvisited), already found **3,003 distinct
  foreign league-seasons** across 2020–2025 — a hard lower bound.
- **The inclusion filter passes ~87%** on a stratified 15-league sample — far above the "what if it's 10%"
  worry.

**Two caveats, both to carry into the corpus build (neither blocks it):**

1. **⚠️ The neighbourhood is *not* full-PPR-1QB — it's the opposite, and heavily so.** It is dominated by
   **custom-scoring, superflex, dynasty** leagues. This is *good* for shape coverage (the any-league code
   finally meets real superflex/division/custom leagues) but forces two things:
   (a) the **`_scoring.recompute_custom_points` rejection path** (first-down / threshold-yardage bonuses)
   **will be hit often** — an unknown fraction of "custom" leagues may be *unscoreable* by today's engine
   and must be excluded or the engine extended (this spike did not quantify it — a cheap Session-1 pre-check);
   (b) **§7's redraft-only V1 sees a smaller slice** — redraft is ~33% of the neighbourhood (still 880
   league-seasons, abundant).
2. **Selection bias is real and must be named** (as `LEAGUE_CORPUS.md` already says). This is a
   dynasty/superflex/custom-heavy *friend-of-friend* network, not a random Sleeper sample. Fine for engine
   mechanics (NFL players, lineup math, playoff odds); **not** a basis for any claim about "typical manager
   behaviour" in §7.

---

## 2. THE SIZING NUMBER

> **Exhaustive depth-2 crawl (capped for politeness at 400 managers / 3,125 calls) found `3,003` distinct
> foreign league-seasons across NFL seasons 2020–2025. At the ~87% inclusion-filter pass rate, usable
> corpus ≈ `2,600` league-seasons ≈ `~31,000` team-seasons and ≈ `~200,000` regular-season matchups —
> versus 10 and 75 today.**
>
> _(Discovery is a hard **lower bound**: the crawl frontier still held **6,784 unvisited** depth-2
> managers when it was capped. The true reachable neighbourhood is several times larger.)_

Sub-sizing that matters downstream:

- **Per-NFL-season supply easily clears the "~10 usable per season" bar for 2021–2025**; 2020 is thinner
  (bonus sixth year). See probe D table.
- **§1–§6 (format-agnostic answer keys):** all formats count — a completed dynasty/keeper season is still
  a fully-resolved answer key of player-weeks, rosters and matchups. Usable ≈ 0.87 × 3,003, **minus** an
  unquantified custom-scoring-unscoreable slice (caveat 1a) for the projection/VOR reads specifically.
- **§7 (redraft-only V1):** usable ≈ 0.87 × 1,068 redraft ≈ **~930 manager-league-seasons**, of which only
  the FAAB-waiver subset supports the FAAB-aggression features (see probe B).

---

## 3. Probe-by-probe findings (real numbers)

### A — Projection depth ✅ (window = 2020–2025, six seasons)
Week-5 board, each season, HTTP 200, all populated:

| season | rows | with `pts_ppr` | top-3 (pts_ppr) |
|---|---|---|---|
| 2019 | 3104 | 290 | Mahomes 27.3 / L.Jackson 23.92 / Watson 23.71 |
| 2020 | 3103 | 299 | Mahomes 26.42 / J.Allen 26.25 / Prescott 26.01 |
| 2021 | 3104 | 359 | J.Allen 27.01 / K.Murray 26.76 / Mahomes 25.88 |
| 2022 | 3103 | 359 | J.Allen 28.43 / L.Jackson 28.07 / Hurts 27.19 |
| 2023 | 3103 | 306 | Mahomes 26.21 / Hurts 25.77 / J.Allen 24.39 |
| 2024 | 3103 | 298 | J.Allen 23.71 / L.Jackson 23.16 / J.Daniels 22.09 |
| 2025 | 3103 | 301 | J.Allen 25.28 / McCaffrey 24.94 / Mahomes 22.51 |

Projections exist back to **2019** — one further than the corpus needs. **2020 is fully populated**, so the
corpus window = the exact window `nfl_stats` already holds. The keystone dependency is confirmed and extended.

### B — Historical transactions ✅ (served back to 2020; FAAB only on FAAB leagues)
One league-season per year (first redraft by id); the 2020/2021 first-picks landed on **dead "Test"
leagues** (0 txns — a selection artifact, not an API limit):

| year | league | total | by type | waiver+FAAB | complete |
|---|---|---|---|---|---|
| 2022 | League 2022 (ppr 10t) | 111 | w38/fa70/t3 | 0 | 108 |
| 2023 | Amazon NYC (half 12t) | 351 | w191/fa155/t3/c2 | **191** | 260 |
| 2024 | Rebel League (custom 10t) | 420 | w204/fa204/t5/c7 | 0 | 321 |
| 2025 | Fish Tank (half 12t) | 474 | w234/fa209/t31 | **234** | 356 |

**Proof that 2020 transactions are served** (checked the live 2020 *Beta Theta Dynasty*):
**685 transactions — 459 waivers, 435 with FAAB bids, 42 trades, 529 complete.** So:
- Transactions + `status:complete` come back historically, richly, **back to 2020**.
- **FAAB `waiver_bid` is present only in FAAB leagues** (2023, 2025, Beta Theta) and **absent in
  priority/rolling-waiver leagues** (2022, 2024 have waivers, zero bids). `compute_manager_features`
  already null-handles undefined FAAB features (law 2), so §7 survives — but FAAB-aggression is only
  computable on the FAAB subset.

### C — `previous_league_id` (measured, not depended on)
- **Seed chain is short:** seed 2025 → 2024 → terminates (length 2). Old objects keep `settings` +
  `scoring_settings` intact.
- **Across 3,004 candidates: 56.4% carry a `previous_league_id`** (1,233 of them point at another league
  already in the crawl — observable chains), driven largely by dynasty/keeper leagues that chain by
  construction; redraft far less. Confirms the doc: chaining is a nice-to-have, **not** the harvest spine.
  Managers are the right unit.

### E — Old matchup completeness ✅ (regular season intact; playoff `matchup_id` thins — expected)
2020 *Beta Theta Dynasty* (12t), weeks 1–17: **every week has 12 rows with non-empty `starters`,
`starters_points`, `players_points`, `points`, and non-zero `points`.** `matchup_id` is fully paired
weeks 1–13, then thins in playoff weeks (14: 8, 16: 8, 17: 0) because eliminated teams have no bracket
pairing. **The answer key (`starters` + per-player points) is complete for all 17 weeks** →
`optimal_lineup` / true_rank / leakage are backfillable. **Implication for the inclusion filter: key on
`starters`/`points`, not `matchup_id`, in playoff weeks** (the H filter does this).

### F — Old player IDs ✅ (the big one — cleared)
Oldest foreign league-season = 2020 *Beta Theta Dynasty* (12t dynasty, deep rosters = hardest case),
**345 roster players**:
- **100.0%** resolve to a **position** (current `/players/nfl` registry).
- **93.6%** resolve to a **`gsis_id`** overall; the 6.4% gap is entirely K/DEF/never-played.
- **Skill players (312): 100.0% resolve to a `gsis_id`.** Zero unresolved, zero skill-but-no-gsis.

No historical-ID reconciliation step is needed for skill positions. (Probe H re-checked ID resolution on
15 more league-seasons across 2020–2025 → all ≥99.5%.)

### G — Cost ✅ (minutes, not hours)
One full league-season harvest (league + rosters + 17 matchups + 17 transactions) = **36 calls in 9.15s**
at the polite 0.1s throttle. Extrapolated: **50 league-seasons ≈ 7.6 min, 100 ≈ 15.2 min.** Throttling
needs no special thought; the harvest is trivially cheap. (Discovery — probe D — is the larger call budget,
but still bounded.)

### D — The harvest mechanic: exhaustive depth-2 manager crawl
Capped at **400 managers / 3,125 calls**; **6,784 managers still queued** → every count below is a
**lower bound**. **3,003 distinct foreign league-seasons.**

**(1) Supply by NFL season**

| NFL season | league-seasons (all formats) | redraft-only (§7 V1) |
|---|---|---|
| 2020 | 95 | 31 |
| 2021 | 198 | 78 |
| 2022 | 331 | 119 |
| 2023 | 510 | 213 |
| 2024 | 720 | 259 |
| 2025 | 1,149 | 368 |
| **total** | **3,003** | **1,068** |

**(2) Shape matrix** (league-season counts, scoring × QB structure)

| | 1QB | superflex |
|---|---|---|
| **PPR** | 465 | 144 |
| **half** | 135 | 89 |
| **std** | 0 | 0 |
| **custom / TE-prem** | 736 | **1,434** |

**Extra splits** — Format: dynasty 1,652 · redraft 1,068 · keeper 243 · `type3` 40 ·
Team sizes 4–32 (mode 12: 1,754; 10: 681; 14: 162; 16: 83; 18: 55; 20: 9; 24: 8; **32: 37**) ·
Divisions set: **401 (13.4%)** · QB: 1QB 1,336 / superflex **1,667** · Scoring: custom 2,170 / PPR 609 /
half 224 / **std 0**.

**Reads:** discovery is abundant and diverse. Supply clears ~10 usable/season for 2021–2025 with wide
margin; 2020 is thinner. **Shape coverage is excellent — the corpus *will* exercise the any-league code**
(superflex, custom scoring, divisions, exotic team sizes all present in volume), so the
`LEAGUE_CORPUS.md` "corpus tests the any-league work" claim is **confirmed, strongly.** The recency skew
predicted by the doc is present but mild (even 2020 is not scarce).

### H — The abandonment filter: THE SIZING PASS RATE
Stratified random sample of **15** league-seasons (2–3 per season, 2020–2025), full inclusion filter:

- **13 / 15 (86.7%) pass** for §5/§6 usability; **all 13 also pass §7** (have transactions).
- **2 rejects, both correctly caught:** a fully-abandoned 2023 redraft (`season_incomplete` +
  10 teams empty ≥3 weeks) and a broken 17-team 2025 league (16 teams under-full + abandoned).
- **ID resolution ≥ 99.5%** on every sampled league; **no** league failed on IDs (re-confirms F at breadth).

The filter behaves as designed: it rejects genuinely dead/broken league-seasons and keeps the rest.
Pass rate ~87% → the binding constraint is **mild**, not fatal.

---

## 4. What this changes in `LEAGUE_CORPUS.md` (deltas — do NOT edit that doc here)

| Claim in `LEAGUE_CORPUS.md` | Status after this spike | Action |
|---|---|---|
| "Historical projections exist back to at least 2021" + open 2020 check | **Confirmed + 2020 (and 2019) present** | Set window to **2020–2025**; strike the open 2020 checkbox. |
| "Discovery is abundant … not the constraint" | **Confirmed** (3,003 league-seasons, lower bound) | Keep; cite the real number. |
| "The corpus is the first time real league shapes hit that code … it will find bugs" | **Confirmed — strongly** (superflex 1,667; custom 2,170; 401 divisions; sizes 4–32) | Keep; upgrade from hope to fact. |
| Shape matrix as a *target to fill* | **Already over-full** on superflex/custom/division; **`std` scoring = 0**, and *homogeneous PPR-1QB is the rare cell, not the common one* | Reframe: the crawl is **over-weighted toward exotic shapes**; the scarce cells are pure `std` and simple PPR-1QB, not the exotic ones. |
| Inclusion filter "nobody knows the pass rate" | **~87%** on a 15-sample | Fill in; note it's a sample, widen later. |
| Stale-player-ID risk "may require a historical-ID reconciliation step" | **Not needed for skill positions** (100% skill→gsis on 2020) | Downgrade risk #1 from "load-bearing unknown" to "monitored, low." |
| `previous_league_id` chaining | **Confirmed low / short**; managers are the unit | Keep as-is. |
| (new) Custom-scoring dominance vs `_scoring` rejection path | **Not previously flagged** | **Add:** ~75% custom → quantify unscoreable (first-down/threshold bonus) leagues as a Session-1 pre-check; exclude or extend the engine. |
| (new) FAAB present only on FAAB leagues | Implicit | **Add:** §7 FAAB features gate to the FAAB subset; rolling/priority-waiver leagues still yield waiver/FA/trade features. |

---

## 5. Surprises

1. **The neighbourhood is a dynasty/superflex/custom world.** Pure `std` scoring is *absent* (0 of 3,003);
   superflex (1,667) *outnumbers* 1QB (1,336); custom scoring is 72% of the pool. The feared "100%
   homogeneous PPR-1QB" is inverted — homogeneity is the rare case here. Great for coverage, but see the
   custom-scoring caveat.
2. **Team sizes are wild** — 4, 6, 8, 10, 12, 14, 16, 18, 20, 24, and **32-team** leagues appear. The pool
   lines / waiver line / playoff-cut math will meet sizes far outside the 10–12 comfort zone. Budget for it.
3. **`type3` leagues** (37) — a league `settings.type` beyond the known 0/1/2 (redraft/keeper/dynasty).
   `_manager.league_format` already degrades gracefully (`type3` label), but it's an unmodelled format to
   note.
4. **Projections reach 2019**, a year *before* the `nfl_stats` backfill — so 2019 is available on the
   projection side but not (yet) the outcome side. Not needed, but noted.
5. **Dead "Test"/"Fun league" leagues are common in the tail** and return empty transactions/abandoned
   seasons — exactly what the H filter exists to drop. They are harmless once filtered.

---

## 6. Definition-of-done checklist

- [x] All eight probes A–H run against the live API with recorded numbers.
- [x] The sizing number is stated (usable ≈ 0.87 × discovered; discovery a lower bound).
- [x] `SPIKE_CORPUS_FINDINGS.md` written; verdict stated; `LEAGUE_CORPUS.md` deltas itemised.
- [x] Spike code deleted; only this findings doc merges.
