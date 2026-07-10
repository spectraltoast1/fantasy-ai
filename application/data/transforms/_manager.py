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

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _scoring import scoring_profile

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
