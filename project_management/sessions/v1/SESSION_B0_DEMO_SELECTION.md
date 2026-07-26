# Stage B — Session B0: Demo selection + models — a brief for Code

**Last reviewed:** 2026-07-25 · **Status:** Ready to run · **Owner:** Code (Will operates; the slate is already locked)

> **What this session does:** lock the approved **12-lineage / 31-slice** demo set into the data layer so the
> heavy compute (B2) and the catalog endpoint (B3) have an authoritative slate to work from. It records each
> lineage's `season → league_id` chain, **pins a viewer per slice**, sets the **panel-gating policy**, and flags
> the demo cohort in `leagues.parquet`. **No analytics are computed this session** (that's B2) and no frontend
> changes (that's B5). Store-agnostic; runs in parallel with B1. Stage B of `MULTI_LEAGUE_STORE_MIGRATION.md` (B0).
>
> **The slate is already decided** (Will approved it). This session is data-modeling + recording, not selection.

## Your part, Will (~5 minutes)
The slate is locked — this is Code recording it. At the end, glance at Code's manifest: 12 lineages, 31 slices,
each with a resolved `league_id`, a pinned viewer, and its panel flags. That's your "looks right."

## The locked slate (authoritative source: `demo_slate.csv`, delivered with this brief)

31 league-seasons across 12 lineages. `demo_slate.csv` has every `(lineage, name, season, league_id, scoring_key,
num_teams, is_mine)` row — **use it as the source of truth for the league_ids** (they're resolved from the passing
`corpus_manifest`; the `previous_league_id` chains are verified).

| lineage | name | scoring | size | QB | format | div | seasons |
|---|---|---|---|---|---|---|---|
| `lorp` ⭐ | League of Random People 2.0 | ppr | 10 | 1QB | redraft | – | 2024–25 |
| `trap` | Trap | ppr | 12 | 1QB | redraft | – | 2020–25 (6) |
| `bgb` | Best Golden Balls | ppr | 8 | **SF** | redraft | – | 2024–25 |
| `fta` | FTA #17 Music City Miracles | half | 14 | 1QB | redraft | – | 2020–22 |
| `dysf` | The Dysfunctionals | ppr | 10 | 1QB | redraft | – | 2020,21,22,24 |
| `ypfl` | Young Professional Football League | ppr | 12 | 1QB | redraft | – | 2021–25 (5) |
| `nbl` | National Bruto Leage | half | 12 | 1QB | redraft | ✓ | 2022–25 |
| `lines` | TheLines Champion's League | half | 10 | 1QB | redraft | ✓ | 2023 |
| `rost` | Rosterbaters Anonymous | half | 12 | 1QB | **keeper** | ✓ | 2022 |
| `phb` | Player Haters Ball | ppr | 14 | 1QB | redraft | – | 2021 |
| `boys` | 3590 & The Boys | half | 8 | **SF** | **keeper** | – | 2023 |
| `wcfc` | Winston Churchill Fan Club | ppr | 12 | **SF** | **keeper** | – | 2023 |

`lorp` is Will's own league (`is_mine`); the other eleven are corpus leagues. Three superflex (`bgb` ppr-redraft,
`boys` half-keeper, `wcfc` ppr-keeper) and three keepers (`rost`, `boys`, `wcfc`).

## Decisions I made for you (locked with Will — Code: follow, don't re-select)

1. **The slate is `demo_slate.csv`** — 12 lineages, 31 slices, resolved league_ids. Don't re-pick; use these exact ids.
2. **Pin a viewer per slice (not neutral mode).** For `lorp`, the viewer is **Will's owner** (resolve his
   `owner_id` → `roster_id` per season — `roster_id` 7 in 2025). For each corpus lineage, pin **one owner** and
   resolve that owner's `roster_id` per season, so "you" is the same person across the lineage's years. Heuristic
   for the corpus pick: an owner **present in the most of the lineage's seasons** with **transaction activity**
   (so the personal panels have real content). *Provisional now — the "mid-table for the most interesting
   buy/sell reads" refinement needs standings, which don't exist until B2; picking mid-table is an optional
   post-B2 polish. Just record a sensible, valid viewer per slice this session.*
3. **Panel-gating policy (record it per slice; B2 computes to it, B3/B5 honor it):**
   - **`manager` (dossiers): ON for all 31 slices** — built from transaction/roster history, which every slice has.
   - **`market` (market-VOR + trade panels): ON only for `lorp` 2025** (the one live slice with a current market
     source); **OFF for the other 30.** Historical/corpus leagues have no contemporaneous market.
   - **`ros` (bull/bear/situation AI news grades): ON only for `lorp` 2025; OFF for the other 30.** The news read
     is a "right now" (2026) signal that can't be reconstructed for past seasons.
4. **No compute, no frontend.** This session only records the slate/viewers/panels + flags the cohort. B2 computes.

## What Code does

1. **Read `demo_slate.csv`** (the resolved slate) and, for each of the 31 slices, confirm the `league_id` resolves
   in `corpus_manifest`/`corpus_discovery` and that the raw harvest for `(league_id, season)` exists (so B2 can
   compute it). Report any slice whose raw data is missing.
2. **Resolve viewers:** per decision 2, pick the viewer owner per lineage and resolve `viewer_roster_id` per
   `(league_id, season)`. Record it.
3. **Record the demo set** — extend `leagues.parquet` (per `MULTI_LEAGUE_STORE_MIGRATION.md` B0): mark the 31
   demo slices with a `demo` cohort, and add `viewer_roster_id` + the three panel flags (`panels_market`,
   `panels_ros`, `panels_manager`) + a **`lineage_id` derived from the chain's root league_id** (see the
   lineage-identity note below) per row. Keep `is_mine` intact for `lorp`. If a
   separate `demo_manifest.parquet` is cleaner than widening `leagues.parquet`, that's fine — but the loader (B3)
   must be able to read `lineage → {season: league_id, viewer_roster_id, panels}` from it.
4. **Confirm the lineage chains** — each lineage's `previous_league_id` links its seasons (already verified for the
   slate; re-confirm after recording so `/api/leagues` (B3) can group per lineage). Single-season lineages
   (`lines`, `rost`, `phb`, `boys`, `wcfc`) have no chain — that's expected.

## Definition of done
✅ The 31-slice demo set is recorded in the data layer (`leagues.parquet` demo cohort and/or a `demo_manifest`),
each slice carrying its resolved `league_id`, a pinned `viewer_roster_id`, a stable `lineage_id`, and the three
panel flags per the policy; every slice's raw harvest is confirmed present (missing ones flagged); the
`previous_league_id` chains group cleanly per lineage; `STATUS.md` updated (B0 done, next = B2 compute — note B1
runs in parallel). No analytics computed; no frontend touched.

## Notes / gotchas
- **It's 31 slices, not 12.** The multi-season lineages (`trap` = 6, `ypfl` = 5, `dysf` = 4, `nbl` = 4, `fta` = 3)
  make the real compute workload ~31 league-seasons — size B2 accordingly (AI dossiers × ~31 slices × ~8–14
  teams ≈ a few hundred haiku calls; substrate is per `scoring_key`×`season`, shared across same-key leagues).
- **Lineage identity must be duplicate-proof.** Key each lineage on its **root league_id** — the earliest league
  in the chain, found by following `previous_league_id` back to null (e.g. `lorp`'s root is the 2024
  league_id `1132400260048977920`). League_ids are globally unique Sleeper ids, so a root-keyed `lineage_id` can
  never collide as the demo (or a future real user's imports) grows. The short slugs in `demo_slate.csv`
  (`lorp`, `trap`, …) are **human labels for this brief only** — do not persist them as the key; the display name
  comes from `corpus_discovery.name`.
- **Viewer for corpus leagues is provisional** — a valid owner now; refine to mid-table after B2 has standings if
  you want the most interesting personal-panel reads. Don't block B0 on it.
- **Keeper leagues (`rost`, `boys`, `wcfc`)** — confirm keeper leagues flow through the same as redraft here (no
  special handling needed for B0; they're just slices).
- **The panel policy is strict on purpose** — 30 of 31 slices show standings / VOR / projections / matchups /
  positional-depth / **dossiers**, but **no** market-trade panel and **no** bull/bear/sit grades. Only `lorp` 2025
  shows the full set. That's the "gate historical, keep dossiers" decision — honest over fabricated.
- **Don't recompute or move any existing derived data** — this is a recording session. B2 does the compute; B1
  (parallel) does the schedule league-scoping fix.
