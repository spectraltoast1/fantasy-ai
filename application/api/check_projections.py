"""Unit check for the projection engine's pure functions (store-migration Session 4).

DB-free: exercises ``expand_slots`` / ``optimal_lineup`` / ``matchup_win_probs`` /
``normal_cdf`` / ``_num`` against hand-computed expectations, so a dialect or ordering
regression in the engine trips here before any endpoint is wired.

Run: ``application/api/.venv/bin/python -m application.api.check_projections``
"""

from __future__ import annotations

import math

from application.api import calcs, projections as pj


def _player(i, position, pts, band=0.0):
    return {"_i": i, "sleeperId": f"p{i}", "name": f"P{i}", "position": position,
            "nflTeam": None, "pts": pts, "band": band,
            "p25": None, "p50": None, "p75": None, "hasProj": True}


def check_expand_slots():
    rows = [
        {"slot": "QB", "count": 1, "eligible": "QB"},
        {"slot": "RB", "count": 2, "eligible": "RB"},
        {"slot": "WR", "count": 2, "eligible": "WR"},
        {"slot": "TE", "count": 1, "eligible": "TE"},
        {"slot": "FLEX", "count": 1, "eligible": "RB,WR,TE"},
    ]
    slots = pj.expand_slots(rows)
    assert len(slots) == 7, f"expected 7 physical slots, got {len(slots)}"
    # Most-constrained first: every len-1 slot precedes the len-3 FLEX.
    assert slots[-1]["slot"] == "FLEX", f"FLEX must sort last, got {slots[-1]}"
    assert all(len(s["eligible"]) == 1 for s in slots[:-1]), "dedicated slots must lead"
    # Stable among equal keys → declaration order preserved for the len-1 slots.
    assert [s["slot"] for s in slots[:-1]] == ["QB", "RB", "RB", "WR", "WR", "TE"]
    print("  ok  expand_slots: 7 slots, most-constrained-first, stable order")


def check_optimal_lineup():
    slots = pj.expand_slots([
        {"slot": "QB", "count": 1, "eligible": "QB"},
        {"slot": "RB", "count": 2, "eligible": "RB"},
        {"slot": "WR", "count": 2, "eligible": "WR"},
        {"slot": "TE", "count": 1, "eligible": "TE"},
        {"slot": "FLEX", "count": 1, "eligible": "RB,WR,TE"},
    ])
    players = [
        _player(0, "QB", 20), _player(1, "RB", 15), _player(2, "RB", 12),
        _player(3, "RB", 10), _player(4, "WR", 14), _player(5, "WR", 8),
        _player(6, "TE", 6), _player(7, "WR", 5),  # WR7 is the odd one out → bench
    ]
    res = pj.optimal_lineup(players, slots)
    picks = res["picks"]
    assert len(picks) == 7, f"expected 7 starters, got {len(picks)}"
    # FLEX should take the best leftover skill player (RB3=10 over WR7=5).
    flex = next(p for p in picks if p["slot"] == "FLEX")
    assert flex["_i"] == 3, f"FLEX should be RB3 (_i=3), got _i={flex['_i']}"
    assert res["total"] == 85.0, f"expected total 85, got {res['total']}"
    started = {p["_i"] for p in picks}
    assert started == {0, 1, 2, 3, 4, 5, 6}, f"unexpected starters {started}"
    assert 7 not in started, "WR7 should be benched"
    print("  ok  optimal_lineup: greedy fill, FLEX takes best leftover, total 85")

    # Tie-break: strict `>` means the FIRST-seen max wins its slot. Two equal RBs → the
    # earlier index starts.
    tie = pj.optimal_lineup(
        [_player(0, "RB", 10), _player(1, "RB", 10)],
        [{"slot": "RB", "eligible": ["RB"]}],
    )
    assert tie["picks"][0]["_i"] == 0, "first-seen must win a points tie"
    print("  ok  optimal_lineup: first-seen wins ties (strict >)")


def check_win_probs():
    # muA=110/muB=100, both σ=10: z=(10)/sqrt(200)=0.70711 → Φ = 0.5*(1+erf(0.5)) ≈ 0.76025.
    pa, pb = pj.matchup_win_probs(110, 10, 100, 10)
    expected = 0.5 * (1 + math.erf(0.5))
    assert abs(pa - expected) < 1e-12, f"pa {pa} != {expected}"
    assert abs((pa + pb) - 1.0) < 1e-12, "win probs must sum to 1"
    assert calcs.js_round(pa * 100) == 76, f"rounded winProb A should be 76, got {calcs.js_round(pa*100)}"
    assert calcs.js_round(pb * 100) == 24, f"rounded winProb B should be 24, got {calcs.js_round(pb*100)}"
    assert calcs.js_round(pa * 100) + calcs.js_round(pb * 100) == 100, "rounded pair must sum to 100 here"
    # Both σ=0 → coin flip.
    assert pj.matchup_win_probs(120, 0, 90, 0) == [0.5, 0.5], "σ=0 both sides → 0.5"
    # normal_cdf(0) == 0.5 exactly.
    assert pj.normal_cdf(0.0) == 0.5
    print("  ok  matchup_win_probs: hand-computed 76/24, σ=0 → coin flip, Φ(0)=0.5")


def check_num():
    assert pj._num(None, 0.0) == 0.0, "null → default"
    assert pj._num(None, None) is None, "null → None default"
    assert pj._num(3, 0.0) == 3.0 and isinstance(pj._num(3, 0.0), float), "coerces to float"
    print("  ok  _num: null-safe coercion")


def main():
    print("check_projections:")
    check_expand_slots()
    check_optimal_lineup()
    check_win_probs()
    check_num()
    print("ALL GREEN")


if __name__ == "__main__":
    main()
