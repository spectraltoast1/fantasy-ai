# V1 · Project 2 · Session S3b — Surface the honest band (rebuild + wire) — a brief for Code

**Last reviewed:** 2026-07-30 · **Status:** Ready to run · **Owner:** Code drives; Will eyeballs the honest
band on the live demo. **Project:** `projects/v1/P2_GO_LIVE_2026.md` (S3b — the deferred half of S3). **This
is the honesty payoff: the first time the 8c band reaches the screen.**

> **What this session does:** the S3 finding was that the honest deterministic ROS band (`ros_player_band`,
> governed by `CENTER_SHRINK=0.8` et al.) has **no wire to the screen** — not in `build_db.DATASETS`, no
> Postgres table, selected by zero endpoints. S3b builds that wire end-to-end: (1) **rebuild** the 2020–2025
> band under the honest constants (fixing the 0.8-vs-1.0 store drift) and fold it into the weekly cadence so
> it stays honest; (2) **load** `ros_player_band` into Postgres scoring-keyed; (3) **select** it in
> `load_player_card`; (4) **render** a deterministic "Rest-of-season range" panel on the player card.
> `P2_GO_LIVE_2026.md` S3b.

> **It ADDS a surface — it does not fill the existing empty state.** The card's "No rest-of-season outlook
> yet" is the **AI** `ros_synthesis` read (bull/bear/situation on live news — P4 territory), a *different
> object* that's empty until in-season. The new deterministic range sits **next to** it, always available
> (the deterministic core stands on its own, independent of the AI grades). Don't conflate the two.

## Your part, Will (~5 min — a sizing awareness + the eyeball)
No big strategic fork here — it's an execution session. Two things for you: (1) **sizing** — this is on the
fuller side (rebuild + cadence + loader-add + API + frontend), so if it bumps the 3-commit cap, the frontend
panel is the clean piece to split into a fast-follow rather than cram. (2) **the eyeball that matters** — on
the live demo, a player's card shows a **"Rest-of-season range"** whose **center matches the production VOR
already on the card** (both honest at 0.8), with bear ≤ center ≤ bull and a confidence read. That center-match
is the whole proof the honest band reached the screen without contradicting itself.

## Decisions I made for you (Code: follow unless you hit a reason not to)

1. **Rebuild the historical band honest — mandatory, not cleanup.** Rebuild `ros_player_band` for 2020–2025 ×
   {ppr,half} under the current honest constants (the store is stale at pre-8c `CENTER_SHRINK=1.0`;
   production_vor already serves `0.8`). This is a **correctness prerequisite of the wire**:
   `production_vor.ros_value` = `0.8 ×` the stale `ros_center`, so wiring the stale band would render a
   ROS-range center ~1.25× above the production VOR on the *same card* — a visible contradiction.
   Determinism-check recompute==intended; prove the rebuilt center == production_vor's implied center on the
   is_mine slice.
2. **Fold the band into the weekly cadence so the drift can't recur.** Today `weekly_refresh` / `compute_spine`
   rebuilds production_vor but never the band, so the band freezes while production_vor advances and the drift
   re-opens week over week. Make the band rebuild alongside production_vor in the spine so it stays honest and
   current. Additive to S2's pipeline — do **not** change the scoped-reload mechanics.
3. **Load `ros_player_band` into Postgres scoring-keyed — the `projection_consensus` pattern.** Add it to
   `build_db.DATASETS` + `schema.sql`, keyed by scoring like the other per-slice tables. **Re-run the S2
   byte-parity oracle** with the new table in the set — a scoped reload must still be byte-identical to a full
   reload for a league (now across the added table too). The scoped reload is table-generic, so this is
   additive; the oracle is the guard. If scoped != full, stop.
4. **Select it in `load_player_card` + render a "Rest-of-season range" panel.** API: `load_player_card`
   returns the ROS range (bear/center/bull + `ros_cv` confidence) from the new table. Frontend: a new panel on
   the player card, **next to** the AI `ros_synthesis` panel (which keeps its own empty state). The
   deterministic range is **always available** — no gating like market/AI; it's the deterministic core. Label
   it clearly as the model's range, distinct from the AI outlook.
5. **Preseason renders the forward-prior band gracefully.** In preseason the band width is the forward
   positional prior (S1's forward path); the **center is still player-specific** (it tracks production_vor), so
   the range is informative per player, not flat across players. Render it cleanly (bear ≤ center ≤ bull); don't
   treat a positional-prior width as an error. It sharpens as real weeks accrue (the S2 cadence).
6. **Scope guard.** Touches: the band builders (rebuild) + `weekly_refresh` / `compute_spine` (fold the band
   into cadence) + `build_db.py` (add the dataset + re-prove parity) + `reads.py` (`load_player_card`) + the
   frontend (new panel) → **redeploy** to surface it. Does **NOT** touch the market work (S3 done), the
   loader's scoped-reload *mechanics* (S2 done — you're adding a table to the existing generic path, guarded by
   the oracle), auth (P5), or the cloud-execution refactor (deferred). Runs **locally** (like S1/S3) — writes
   to prod Postgres, no cloud execution. Fly secrets unchanged.

## The brief to paste to Code

```
Goal: V1 Project 2, Session S3b (projects/v1/P2_GO_LIVE_2026.md) — surface the honest band. The S3 finding
was that ros_player_band (the deterministic ROS band governed by CENTER_SHRINK=0.8 et al.) has no wire to the
screen: not in build_db.DATASETS, no Postgres table, selected by zero endpoints. Build the wire end-to-end +
fix the store drift. Runs locally (no cloud execution). Redeploy to surface the panel.

Part 1 — rebuild honest + fix the cadence (correctness):
- Rebuild ros_player_band 2020-2025 x {ppr,half} under the current honest constants (store is stale at pre-8c
  CENTER_SHRINK=1.0; production_vor already serves 0.8). MANDATORY, not cleanup: production_vor.ros_value ==
  0.8 x the stale ros_center, so wiring the stale band would show a ROS-range center ~1.25x above the
  production VOR on the same card. Determinism-check recompute==intended; prove rebuilt center == the
  production_vor implied center on the is_mine slice.
- Fold the band rebuild into weekly_refresh/compute_spine so it advances WITH production_vor and the drift
  can't re-open week over week. Additive — do NOT change the S2 scoped-reload mechanics.

Part 2 — load + select + render (the wire):
- Add ros_player_band to build_db.DATASETS + schema.sql, scoring-keyed (the projection_consensus pattern).
  RE-RUN the S2 byte-parity oracle with the new table: scoped reload must still == full reload for a league.
- reads.load_player_card returns the ROS range (bear/center/bull + ros_cv confidence) from the new table.
- PlayerCard renders a new "Rest-of-season range" panel NEXT TO the AI ros_synthesis panel (which keeps its
  empty state — a different object, P4). The deterministic range is always available (no gating). Label it
  clearly as the model's range, distinct from the AI outlook. Forward-prior (preseason) renders gracefully:
  player-specific center, positional-prior width, bear<=center<=bull.

Parity line: only the new ROS-range panel appears + the band store becomes honest. Every other surface
(production VOR, matchups, the S3 market gating, standings) identical. On the live demo, a player's
Rest-of-season range center matches the production VOR already shown (both honest at 0.8), bear<=center<=bull.

Follow SESSION_GUIDE: fresh worktree, worktree-setup.sh, 3-commit cap, update STATUS.md, close/merge, push.
Suggested commits: (1) rebuild band honest + fold into cadence + determinism/drift proof; (2) load
ros_player_band into Postgres + re-prove scoped-reload parity + API select in load_player_card; (3) the
Rest-of-season range panel + redeploy + live verify (honest band renders; center == production VOR) + STATUS.
If it runs long, the frontend panel is the natural piece to land last/split. Show me: a player's card with the
honest Rest-of-season range, center == production VOR; and the parity oracle green with the new table.

Close: update STATUS.md (P2/S3b done: honest band wired end-to-end + store drift fixed + folded into the
weekly cadence; first time 8c is visible; next = P2/S4 early-season readiness). Merge/push.
```

## Definition of done (S3b)
✅ The player card renders a deterministic **"Rest-of-season range"** (bear/center/bull + confidence) whose
center **matches the served production VOR** (both honest at 0.8), sitting **next to** — not replacing — the AI
`ros_synthesis` panel. `ros_player_band` is rebuilt honest, loaded into Postgres scoring-keyed, and folded into
the weekly cadence so the 0.8-vs-1.0 drift can't recur; the S2 scoped-reload byte-parity oracle is green with
the new table. Only the new panel + the honest band store change; every other surface identical. Redeployed +
verified live. STATUS updated, S4 next.

## Notes / gotchas
- **This is the honesty payoff — verify by eye.** All the 8c tuning finally reaches the screen. The proof is a
  player's Rest-of-season range center lining up with the production VOR already on the card (no
  contradiction), in the honest (lower/wider) shape.
- **The rebuild is a correctness gate, not cosmetic.** Wiring the stale band would ship a visible
  self-contradiction. Rebuild first, prove the center-match, then wire.
- **Additive to the loader, guarded by the oracle.** You're adding a table to the generic scoped-reload path
  S2 built — not changing its mechanics. The byte-parity oracle (now including the new table) is the safety
  net; if scoped != full, stop.
- **Runs locally — no cloud dependency.** Like S1/S3, the rebuild + reload run where the store lives; the
  deferred cloud refactor doesn't block this.
- **Don't touch the market (S3) or the AI outlook (P4).** The new panel is the deterministic range only. The
  AI `ros_synthesis` panel keeps its own empty state; the market stays gated per S3.
- **Handoff to S4:** early-season readiness — how Weeks 0–3 of a live 2026 league degrade gracefully, and
  where the live 2026 market panel turns on (with its cadence / `MARKET_PROFILE` / week-replay items from the
  S3 findings).
