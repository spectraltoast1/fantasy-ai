# Dynasty Support — Assessment & Plan

**Last reviewed:** 2026-07-16 · **Status:** Scope / design doc — **not yet started.**

> **Verdict:** Dynasty is a **different value model, not a scoring change.** Keepers, contracts, a
> multi-year horizon, and rookie picks as assets change the **ROS value read, the ADP anchor, and VOR** —
> not the points transform. So unlike standard/custom, dynasty is **not** answered by "certify the
> scoring-invariant constants": the residual-shape constants stay invariant, but the **value layer needs
> new substrate (dynasty ADP curve, dynasty market profile) and, plausibly, its own fitting.** Biggest lift
> of the three. Scope V1 to *player-asset value under a multi-year horizon*; defer picks/contracts/taxi.
>
> **Origin:** produced 2026-07-16 from a code-grounded read of the value seams
> (`compute_ros_player_band.py`, `fetchers/adp.py`, `compute_market_vor.py`, `fetchers/leaguelogs.py`,
> `transforms/_manager.py`) and the corpus. Companion to
> [`STANDARD_SCORING_SUPPORT.md`](./STANDARD_SCORING_SUPPORT.md) and
> [`CUSTOM_SCORING_SUPPORT.md`](./CUSTOM_SCORING_SUPPORT.md); cross-links the lineage model in
> [`MULTI_LEAGUE_STORE_MIGRATION.md`](./MULTI_LEAGUE_STORE_MIGRATION.md).

---

## Context

**Why:** Dynasty is the **majority of the discovered universe** — 1,559 of 2,729 discovered league-seasons
are `dynasty` (redraft 914, keeper 218, type3 38). The product deliberately stayed narrow (redraft) for
tuning, so dynasty was never given a value model. This doc maps what specifically changes.

**Corrected mental model.** The instinct is to treat dynasty like another scoring key — flip a flag,
rebuild a substrate. That is wrong. Dynasty shares the *scoring* transform with redraft (a dynasty PPR
league scores a week identically to a redraft PPR league), so `scoring_key` and the delta engine are
untouched. What changes is **value**: in redraft a player is worth his *rest-of-this-season* points; in
dynasty he is worth a *discounted multi-year stream weighted by age*, and a 22-year-old breakout and a
34-year-old on a title team have inverted relative values. Every read built on "rest-of-season value"
(`ros_player_band` → `production_vor` → `true_rank`/`market_vor`/`bracket_odds`) inherits a redraft
assumption dynasty breaks.

**Where dynasty lands on the shared invariance thesis** (see
[`STANDARD_SCORING_SUPPORT.md`](./STANDARD_SCORING_SUPPORT.md)): **split.** The residual-shape / weekly
constants `BAND_Z` (`compute_projection_consensus.py:86`) and `SKEW_GAIN` (`:95`) stay **format-invariant**
— a player's week-to-week variance doesn't care about league format. But the **value-layer** inputs —
`ANCHOR_W` (`compute_ros_player_band.py:57`) and the ADP anchor curve it blends toward — are
**format-specific**, and `ros_center` itself is a redraft horizon. Dynasty is the one type that may need
its own value-layer fitting, not just certification.

---

## What the engine supports today (grounded)

- **Format is fully classified — dynasty is *visible*, just unmodeled.**
  `_manager._FORMAT_LABELS = {0:"redraft", 1:"keeper", 2:"dynasty"}` (`transforms/_manager.py:30`);
  discovery persists `league_format` + `previous_league_id` (`corpus/discover.py:57-77`); `shape_key`
  encodes it (`_keys.py:33-36`, e.g. `12t-sf-dynasty`); `config.LEAGUE_TYPES` allows a per-league override
  (`config.py:15-20`). There is already a hook for `dynasty<->dynasty` manager comparability
  (`_manager.py:29`).
- **But dynasty is not a corpus stratum.** `is_matched_eligible` requires `league_format=="redraft"`
  (`_corpus.py:23-34`); the generalization axes are size / division / superflex / custom — **no format
  axis** (`_gen_axis`, `select.py:185-197`; `is_generalization_eligible`, `_corpus.py:37-46`). So the 34
  dynasty leagues that reached the manifest are **incidental** (selected for a superflex/division/size
  axis), and none of the value reads were built or certified for dynasty.
- **The value seams are redraft-pinned:**
  - **ADP anchor.** The ADP fetcher hardcodes redraft-overall `_REDRAFT_OVERALL="ro"` (`fetchers/adp.py:35`);
    dynasty `do` and superflex `rsf` ranking types are named in the comment but **never fetched** (`:33-34`).
    `_preseason_anchor` (`compute_ros_player_band.py:123-150`) turns that redraft ADP into a
    floor/center/ceiling, and `_blended_band` (`:153-166`) blends the band toward it with weight `ANCHOR_W`.
    A dynasty rookie with elite dynasty value but no redraft ADP gets **no anchor** (`None` → pure-projection
    fallback, `:132-138`).
  - **Market VOR.** `compute_market_vor` pins the *"valuation context (redraft, not dynasty; 1QB; full
    PPR)"* (`:64`). **But the market source already has dynasty:** `fetchers/leaguelogs.py:13-16` collects
    **dynasty profiles** and even **rookie-pick rows** (synthetic ids like `PICK#2026#01`, `is_pick=True`).
    So dynasty market values *exist in the store* — `market_vor` simply selects the redraft profile.
  - **ROS horizon.** `ros_center`/`ros_sigma` are a rest-of-**this-season** quantity
    (`compute_ros_player_band.py:5, 22-23`). Dynasty asset value is a discounted multi-year stream — a
    different quantity, not a re-parameterization.
  - **Non-player assets.** `derive_lineup_slots.py:40` drops `TAXI` (and IR) slots as reserve; rookie draft
    picks are assets no player-keyed read can represent.
- **Continuity difference (feeds the store doc).** Dynasty keeps **one `league_id` across seasons**;
  redraft gets a fresh id each year (`previous_league_id`, `discover.py:71`;
  `MULTI_LEAGUE_STORE_MIGRATION.md:105-108`). So the lineage grouping is *trivial* for dynasty (one id) and
  the season selector maps directly.

## The gap (grounded)

The scoring path needs nothing. The **value path** needs, in increasing depth:
1. A **dynasty ADP substrate** (the `do`/`rsf` boards aren't fetched).
2. A **dynasty market profile** selection in `market_vor` (the data exists; the context is pinned to
   redraft).
3. A **multi-year value read** — the genuinely new piece; `ros_value` as defined is redraft-only.
4. **New asset entities** for rookie picks / contracts / taxi that no current read can hold.

---

## Plan (staged; value-layer, backend-first)

**Stage 1 — Dynasty ADP substrate.** Extend `fetchers/adp.py` to fetch the dynasty ranking type (`do`, and
`rsf` for SF-dynasty) alongside redraft `ro`; key the preseason ADP + `adp_points_curve` by **format** so
`_preseason_anchor` can select the dynasty board. Probe board coverage/quality first, exactly as the
redraft board was probed (`_MIN_SKILL_BOARD` sanity, `adp.py:44-46`). Feeds the anchor without touching
`BAND_Z`/`SKEW_GAIN`.

**Stage 2 — Dynasty market profile.** Point `compute_market_vor` at the dynasty LeagueLogs profile (already
collected, `leaguelogs.py:13-16`) when the league is dynasty; decide rookie-pick handling — carry `is_pick`
rows as a separate asset lane or exclude for V1. Smaller lift than expected because the source data exists.

**Stage 3 — The multi-year value read (the core).** Define a dynasty `ros_value` = discounted multi-year
projection × an **age curve** (vs redraft's rest-of-season). Decide whether this is a **new read** or a
**format-parameterized `ros_player_band`** (a `horizon`/`format` argument selecting rest-of-season vs
multi-year). This is where **`ANCHOR_W` may need dynasty-specific re-fitting** — the anchor curve is a
different shape — while the band-shape constants stay invariant. New model: the age curve (position × age →
value multiplier), which the current substrate does not carry.

**Stage 4 — Harvest a dynasty stratum + certify/fit.** Add a `dynasty` axis to selection (`_corpus.py` +
`select.py`) and harvest from the 1,559 already-discovered dynasty leagues; run the spine. **Certify** the
invariant constants (`BAND_Z`, `SKEW_GAIN`) on dynasty as a league-wise holdout; **fit only** the value-layer
inputs (`ANCHOR_W`, the age curve) on a dynasty TRAIN/DEV/TEST split — the one place this program *does* fit,
and it fits value inputs, not the residual-shape constants (honoring "report, don't tune" for the invariant
set).

**Stage 5 — Defer explicitly (out of V1 skill-position scope).** Rookie picks as tradable assets,
contracts / salary-cap cost basis, and taxi-squad eligibility are **new entities**, not read tweaks. Name
them out of scope for V1 and note the seams they'd touch (a pick/asset entity in `data_layer`; taxi
eligibility in `derive_lineup_slots`).

---

## Risks / can't-generalize

- **Multi-year projection horizon doesn't exist yet.** The substrate is rest-of-season; a multi-year value
  needs a forward-season projection the current pipeline doesn't produce. Stage 3 may be bounded by that.
- **Age curve is a new model** with its own fitting + gate; dynasty value is where the project first *fits*
  a format-specific constant, so the split discipline (TRAIN/DEV/TEST, holdout) must be applied carefully.
- **Un-backtestable value, like market_vor.** Dynasty market history also starts 2026-05-31
  (`LEAGUE_CORPUS.md:205`), so a dynasty market/value read can only be graded **forward** — the same
  boundary the redraft market read hit.
- **Dynasty ADP `do`/`rsf` coverage unverified** — must be probed before relying on it (a junk board is
  worse than no anchor).
- **Selection bias.** A dynasty stratum harvested from the same 6-degrees crawl is a friend-of-friend
  sample; fine for engine mechanics, not for behavioral claims (`LEAGUE_CORPUS.md:287-291`).

---

## Critical files

**Modify:** `fetchers/adp.py` (fetch `do`/`rsf`; format-key the board), `transforms/compute_ros_player_band.py`
(format-aware anchor + a multi-year/age value path), `transforms/compute_market_vor.py` (dynasty profile
selection), `corpus/_corpus.py` + `corpus/select.py` (a `dynasty` stratum + axis), `data/data_layer.py`
(format-keyed adp/curve paths; an optional pick/asset entity).
**Create:** an age-curve model + its gate (mirrors `compute_adp_points_curve` + `check_*`).
**Reference (reuse, don't rebuild):** `_manager._FORMAT_LABELS` (`:30`), `leaguelogs` dynasty/`is_pick` rows
(`:13-16`), `_preseason_anchor` / `_blended_band` (the anchor blend to make format-aware), the
`previous_league_id` continuity for the store doc's lineage model.

---

## Verification

- **ADP substrate:** after Stage 1, a dynasty board resolves for a sample of rookies that have *no* redraft
  ADP (the redraft-anchor `None` case, `compute_ros_player_band.py:132`); the dynasty anchor is non-null and
  age-ordered.
- **Market:** after Stage 2, a dynasty league's `market_vor` reflects the dynasty profile (youth valued
  above equivalent-production veterans) rather than the redraft profile.
- **Value read:** on a dynasty slice, `ros_value` ranks a young ascending player above a veteran with equal
  rest-of-season points (the redraft read would tie them); `check_spine` green on the dynasty stratum.
- **Invariance held:** matched + is_mine spine byte-identical after all dynasty changes (they must be
  additive/format-gated) — the 3d/3e "0/666 changed" discipline.
- **Certification vs fit:** the tuner proposal artifact (if L4 exists) shows `BAND_Z`/`SKEW_GAIN` unchanged
  on the dynasty holdout, and any `ANCHOR_W`/age-curve fit improves the **held-out** dynasty metric with no
  other-gate regression (`IMPROVEMENT_LOOP.md:283-289`).

---

## Session / commit sequencing

Largest of the three: ~4-6 sessions (3-commit cap each). S1 = dynasty ADP fetch + substrate. S2 = dynasty
market profile. S3-4 = the multi-year/age value read + its gate (the core). S5 = dynasty stratum harvest +
certify/fit. S6 (deferred) = pick/contract/taxi entities. Fresh worktree → `worktree-setup.sh` → work →
update `STATUS.md` + `TECHNICAL_ARCHITECTURE.md` (a new value read is a structural change) →
`worktree-close.sh --merge`.
