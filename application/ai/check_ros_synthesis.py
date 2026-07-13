"""
ROS Synthesis gate — internal-consistency checks for the §2 AI synthesis (no API, no answer key).

The synthesis is live + qualitative, so there is no ground truth to score against; instead we verify
the read is INTERNALLY consistent with its own inputs and honest about its confidence:

  1. coverage    — one row per player, no dupes; identity columns populated.
  2. schema      — grades are ints 1-10 with a non-empty note each (or all-null ONLY on a zero row);
                   confidence in vocab; headlines a list of {text, ids}.
  3. grounding   — every headline's cited source_article_ids exist in that player's player_news_slice
                   (the faithfulness guardrail — the receipts are real, not invented).
  4. confidence  — thin/none news OR no anchor => confidence != 'high'; a zero-signal row carries the
                   hardcoded fallback (null grades, null model, low confidence, no headlines).
  5. data-flags  — has_ros_anchor / has_news / n_news_claims match what actually resolves from the
                   anchors (ros_player_band ⋈ ros_league_view) + the news slice.

Plus a soft evidence block (grade spread, anchor consistency, a prose-leak scan) — reported, not gated.

Reads persisted output + its two anchors only. Exit 0 iff all hard checks pass.

Usage:
    python3 -m application.ai.check_ros_synthesis [--season 2026] [--week 0]
"""

import argparse
import sys

import polars as pl

from application.data import data_layer
from application.data.fetchers import news
from application.ai import ros_synthesis_prompt as rp

# Substrings the manager-facing notes should never contain — the prose-discipline leak scan (soft).
# High-precision internal-only markers: common football words that overlap ('tier' in 'top-tier',
# 'projection' in a cited analyst projection, 'reliability') are deliberately EXCLUDED to avoid crying
# wolf; this flags the giveaways a manager would not understand ('anchor', 'prior-season', 'bucket').
_LEAK_TERMS = ("percentile", "spectrum", "ros_", "prior-season", "anchor", "bucket", "trend flag")


def _slice_ids_by_player(season: int, week: int) -> dict:
    """Per player: the set of source_article_ids present in his news slice (the grounding universe)."""
    if not data_layer.player_news_slice_exists():
        return {}
    df = data_layer.read_player_news_slice(season=season, week=week)
    out: dict[str, set] = {}
    for r in df.select("sleeper_player_id", "source_article_ids").to_dicts():
        out.setdefault(r["sleeper_player_id"], set()).update(r["source_article_ids"] or [])
    return out


def _news_claim_counts(season: int, week: int) -> dict:
    """Per player: number of real (non-empty) inherited claims in his slice."""
    if not data_layer.player_news_slice_exists():
        return {}
    df = data_layer.read_player_news_slice(season=season, week=week)
    if "is_empty" in df.columns:
        df = df.filter(~pl.col("is_empty"))
    return {r["sleeper_player_id"]: r["n"]
            for r in df.group_by("sleeper_player_id").len(name="n").to_dicts()}


def _check_coverage(s: pl.DataFrame) -> bool:
    dupes = s.group_by("season", "week", "sleeper_player_id").len().filter(pl.col("len") > 1).height
    missing_id = s.filter(pl.col("sleeper_player_id").is_null()).height
    ok = dupes == 0 and missing_id == 0
    print(f"  [{'PASS' if ok else 'FAIL'}] coverage — {s.height} rows, {dupes} dup key(s), "
          f"{missing_id} null id(s)")
    return ok


def _check_schema(s: pl.DataFrame) -> bool:
    ok = True
    for r in s.iter_rows(named=True):
        who = r["sleeper_player_id"]
        if r["is_zero_signal"]:
            if any(r[g] is not None for g in rp.GRADE_KEYS):
                print(f"  [FAIL] schema — zero-signal row {who} has a non-null grade"); ok = False
            continue
        for g in rp.GRADE_KEYS:
            v = r[g]
            if not isinstance(v, int) or not (rp.GRADE_MIN <= v <= rp.GRADE_MAX):
                print(f"  [FAIL] schema — {who} {g}={v!r} out of range"); ok = False
        for n in rp.NOTE_KEYS:
            if not str(r[n] or "").strip():
                print(f"  [FAIL] schema — {who} {n} empty"); ok = False
        if r["confidence"] not in rp.CONFIDENCE:
            print(f"  [FAIL] schema — {who} confidence={r['confidence']!r}"); ok = False
        if not isinstance(r["headlines"], list):
            print(f"  [FAIL] schema — {who} headlines not a list"); ok = False
    if ok:
        print(f"  [PASS] schema — grades/notes/confidence/headlines well-formed ({s.height} rows)")
    return ok


def _check_grounding(s: pl.DataFrame, ids_by_player: dict) -> bool:
    ok, checked = True, 0
    for r in s.iter_rows(named=True):
        universe = ids_by_player.get(r["sleeper_player_id"], set())
        for h in (r["headlines"] or []):
            checked += 1
            stray = [i for i in (h.get("source_article_ids") or []) if i not in universe]
            if stray:
                print(f"  [FAIL] grounding — {r['sleeper_player_id']} headline cites {stray} "
                      f"not in his news slice"); ok = False
    if ok:
        print(f"  [PASS] grounding — all {checked} headline citation-set(s) trace to the news slice")
    return ok


def _check_confidence(s: pl.DataFrame) -> bool:
    ok = True
    for r in s.iter_rows(named=True):
        who = r["sleeper_player_id"]
        if r["is_zero_signal"]:
            if r["model"] is not None or r["confidence"] != "low" or (r["headlines"] or []):
                print(f"  [FAIL] confidence — zero-signal row {who} not a clean fallback"); ok = False
            continue
        if r["model"] is None:
            print(f"  [FAIL] confidence — non-zero row {who} has null model"); ok = False
        thin = (r["signal_tier"] in (None, "thin", "none")) or (not r["has_ros_anchor"])
        if thin and r["confidence"] == "high":
            print(f"  [FAIL] confidence — {who} says 'high' on thin data "
                  f"(tier={r['signal_tier']}, anchor={r['has_ros_anchor']})"); ok = False
    if ok:
        print("  [PASS] confidence — no over-confident thin reads; zero rows are clean fallbacks")
    return ok


def _check_data_flags(s: pl.DataFrame, ids_by_player: dict, claim_counts: dict) -> bool:
    ok = True
    # anchor presence: recompute from the rostered anchor set (ros_league_view — the writer's grain) for
    # each anchor_season present. (ros_player_band covers the whole pool; only rostered players anchor.)
    anchor_ids: dict[int, set] = {}
    for aseason in s.select("anchor_season").unique().to_series().to_list():
        try:
            anchor_ids[aseason] = set(
                data_layer.read_ros_league_view(aseason)["sleeper_player_id"].to_list())
        except FileNotFoundError:
            anchor_ids[aseason] = set()
    for r in s.iter_rows(named=True):
        who = r["sleeper_player_id"]
        true_anchor = who in anchor_ids.get(r["anchor_season"], set())
        if bool(r["has_ros_anchor"]) != true_anchor:
            print(f"  [FAIL] data-flags — {who} has_ros_anchor={r['has_ros_anchor']} but "
                  f"anchor-present={true_anchor}"); ok = False
        true_claims = claim_counts.get(who, 0)
        if bool(r["has_news"]) != (true_claims > 0) or (r["n_news_claims"] or 0) != true_claims:
            print(f"  [FAIL] data-flags — {who} news flags disagree with the slice "
                  f"(has_news={r['has_news']}, n={r['n_news_claims']}, true={true_claims})"); ok = False
    if ok:
        print("  [PASS] data-flags — has_ros_anchor / has_news / n_news_claims match the inputs")
    return ok


def _evidence(s: pl.DataFrame) -> None:
    graded = s.filter(~pl.col("is_zero_signal"))
    if graded.is_empty():
        print("  [evidence] no graded rows"); return
    for g in rp.GRADE_KEYS:
        vals = graded[g].drop_nulls().to_list()
        print(f"  [evidence] {g}: min {min(vals)} / mean {sum(vals) / len(vals):.1f} / max {max(vals)}")
    conf = graded.group_by("confidence").len().sort("confidence").to_dicts()
    print(f"  [evidence] confidence mix: {conf}")
    anchored = graded.filter(pl.col("has_ros_anchor")).height
    print(f"  [evidence] fully-anchored: {anchored}/{graded.height}")
    # prose-leak scan (soft): notes that echo internal vocabulary.
    leaks = 0
    for r in graded.iter_rows(named=True):
        blob = " ".join(str(r[n] or "").lower() for n in rp.NOTE_KEYS)
        hits = [t for t in _LEAK_TERMS if t in blob]
        if hits:
            leaks += 1
            print(f"  [evidence] leak? {r['sleeper_player_id']} notes mention {hits}")
    if not leaks:
        print("  [evidence] prose-leak scan: clean (no internal vocabulary in the notes)")


def run(season: int, week: int) -> bool:
    if not data_layer.ros_synthesis_exists(season):
        print(f"ROS synthesis gate: no ros_synthesis_{season}.parquet — nothing to check. FAIL")
        return False
    s = data_layer.read_ros_synthesis(season, week=week)
    if s.is_empty():
        print(f"ROS synthesis gate: no rows for season={season} week={week}. FAIL")
        return False
    print(f"=== ROS synthesis gate: season={season} week={week}  ({s.height} player rows) ===")
    ids_by_player = _slice_ids_by_player(season, week)
    claim_counts = _news_claim_counts(season, week)
    checks = [
        _check_coverage(s),
        _check_schema(s),
        _check_grounding(s, ids_by_player),
        _check_confidence(s),
        _check_data_flags(s, ids_by_player, claim_counts),
    ]
    _evidence(s)
    ok = all(checks)
    print(f"VERDICT: {'PASS' if ok else 'FAIL'}")
    return ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ROS synthesis internal-consistency gate (§2).")
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--week", type=int, default=None)
    args = parser.parse_args()
    _season, _week = news._nfl_state()
    season = args.season if args.season is not None else _season
    week = args.week if args.week is not None else _week
    sys.exit(0 if run(season, week) else 1)
