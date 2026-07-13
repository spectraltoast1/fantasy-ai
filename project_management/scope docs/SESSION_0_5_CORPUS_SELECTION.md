# Session 0.5 — Corpus Discovery, Selection & the League Registry

**Hand this file to Claude Code as the session brief.**

**Type:** real, merged work (not a spike) · **Commits:** 3
**Reads first:** `CLAUDE.md` · `LLM context/SPIKE_CORPUS_FINDINGS.md` · `scope docs/LEAGUE_CORPUS.md`
**Unblocks:** the L0 keying sessions (this produces the registry they key against)

---

## What Session 0 changed

The spike came back green, and **bigger than the plan assumed** — which flipped the constraint twice:

| | before | after Session 0 |
|---|---|---|
| binding constraint | *"can we even find leagues?"* | **selection.** 3,003 league-seasons found (a **lower bound** — 6,784 managers still queued), ~87% pass the filter |
| corpus window | 2021–2025 (2020 unknown) | **2020–2025 confirmed** (projections reach 2019; exactly matches the `nfl_stats` backfill) |
| stale player IDs | *"most likely to be false"* | **cleared** — 100% of skill players on a 2020 dynasty roster resolve to a `gsis_id` |
| harvest cost | unknown | **36 calls / 9.15s per league-season** |

**⚠️ And it surfaced the trap this session exists to avoid.**

The neighbourhood is **not** the product's shape — it's close to the inverse:

| | the product | the corpus (3,003) |
|---|---|---|
| scoring | **PPR / half** | 72% **custom** · pure `std` = **0** |
| QB | **1QB** | superflex (1,667) **>** 1QB (1,336) |
| format | **redraft** | dynasty (1,652) **>** redraft (1,068) |
| size | **10–12** | mode 12, but 4 → **32** |

> **Pooling all of it and tuning on it would trade "overfit to one league" for "overfit to a
> dynasty/superflex/custom population" — then ship those constants to a PPR-1QB-redraft product.**
> That is a distribution shift, and it is exactly the silent miscalibration the improvement loop exists
> to prevent. **Do not pool. Stratify.**

**Product decision (made 2026-07-13): stay narrow — PPR/half · 1QB · redraft.** Exotic leagues are a
**robustness test set**, never a tuning input.

---

## The governing principle

> **Discovery is free. Harvest is what costs.**
>
> `classify_league()` runs off the `/user/.../leagues` payload with **zero extra API calls**. Harvesting a
> league-season costs **36 calls**. So: **crawl broadly · select narrowly · harvest only the selection.**
>
> **Do NOT put 2,600 league-seasons on disk.** You need a few hundred. More is compute you pay for and
> bias you import.

---

## Scope — three commits

### Commit 1 — `application/data/corpus/discover.py`
Manager-keyed BFS (the Session-0 mechanic, now **persisted** — the spike deleted its data, so the crawl
is re-run once, properly).

- Seed: the leagues in `config` → `/rosters` → `owner_id[]`
- `sleeper._manager_leagues(owner_id, season, seasons_back)` → every `(league_id, season)` per manager
- `_manager.classify_league()` on each — **free**, no extra call
- Dedupe on `(league_id, season)`; recurse to **depth 2**
- **All network I/O through `fetchers/_http.py`** (retry / backoff / **throttle** / per-item isolation) —
  no bare `requests`
- **Incremental + idempotent + resumable** persistence (the `leaguelogs.snapshot()` precedent) — the
  frontier is large; a mid-crawl failure must not discard the run

**Writes:** `snapshots/corpus/corpus_discovery.parquet` — one row per `(league_id, season)` with the full
classification signature (`scoring_profile`, `num_teams`, `qb_structure`, `league_format`,
`waiver_budget`, `has_divisions`, `previous_league_id`, `discovered_at`, `depth`).

**Crawl target — don't run it to exhaustion.** Crawl until the matched stratum (below) is **comfortably
over-supplied in every season**, then stop. Report the frontier size at stop.

### Commit 2 — `application/data/corpus/select.py` → **the league registry**
Applies the filter, scores scoreability, stratifies, and emits the manifest.

**Inclusion filter** (per `LEAGUE_CORPUS.md`, validated at ~87% in Session 0) — record the **reason** for
every rejection:

| Check | Reject if |
|---|---|
| Season complete | any regular-season week missing matchups / all-zero points |
| No abandonment | any team with ≥3 weeks of empty/zero `starters` after week 2 |
| Roster integrity | `len(rosters) != settings.num_teams`; teams far under-full |
| Transactions present | zero all season → **exclude from §7 only**, keep for §5/§6 |
| ID resolution | skill-player → `gsis_id` below threshold |

> **Note (from probe E):** in playoff weeks `matchup_id` legitimately thins as teams are eliminated. **Key
> the completeness check on `starters` / `points`, NOT on `matchup_id`.**

**Scoreability check** — run `_scoring.scoring_profile()` and, for custom leagues,
`_scoring.recompute_custom_points()` in a try/except. **Record `scoreable` + the rejecting key**
(first-down / threshold-yardage bonuses raise today). *The narrow stratum avoids this entirely — but
**quantify it anyway**, it's a roadmap input (see Deliverable §3).*

**Stratify:**

| stratum | definition | target | use |
|---|---|---|---|
| **`matched`** | `scoring ∈ {ppr, half}` · `1qb` · `10–14` teams · `redraft` · passes filter · scoreable | **~300**, **capped per NFL season** (e.g. ≤60/yr) so 2025 can't dominate | **tune + gate here** |
| **`generalization`** | deliberate spread: superflex · divisions · custom-but-scoreable · exotic sizes (incl. a 32-team) | **~75** | **robustness test only — `never_tune = true`** |
| **`mine`** | your own leagues | all | live path |
| *(everything else)* | classified, filtered, **not selected — not harvested**| — | stays a manifest row only |

**Per-season balance is not optional.** The NFL season is the independence axis (`LEAGUE_CORPUS.md`).
Supply is recency-skewed (2020: 95 league-seasons total → matched supply will be **thin**; 2025: 1,149).
**Enforce a per-season cap, report the achieved balance, and if an early season is short, say so — don't
silently backfill it from 2025.**

**Writes:** `snapshots/corpus/corpus_manifest.parquet` — **this is the league registry the L0 sessions
key against.** One row per selected `(league_id, season)`:
`league_id · season · scoring_key · shape_key · num_teams · qb_structure · league_format · has_divisions ·
stratum · never_tune · scoreable · filter_result · filter_reason · is_mine · selected_at`

Plus a minimal `data_layer.write_corpus_manifest` / `read_corpus_manifest` / `write_corpus_discovery` /
`read_corpus_discovery` (**additive only — no existing entity or path changes; L0 does the keying**).

### Commit 3 — `application/data/corpus/check_corpus.py` + docs
**Internal-consistency gate** (no answer key — the `check_market_vor` / `check_ros_synthesis` regime),
exit 0/1:

- **Stratum integrity** — every `matched` row genuinely satisfies the matched predicate; **zero `matched`
  rows are unscoreable**; every `generalization` row has `never_tune = true`
- **Season balance** — matched supply reported per season; **FAIL if any season in the intended train
  window is below a declared floor** (make the floor explicit; don't paper over a thin 2020)
- **Filter honesty** — every discovered row has a `filter_result`; every rejection has a **reason**;
  pass-rate reported and compared to Session 0's 87%
- **No leakage of intent** — `generalization` rows never appear in a tuning selection

Update `LEAGUE_CORPUS.md` with the **real** numbers (the Session-0 findings doc lists the deltas in its §4
— apply them) and add the Session-0.5 entry to `STATUS.md` + `READ_BUILD_ORDER.md`.

---

## Deliverable — the three numbers this session must produce

1. **The matched crosstab** (currently unknown — the Session-0 shape matrix didn't cross format with
   scoring/QB): **redraft × {ppr, half} × 1qb × 10–14 teams, per NFL season.** This is the actual tuning
   supply, and everything downstream is sized by it.
2. **Achieved season balance** of the matched stratum — and an honest statement of whether 2020/2021 are
   too thin to train on. *(If they are: propose the split. My prior — **train 2020–2023 · dev 2024 · test
   2025** — test on the most recent season because it's the closest analogue to 2026.)*
3. **The unscoreable rate** among custom-scoring leagues, **with the rejecting keys named.** Not needed for
   the narrow corpus — but 72% of your neighbourhood is custom, so this quantifies *"how much of the real
   world can this engine not score?"* **That is a roadmap finding, not a corpus finding.** Report it
   plainly; don't act on it here.

---

## Explicitly out of scope

- **Harvesting.** This session selects; it does not pull rosters/matchups/transactions. That's Session 4,
  and it reads this manifest.
- `league_id` / `scoring_key` **keying** of existing entities — that's L0 (Sessions 1–3). This session adds
  **new, additive** entities only and **changes no existing path**.
- Any change to a transform, a gate, or the front end.
- **Fixing** `_scoring`'s rejection path. Quantify it. Don't touch it.
- Extending the corpus to serve superflex/custom leagues (product decision: **narrow for 2026**).

---

## Definition of done

- `corpus_discovery` persisted; crawl idempotent + resumable; frontier size at stop reported.
- `corpus_manifest` written — **the league registry** — with `matched` ≈ 300 (season-capped) and
  `generalization` ≈ 75, every row carrying `stratum` / `never_tune` / `scoreable` / `filter_reason`.
- `check_corpus.py` exits 0.
- **The three numbers** above are stated in `STATUS.md`.
- All network I/O through `_http`; all parquet I/O through `data_layer`; runs as
  `python3 -m application.data.corpus.<module>`.
