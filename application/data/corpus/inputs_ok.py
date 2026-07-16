"""Versioned `inputs_ok` derivation — the per-(league, season) input-integrity flag for the L2
predictions ledger (Session 4a).

`inputs_ok` answers "were this claim's inputs trustworthy?" It is a DERIVED column (Will's call — no
`data_health` entity; that daily `(date, source)` table is a live-path Session-7 concern whose grain
doesn't fit a frozen 2022 league). It is derived from four signals already produced at harvest/selection
on the FROZEN corpus:
  1. manifest `filter_result`   — the league passed the inclusion filter,
  2. manifest `id_resolution_pct` — % of rostered skill players resolving to a gsis_id,
  3. the degenerate-league flag  — garbled playoff config ⇒ no season to simulate,
  4. the per-league remainder rate — rostered mass lost to unresolvable players in `join_season`.

Signals 1–2 are persisted manifest columns; 3 is `compute_spine._degenerate_reason`; 4 is recomputed via
`check_harvest._remainder_rate` (there is no stored remainder column — the same scan the harvest gate uses).

The thresholds are PINNED + VERSIONED so that when the perpetual-refinement loop re-derives `inputs_ok`
on new leagues a year from now, "ok" means the same thing. They are set STRICTER than the selection /
harvest bounds (id ≥ 98 vs the 90.0 selection floor; remainder ≤ 0.08 vs the 0.15 harvest bound) so the
genuinely marginal corpus leagues resolve `false` — the `false` path gets real offline coverage instead
of debuting untested in a live week (standing instr 1: a blanket-true flag is the suspiciously-clean trap).
Measured across the 270 spined league-seasons (2026-07-16): id_resolution_pct min 97.6 / median 100;
remainder_rate median 0.005 / p95 0.056 / max 0.107. Under these thresholds **4 league-seasons flip
`false`** (all four on the remainder axis; one also on the id axis) — real, bounded coverage.
"""
import polars as pl

from application.data import data_layer
from application.data.corpus import check_harvest, compute_spine

# Versioned so "ok" is stable across future re-derivations. Bump `version` whenever a threshold changes
# (that changes what "ok" means, exactly the drift the version tag exists to make visible).
INPUTS_OK_THRESHOLDS: dict = {
    "version": "2026-07-16",
    "require_filter_pass": True,     # manifest filter_result must be "pass"
    "require_non_degenerate": True,  # compute_spine._degenerate_reason must be None
    "id_resolution_min": 98.0,       # % rostered skill → gsis_id; stricter than the 90.0 selection floor
    "remainder_rate_max": 0.08,      # rostered-mass loss to remainders; stricter than the 0.15 harvest bound
}


def inputs_ok_detail(league_id, season: int, *, manifest: pl.DataFrame | None = None) -> dict:
    """The full derivation with its reasons — a dict:
    `{ok, filter_result, id_resolution_pct, degenerate, remainder_rate, fail_reasons}`.

    `manifest` may be passed to avoid re-reading it per league in a batch (the driver reads it once and
    threads the frame). `fail_reasons` names every signal that flipped `ok=False` (the driver stamps
    `ok`; the gate reports the reasons)."""
    lid, s = str(league_id), int(season)
    man = manifest if manifest is not None else data_layer.read_corpus_manifest()
    row = man.filter((pl.col("league_id") == lid) & (pl.col("season") == s))
    if row.is_empty():
        return {"ok": False, "filter_result": None, "id_resolution_pct": None, "degenerate": None,
                "remainder_rate": None, "fail_reasons": ["not_in_manifest"]}
    r = row.row(0, named=True)
    thr = INPUTS_OK_THRESHOLDS
    filter_result = r["filter_result"]
    id_pct = float(r["id_resolution_pct"])
    degenerate = compute_spine._degenerate_reason(lid, s)
    try:
        reg_end = check_harvest._reg_end(lid, s)
        _, _, remainder_rate = check_harvest._remainder_rate(lid, s, reg_end)
    except Exception:                       # no reg config ⇒ treat as maximally lossy (fails the bound)
        remainder_rate = 1.0

    reasons = []
    if thr["require_filter_pass"] and filter_result != "pass":
        reasons.append(f"filter_result={filter_result}")
    if thr["require_non_degenerate"] and degenerate is not None:
        reasons.append(f"degenerate:{degenerate[:40]}")
    if id_pct < thr["id_resolution_min"]:
        reasons.append(f"id_resolution_pct={id_pct}<{thr['id_resolution_min']}")
    if remainder_rate > thr["remainder_rate_max"]:
        reasons.append(f"remainder_rate={round(remainder_rate, 4)}>{thr['remainder_rate_max']}")
    return {"ok": not reasons, "filter_result": filter_result, "id_resolution_pct": id_pct,
            "degenerate": degenerate, "remainder_rate": round(remainder_rate, 4), "fail_reasons": reasons}


def derive_inputs_ok(league_id, season: int, *, manifest: pl.DataFrame | None = None) -> bool:
    """True iff all four frozen integrity signals clear the pinned thresholds."""
    return inputs_ok_detail(league_id, season, manifest=manifest)["ok"]
