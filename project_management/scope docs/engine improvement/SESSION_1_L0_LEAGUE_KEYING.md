# Session 1 — L0 Keying, part 1: the League Registry + `league_id`

**Hand this file to Claude Code as the session brief.**

**Type:** structural refactor — **behaviour-preserving by construction** · **Commits:** 3
**Reads first:** `CLAUDE.md` · `712_BACKEND_AUDIT.md` (§S1.3) · `IMPROVEMENT_LOOP.md` (L0) · `LEAGUE_CORPUS.md`
**Blocks:** the corpus harvest, the ledger, everything in the improvement loop
**Followed by:** Session 2 (`scoring_key` + the `ros_outcome_shape` split) · Session 3 (2nd real league, end-to-end)

---

## The problem (audit S1.3)

Every league-scoped entity is keyed by **season only**:

```
derived/production_vor_2025.parquet          ← no league_id
derived/true_rank_2025.parquet               ← no league_id
sleeper/2025/teams_2025.parquet              ← no league_id
nfl_sleeper_weekly_joined/season_2025.parquet
```

`config.SLEEPER_LEAGUE_ID` is **one string**. **Adding a second league silently overwrites the first.**
No error. Just gone.

You now hold a **221-league-season matched corpus**. It cannot be written to disk until this is fixed.

---

## ⚠️ The one rule for this session

> **This session changes WHERE data lives. It changes NO NUMBER, ANYWHERE.**
>
> Every backtest must exit 0 with **byte-identical** output. The front end must render **identically**.
> If any number moves, you have introduced a bug — stop and find it. This is the
> `backtest_roster_shape.py` *"no-regression frame-equal"* discipline, applied to the whole data layer.

---

## Design

### Three scopes (make them explicit in `data_layer`, not implicit in filenames)

| Scope | Key | Entities | This session |
|---|---|---|---|
| **NFL-global** | `season[, week]` | `nfl_stats`, `projections`, `adp_*`, `market_values`, `team_news_*`, `player_news_slice` | **untouched** |
| **Scoring-scoped** | `+ scoring_key` | `projection_consensus`, `ros_synthesis` | **Session 2** — leave alone |
| **League-scoped** | `+ league_id` | `player_signal`, `production_vor`, `market_vor`, `ros_outcome_shape`, `true_rank`, `positional_depth`, `bracket_odds`, `team_form`, `team_leakage`, `manager_features`, `manager_dossiers`, `manager_activity`, `teams`, `roster_positions`, `lineup_slots`, `league_settings`, `schedule`, the season join + remainders | **THIS SESSION** |

### Layout: **partition by league in the path, AND carry `league_id` as a column**

```
snapshots/derived/production_vor/{league_id}/production_vor_{season}.parquet
snapshots/sleeper/{league_id}/{season}/teams_{season}.parquet
```

- **Path partitioning bounds the write.** The known O(n²) read-modify-write (710 audit #2) would other­wise
  detonate at 221 leagues — this is the mitigation, and it costs nothing.
- **The `league_id` column** makes the cross-league scans the scorer will need trivial (glob + scan).

### Backwards compatibility — the mechanism that makes this safe

```python
def read_production_vor(season, as_of_week=None, league_id=None): ...
#   league_id=None  →  the PRIMARY league  →  exactly today's behaviour
```

**Every existing caller keeps working, unchanged, because `None` resolves to the primary league.** That
is what lets you prove no number moved.

---

## Commit 1 — The league registry

**The corpus manifest already *is* the registry** — it holds `league_id · season · scoring_key ·
shape_key · num_teams · qb_structure · league_format · has_divisions · stratum · is_mine` for 365 leagues,
including your own two (`stratum = 'mine'`).

- **Rename `corpus_manifest` → `league_registry`.** It stopped being a corpus artifact the moment
  `data_layer` depends on it at runtime; the name will confuse in a month. Only `select.py` and
  `check_corpus.py` reference it — a cheap rename, do it now. Keep `stratum` as a column.
- Add **`is_primary`** (exactly one row per season may be true — assert it) and **`role`**
  (`primary` | `mine` | `corpus_matched` | `corpus_generalization` | `excluded`).
- New **`data_layer.resolve_league(league_id=None, season=...) -> dict`** — the single lookup. `None` ⇒
  the primary league. **This is the one place "which league am I?" is answered.** Everything else calls it.
- `config.SLEEPER_LEAGUE_ID` becomes the **seed that marks the primary row**, not a value threaded through
  the code. `shared/league_resolver.py` reads the registry.
- **Kill the `MY_USERNAME` hardcode in `queries.js`** (a documented latent in TECHNICAL_ARCHITECTURE): bake
  **`is_me`** into the teams parquet at fetch time and have the front end read that.

## Commit 2 — Key the league-scoped entities

- Every league-scoped path fn takes `league_id`; every league-scoped read/write takes
  `league_id=None → primary`.
- **Add a `league_id` column** to every league-scoped entity on write.
- **One-time migration script** — move the existing 2025 files into the new layout.
  **Idempotent and reversible.** Run it; don't hand-move files.
- **Do not touch the transforms' math.** They gain a `league_id` parameter that they pass through to
  `data_layer`. Nothing else.

## Commit 3 — Front end + the collision proof

**The front-end blast radius is one file** — and that's not luck, it's the
`TECHNICAL_ARCHITECTURE` client/server invariant #4 (*"keep 'where the data is' in `db.js`"*) paying off.
`queries.js` writes SQL against **registered aliases** (`FROM 'production_vor.parquet'`), never paths.

- **`db.js` only:** update the 15 `registerParquet(...)` **source paths**. The **alias names stay
  identical**, so **not one line of `queries.js` or any view component changes.** If you find yourself
  editing `queries.js` or a `.jsx` file, the seam has leaked — stop and reconsider.
- Update the `public/data/` symlinks to the new layout.
- Docs: `STATUS.md`, `TECHNICAL_ARCHITECTURE.md` (folder structure + strike the *"single-season file
  addressing in db.js"* and *"`MY_USERNAME` hardcode"* latents — **you are resolving both**),
  `READ_BUILD_ORDER.md`.

---

## Acceptance gates — all five must pass

1. **Every backtest exits 0 with byte-identical numbers**: `backtest_player_signal`,
   `backtest_projection_consensus`, `backtest_production_vor`, `backtest_true_rank`,
   `backtest_positional_depth`, `backtest_bracket_sim`, `backtest_ros_outcome_shape`,
   `backtest_roster_shape`, `backtest_scoring_recompute`, `backtest_manager_features`. Plus
   `check_market_vor`, `check_corpus`, `check_collectors`, the `ai/check_*` gates.
2. **Default-arg equivalence:** for every league-scoped entity, `read_x(season)` (no `league_id`) returns
   a frame **equal to the pre-migration file**. Prove it — compare against a snapshot taken before the
   migration.
3. **Front end renders identically.** Load it, walk all five `DATA_CONTRACT` surfaces (Players · Dossier ·
   Teams · League · Matchups), **take a screenshot, and look at it.** Zero console errors.
   *(Per CLAUDE.md: verify yourself and show proof — never ask the user to check manually.)*
4. **🔑 THE COLLISION PROOF — this is the whole point of the session.** Write a **synthetic second
   `league_id`** through the full league-scoped write path. Then assert:
   - league #2's files exist at their own paths,
   - **league #1's files are byte-identical to before**,
   - `read_x(season, league_id=L1)` and `read_x(season, league_id=L2)` return **different, correct** frames,
   - `read_x(season)` still returns **L1** (the primary).

   **This is the bug the session exists to kill.** A green gate without this proof is not a green gate.
5. **Registry invariant:** exactly one `is_primary` row per season; `resolve_league(None)` returns it;
   every league-scoped write records a `league_id` that exists in the registry.

---

## Out of scope — do not drift into these

- **`scoring_key`** and the **`ros_outcome_shape` split** (audit S3.1 / S3.2) — **Session 2.** Leave
  `projection_consensus` and `ros_synthesis` exactly as they are.
- **Harvesting** any corpus league. Session 4.
- The **generalization-stratum season gap** (a known defect: all 55 rows are from 2023–24; zero in 2025,
  the test season). **Add a per-season floor + a distinct-custom-scoring-key cap (~12) to `check_corpus`
  as a FLAGGED (warn, not fail) defect** so it can't be forgotten — then leave it. Fixed in Session 4.
- Any change to a transform's **math**, any new read, any front-end feature.
- Optimising the O(n²) writer. **Partitioning is the mitigation.** Don't hand-tune the writers.

---

## Definition of done

- `league_registry` exists with `is_primary`; `resolve_league()` is the single lookup; `MY_USERNAME` is
  gone.
- All 18 league-scoped entities keyed by `league_id`, path-partitioned, with a `league_id` column.
- Migration script run; **all five acceptance gates green**, including the **collision proof**.
- `db.js` updated; **`queries.js` and every `.jsx` untouched**; front end screenshot-verified.
- Docs updated; two latents struck from TECHNICAL_ARCHITECTURE.

---

> ## Standing instructions (carried forward)
> 1. **A suspiciously clean zero is a bug until proven otherwise.** *(§0.5 nearly binned two seasons of
>    corpus by recording an implausible hard zero as a fact. §0.6 encoded this as a hard gate — keep
>    that reflex.)*
> 2. **A refactor that changes a number is a bug, not a refactor.** Prove equivalence; don't assume it.
> 3. **If the fix wants to touch `queries.js` or a view component, the seam has leaked.** Stop and
>    reconsider before you edit it.
