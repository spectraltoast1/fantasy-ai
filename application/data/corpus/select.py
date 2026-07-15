"""
Corpus selection → the league registry (Session 0.5, commit 2).

Reads corpus_discovery, narrows by classification (FREE), then runs the inclusion filter +
scoreability ONLY on a bounded pre-selected pool (discovery is free; harvest is what costs).
The filter transiently fetches rosters/matchups/transactions via _http to compute pass/fail — it
persists the VERDICT, never the raw game data (Session 4 does the persisted harvest). Emits the
stratified manifest (matched / generalization / mine) through data_layer.

Also reports the three deliverable numbers straight off discovery (both are free/deterministic):
  1. the matched crosstab (redraft × {ppr,half} × 1qb × 10-14, per season),
  3. the unscoreable rate among custom leagues, with the rejecting keys named.

Run: python3 -m application.data.corpus.select [--id-threshold 90] [--verbose]
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

import polars as pl

from application import config
from application.data import data_layer
from application.data.corpus import _corpus
from application.data.fetchers import _http
from application.data.fetchers.sleeper import _SLEEPER_BASE
from application.data.transforms import _scoring

_SKILL = {"QB", "RB", "WR", "TE"}
MATCHED_CAP_PER_SEASON = 60
MATCHED_TARGET = 300
DEFAULT_ID_THRESHOLD = 90.0        # % skill players resolving to gsis_id
UNDERFULL_FRAC = 0.5
_PASS = 0.87                        # Session-0 pass rate — size the filter pool to fill caps after loss
_MATCHED_FILTER_MARGIN = 1.4
# Generalization is selected PER SEASON now (Session 2.5 — the season-collapse fix). Aim GEN_PER_SEASON_TARGET
# passes/season out of a GEN_SEASON_POOL candidate pool; the gate hard-requires ≥ _corpus.GEN_SEASON_MIN each.
GEN_PER_SEASON_TARGET = 8
GEN_SEASON_POOL = 18               # max candidates filtered per season (target 8 at ~87% + margin)

_MANIFEST_COLS = [
    "league_id", "season", "scoring_key", "shape_key", "num_teams", "qb_structure",
    "league_format", "has_divisions", "stratum", "never_tune", "scoreable", "scoreable_reject",
    "filter_result", "filter_reason", "id_resolution_pct", "has_transactions", "is_mine", "selected_at",
]


# --- scoreability (deterministic, no API) --------------------------------------------------------

def scoreability(scoring_profile, scoring_settings):
    """(scoreable: bool, reject_keys: str|None) — custom leagues run through the real _scoring engine."""
    if scoring_profile != "custom":
        return True, None
    try:
        _scoring.recompute_custom_points(scoring_settings, "proj")
        return True, None
    except Exception as exc:   # noqa: BLE001 — NotImplementedError names the unsupported keys
        m = re.search(r"\[([^\]]*)\]", str(exc))
        keys = m.group(1).replace("'", "") if m else str(exc)[:80]
        return False, keys


# --- inclusion filter (transient _http fetch; verdict-only) --------------------------------------

def _position_maps():
    players = data_layer.read_sleeper_players()
    pos_by_id = dict(zip(players["sleeper_player_id"].to_list(), players["position"].to_list()))
    idmap = data_layer.read_player_id_map()
    idmap = idmap.filter(pl.col("gsis_id").is_not_null() & pl.col("sleeper_player_id").is_not_null())
    gsis_ids = set(idmap["sleeper_player_id"].to_list())
    return pos_by_id, gsis_ids


def apply_filter(cand, pos_by_id, gsis_ids, id_threshold):
    """Run the inclusion filter on ONE discovery candidate. Returns a dict verdict."""
    lid = cand["league_id"]
    num_teams = cand["num_teams"]
    playoff_start = cand.get("playoff_week_start") or 15
    reg_weeks = list(range(1, min(int(playoff_start), 15)))
    roster_len = len(cand.get("roster_positions") or []) or 15
    reasons = []

    rosters = _http.get_json(f"{_SLEEPER_BASE}/league/{lid}/rosters") or []
    if num_teams is not None and len(rosters) != num_teams:
        reasons.append(f"roster_count={len(rosters)}!={num_teams}")
    if sum(1 for r in rosters if len(r.get("players") or []) < UNDERFULL_FRAC * roster_len):
        reasons.append("teams_underfull")

    skill = skill_gsis = 0
    for r in rosters:
        for pid in (r.get("players") or []):
            if pos_by_id.get(str(pid)) in _SKILL:
                skill += 1
                skill_gsis += 1 if str(pid) in gsis_ids else 0
    id_pct = round(100 * skill_gsis / skill, 1) if skill else 0.0
    if id_pct < id_threshold:
        reasons.append(f"id_resolution={id_pct}%")

    empty_by_roster = defaultdict(int)
    complete = True
    for wk in reg_weeks:
        rows = _http.get_json(f"{_SLEEPER_BASE}/league/{lid}/matchups/{wk}") or []
        if num_teams is not None and (len(rows) < num_teams
                                      or sum(1 for r in rows if (r.get("points") or 0) > 0) < num_teams):
            complete = False
        if wk > 2:
            for r in rows:
                if (not r.get("starters")) or (r.get("points") or 0) == 0:
                    empty_by_roster[r.get("roster_id")] += 1
    if not complete:
        reasons.append("season_incomplete")
    if [rid for rid, n in empty_by_roster.items() if n >= 3]:
        reasons.append("abandonment")

    has_txn = False
    for wk in range(1, 17):
        if _http.get_json(f"{_SLEEPER_BASE}/league/{lid}/transactions/{wk}"):
            has_txn = True
            break

    passed = not reasons
    return {"filter_result": "pass" if passed else "fail",
            "filter_reason": None if passed else ";".join(reasons),
            "id_resolution_pct": id_pct, "has_transactions": has_txn}


# --- mine (the seed league + its previous_league_id chain) ---------------------------------------

def _mine_ids(disc):
    prev_by_id = dict(zip(disc["league_id"].to_list(), disc["previous_league_id"].to_list()))
    mine, lid = set(), str(config.SLEEPER_LEAGUE_ID)
    while lid and lid not in mine:
        mine.add(lid)
        lid = prev_by_id.get(lid)
    return mine


# --- deliverable reports (free, off discovery) ---------------------------------------------------

def matched_crosstab(disc):
    rows = [r for r in disc.to_dicts()
            if _corpus.is_matched_eligible(r["scoring_profile"], r["qb_structure"],
                                           r["league_format"], r["num_teams"])]
    tab = defaultdict(lambda: Counter())
    for r in rows:
        tab[r["season"]][r["scoring_profile"]] += 1
    return tab, len(rows)


def unscoreable_report(disc):
    custom = [r for r in disc.to_dicts() if r["scoring_profile"] == "custom"]
    bad = 0
    keys = Counter()
    for r in custom:
        ok, rej = scoreability("custom", json.loads(r["scoring_settings_json"]))
        if not ok:
            bad += 1
            for k in (rej or "").split(","):
                if k.strip():
                    keys[k.strip()] += 1
    pct = round(100 * bad / len(custom), 1) if custom else None
    return {"custom_total": len(custom), "unscoreable": bad, "unscoreable_pct": pct,
            "top_rejecting_keys": dict(keys.most_common(8))}


# --- selection driver ----------------------------------------------------------------------------

def _preselect_matched(disc_rows):
    """Per season, up to cap/pass + margin matched-eligible candidates to filter (deterministic order)."""
    per_season = defaultdict(list)
    for r in sorted(disc_rows, key=lambda x: str(x["league_id"])):
        if _corpus.is_matched_eligible(r["scoring_profile"], r["qb_structure"],
                                       r["league_format"], r["num_teams"]):
            per_season[r["season"]].append(r)
    budget = int(MATCHED_CAP_PER_SEASON / _PASS * _MATCHED_FILTER_MARGIN)
    return {s: rows[:budget] for s, rows in per_season.items()}


_GEN_AXES = ["exotic_size", "division", "superflex", "custom"]


def _gen_axis(r):
    """The robustness axis a generalization candidate exercises (mutually exclusive, priority order:
    divisions > exotic size > superflex > custom scoring)."""
    nt = r["num_teams"] or 0
    if r["has_divisions"]:
        return "division"
    if nt >= 16 or nt < 10:
        return "exotic_size"
    if r["qb_structure"] == "sf":
        return "superflex"
    if r["scoring_profile"] == "custom":
        return "custom"
    return None


def _preselect_generalization(disc_rows, mine):
    """PER-SEASON candidate pools for the generalization stratum (Session 2.5 — the season-collapse fix).

    The old selection round-robined the robustness axes but was **season-blind**, so the whole stratum
    collapsed into the seasons with the most discovered leagues (2023-24) — leaving the *test* season
    (2025) empty. Now each season gets its own ordered pool so the selection loop can guarantee every
    season is represented. Within a season the order is:
    Ordering: the four axes ROUND-ROBIN within a season so every code path — including custom scoring /
    TE-premium — is represented (a season filled purely from standard shape leagues would leave the
    custom-scoring path untested). WITHIN the three shape axes, standard-scored leagues sort first, so a
    superflex/division/exotic slot is filled at ZERO custom-key cost; the dedicated custom axis is what
    spends the GEN_CUSTOM_KEY_CAP budget (enforced in the selection loop). Deterministic: league_id order
    within each axis, fixed axis cycle → two runs produce identical pools.

    Returns {season: [(axis, row), …]} capped at GEN_SEASON_POOL per season.
    """
    def _key(r):
        return _corpus.scoring_key(r["scoring_profile"], json.loads(r["scoring_settings_json"]))

    per_season = defaultdict(lambda: {a: [] for a in _GEN_AXES})
    for r in sorted(disc_rows, key=lambda x: str(x["league_id"])):
        if r["league_id"] in mine:
            continue
        if _corpus.is_matched_eligible(r["scoring_profile"], r["qb_structure"],
                                       r["league_format"], r["num_teams"]):
            continue
        if not _corpus.is_generalization_eligible(r["scoring_profile"], r["qb_structure"],
                                                  r["has_divisions"], r["num_teams"]):
            continue
        a = _gen_axis(r)
        if a is None:
            continue
        per_season[r["season"]][a].append(r)

    pools = {}
    for season, axes in per_season.items():
        # within each SHAPE axis, standard-scored leagues sort first (conserve the custom-key budget); the
        # custom axis is custom by definition and keeps league_id order.
        for a in ("exotic_size", "division", "superflex"):
            axes[a].sort(key=lambda r: (str(_key(r)).startswith("cust"), str(r["league_id"])))
        idx = {a: 0 for a in _GEN_AXES}
        ordered = []
        while any(idx[a] < len(axes[a]) for a in _GEN_AXES):
            for a in _GEN_AXES:               # round-robin the four axes so custom scoring is covered
                if idx[a] < len(axes[a]):
                    ordered.append((a, axes[a][idx[a]]))
                    idx[a] += 1
        pools[season] = ordered[:GEN_SEASON_POOL]
    return pools


def run(id_threshold, verbose):
    _http.set_throttle(0.1)
    disc = data_layer.read_corpus_discovery()
    # Re-classify scoring_profile from the persisted raw scoring_settings_json (the source of truth)
    # via the fixed classifier — discovery's stored `scoring_profile` column was written by the crawl
    # under the float32-tolerance bug (Session 0.6), so trusting it would re-import the misclassification.
    disc = disc.with_columns(
        pl.col("scoring_settings_json")
        .map_elements(lambda j: _scoring.scoring_profile(json.loads(j)), return_dtype=pl.Utf8)
        .alias("scoring_profile")
    )
    disc_rows = disc.to_dicts()
    pos_by_id, gsis_ids = _position_maps()
    mine = _mine_ids(disc)
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"discovery: {len(disc_rows)} league-seasons | mine={len(mine)}")

    # ---- deliverables 1 & 3 (free, off discovery) ----
    tab, matched_total = matched_crosstab(disc)
    print("\n=== [Deliverable 1] matched crosstab (redraft·1qb·10-14t) per season ===")
    print(f"{'season':>7} {'ppr':>5} {'half':>5} {'total':>6}")
    for s in sorted(tab):
        print(f"{s:>7} {tab[s]['ppr']:>5} {tab[s]['half']:>5} {tab[s]['ppr']+tab[s]['half']:>6}")
    print(f"  matched-eligible total (pre-filter): {matched_total}")
    uns = unscoreable_report(disc)
    print(f"\n=== [Deliverable 3] custom-scoring unscoreable rate ===\n  {json.dumps(uns)}")

    # ---- filter verdict cache (idempotent + crash-safe: a re-run never re-hits Sleeper for a
    #      league already judged; verdicts are deterministic) ----
    cache_path = data_layer._corpus_manifest_path().parent / "corpus_filter_cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    _dirty = {"n": 0}

    def flush_cache():
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache))

    def verdict_for(r):
        lid = r["league_id"]
        if lid in cache:
            return cache[lid]
        try:
            v = apply_filter(r, pos_by_id, gsis_ids, id_threshold)
        except Exception as exc:   # noqa: BLE001 — isolate a dead league
            v = {"filter_result": "fail", "filter_reason": f"error:{type(exc).__name__}",
                 "id_resolution_pct": 0.0, "has_transactions": False}
        cache[lid] = v
        _dirty["n"] += 1
        if _dirty["n"] % 20 == 0:
            flush_cache()
        return v

    # ---- filter the bounded pre-selected pools ----
    manifest = {}   # league_id -> row

    def add_manifest(r, stratum, verdict, sc_ok, sc_rej):
        manifest[r["league_id"]] = {
            "league_id": r["league_id"], "season": r["season"],
            "scoring_key": _corpus.scoring_key(r["scoring_profile"], json.loads(r["scoring_settings_json"])),
            "shape_key": _corpus.shape_key(r["num_teams"], r["qb_structure"], r["league_format"]),
            "num_teams": r["num_teams"], "qb_structure": r["qb_structure"],
            "league_format": r["league_format"], "has_divisions": bool(r["has_divisions"]),
            "stratum": stratum, "never_tune": stratum != "matched",
            "scoreable": sc_ok, "scoreable_reject": sc_rej,
            "filter_result": verdict["filter_result"], "filter_reason": verdict["filter_reason"],
            "id_resolution_pct": verdict["id_resolution_pct"], "has_transactions": verdict["has_transactions"],
            "is_mine": r["league_id"] in mine, "selected_at": now_iso,
        }

    filtered = 0
    passes = 0

    def filter_and_classify(r, target_stratum):
        nonlocal filtered, passes
        sc_ok, sc_rej = scoreability(r["scoring_profile"], json.loads(r["scoring_settings_json"]))
        verdict = verdict_for(r)
        filtered += 1
        passed = verdict["filter_result"] == "pass"
        passes += 1 if passed else 0
        # a candidate is SELECTED into its stratum only if it passes AND (matched/gen require scoreable)
        selected = passed and sc_ok
        stratum = target_stratum if selected else "excluded"
        add_manifest(r, stratum, verdict, sc_ok, sc_rej)
        return selected

    # mine: filter for completeness but always keep (live path)
    for r in disc_rows:
        if r["league_id"] in mine:
            sc_ok, sc_rej = scoreability(r["scoring_profile"], json.loads(r["scoring_settings_json"]))
            add_manifest(r, "mine", verdict_for(r), sc_ok, sc_rej)

    # matched: per-season cap
    matched_pool = _preselect_matched(disc_rows)
    matched_selected = defaultdict(int)
    print(f"\nfiltering matched pool ({sum(len(v) for v in matched_pool.values())} candidates)…")
    for s in sorted(matched_pool):
        for r in matched_pool[s]:
            if matched_selected[s] >= MATCHED_CAP_PER_SEASON:
                break
            if r["league_id"] in manifest:
                continue
            if filter_and_classify(r, "matched") and manifest[r["league_id"]]["stratum"] == "matched":
                matched_selected[s] += 1

    # generalization: SEASON-BALANCED + custom-key-capped (Session 2.5). Fill each season to
    # GEN_PER_SEASON_TARGET, opening a NEW custom scoring_key only while under GEN_CUSTOM_KEY_CAP
    # (reused keys are free — their substrate is shared). Seasons processed in order → deterministic.
    gen_pools = _preselect_generalization(disc_rows, mine)
    gen_by_season = Counter()
    custom_keys_used = set()
    total_cands = sum(len(v) for v in gen_pools.values())
    print(f"filtering generalization pool ({total_cands} candidates over {len(gen_pools)} seasons; "
          f"target {GEN_PER_SEASON_TARGET}/season, custom-key cap {_corpus.GEN_CUSTOM_KEY_CAP})…")
    for season in sorted(gen_pools):
        for axis, r in gen_pools[season]:
            if gen_by_season[season] >= GEN_PER_SEASON_TARGET:
                break
            if r["league_id"] in manifest:
                continue
            key = _corpus.scoring_key(r["scoring_profile"], json.loads(r["scoring_settings_json"]))
            is_custom = key.startswith("cust")
            # custom-key budget: never open a NEW custom key past the cap (a reused key costs no substrate)
            if is_custom and key not in custom_keys_used and len(custom_keys_used) >= _corpus.GEN_CUSTOM_KEY_CAP:
                continue
            if filter_and_classify(r, "generalization") and manifest[r["league_id"]]["stratum"] == "generalization":
                gen_by_season[season] += 1
                if is_custom:
                    custom_keys_used.add(key)
    gen_selected = sum(gen_by_season.values())

    # ---- write manifest ----
    flush_cache()
    mdf = pl.DataFrame(list(manifest.values()), infer_schema_length=None).select(_MANIFEST_COLS)
    data_layer.write_corpus_manifest(mdf)

    # ---- report ----
    strat = Counter(row["stratum"] for row in manifest.values())
    print(f"\n=== manifest written: {mdf.height} rows ===")
    print(f"  strata: {dict(strat)}")
    print(f"  filtered {filtered} candidates | pass-rate={round(100*passes/filtered,1) if filtered else 0}% "
          f"(Session 0: 87%)")
    print("\n=== [Deliverable 2] achieved matched balance (SELECTED) per season ===")
    sel_by_season = Counter(row["season"] for row in manifest.values() if row["stratum"] == "matched")
    for s in sorted(_corpus.SEASONS):
        note = " (THIN)" if sel_by_season.get(s, 0) < 20 else ""
        print(f"  {s}: {sel_by_season.get(s,0)}{note}")
    print(f"  matched total selected: {sum(sel_by_season.values())} (target ~{MATCHED_TARGET})")

    # ---- generalization report (Session 2.5): per-season spread + custom-key budget + shape matrix ----
    gen_rows = [row for row in manifest.values() if row["stratum"] == "generalization"]
    gen_seasons = Counter(row["season"] for row in gen_rows)
    gen_custom_keys = sorted({row["scoring_key"] for row in gen_rows if str(row["scoring_key"]).startswith("cust")})
    print("\n=== generalization spread (SELECTED) per season ===")
    for s in sorted(_corpus.SEASONS):
        note = "" if gen_seasons.get(s, 0) >= _corpus.GEN_SEASON_MIN else f" ⚠ < min {_corpus.GEN_SEASON_MIN}"
        print(f"  {s}: {gen_seasons.get(s, 0)}{note}")
    print(f"  generalization total: {gen_selected} | distinct custom keys: {len(gen_custom_keys)} "
          f"(cap {_corpus.GEN_CUSTOM_KEY_CAP})")
    print("\n=== generalization shape matrix (coverage, not representativeness) ===")
    def _size_band(nt):
        nt = nt or 0
        return "<10" if nt < 10 else ("10-14" if nt <= 14 else ("15-16" if nt <= 16 else ">16"))
    shape = Counter((row["scoring_key"] if not str(row["scoring_key"]).startswith("cust") else "cust",
                     row["qb_structure"], "div" if row["has_divisions"] else "nodiv",
                     _size_band(row["num_teams"])) for row in gen_rows)
    for (sc, qb, dv, sz), n in sorted(shape.items()):
        print(f"  scoring={sc:<5} qb={qb:<4} {dv:<5} size={sz:<5} : {n}")


def main():
    ap = argparse.ArgumentParser(description="Corpus selection → the league registry.")
    ap.add_argument("--id-threshold", type=float, default=DEFAULT_ID_THRESHOLD)
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    run(a.id_threshold, a.verbose)


if __name__ == "__main__":
    main()
    sys.exit(0)
