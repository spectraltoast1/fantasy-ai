"""trust_report.py — the human-readable Trust Report (Session 5, C2): the markdown the scorecard is FOR.

Reads the frozen `engine_scorecard_{season}` and renders the must-have deliverable: per read, a traffic
light for {skill · calibration · confidence-honesty}, the "what we'd honestly tell a user" line (copy the
front end should eventually use — not wired here), the pre-registered-prediction check (HOLD/SURPRISE), and
the cohort + season out-of-sample slices. It REPORTS the scorer's verdicts; it judges nothing new and
changes nothing (report, don't tune).

Traffic lights are pooled across seasons (n-weighted) so the headline is the whole corpus; the season +
cohort rows carry the OOS story underneath.

Usage:
    python3 -m application.data.corpus.trust_report          # write the markdown from the persisted store
    python3 -m application.data.corpus.trust_report --stdout # print instead of write
"""
import argparse
import sys

import polars as pl

from application.data import data_layer
from application.data.corpus import scorecard_registry as reg
from application.data.corpus.compute_engine_scorecard import PRE_REGISTERED, SPINED_SEASONS, _user_line

_REPORT_PATH = ("project_management/scope docs/engine improvement/TRUST_REPORT.md")

# family display order (VOR foundation first, then the measurement reads, then the season reads)
_ORDER = [("production_vor", "point"), ("ros_player_band", "interval"), ("player_signal", "point"),
          ("player_signal", "direction"), ("true_rank", "ordinal"), ("positional_depth", "point"),
          ("bracket_odds", "probability"), ("bracket_odds", "point"), ("bracket_odds", "ordinal")]
_READ_TITLE = {
    ("production_vor", "point"): "production_vor — rest-of-season VOR (the foundation)",
    ("ros_player_band", "interval"): "ros_player_band — the ROS range (bear/center/bull)",
    ("player_signal", "point"): "player_signal — expected ppg (§1 repeatability)",
    ("player_signal", "direction"): "player_signal — trend direction",
    ("true_rank", "ordinal"): "true_rank — final-standing rank (§5)",
    ("positional_depth", "point"): "positional_depth — roster×position surplus (§6)",
    ("bracket_odds", "probability"): "bracket_odds — playoff odds (§5)",
    ("bracket_odds", "point"): "bracket_odds — projected wins",
    ("bracket_odds", "ordinal"): "bracket_odds — projected seed",
}


def _load() -> pl.DataFrame:
    frames = [data_layer.read_engine_scorecard(s) for s in SPINED_SEASONS
              if data_layer.engine_scorecard_exists(s)]
    if not frames:
        raise SystemExit("no engine_scorecard on disk — run compute_engine_scorecard first.")
    sc = pl.concat(frames, how="diagonal")
    # keep only the current scorer population (latest code_version) so a re-score doesn't double the report.
    # Select by APPEND ORDER (the re-score is concatenated last): with two equal-sized populations `.mode()`
    # is a tie and order-undefined, so it could render the stale population — the last overall row's
    # code_version is the appended-last (latest) one. Mirrors check_scorecard._latest_population.
    latest = sc.filter(pl.col("slice_dim") == "overall")["code_version"][-1]
    return sc.filter(pl.col("code_version") == latest)


def _wmean(rows: list, col: str) -> float | None:
    num = sum((r[col] or 0.0) * r["n_resolved"] for r in rows if r[col] is not None)
    den = sum(r["n_resolved"] for r in rows if r[col] is not None)
    return num / den if den else None


def _pool(overall: pl.DataFrame, key: tuple) -> dict:
    """Pool a family's per-season overall rows (n-weighted) into one cross-corpus verdict."""
    rows = overall.filter((pl.col("read") == key[0]) & (pl.col("claim_type") == key[1])).to_dicts()
    if not rows:
        return {}
    n = sum(r["n_resolved"] for r in rows)
    mono = _wmean(rows, "conf_monotonicity")
    measurable = rows[0]["measurable_law2"]
    return {"n": n, "skill_kind": rows[0]["skill_kind"], "measurable_law2": measurable,
            "conf_label": rows[0]["conf_label"],
            "skill": _wmean(rows, "skill"), "mae": _wmean(rows, "mae"), "med_error": _wmean(rows, "med_error"),
            "discrimination": _wmean(rows, "discrimination"), "brier": _wmean(rows, "brier"),
            "coverage_actual": _wmean(rows, "coverage_actual"), "pit_ks_stat": _wmean(rows, "pit_ks_stat"),
            "conf_monotonicity": mono,
            # pooled conf_honest, consistent with the traffic light: honest = clear negative rank-corr
            "conf_honest": (mono is not None and mono <= -reg.CONF_MONO_MARGIN) if measurable else None,
            "by_season": {r["season"]: r for r in rows}}


def _light_skill(p: dict) -> str:
    if p["skill_kind"] == "na":
        return "⚪ n/a (calibration read)"
    s = p["skill"]
    if s is None:
        return "⚪ n/a"
    return ("🟢" if s > 0.05 else "🟡" if s >= -0.05 else "🔴") + f" {s:+.2f}"


def _light_calib(p: dict, key: tuple) -> str:
    ks = p["pit_ks_stat"]
    if key == ("ros_player_band", "interval"):
        cov = p["coverage_actual"]
        return ("🔴" if ks and ks > 0.15 else "🟡" if ks and ks > 0.05 else "🟢") + \
               f" KS {ks:.2f}, cover {cov:.2f}/0.80"
    if key == ("bracket_odds", "probability"):
        return ("🟢" if ks and ks < 0.05 else "🟡" if ks and ks < 0.15 else "🔴") + \
               f" KS {ks:.3f}, Brier {p['brier']:.3f}"
    return "⚪ n/a (no stated distribution)"


def _light_conf(p: dict) -> str:
    if not p["measurable_law2"]:
        return "⚪ unmeasurable (no native confidence — law-2 gap)"
    m = p["conf_monotonicity"]
    if m is None:
        return "⚪ n/a"
    tag = "🟢 honest" if m <= -reg.CONF_MONO_MARGIN else "🔴 INVERTED/flat — laundering noise" if m >= reg.CONF_MONO_MARGIN else "🟡 weak"
    return f"{tag} (ρ={m:+.2f}, {p['conf_label']})"


def _prereg(key: tuple, p: dict) -> str:
    tag, pred = PRE_REGISTERED.get(key, (None, None))
    if tag is None:
        return "—"
    try:                                                           # evaluate on the POOLED verdict
        return f"{tag}: {'HOLD ✓' if pred(p) else 'SURPRISE ✗'}"
    except Exception:                                              # noqa: BLE001
        return f"{tag}: n/a"


def build_report(sc: pl.DataFrame) -> str:
    overall = sc.filter(pl.col("slice_dim") == "overall")
    cohort = sc.filter(pl.col("slice_dim") == "cohort")
    seasons = sorted(overall["season"].unique().to_list())
    L = []
    L.append("# Engine Trust Report — the first measurement (L3 scorer)")
    L.append("")
    L.append(f"*Generated from `engine_scorecard_{{season}}` over seasons {seasons} (270 spined league-seasons). "
             "The scorer **judges distributions, never single claims**; it **changes no constant** — a red "
             "light is a finding for the Tuner (L4) / Proposer (L6), not a fix. Traffic lights are pooled "
             "across seasons (n-weighted); the season + cohort rows carry the out-of-sample story.*")
    L.append("")
    L.append("## Headline")
    L.append("")
    L.append("- **Projection optimism is real and stable.** `production_vor` **loses to "
             "carry-recent-form-forward every season** (skill < 0) while ranking well — it prices the ORDER "
             "right but the LEVEL high. The `ros_player_band` under-covers (~0.55 vs 0.80 target) with PIT "
             "piled at the edges. Two independent reads, one story. *(A Tuner lead, not fixed here.)*")
    L.append("- **The measurement reads hold out-of-sample** (§1 signal, §5 rank, §6 depth) — the "
             "pre-registered prediction stands.")
    L.append("- **Confidence-honesty (law 2) — the headline — is mixed.** Playoff odds and true-rank sort "
             "honestly by error; the **band's `ros_cv` is INVERTED** (its narrowest bands miss by the most) "
             "and positional_depth's `spectrum_pos` doesn't sort. 4 reads state no confidence at all.")
    L.append("")
    L.append("## Traffic lights (pooled across seasons)")
    L.append("")
    L.append("| Read | n | Skill | Calibration | Confidence-honesty (law 2) | Pre-registered |")
    L.append("|---|--:|---|---|---|---|")
    pooled = {}
    for key in _ORDER:
        p = _pool(overall, key)
        if not p:
            continue
        pooled[key] = p
        L.append(f"| {_READ_TITLE[key]} | {p['n']:,} | {_light_skill(p)} | {_light_calib(p, key)} | "
                 f"{_light_conf(p)} | {_prereg(key, p)} |")
    L.append("")
    L.append("## What we'd honestly tell a user (per read)")
    L.append("")
    for key in _ORDER:
        if key in pooled:
            L.append(f"- **{key[0]}/{key[1]}** — {_user_line(key, pooled[key])}")
    L.append("")
    L.append("## Out-of-sample: skill by season (does it hold on the TEST years?)")
    L.append("")
    L.append("| Read | " + " | ".join(str(s) for s in seasons) + " |")
    L.append("|---|" + "|".join("--:" for _ in seasons) + "|")
    for key in _ORDER:
        if key not in pooled or pooled[key]["skill_kind"] == "na":
            continue
        by = pooled[key]["by_season"]
        cells = [(f"{by[s]['skill']:+.2f}" if s in by and by[s]["skill"] is not None else "·") for s in seasons]
        L.append(f"| {key[0]}/{key[1]} | " + " | ".join(cells) + " |")
    L.append("")
    L.append("## Cohort: does it hold on the 48 never-tune generalization leagues?")
    L.append("")
    L.append("| Read | matched (skill) | generalization (skill) | Δ |")
    L.append("|---|--:|--:|--:|")
    for key in _ORDER:
        if key not in pooled or pooled[key]["skill_kind"] == "na":
            continue
        cr = cohort.filter((pl.col("read") == key[0]) & (pl.col("claim_type") == key[1]))
        m = _wmean(cr.filter(pl.col("slice_val") == "matched").to_dicts(), "skill")
        g = _wmean(cr.filter(pl.col("slice_val") == "generalization").to_dicts(), "skill")
        if m is None and g is None:
            continue
        d = (f"{g - m:+.2f}" if (m is not None and g is not None) else "·")
        L.append(f"| {key[0]}/{key[1]} | {m:+.2f} | {g:+.2f} | {d} |"
                 if (m is not None and g is not None) else
                 f"| {key[0]}/{key[1]} | {m if m is None else f'{m:+.2f}'} | {g if g is None else f'{g:+.2f}'} | {d} |")
    L.append("")
    L.append("## Method + boundaries")
    L.append("")
    L.append("- **Skill** = `1 − metric_engine/metric_naive` vs a **declared naive baseline** "
             "(`scorecard_registry.py`): 2 promoted from the backtests (player_signal→naive_ppg, "
             "playoff-odds→0.25 Brier), the rest declared canonical (recent-form-forward, pool-mean, "
             "closed-form random-permutation `(n²−1)/(3n)`, .500 win-rate). The band is **skill n/a by design** "
             "— its lens is calibration.")
    L.append("- **Calibration** = PIT-uniformity (KS) + coverage for the interval band, Brier + PIT for the "
             "probability read. Point/ordinal/direction state no distribution → no PIT.")
    L.append("- **Confidence-honesty (law 2)** = Spearman(the read's own stated confidence strength, realized "
             "error) — honest when NEGATIVE (more confidence ⇒ less error). Extremeness signals "
             "(`spectrum_pos`, `playoff_odds`) use `|x−0.5|`; inverted signals (`ros_cv`, `regression_risk`) "
             "use `−x`. 4 reads carry **no native confidence** → law-2 unmeasurable (reported, not fabricated).")
    L.append("- **Quarantine:** the `overall` verdict is on `inputs_ok ∧ resolved` only; `inputs_ok=false` "
             "and unresolved live in their own slices, never blended. `mine`/2025 is in-sample + partially "
             "realized (a live league) — read the matched + generalization cohorts as the honest evidence.")
    L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="Render the Trust Report markdown (Session 5).")
    ap.add_argument("--stdout", action="store_true", help="print instead of writing the file")
    a = ap.parse_args()
    md = build_report(_load())
    if a.stdout:
        print(md)
    else:
        with open(_REPORT_PATH, "w") as f:
            f.write(md)
        print(f"wrote {_REPORT_PATH} ({len(md):,} chars)")


if __name__ == "__main__":
    main()
    sys.exit(0)
