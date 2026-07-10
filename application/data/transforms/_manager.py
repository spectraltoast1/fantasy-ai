"""
Pure helpers for the cross-league Manager Dossiers read (DECISION_READS.md §7).

Comparability (classify a league, decide whether two are comparable, select the best
few) and transaction attribution — all pure, no I/O, no polars — so the three consumers
share one source of truth:
  - sleeper.py's `fetch-manager-activity` mode (must classify to know what to fetch),
  - compute_manager_features.py (the deterministic feature extraction),
  - backtest_manager_features.py (the comparability invariant + accounting checks).

Reuses transforms/_scoring.scoring_profile so the "same scoring" axis matches the rest
of the project rather than being re-derived here (single source of truth). Feature math
(Phase A commit 3) is appended to this module.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _scoring import scoring_profile

_SKILL = {"QB", "RB", "WR", "TE"}

# --- Comparability (which of a manager's other leagues are "like" the target) --------

# Sleeper settings.type -> format label. Comparability matches format EXACTLY, so redraft
# (0) pools only with redraft; keeper (1) and dynasty (2) are their own families (their
# waiver/trade behaviour differs). redraft<->redraft is the V1 scope; tagging the label
# lets dynasty<->dynasty turn on later with no code change (DECISION_READS.md §7).
_FORMAT_LABELS = {0: "redraft", 1: "keeper", 2: "dynasty"}

# Slots that let a manager start a QB — used to split 1QB from superflex/2QB, the one
# roster axis the design says changes behaviour enough to matter.
_QB_CAPACITY_SLOTS = {"QB", "SUPER_FLEX", "SUPERFLEX"}

# The four axes two leagues must share to be comparable.
_COMPARE_AXES = ("scoring_profile", "num_teams", "qb_structure", "league_format")


def league_format(type_code) -> str:
    if type_code is None:
        return "redraft"          # Sleeper omits type on a classic redraft league
    return _FORMAT_LABELS.get(int(type_code), f"type{int(type_code)}")


def qb_structure(roster_positions) -> str:
    """ "1qb" | "sf" — sf = a manager can start >=2 QBs (a SUPER_FLEX slot, or >=2 QB slots). """
    cap = sum(1 for s in (roster_positions or []) if s in _QB_CAPACITY_SLOTS)
    return "sf" if cap >= 2 else "1qb"


def classify_league(league: dict) -> dict:
    """The comparability signature of a league from its /league (or /user/.../leagues) object.

    Both endpoints carry scoring_settings + roster_positions + settings, so a candidate is
    classified with no extra API call. `waiver_budget` rides along (a league property the
    feature layer needs for bid-as-fraction-of-budget), not a comparability axis.
    """
    settings = league.get("settings") or {}
    num_teams = settings.get("num_teams") or league.get("total_rosters")
    return {
        "league_id": league.get("league_id"),
        "scoring_profile": scoring_profile(league.get("scoring_settings") or {}),
        "num_teams": int(num_teams) if num_teams is not None else None,
        "qb_structure": qb_structure(league.get("roster_positions")),
        "league_format": league_format(settings.get("type")),
        "waiver_budget": settings.get("waiver_budget"),
    }


def is_comparable(target: dict, cand: dict) -> bool:
    """True iff cand matches target on all four comparability axes (and has a known size)."""
    if cand.get("num_teams") is None:
        return False
    return all(target.get(ax) == cand.get(ax) for ax in _COMPARE_AXES)


def select_comparables(candidates, *, target_league_id, current_season,
                       max_leagues=5, bias_season=None):
    """Pick up to `max_leagues` comparable leagues, biased toward the immediately-prior season.

    `candidates` = comparable-league classification dicts, each carrying `league_id` and
    `source_season`. Season preference: prior (bias) first, then current, then older — so a
    manager active mostly last season is profiled on last season, and current/older leagues
    fill in only when prior doesn't reach the cap. Excludes the target league itself;
    degrades gracefully (returns fewer / none). Deterministic tie-break (newest season, then
    league_id) so a re-run selects the same set. The 3-season window is enforced upstream by
    the fetch querying only {current, current-1, current-2}.
    """
    bias = bias_season if bias_season is not None else current_season - 1

    def rank(c):
        s = c["source_season"]
        pref = 0 if s == bias else (1 if s == current_season else 2)
        return (pref, -s, str(c["league_id"]))

    ordered = [c for c in sorted(candidates, key=rank) if c["league_id"] != target_league_id]
    return ordered[:max_leagues]


# --- Transaction attribution (is this the manager's move, and which players) ----------

def manager_in_transaction(txn: dict, roster_id) -> bool:
    """Whether `roster_id` participated in a Sleeper transaction (live payload, native types).

    Trades list every participant in `roster_ids`; waiver/free-agent moves encode the acting
    roster as the value in the adds/drops {player_id: roster_id} maps.
    """
    if roster_id is None:
        return False
    if roster_id in (txn.get("roster_ids") or []):
        return True
    for mapping in (txn.get("adds") or {}, txn.get("drops") or {}):
        if roster_id in mapping.values():
            return True
    return False


def manager_moves(mapping, roster_id) -> list:
    """The player_ids the given roster added (or dropped) in a txn — filters an adds/drops map."""
    return [str(pid) for pid, rid in (mapping or {}).items() if rid == roster_id]


# --- Behavioural features (the deterministic AI-input, Phase A commit 3) --------------

# Empty when a manager has no captured transactions — every rate/lean feature is undefined
# (zero behavioural signal), kept apart from the depth counts so the schema stays stable.
_RATE_KEYS = (
    "n_waivers", "n_free_agents", "n_trades", "waiver_share", "waiver_success_rate",
    "avg_bid_frac", "max_bid_frac", "budget_spent_frac", "trades_per_league",
    "moves_per_league", "add_qb_share", "add_rb_share", "add_wr_share", "add_te_share",
)


def manager_features(rows, pos_by_id, *, depth_thin=10, depth_moderate=30) -> dict:
    """Deterministic behavioural profile for ONE manager from their cross-league activity rows.

    `rows` = that manager's manager_activity rows (both "league" markers and "txn" rows, as
    plain dicts). `pos_by_id` = sleeper_player_id -> position, for the positional lean of adds
    (skill only; DST/K adds are dropped, V1 scope). Every rate/lean feature returns None when
    its denominator is 0 — never a fabricated 0 (law 2 / the _analytics None convention) — so
    Phase B can gate confidence on the signal-depth counts. Pure: no I/O, no polars.
    """
    league_rows = [r for r in rows if r.get("kind") == "league"]
    txns = [r for r in rows if r.get("kind") == "txn"]

    n_leagues = len({(r["source_league_id"], r["source_season"]) for r in league_rows})
    n_seasons = len({r["source_season"] for r in league_rows})
    n_transactions = len(txns)
    depth_tier = ("none" if n_transactions == 0 else
                  "thin" if n_transactions < depth_thin else
                  "moderate" if n_transactions < depth_moderate else "deep")
    depth = {"n_leagues": n_leagues, "n_seasons": n_seasons,
             "n_transactions": n_transactions, "depth_tier": depth_tier}

    if n_transactions == 0:                         # zero behavioural signal
        return {**depth, "n_waivers": 0, "n_free_agents": 0, "n_trades": 0,
                **{k: None for k in _RATE_KEYS if k not in ("n_waivers", "n_free_agents", "n_trades")}}

    waivers = [t for t in txns if t.get("txn_type") == "waiver"]
    free_agents = [t for t in txns if t.get("txn_type") == "free_agent"]
    n_waivers, n_fa, n_trades = len(waivers), len(free_agents), sum(
        1 for t in txns if t.get("txn_type") == "trade")

    add_moves = n_waivers + n_fa
    waiver_share = (n_waivers / add_moves) if add_moves else None       # waiver vs free-agent mix
    completed = [t for t in waivers if t.get("status") == "complete"]
    waiver_success_rate = (len(completed) / n_waivers) if n_waivers else None

    # FAAB aggression — each bid as a fraction of THAT bid's league budget (normalises 200 vs 1000).
    bid_fracs = [t["faab_bid"] / t["faab_budget"] for t in waivers
                 if t.get("faab_bid") is not None and t.get("faab_budget")]
    avg_bid_frac = (sum(bid_fracs) / len(bid_fracs)) if bid_fracs else None
    max_bid_frac = max(bid_fracs) if bid_fracs else None

    # Budget-spent fraction — per league-season: FAAB spent (completed) / budget, then averaged.
    spent, budget = {}, {}
    for t in completed:
        k = (t["source_league_id"], t["source_season"])
        if t.get("faab_bid") is not None:
            spent[k] = spent.get(k, 0.0) + t["faab_bid"]
        if t.get("faab_budget"):
            budget[k] = t["faab_budget"]
    spent_fracs = [spent[k] / budget[k] for k in spent if budget.get(k)]
    budget_spent_frac = (sum(spent_fracs) / len(spent_fracs)) if spent_fracs else None

    trades_per_league = n_trades / n_leagues if n_leagues else None
    moves_per_league = n_transactions / n_leagues if n_leagues else None

    # Positional lean of adds (skill only; team-abbrev DST ids + K map outside _SKILL -> dropped).
    pos_counts = {p: 0 for p in _SKILL}
    for t in txns:
        for pid in json.loads(t.get("adds_json") or "[]"):
            p = pos_by_id.get(str(pid))
            if p in _SKILL:
                pos_counts[p] += 1
    total = sum(pos_counts.values())
    share = (lambda p: pos_counts[p] / total) if total else (lambda p: None)

    return {**depth,
            "n_waivers": n_waivers, "n_free_agents": n_fa, "n_trades": n_trades,
            "waiver_share": waiver_share, "waiver_success_rate": waiver_success_rate,
            "avg_bid_frac": avg_bid_frac, "max_bid_frac": max_bid_frac,
            "budget_spent_frac": budget_spent_frac,
            "trades_per_league": trades_per_league, "moves_per_league": moves_per_league,
            "add_qb_share": share("QB"), "add_rb_share": share("RB"),
            "add_wr_share": share("WR"), "add_te_share": share("TE")}
