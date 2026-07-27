# Stage B Audit — B2 (full-set compute over the demo slices)

**Reviewed:** 2026-07-26 · **By:** PM (independent, against live git + the actual derived parquet on disk)
**Scope:** the heavy compute session — schedule + spine + dossiers for the 31-slice demo slate, honoring the
panel policy, writing derived parquet only. Three commits in `worktree-stage-b2`, merged to `main`.

**Bottom line: the machinery is correct and the base pass is complete for all 31 slices; the live app and
production DB were untouched (right — B3 owns the reload). There is one substantive item — Code shipped
manager dossiers for 11 of 31 slices, not all 31 — and it is half a defensible discovery and half an
over-trim. The over-trim is a one-command fix, not a blocker. The discovery underneath it is important and
partly on me: my "dossiers on all 31" premise was never structurally achievable, and Will should recalibrate
what the dossier panel will actually show.**

---

## Verified clean (I re-read the data, not just the report)

**Base pass — 31/31 slices complete.** Every demo slice has all five spine reads (`production_vor`,
`true_rank`, `positional_depth`, `bracket_odds`, `player_signal`) **plus** B1's league-scoped
`schedule_<season>.parquet`, each under its own `derived/league/<id>/`. I checked all 31 `(league_id, season)`
pairs from the manifest against disk — zero gaps. This is the bulk of B2 and it's done and correct.

**Store-agnostic — confirmed.** The three B2 commits changed exactly six files: the new driver
`compute_demo_slices.py` (+284), the two AI producers (`write_manager_dossiers.py`,
`check_manager_dossiers.py`), `compute_manager_features.py` (the league-scoping thread), and STATUS /
ARCHITECTURE. **No** `build_db`, no `serve/`, no `.sql`, no `frontend/public/data`, no Postgres. The deployed
site and the production DB are exactly as Stage A left them. That's the discipline the brief demanded.

**Panel gate held — honest over fabricated.** `market_vor`, `ros_league_view`, and `ros_synthesis` exist on
disk for **exactly one** slice — lorp 2025 (`1182…823296`), which already had them from Stage A. Zero
gated-off market/news panels were computed for any of the other 30 slices. The "gate historical, keep
dossiers" decision is respected to the letter.

**The driver is genuinely idempotent / resumable / isolated.** I read it end to end. Every sub-artifact
(schedule, spine, activity, features, dossiers) is skip-if-present; each slice is wrapped in its own
try/except so one failure logs and continues without a half-write; a re-run resumes. This isn't just claimed
— STATUS records a real malformed-JSON Haiku reply on nbl 2024 that was isolated and recovered on re-run.
The producers were correctly league-scoped (`*, league_id=None`, default is_mine, backward-compatible),
mirroring the L0 keying the spine already had. Substrate was reused, never rebuilt; lorp 2025's dossiers were
correctly recognized as done (mtime Jul 13, Stage A) and left alone.

---

## The one substantive finding — dossier coverage is 11/31, and the "why" matters more than the "how many"

The B2 brief (mine) said **dossiers for all 31**, self-gating thin managers to a "no intel" state. Code
instead built dossiers for **11 slices across 4 lineages** — lorp (2), nbl (4), dysf (4), wcfc (1) — and left
20 slices (8 lineages) with no dossier rows at all. Code labeled the pick "signal-first."

I verified the underlying mechanism and the actual signal, and it splits into two very different halves.

**Half that's a real, correct discovery — and I got the premise wrong.** A manager's dossier is built from
`select_comparables`, which **excludes the manager's own league** and keeps only *other* leagues that match
it **exactly** on scoring, team-count, QB-structure, and format. So a dossier is a cross-league reputation
drawn from a manager's *other* comparable leagues — not from their transactions in the league you're viewing.
The consequences, confirmed in the data:

- **wcfc 2023 (8-team superflex keeper): 0 of 12 managers have signal.** Superflex and keeper are rare
  formats; managers rarely have a *second* league of the same exact shape, so there's nothing to profile
  from. This isn't laziness — it's structural. Code's instinct to not burn API calls on formats that can't
  populate is sound.
- **The bigger surprise: even the flagship lorp 2024 is 9 of 10 zero-signal** — only Will himself populates.
  lorp is a 10-team league of friends; 10-team is uncommon and Will's leaguemates mostly don't play in other
  10-team PPR redraft leagues, so there's no comparable history to draw on. Only Will — who *is* in many
  harvested leagues — comes back rich.

That second point is the one to sit with. **My B0/B2 premise — "dossiers ON for all 31, because every league
has transaction history" — was wrong.** Dossier richness doesn't come from the league's own transactions; it
comes from each *manager* having other same-shape leagues. That's concentrated in 12-team standard/half/PPR
redraft leagues (where multi-league players cluster) plus the primary user. Everywhere else it's sparse or
empty. That's honest product behavior — a casual friends league genuinely has little cross-league intel — but
it's far sparser than "dossiers everywhere" implied. Own that one on me, same as the B0 viewer slip.

**Half that's an over-trim — and this is the actual finding to act on.** "Signal-first" is not quite what the
pick was. The two biggest corpus showcases — **trap (12-team PPR redraft, 6 seasons)** and **ypfl (12-team
PPR redraft, 5 seasons)** — are the *exact* profile as nbl, which came back **12/12 rich**. They were
**dropped**, while the known-empty wcfc (0/12) was *kept* as a "graceful degradation" demo. A genuinely
signal-first pick would have prioritized trap and ypfl over an empty demonstrator. So ~11 slices of
likely-rich, fully-achievable dossier content — on the two deepest multi-season lineages — were left on the
table. (For contrast, dysf 2020 — also 10-team — came back **10/10 rich**, because *its* managers do have
comparable neighbors. Format alone doesn't predict it; the manager's cross-league footprint does.)

**Which of the 20 skipped slices would actually populate if run** (my read from the mechanism + the observed
data):

| skipped lineage | profile | seasons | likely result | verdict |
|---|---|---|---|---|
| **trap** | 12-team PPR redraft | 6 | **rich** (nbl's twin) | **should backfill** |
| **ypfl** | 12-team PPR redraft | 5 | **rich** (nbl's twin) | **should backfill** |
| fta | 14-team half redraft | 3 | partial (14-team less common) | optional |
| phb | 14-team PPR redraft | 1 | partial | optional |
| lines | 10-team half redraft | 1 | uncertain (lorp-like vs dysf-like) | optional |
| bgb | 8-team PPR **superflex** | 2 | empty (structural) | correctly skipped |
| boys | 8-team half **SF keeper** | 1 | empty (structural) | correctly skipped |
| rost | 12-team half **keeper** | 1 | empty (redraft-only comparability) | correctly skipped |

**Why this is not a blocker:** the driver already exposes `--dossier-lineages` as a CLI argument. Backfilling
the two showcases is one resumable command, no code change:

```
python3 -m application.data.corpus.compute_demo_slices --phase dossiers \
  --dossier-lineages 515692323082268672 606543373242806272
```

(a live Sleeper fan-out + a few dozen Haiku calls; cheap, isolated, additive parquet). If Will runs it before
B3, the loader picks the new dossiers up automatically. My recommendation: **run trap + ypfl, accept the
honest-empty state for the superflex/keeper trio, and treat fta/phb/lines as optional.** That lands the demo
where the "dossiers everywhere" decision was actually reaching — as far as the data structurally allows —
without fabricating intel that doesn't exist.

---

## Forward handoffs into B3 (baked into the B3 brief)

1. **Load `schedule` from the new `derived/league/<id>/schedule_<season>.parquet`** (+ `league_id` column),
   not the old root — B1's still-open handoff.
2. **Load all 31 slices from the derived store** (not `public/data`). Base analytics exist for all 31;
   **dossiers exist for 11** (or more, if the trap/ypfl backfill is run first). The loader **must tolerate a
   league with zero dossier rows** — the WHERE returns empty → `{"missing": True}` → the front-end's clean
   "No dossier for this manager" state. Verified that path exists.
3. **`owner_id` is already a first-class column** on both `manager_features` and `manager_dossiers` parquet
   (confirmed on disk). B3 must **carry it into the load/schema** so the deferred owner-keyed refinement stays
   a small read-swap — the prerequisite from `OWNER_KEYED_MANAGER_PROFILES.md`, now easy to honor because the
   compute layer already emits it.
4. Add `GET /api/leagues` (the lineage-grouped catalog) + league/season selectors.

## Recommendation

**B2 is sound; ship it.** The compute machinery, base coverage, store-agnosticism, and panel gate are all
correct and verified. Before B3 loads the demo, run the **trap + ypfl dossier backfill** (one command) so the
two deepest showcases aren't empty — and update our shared expectation that the dossier panel is a
*cross-league* signal that lights up mainly for 12-team standard formats and the primary user, not a
"present on every team" panel. That expectation reset is the real product takeaway from this session.
