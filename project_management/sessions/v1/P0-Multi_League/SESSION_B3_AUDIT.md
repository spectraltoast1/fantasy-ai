# Stage B Audit — B3 (load all 31 slices + `GET /api/leagues`)

**Reviewed:** 2026-07-26 · **By:** PM (independent — against live git on `main`, the actual derived
parquet on disk, and the live deployed app at fantasy-ai-api.fly.dev)
**Scope:** the **first Stage-B production write** — rewrite `build_db.py` into a manifest-driven
multi-slice loader, reload the live Supabase from the derived store, and add the lineage catalog
endpoint. Three commits (`25aa4b8`, `fda30a3`, `d57ead4`) + merge `9a7218b` on `main`; tree clean.

**Bottom line: the dangerous part was done right and I can prove it.** The production reload
preserved the live app — I independently confirmed the is_mine league still serves correct data
(standings, weeks, league, matchups). All three bugs Code caught pre-flight were real; I reproduced
each in the data. The loader code is faithful to the brief on every point. The `ros_synthesis 16→0`
change is a defensible, honest call, not a mistake — but it is a **visible product change** to the
flagship demo slice that Will should consciously ratify. **One concrete gap:** the new
`GET /api/leagues` endpoint is **not live on the deployed app (404)** — the database was reloaded but
the app image was not redeployed. Low-severity (nothing consumes it until B5), but the report's
framing implies it's live and it isn't. **Endorse B3, with two items to close going into B4.**

---

## Verified clean (I re-read the code, the data, and the live app — not the report)

**Git + code faithful to the brief.** Three commits land the exact split the brief asked for. I read
`build_db.py` end to end (merged `9a7218b`), and every decision is implemented as specified:

- **Manifest-driven, all 31 slices, sourced from the derived store via `data_layer`** — no
  hand-built paths (`DATASETS` maps each dataset to a `data_layer` path helper).
- **Reads the RAW parquet, not the `read_*` accessors** — the accessors apply the app's "latest
  week" slice, which would have loaded only the newest week. Confirmed in the data: is_mine
  `production_vor` is **635 rows across weeks 1–4**; the sliced accessor returns **164** (week 4
  only). Code's "635 not 164" is exact. This is the bug that would have silently broken the week
  switcher for every historical week.
- **Skip-if-absent** (`if not p.exists(): continue`) — panel gating falls out of the data, no crash,
  no fabrication.
- **`schedule` `league_id` de-dup** — `_copy_slice` asserts the parquet's own `league_id` equals the
  slice, then drops it before COPY, so every table has exactly one `league_id` (the double-column SQL
  error the brief warned about).
- **`owner_id` retained + indexed** — `ix_manager_dossiers_league_id_owner_id` is in `schema.sql`
  (the OWNER_KEYED prerequisite; keeps the deferred rework a read-swap, not a reload).
- **`verify()` went multi-league** — asserts per-table row count == the on-disk sum over present
  slices, prints per-table distinct-league counts + an is_mine parity spot-check. The
  `n_leagues == 1` assertion is gone.
- **`--dry-run`** — offline load/skip plan with expected counts, no DB connection. A genuinely useful
  addition beyond the brief.

**The two bugs Code caught mid-flight were real — I reproduced both.**

- **Union schema across slices.** The is_mine `teams` parquet has **no `division` column** (cols:
  `roster_id, team_name, owner_name, owner_id`), but division-aware corpus leagues carry one. A DDL
  built from the is_mine reference alone would `DROP+CREATE` then fail on a division-bearing slice
  mid-COPY. `schema.sql` correctly carries `division BIGINT` (the union), and per-slice COPY names
  only its own columns. The commit notes the first `--load` hit exactly this and the corrected
  re-load restored the is_mine data — the honest "direct-reload risk, roll-forward-recovered" story.
- **`weeks_available` source.** is_mine `schedule` carries the full forward pairing structure —
  **weeks [1–18]**; the `season` table carries only **played weeks [1–4]**. `load_leagues()` (and the
  `/api/leagues` contract) correctly derives `weeks_available` from `season`, the same source
  `load_weeks` uses. The live `/api/weeks` returns **[1,2,3,4]**. Correct.

**The catalog code matches the contract.** `reads.load_leagues()` groups by `lineage_id` (the root
`league_id` string, not a slug), seasons descending, is_mine first; `weeks_available` from the loaded
`season` table; `panels`/`name`/`viewer_roster_id` mirrored from the manifest. I read the
`demo_manifest.parquet` directly: **31 slices / 12 lineages**, both is_mine slices pin
`viewer_roster_id = 8` (the corrected value, not the doc's "7" slip). Shape is right.

**Parity held for the live app — independently confirmed.** I hit the deployed app directly:
`/api/standings?as_of_week=4` returns the real 10-team is_mine league with `isMe:true` on roster 8
(Tet Lasso / spectraltoast1) and correct Week-4 playoff odds; `/api/league` and `/api/weeks` serve
correctly too. And I reconstructed the parity mechanism from the file layout: Stage-A `public/data`
symlinked to the **same** `derived/league/1182…` files B3 now loads — so the is_mine slice reloads
**byte-identical except** (a) `schedule`, now the B1 league-scoped copy (B1 already proved byte-parity
of the pairings), and (b) `ros_synthesis`, intentionally dropped (below). That structurally confirms
Code's "identical except ros_synthesis 16→0" without taking it on faith.

---

## Finding 1 — `GET /api/leagues` is not live on the deployed app (the item to act on)

The endpoint code is merged and correct, and the `demo_manifest` catalog table is in the reloaded
DB. But the **deployed Fly app returns 404 for `/api/leagues`** — I hit it three times with fresh
cache-busted URLs; each 404'd, while the sibling Stage-A routes (`/api/league`, `/api/weeks`,
`/api/standings`) all return 200 on the same app. The only difference is that `/api/leagues` is
**new B3 code**. Conclusion: **the database was reloaded, but the app image was not redeployed** with
the B3 code, so the new route isn't served.

**Severity: low, but it's a real gap between "merged + loaded" and "live."** Nothing consumes
`/api/leagues` until B5 (the commit itself says "not wired into any view this session"), and the
parity headline — the is_mine app rendering identically — does **not** depend on it. So the demo is
unaffected today. But two things are worth stating plainly:

1. The report's headline ("…plus the catalog endpoint") reads as *live*; on the deployed app it
   **404s**. Code's parity checklist verified weeks/standings/league/matchups on the deployed app but
   did **not** include hitting the deployed `/api/leagues` — a small blind spot, because it isn't
   there to hit.
2. **Action:** either redeploy the app now to make `/api/leagues` live (and re-verify it returns the
   lineage tree on the deployed URL, not just in the worktree), **or** consciously accept that it goes
   live with the B4/B5 redeploy. B4 (parameterize the reads) will require a redeploy regardless, so
   folding the `/api/leagues` deploy into B4 is the natural path — as long as nobody believes it's
   already live in the meantime.

---

## Finding 2 — the live demo lost its ROS "bull/bear/sit" grades (a decision fork for Will)

**What happened, in plain English.** The flagship is_mine slice used to show forward-looking
"rest-of-season" grades on player cards (the bull / bear / sit calls). Those came from a file that was
actually built from **2026 news** and shown under the **2025** season — a known proof-of-concept
splice from Stage A. B3 sources every dataset faithfully by `(league, season)`; the only ROS file on
disk is `ros_synthesis_2026.parquet` (16 rows, season 2026), and no demo slice is season 2026, so the
loader finds nothing at 2025 → **16 rows → 0**. On the live app those grades now render "—".

**My read: Code made the right call, and disclosed it honestly.** Showing 2026 news as 2025 ROS was
the dishonest state; an empty "—" is the honest one. This is squarely in line with the engine's
north star — *confidence-honesty over a fake crystal ball*. It also isn't a rogue decision: it's the
direct, unavoidable consequence of the brief's own "source from the derived store by season" rule.
The brief was quietly self-contradictory (it also listed `ros_synthesis` as a dataset that "exists
for the is_mine slice"), Code hit the contradiction, resolved it toward honesty, and said so plainly.

**But it is a visible product change to your best demo slice, so it's yours to ratify.** Two sub-points:

- The `demo_manifest` still flags `panels_ros = true` for lorp-2025, while the data behind it is now
  empty. Harmless today (the app degrades to "—"), but it's a **catalog-says-available / data-is-empty
  mismatch** that B5's panel-gating will inherit. B4/B5 must define the "flagged-on-but-empty"
  behavior, **or** flip `panels_ros → false` for lorp-2025 so the catalog matches reality.
- If the bull/bear/sit grades matter for how impressive the demo looks, the honest way to bring them
  back is a **real 2025 (year-matched) news read** — not the 2026 splice. That's future work, out of
  B3 scope; the ROS table and read path were correctly left in place for exactly that.

**Recommendation:** ratify the honest-empty state for now (cheapest, preserves the current layout,
matches the north star), and decide the panel flag: I lean toward keeping `panels_ros = true` so the
panel stays visible-but-empty (closest to today's app) **and** adding a one-line note in the B4/B5
brief that the flag currently outruns the data. Reopen "real 2025 ROS read" only if the demo needs
the grades back. `market_vor` is unaffected — it still loads for lorp-2025 and that panel is intact.

---

## Not findings (as-designed, noted so they don't resurface)

- **`projection_consensus` is duplicated per slice** (same players under many `league_id`s). The
  brief explicitly accepted this to keep the read SQL untouched; a scoring-keyed single-load
  normalization is a real later option, not a B3 defect.
- **Dossiers loaded for 11 of 31 slices.** This is the locked B2 coverage (Will's call — not
  relitigated). The loader tolerates zero-dossier leagues cleanly; the count is whatever was on disk.
- **`verify()` proves DB == disk, not DB == pre-B3.** Its is_mine spot-check prints counts without
  asserting them against the Stage-A baseline — so the automated verify corroborates the load, but the
  true parity proof is the byte-identical-source argument above + the live-endpoint check, both of
  which I ran independently.

---

## Recommendation

**B3 is sound — endorse it.** The one genuinely risky action in the whole Stage-B program (a
`DROP+CREATE` reload of the live production DB) was executed correctly, verified, and independently
re-verified here: the live app still serves the is_mine league correctly. The three pre-flight bugs
were real and their fixes are correct. Two things to carry into B4, neither a blocker:

1. **Deploy `/api/leagues`.** It's merged and DB-backed but 404s on the live app — redeploy (bundled
   with B4 is fine) and verify the tree on the deployed URL.
2. **Ratify the ROS retirement + reconcile the panel flag.** Accept honest-empty (my rec), and either
   define the "panel on but empty" behavior for B5 or flip `panels_ros=false` for lorp-2025 so the
   catalog stays honest.

Then draft B4 — parameterize every read endpoint on `league_id` + `season`.
