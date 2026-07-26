# Session 3a — The Raw Harvest (league-key the raw/join layer + pull the corpus)

**Hand this file to Claude Code as the session brief.**

**Type:** L0 raw-layer keying + corpus raw fetch · **Commits:** 3
**Reads first:** `CLAUDE.md` · `LEAGUE_CORPUS.md` · `SESSION_1_L0_LEAGUE_KEYING.md` · `S1_6_FINDING_roster_reproducibility.md` · `SESSION_2_5_CORPUS_FINALIZATION.md`
**Blocks:** Session 3b (the read spine) — **hard prerequisite; no second league's spine can compute until the raw layer is collision-safe.**
**Prior:** Session 2.5 (corpus **FINAL / harvest-ready**); Session 1 (L0 keyed the *derived* league-scoped layer and **explicitly deferred re-keying the *raw* fetched layer** — that deferral is now due).
**Reads the FROZEN manifest** (`corpus_manifest.parquet`) — it does **not** re-select. Zero selection decisions in this session.

---

## Why this exists

Session 2.5 marked the corpus final. Verified against the live manifest (2026-07-15):

| stratum | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | total |
|---|---|---|---|---|---|---|---|
| **matched** (tune) | 9 | 15 | 24 | 53 | 60 | 60 | **221** |
| **generalization** (`never_tune`) | 8 | 8 | 8 | 8 | 8 | 8 | **48** |
| **mine** | 0 | 0 | 0 | 0 | 1 | 1 | **2** |
| excluded (not harvested) | 3 | 7 | 8 | 15 | 4 | 4 | 41 |

**The harvest target is 271 league-seasons** (269 foreign + your 2). The 41 excluded rows stay out.

The harvest cannot start, though, because of an unclosed L0 gap. **Session 1 keyed the *derived* league-scoped
entities** (`production_vor`, `true_rank`, `positional_depth`, `bracket_odds`, `player_signal`,
`ros_league_view`, `manager_*`) into `derived/league/<league_id>/…` — and its own closedown says the **raw
fetched entities were deferred**: *"Deferred to Session 2 … re-keying the fetched league entities
(teams/roster_positions/league_settings)."* Session 2 was the substrate backfill and never touched it. So the
raw layer is **still season-keyed only.** Verified 2026-07-15:

| Raw / join entity | current path | keyed by |
|---|---|---|
| `sleeper_matchups` | `sleeper/{season}/matchups_week_{w}.parquet` | season, week |
| `sleeper_transactions` | `sleeper/{season}/transactions_week_{w}.parquet` | season, week |
| `teams` | `sleeper/{season}/teams_{season}.parquet` | season |
| `roster_positions` | `sleeper/{season}/roster_positions_{season}.parquet` | season |
| `lineup_slots` | `sleeper/{season}/lineup_slots_{season}.parquet` | season |
| `league_settings` / config | `sleeper/{season}/league_settings_{season}.parquet` | season |
| `join_season` (+ remainders) | `nfl_sleeper_weekly_joined/season_{season}.parquet` | season |

**Pulling league #2 into a season overwrites league #1.** `sleeper.backfill(league_id, year)` already pulls
per-league but writes to these season-keyed paths. This is the collision the entire harvest sits on, and it
must be closed **before** any second league is fetched.

**This is 3a of a two-part Session 3** (2.5's closedown flagged the split). **3a = the raw harvest (this
brief). 3b = the league-scoped read spine + the corpus-level gate** (scoped in *Out of scope* below —
**scoped, not started**). The split is a risk boundary, not just a size one: the raw pull is
**shape-agnostic** (a superflex league's rosters/matchups/transactions are structurally identical to a
1QB league's), so 3a can pull all 271 uniformly with no shape risk. The exotic-shape bugs live in the
**spine compute** — so they belong to 3b.

### The storage decision (decided): persist, league-keyed

The raw pull is **persisted on disk, partitioned by `league_id`** (the `leaguelogs.snapshot()` precedent),
not streamed-and-discarded. The reason is the **determinism acceptance gate**: a re-run must be
byte-identical, and Sleeper is a **moving source** — the 1.7 Hunter drift (nflreadpy accumulating his CB
rows after the fact) is proof that re-fetching a "historical" fact gives a different answer on a different
day. Persisting freezes the corpus into a re-derivable artifact; discarding would make "deterministic on
re-run" **unprovable**, and would force the ledger/scorer/tuner to re-hit the API on every recompute. This
is the pinned-registry discipline (1.7) applied to the raw layer. **(New standing instruction 8, below.)**

---

## Commit 1 — Extend L0 keying to the raw + join layer (+ migrate the existing league)

Mirror Session 1's derived-layer pattern exactly: a **default-resolves-active `league_id=None` kwarg** on
every write/read/path helper, so existing single-league callers are **unchanged** and only the harvest
driver passes explicit keys.

- **Re-key the league-scoped raw entities by `league_id`:** `sleeper_matchups`, `sleeper_transactions`,
  `teams`, `roster_positions`, `lineup_slots`, `league_settings`/config, and `join_season` (+ its
  `remainders`). New paths under a league partition (e.g. `sleeper/{season}/league/{league_id}/…` and
  `nfl_sleeper_weekly_joined/league/{league_id}/season_{season}.parquet`) — match the naming Session 1 chose
  for the derived side.
- **Thread `league_id` through the fetch/join path:** `sleeper.backfill`, `fetch_teams`,
  `fetch_roster_positions`, `fetch_league_config`, and `join_nfl_sleeper_weekly` so the write lands under the
  right league. The **pinned registry (1.7) stays authoritative** for rostered skill-eligibility — the join
  reads the pin, not the 24h cache.
- **Byte-preserving migration of the one existing league** (`1182101676608823296` — is_mine 2025 — and the
  is_mine 2024 league `1132400260048977920`): copy the season-keyed raw + join files to the new league-keyed
  paths **without recomputing** (a re-pull would drift — 1.7), repoint the `public/data` symlinks the front
  end reads, then **verify byte-identical** before removing the flat originals (the verify-then-remove Session
  1 ran; standing instruction 5).
- **Gate teeth — raw-layer collision isolation:** mirror `backtest_l0_keying`'s collision test on the raw
  layer — write two different leagues' matchups under two `league_id`s in the same season, assert **distinct
  paths + neither overwrites the other**. Prove it **bites** (a deliberately season-keyed write collides and
  the check goes red).

> **This is a refactor.** The migrated league must read back **byte-identical** (prove equivalence —
> standing instruction 2). **No `queries.js` / view edits** — the re-key repoints symlinks only; if a fix
> wants to touch a view, the seam has leaked (standing instruction 3).

## Commit 2 — The harvest driver: pull the corpus raw + build per-league `join_season`

- **New harvest driver** reads the **frozen** `corpus_manifest.parquet`, filters to the harvested strata
  (`matched` ∪ `generalization` ∪ `mine` = 271; **exclude `excluded`**), and iterates `(league_id, season)`.
  **Do not re-select, re-crawl, or re-filter** — the manifest is the authority.
- **Per league-season, pull:** rosters + `teams`/config + `roster_positions`/`lineup_slots` + all
  regular-season `matchups` + `transactions`. Route **everything** through `fetchers/_http` with
  `set_throttle` (the §7 fan-out precedent). **Idempotent + incremental per league** (the
  `leaguelogs.snapshot()` precedent): a re-run pulls only what's missing.
- **Build `join_season` per league** against the **frozen substrate** (`projection_consensus` /
  `ros_player_band` for `{ppr, half}` + the 8 custom keys × 2020–2025 — already built in 2.5; **do not
  recompute it; verify byte-identical if touched**) and the pinned registry. **Carry the two-way flag**
  through from `corpus_two_way_flags.parquet` (10 rows total across 2021–2025 — ~2 material/season, not the
  ~4–6 the earlier estimate assumed; 2025 = 4 incl. Hunter) as a first-class boolean on the join output — **FLAG, do not exclude** (the recorded decision; deep-wiring exclusion is the
  scorer's job).
- **Harvest-time integrity re-verify — FLAG, don't silently drop.** The manifest was filtered at selection,
  but re-check at *pull* time (a league can have drifted since discovery) that each league-season resolves:
  every regular-season week has matchups and is not all-zero; no team has ≥3 empty/zero-`starters` weeks
  after week 2; `len(rosters) == num_teams`; skill-player id-resolution ≥ threshold. A league that fails is
  **flagged with a named reason**, not harvested into a silent hole (LEAGUE_CORPUS's "half-dead leagues
  silently poison it"; standing instruction 1 — a clean zero is a bug).
- **Budget + report the fetch cost.** "Free" applies to *classification*, never to *validity* — these are
  real throttled fetches. Report: total API calls
  (≈ Σ leagues × [rosters + teams + config + ~N_weeks matchups + ~N_weeks transactions]), wall-clock at the
  throttle, and the **incremental re-run cost (≈ 0 because raw is persisted).** If the total is
  uncomfortable, say so before pulling all 271, not mid-harvest.
- **Historical-accuracy footnote (the 1.7 residual — report, don't fix).** The pinned registry is
  current-state, so for a 2020–2024 league a player's skill-eligibility label is *today's*, not that
  season's. Quantify the exposure across the harvested corpus (the ~handfuls/season two-way ceiling 1.7
  measured) and report it. **It is a bounded footnote, not a blocker** — the fix (if any) is a scorer-era
  slice, not a harvest job.

## Commit 3 — The raw-harvest gate + docs

- **New corpus-level `check_harvest` gate** (or extend the corpus gate — mirror `backtest_l0_keying`'s
  structure). It asserts, over every one of the 271 selected leagues:
  1. **Raw present** — rosters + all regular-season `matchups` + `transactions` + `teams`/config exist under
     the league-keyed paths.
  2. **`join_season` computes** for every league.
  3. **No silent roster-mass loss** — every rostered skill player either resolves into the join or is a
     **named, bounded remainder**; the per-league remainder count is reported, not hidden. (Standing
     instruction 6 — name the players, don't assert a clean join.)
  4. **Deterministic on re-run** — twice-pull-from-persisted-raw + twice-join is **byte-identical.** *(This
     is the gate the persist decision exists to satisfy.)*
  5. **Two-way flags ride the harvested join** and are sliceable; count matches the 2.5 reference (10 rows).
- **Prove the gate bites:** a deliberately truncated league (drop one week's matchups) **fails** the
  completeness check; a deliberately roster-mass-losing join **fails** check 3. A gate that can't fail is not
  a gate.
- **Docs:** `STATUS.md` (raw layer keyed; corpus raw harvested — counts, budget, flagged-league list);
  `TECHNICAL_ARCHITECTURE.md` (raw layer now league-partitioned; the harvest driver; `join_season` per
  league); `READ_BUILD_ORDER.md`; `LEAGUE_CORPUS.md` (harvest-in-progress → **raw done**). **Scope 3b in the
  closedown** (see *Out of scope*).

---

## Acceptance gates

1. **Refactor equivalence:** raw league-scoped entities are league-keyed; the existing league(s) migrated
   **byte-preserving** and read back **byte-identical** (matched-substrate discipline — no number moves on a
   refactor).
2. **Collision isolation:** two leagues, same season, **distinct paths, no overwrite** — and the check is
   **proven to bite** on a deliberately season-keyed write.
3. **Coverage:** all 271 selected leagues' raw pulled (rosters + reg-week matchups + transactions +
   teams/config); a re-run pulls **only what's missing** (idempotent, incremental).
4. **No silent loss:** `join_season` computes for every league; roster-mass loss is **bounded + named
   per league**; no league is silently dropped — drifted leagues are **flagged with a reason.**
5. **Determinism:** twice-pull-from-persisted-raw + twice-join is **byte-identical.**
6. **Budget reported:** total call count, wall-clock at the throttle, and incremental re-run cost (≈ 0).
7. **Two-way flags** ride the harvested join; count matches the 2.5 reference.
8. **Seam held:** `queries.js` / views untouched; the is_mine league still resolves post-migration and the
   front end renders (browser preview — verify, don't ask the user to check).

---

## Out of scope

- **The read spine — Session 3b (scope it in the closedown; DO NOT start it).**
  `production_vor → { true_rank · positional_depth · bracket_odds }`, `player_signal`, `ros_league_view`,
  `manager_features` — with **explicit `league_id` + `scoring_key` threaded through the `compute_*`
  functions** (today they take `season` only and implicitly resolve the active league; the `data_layer`
  write side is already keyed, the compute side is not), computed **per league against the frozen
  substrate**, with the **10k-Monte-Carlo `bracket_sim` (SIMS = 10_000) per league per as-of week** — the
  expensive step; **budget it explicitly.** **Sequencing: matched-first** (the 221-league clean tuning path
  — same shape as the live league, best-tested code), **then generalization (48) as a separate budgeted
  robustness pass** where the synthetic-gated paths (`position_pools` superflex, `bracket_sim._seed_table`
  division seeding, `_scoring.recompute_custom_points`) meet real shapes and **will** surface bugs — that is
  the point (IMPROVEMENT_LOOP session 6: *"fix what the corpus broke; budget the session"*). Isolating it
  keeps a division-league crash from stalling the tuning corpus you need first. Ends with the **corpus-level
  spine gate** (spine computes for every league; deterministic; two-way sliceable).
- **The ledger (L2), scorer (L3), tuner (L4).** Report, don't tune.
- **Re-selecting / re-crawling the corpus** — frozen. **Recomputing the substrate** — frozen (verify
  byte-identical if touched).
- **Deep-wiring two-way exclusion** — scorer's job; FLAG only here.
- **Any constant change.**

---

## Definition of done

- Raw + join layer **league-keyed**; existing league(s) migrated **byte-identical**; collision-safe (proven
  to bite).
- **271 leagues' raw persisted**, league-keyed, idempotent/incremental; drifted leagues **flagged, not
  dropped.**
- `join_season` per league; roster-mass loss **bounded + named**; **deterministic on re-run.**
- **Fetch budget reported** (calls, wall-clock, ≈0 re-run); two-way flags ride through.
- `check_harvest` **green with teeth**; front end unaffected.
- **Session 3b (read spine, matched-first) scoped in the closedown — not started.**

---

> ## Standing instructions
> 1. **A suspiciously clean zero is a bug until proven otherwise.** *(A league with an empty/all-zero week or
>    empty starters is exactly this — flag it, don't harvest it into a hole.)*
> 2. **A refactor that changes a number is a bug** — prove equivalence. *(The raw re-key migrates the
>    existing league; it must read back byte-identical.)*
> 3. **If the fix wants to touch `queries.js` or a view, the seam has leaked.** *(The re-key repoints
>    symlinks; it does not edit views.)*
> 4. **Report, don't tune.** *(Report the multi-league roster-mass + two-way exposure + the historical-label
>    footnote; change no constant, recompute no substrate.)*
> 5. **Deleting dead code must not move a live number.** *(Removing the flat raw parquets post-migration is
>    verify-then-remove, as Session 1 did.)*
> 6. **A plausible explanation is not a diagnosis** — name the mechanism, or write UNKNOWN and escalate.
>    *(A league that loses roster mass: name which players and why.)*
> 7. **"The artifact exists" and "the consumer uses it" are two different gates.** *(Raw pulled ≠ join
>    computes ≠ the spine reads it. Gate that the join computes here; the spine's consumption is 3b's gate.)*
> 8. **NEW — Persist the substrate; never re-derive from a moving source.** *(The raw pull is frozen on disk,
>    league-keyed, because the determinism gate cannot be honored against a live Sleeper — 1.7's drift is the
>    proof. Discard would make "deterministic on re-run" unprovable and force every downstream recompute to
>    re-hit the API.)*
