"""
compute_demo_slices.py — the Stage-B (B2) full-set compute over the demo slate.

Reads `demo_manifest.parquet` (B0's slate: 31 (league_id, season) slices across 12 lineages, each
carrying `scoring_key`, `viewer_roster_id`, and the three panel flags) as its work-list and ensures
the complete derived analytics the loader (B3) needs exist for every slice — reusing what's already
on disk, computing only what's genuinely missing, and HONORING the panel policy. Store-agnostic: it
writes derived PARQUET only (`derived/league/<id>/` + the shared `derived/scoring/<key>/` substrate);
it does NOT load Postgres and does NOT touch the live app / `public/data` (that's B3).

Two phases (mirrors `MULTI_LEAGUE_STORE_MIGRATION.md` B2's dependency order):

  BASE  (un-gated — every slice):
    1. schedule — B1's league-scoped `export_schedule.run(season, league_id)` (points-dropped pairings).
    2. spine    — the 5 measurement reads, reusing `compute_spine._compute_league` where present,
                  computing where missing (in practice only the is_mine 2024 slice + any non-corpus).
    Substrate (`projection_consensus`/`ros_player_band` per scoring_key×season) is REUSED — it's already
    built for {ppr,half}×2020–2025 by the engine track's `build_substrate.py`; we never rebuild it here.

  DOSSIERS  (panel-gated + lineage-scoped):
    3. manager dossiers for the slices whose LINEAGE is in the backfill allowlist (`DOSSIER_LINEAGES`)
       and whose `panels_manager` is set: fan out `manager_activity` (the cross-league behavioural
       fetch), compute `manager_features`, write the Haiku dossiers, validate. Per the locked demo
       decision, the market + ros panels are gated ON for ONLY the is_mine 2025 slice (already computed
       in Stage A), so B2 computes NO new market/news data — a deliberate no-op.

Idempotent + resumable + per-slice-isolated (the compute_spine precedent): a sub-artifact already on
disk is skipped, so a long/interrupted run resumes rather than restarts; one slice's failure is logged
and isolated, never fatal, and never leaves a half-written slice that a re-run can't recover.

Usage:
    # everything the demo needs (base for all 31, dossiers for the 4 allowlisted lineages):
    python3 -m application.data.corpus.compute_demo_slices

    # just the un-gated base pass (schedule + spine for all 31):
    python3 -m application.data.corpus.compute_demo_slices --phase base

    # just the dossier backfill (the 4 lineages), e.g. as a resumable AI follow-on:
    python3 -m application.data.corpus.compute_demo_slices --phase dossiers

    # scope / debug:
    python3 -m application.data.corpus.compute_demo_slices --only-league 854774241676091392
    python3 -m application.data.corpus.compute_demo_slices --dossier-lineages 1132400260048977920 ...
"""
import argparse
import contextlib
import io
import sys
import time
from collections import defaultdict

from application.data import data_layer
from application.data.corpus import compute_spine
from application.data.transforms import (
    compute_manager_features,
    compute_bracket_sim,
    export_schedule,
)
from application.ai import write_manager_dossiers, check_manager_dossiers

# The lineages whose manager dossiers are backfilled this session (root-keyed lineage_id — the
# chain-root league_id B0 recorded). A representative subset spanning the demo's axes:
#   lorp  1132400260048977920 — ppr / 10 / 1QB / redraft — is_mine (your league)
#   nbl    599438300482174976 — half / 12 / 1QB / redraft / division — a 4-season lineage
#   bgb    866773569361801216 — ppr /  8 / SUPERFLEX / redraft
#   wcfc  1002292172076539904 — ppr / 12 / SUPERFLEX / keeper
# The other 8 lineages deliberately ship WITHOUT dossiers this session; a missing dossier degrades
# cleanly to the front-end's "No dossier for this manager" empty state (reads.py load_manager_dossier
# → {"missing": True}), so a skipped slice looks intentional, not broken.
DOSSIER_LINEAGES = (
    "1132400260048977920",
    "599438300482174976",
    "866773569361801216",
    "1002292172076539904",
)

SPINE_READS = compute_spine.READS


@contextlib.contextmanager
def _quiet():
    """Silence a compute's own verbose per-league prints; the driver prints its own concise lines."""
    with contextlib.redirect_stdout(io.StringIO()):
        yield


# --- work-list -----------------------------------------------------------------------------------

def targets(only_league=None):
    """The demo slices to process, in a deterministic order (season, then league_id). Each row carries
    league_id, season, scoring_key, viewer_roster_id, is_mine, lineage_id, and the three panel flags."""
    man = data_layer.read_demo_manifest()
    rows = [r for r in man.iter_rows(named=True)]
    if only_league:
        rows = [r for r in rows if str(r["league_id"]) == str(only_league)]
    rows.sort(key=lambda r: (int(r["season"]), str(r["league_id"])))
    return rows


# --- BASE: schedule + spine (un-gated) -----------------------------------------------------------

def _schedule_present(lid, season):
    return data_layer._schedule_path(season, lid).exists()


def _spine_present(lid, season):
    return compute_spine._spine_present(lid, season)


def _do_base(lid, season, scoring_key, timing, actions):
    """Ensure schedule + spine exist for one slice (reuse or compute). Returns without touching a
    sub-artifact already on disk (resumability)."""
    # 1. schedule — B1's league-scoped export (points dropped).
    if _schedule_present(lid, season):
        actions.append("schedule:reused")
    else:
        t = time.time()
        with _quiet():
            export_schedule.run(season, league_id=lid)
        timing["schedule"] += time.time() - t
        actions.append("schedule:computed")

    # 2. spine — reuse compute_spine's per-league compute where the 5 reads aren't all present.
    if _spine_present(lid, season):
        actions.append("spine:reused")
        return
    reason = compute_spine._degenerate_reason(lid, season)
    if reason:
        for rd in SPINE_READS:
            compute_spine._PATH[rd](season, lid).unlink(missing_ok=True)
        raise RuntimeError(f"degenerate raw — no spine: {reason}")
    compute_spine._compute_league(lid, season, scoring_key, timing)
    actions.append("spine:computed")


def _validate_spine(lid, season, scoring_key) -> str:
    """Determinism re-check for a freshly-computed spine (the is_mine slices sit outside the corpus
    manifest, so check_spine doesn't cover them). Recompute one read and assert byte-stable — the
    load-bearing property. Returns 'ok' / 'na' / a failure string."""
    try:
        from application.data.transforms import compute_production_vor
        before = data_layer.read_production_vor(season, league_id=lid)
        with _quiet():
            compute_production_vor.run(season, league_id=lid, scoring_key=scoring_key)
        after = data_layer.read_production_vor(season, league_id=lid)
        return "ok" if before.equals(after) else "NON-DETERMINISTIC production_vor"
    except Exception as e:  # noqa: BLE001
        return f"validate-error: {str(e)[:80]}"


# --- DOSSIERS: manager_activity → features → dossiers (panel-gated, lineage-scoped) ---------------

def _do_dossiers(lid, season, viewer_roster_id, actions, *, model, force=False):
    """Ensure the manager dossier set exists for one allowlisted slice (reuse or compute), then
    validate. Each sub-step is resumable (skip if its artifact is present)."""
    # 3a. manager_activity — the expensive cross-league fan-out fetch (LIVE Sleeper). Resumable:
    #     skip if the league's activity file already exists.
    if not data_layer.manager_activity_exists(season, league_id=lid):
        from application.data.fetchers import sleeper
        with _quiet():
            sleeper.fetch_manager_activity(lid, season)
        actions.append("activity:fetched")
    else:
        actions.append("activity:reused")

    # 3b. manager_features — deterministic, league-scoped.
    if not data_layer.manager_features_exists(season, league_id=lid):
        with _quiet():
            compute_manager_features.run(season, league_id=lid)
        actions.append("features:computed")
    else:
        actions.append("features:reused")

    # 3c. dossiers — the Haiku writer (self-gates zero-signal managers).
    if data_layer.manager_dossiers_exist(season, league_id=lid) and not force:
        actions.append("dossiers:reused")
    else:
        with _quiet():
            write_manager_dossiers.run(season, league_id=lid, force=force, model=model)
        actions.append("dossiers:computed")

    # 3d. validate — the existing internal-consistency gate, league-scoped.
    with _quiet():
        ok = check_manager_dossiers.run(season, league_id=lid)
    return "ok" if ok else "GATE-FAIL"


# --- driver --------------------------------------------------------------------------------------

def run(phase="all", only_league=None, dossier_lineages=DOSSIER_LINEAGES, model=None, force=False) -> dict:
    tgts = targets(only_league)
    do_base = phase in ("all", "base")
    do_doss = phase in ("all", "dossiers")
    model = model or write_manager_dossiers.client.DEFAULT_MODEL
    dossier_lineages = set(str(x) for x in dossier_lineages)

    t0 = time.time()
    timing = defaultdict(float)
    results = []          # per-slice: dict(league_id, season, actions, base_valid, dossier_valid)
    errored = []          # (league_id, season, error) — isolated; retried on re-run

    for i, r in enumerate(tgts, 1):
        lid, season, sk = str(r["league_id"]), int(r["season"]), str(r["scoring_key"])
        lineage, mine = str(r["lineage_id"]), bool(r["is_mine"])
        viewer = r.get("viewer_roster_id")
        gated_in = (lineage in dossier_lineages) and bool(r.get("panels_manager"))
        tag = f"[{i}/{len(tgts)}] {lid} {season} {sk}{' ⭐' if mine else ''}"
        actions, base_valid, doss_valid = [], "-", "-"
        try:
            if do_base:
                _do_base(lid, season, sk, timing, actions)
                # validate only a freshly-computed spine (reused spine is already gate-covered).
                if "spine:computed" in actions:
                    base_valid = _validate_spine(lid, season, sk)
                else:
                    base_valid = "reused"
            if do_doss and gated_in:
                doss_valid = _do_dossiers(lid, season, viewer, actions, model=model, force=force)
            elif do_doss:
                actions.append("dossiers:skipped(not-in-allowlist)")
            # market/ros panels: gated ON only for is_mine 2025 (already computed in Stage A) — no-op.
            if bool(r.get("panels_market")) or bool(r.get("panels_ros")):
                actions.append("market/ros:present(Stage-A)" if data_layer._market_vor_path(season, lid).exists()
                               else "market/ros:FLAGGED-MISSING")
            results.append({"league_id": lid, "season": season, "lineage": lineage, "is_mine": mine,
                            "actions": actions, "base_valid": base_valid, "dossier_valid": doss_valid})
            print(f"  {tag}  {', '.join(actions)}  | base={base_valid} dossier={doss_valid}")
        except Exception as exc:  # noqa: BLE001 — isolate one slice; a re-run retries it
            errored.append((lid, season, str(exc)[:160]))
            print(f"      ✗ ERROR (isolated, retried on re-run): {str(exc)[:160]}")

    report = {
        "phase": phase, "targets": len(tgts), "elapsed_s": round(time.time() - t0, 1),
        "timing": {k: round(v, 1) for k, v in timing.items()},
        "results": results, "errored": errored,
        "dossier_lineages": sorted(dossier_lineages),
    }
    _print_report(report)
    return report


def _print_report(rep: dict) -> None:
    print("\n=== demo-slice compute report ===")
    print(f"  phase={rep['phase']}  slices={rep['targets']}  wall-clock={rep['elapsed_s']}s")
    if rep["timing"]:
        print("  compute time by stage:")
        for k, v in rep["timing"].items():
            print(f"    {k:18} {v:>8.1f}s")
    # base coverage
    base_ok = sum(1 for r in rep["results"] if r["base_valid"] in ("ok", "reused"))
    doss_done = [r for r in rep["results"] if r["dossier_valid"] not in ("-",)]
    doss_ok = sum(1 for r in doss_done if r["dossier_valid"] == "ok")
    print(f"  base (schedule+spine): {base_ok}/{len(rep['results'])} valid")
    print(f"  dossiers: {doss_ok}/{len(doss_done)} slices validated "
          f"(lineages: {', '.join(rep['dossier_lineages'])})")
    er = rep["errored"]
    print(f"  errored slices (isolated; retried on re-run): {len(er)}")
    for lid, season, err in er:
        print(f"    {lid} {season}: {err}")


def main():
    ap = argparse.ArgumentParser(description="Stage-B B2 full-set compute over the demo slate.")
    ap.add_argument("--phase", choices=["all", "base", "dossiers"], default="all",
                    help="'base' = schedule+spine for all slices; 'dossiers' = the gated backfill; 'all' = both.")
    ap.add_argument("--only-league", type=str, default=None, help="restrict to one league_id (debug).")
    ap.add_argument("--dossier-lineages", nargs="+", default=list(DOSSIER_LINEAGES),
                    help="lineage_ids to backfill dossiers for (default: the 4 representative lineages).")
    ap.add_argument("--model", default=None, help="Haiku model for dossiers (default: client.DEFAULT_MODEL).")
    ap.add_argument("--force", action="store_true", help="regenerate dossiers even if present.")
    a = ap.parse_args()
    run(phase=a.phase, only_league=a.only_league, dossier_lineages=a.dossier_lineages,
        model=a.model, force=a.force)


if __name__ == "__main__":
    main()
    sys.exit(0)
