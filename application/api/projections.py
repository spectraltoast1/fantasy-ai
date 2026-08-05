"""The shared projection / win-probability engine (store-migration Session 4).

The Python mirror of the projection block in ``application/frontend/src/queries.js``
(l.760-1036): the optimal-lineup → μ/σ → analytic win-prob chain that three surfaces
reuse — the Matchups slate (``load_matchups``), the matchup detail (``load_matchup_detail``),
and the Team-detail ``thisWeek`` bar (``team_matchup_summary``). Built ONCE here so those
three never inline it.

Pure helpers (``expand_slots``, ``optimal_lineup``, ``matchup_win_probs``, ``normal_cdf``,
``records_by_roster``, ``_num``) have no data access; ``team_projections`` /
``team_matchup_summary`` / ``target_week_for`` read the store. Every query is league-scoped
(the Stage-B seam). The DuckDB ``arg_max(col, week)`` roster read is the SAME ``_latest``
definition Team detail uses, so the surfaces agree on who is rostered.

Import note: ``reads`` and this module import each other at top level, but neither *accesses*
the other's attributes at import time (only inside function bodies) — so the circular import
resolves cleanly whichever loads first. This lets ``team_projections`` reuse ``reads._latest``
/ ``reads._week_cutoff`` verbatim (decision 3: same definition, do not re-derive).
"""

from __future__ import annotations

import math

from application.api import calcs, db, reads, settings

POS = ["QB", "RB", "WR", "TE"]


def _num(x, default):
    """Null-safe numeric coercion — ``x == null ? default : Number(x)``.

    The projection reads (``center_ppr``/``band_ppr``/``p25``/``p50``/``p75``) are nullable;
    the browser coerced a missing value with ``Number(...)`` (``Number(null) === 0``). Use this
    instead of a bare ``float()`` (which would 500 on a null) so the endpoint reproduces the JS
    fallbacks. Establishes the guardrail from the Session-1-3 audit (finding 2).
    """
    return default if x is None else float(x)


# Φ(z): the standard-normal CDF (queries.js normalCdf, l.1034). The browser uses an
# Abramowitz-Stegun erf approximation (|ε| < 1.5e-7); math.erf is exact and well within that,
# and the win % is rounded to an integer percent downstream, so the result is identical.
def normal_cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def expand_slots(slot_rows) -> list[dict]:
    """One entry per physical starting slot (queries.js expandSlots, l.994).

    A FLEX ``count`` of 2 → two slots, each carrying its ``eligible`` position list. Sorted
    most-constrained first (``len(eligible)`` ascending) so dedicated slots claim their stars
    before FLEX draws from the pool.
    """
    slots = []
    for s in slot_rows:
        eligible = str(s["eligible"]).split(",")
        for _ in range(int(s["count"])):
            slots.append({"slot": s["slot"], "eligible": eligible})
    slots.sort(key=lambda x: len(x["eligible"]))
    return slots


def optimal_lineup(players, slots) -> dict:
    """Greedy optimal lineup (queries.js optimalLineup, l.1007).

    For each slot in order, pick the highest-``pts`` eligible *unused* player. Strict ``>`` so
    the FIRST max wins ties — the caller must iterate ``players`` in a stable order (the roster
    read's ``ORDER BY sleeper_player_id``) so the pick matches the app. Each player carries a
    stable ``_i`` so "used across slots" tracks correctly. Returns ``{"total", "picks"}`` with
    each pick tagged with its filled ``slot``.
    """
    used = set()
    picks = []
    total = 0.0
    for slot in slots:
        best = None
        for p in players:
            if p["_i"] in used or p["position"] not in slot["eligible"]:
                continue
            if best is None or p["pts"] > best["pts"]:
                best = p
        if best is None:
            continue
        total += best["pts"]
        used.add(best["_i"])
        picks.append({**best, "slot": slot["slot"]})
    return {"total": total, "picks": picks}


def matchup_win_probs(mu_a, sig_a, mu_b, sig_b) -> list[float]:
    """One matchup's two sides → ``[winProbA, winProbB]`` as 0-1 fractions (queries.js l.837).

    ``pa = normal_cdf((muA - muB) / sqrt(sigA² + sigB²))``; ``0.5`` if both σ are 0.
    """
    denom = math.sqrt(sig_a * sig_a + sig_b * sig_b)
    pa = normal_cdf((mu_a - mu_b) / denom) if denom > 0 else 0.5
    return [pa, 1 - pa]


EMPTY_RECORD = {"w": 0, "l": 0, "t": 0}


def records_by_roster(week_rows) -> dict:
    """Real W-L-T per roster from the team-week results (queries.js recordsByRoster, l.750).

    ``week_rows`` are ``_sql_standings_weeks`` rows (one per team-week, weeks ≤ N).

    ``result`` is NULL for a week with no gradeable matchup — unplayed, a bye, or no matchup_id
    (``transforms/_matchup``). That week counts NOWHERE: not a win, not a loss, not a tie. The absent
    ``else`` is the point, not an oversight — it is what makes a freshly drafted league read 0-0 instead
    of inventing a record out of a slate nobody has played.
    """
    rec: dict[int, dict] = {}
    for r in week_rows:
        x = rec.setdefault(int(r["roster_id"]), dict(EMPTY_RECORD))
        if r["result"] == "W":
            x["w"] += 1
        elif r["result"] == "L":
            x["l"] += 1
        elif r["result"] == "T":
            x["t"] += 1
    return rec


def target_week_for(as_of_week, conn=None, lid=None):
    """Resolve as-of N → the upcoming target week N+1 (queries.js targetWeekFor, l.740).

    ``as_of_week`` null → ``max(week) + 1`` (the latest played week's next week); a number →
    ``N + 1``. Returns ``None`` only when the season has no weeks. ``lid`` defaults to the is_mine
    league (parity) when None.
    """
    if as_of_week is not None:
        return int(as_of_week) + 1

    sql = "SELECT max(week) AS w FROM season WHERE league_id = %(lid)s"
    params = {"lid": lid or settings.league_id()}
    if conn is not None:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    else:
        rows = db.fetch_all(sql, params)
    w = rows[0]["w"] if rows else None
    return None if w is None else int(w) + 1


def team_projections(as_of_week, target_week, lid=None, viewer=None) -> dict:
    """Per-team projected lineup for ``target_week`` (queries.js teamProjections, l.765).

    Roster-as-of-N (``_latest`` arg_max — the SAME definition Team detail uses) × that week's
    ``projection_consensus``. Per team: attach each rostered skill player's ``center_ppr`` (→
    ``pts``, the μ term), ``band_ppr`` (→ the σ term) and ``p25/p50/p75``; run ``optimal_lineup``;
    then **μ = round1(Σ starters' pts)** and **σ = √(Σ starters' band²), raw**. The rounded μ is
    what the win-prob math consumes downstream (round first, then compute win prob).

    Returns ``rosterId → {rosterId, name, owner, isMe, mu, sigma, starters, bench}`` — bench =
    non-starters sorted by ``pts`` desc. ``lid`` defaults to the is_mine league (parity) when None;
    ``viewer`` is the resolved "you" roster_id (from the caller's ``resolve_viewer``) — ``isMe`` is
    ``rid == viewer``. When ``viewer`` is None (no viewer in this league) nothing is flagged "me".
    """
    lid = lid or settings.league_id()

    with db.connect() as conn:
        def q(sql, params):
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall()

        # Roster-as-of-N: latest non-null value per column, WHERE roster_id resolves. ORDER BY
        # sleeper_player_id makes the optimal-lineup tie-break (strict >, first-seen) deterministic
        # and identical to Team detail's roster order.
        roster_rows = q(
            "WITH latest AS ("
            "  SELECT sleeper_player_id,"
            f"    {reads._latest('roster_id')} AS roster_id,"
            f"    {reads._latest('player_display_name')} AS name,"
            f"    {reads._latest('position')} AS position,"
            f"    {reads._latest('team')} AS nfl_team"
            "  FROM season"
            "  WHERE league_id = %(lid)s AND position IN ('QB','RB','WR','TE') AND "
            + reads._week_cutoff(as_of_week) +
            "  GROUP BY sleeper_player_id"
            ") SELECT * FROM latest WHERE roster_id IS NOT NULL ORDER BY sleeper_player_id",
            {"lid": lid, "n": as_of_week},
        )
        proj_rows = q(
            "SELECT sleeper_player_id, center_ppr, band_ppr, p25_ppr, p50_ppr, p75_ppr "
            "FROM projection_consensus WHERE league_id = %(lid)s AND week = %(tw)s",
            {"lid": lid, "tw": int(target_week)},
        )
        slot_rows = q(
            "SELECT slot, count, eligible FROM lineup_slots WHERE league_id = %(lid)s",
            {"lid": lid},
        )
        team_rows = q(
            "SELECT roster_id, team_name, owner_name FROM teams WHERE league_id = %(lid)s",
            {"lid": lid},
        )

    proj_by = {p["sleeper_player_id"]: p for p in proj_rows}
    slots = expand_slots(slot_rows)

    by_roster: dict[int, list] = {}
    for r in roster_rows:
        by_roster.setdefault(int(r["roster_id"]), []).append(r)

    teams = {}
    for t in team_rows:
        rid = int(t["roster_id"])
        roster = by_roster.get(rid, [])
        # Attach the target-week projection to each rostered skill player. A player with no
        # projection row that week contributes pts=0 / band=0 and won't start; when the row
        # exists but a column is null, Number(null)===0 (so p25/50/75 default to 0, not null —
        # matching queries.js l.809-814). p25/50/75 stay null ONLY when the whole row is missing.
        players = []
        for i, p in enumerate(roster):
            pr = proj_by.get(p["sleeper_player_id"])
            players.append({
                "_i": i,
                "sleeperId": p["sleeper_player_id"],
                "name": p["name"],
                "position": p["position"],
                "nflTeam": p["nfl_team"] if p["nfl_team"] is not None else None,
                "pts": _num(pr["center_ppr"], 0.0) if pr else 0.0,
                "band": _num(pr["band_ppr"], 0.0) if pr else 0.0,
                "p25": _num(pr["p25_ppr"], 0.0) if pr else None,
                "p50": _num(pr["p50_ppr"], 0.0) if pr else None,
                "p75": _num(pr["p75_ppr"], 0.0) if pr else None,
                "hasProj": bool(pr),
            })
        picks = optimal_lineup(players, slots)["picks"]
        starter_set = {p["_i"] for p in picks}
        bench = sorted(
            (p for p in players if p["_i"] not in starter_set),
            key=lambda p: p["pts"],
            reverse=True,
        )
        mu = sum(p["pts"] for p in picks)
        sigma = math.sqrt(sum(p["band"] * p["band"] for p in picks))
        teams[rid] = {
            "rosterId": rid,
            "name": t["team_name"] or t["owner_name"] or f"Team {rid}",
            "owner": t["owner_name"] if t["owner_name"] is not None else None,
            "isMe": rid == viewer,
            "mu": calcs.round1(mu),  # round μ at the team level; the win-prob math reads THIS.
            "sigma": sigma,
            "starters": picks,
            "bench": bench,
        }
    return teams


def team_matchup_summary(roster_id, as_of_week, lid=None):
    """One team's upcoming (week N+1) game — opponent + projected totals + win prob.

    The Team-detail ``thisWeek`` bar (queries.js teamMatchupSummary, l.846). ``None`` when there
    is no next game (season complete) or the team isn't scheduled that week. ``lid`` defaults to
    the is_mine league (parity) when None.
    """
    rid = int(roster_id)
    lid = lid or settings.league_id()
    target_week = target_week_for(as_of_week, lid=lid)
    if target_week is None:
        return None

    mine = db.fetch_all(
        "SELECT matchup_id FROM schedule "
        "WHERE league_id = %(lid)s AND week = %(tw)s AND roster_id = %(rid)s "
        "AND matchup_id IS NOT NULL",
        {"lid": lid, "tw": target_week, "rid": rid},
    )
    if not mine:
        return None
    mid = int(mine[0]["matchup_id"])

    teams = team_projections(as_of_week, target_week, lid=lid)
    sides = db.fetch_all(
        "SELECT roster_id FROM schedule "
        "WHERE league_id = %(lid)s AND week = %(tw)s AND matchup_id = %(mid)s",
        {"lid": lid, "tw": target_week, "mid": mid},
    )
    opp_id = next((int(r["roster_id"]) for r in sides if int(r["roster_id"]) != rid), None)
    if opp_id is None or rid not in teams or opp_id not in teams:
        return None

    me = teams[rid]
    opp = teams[opp_id]
    p_me, p_opp = matchup_win_probs(me["mu"], me["sigma"], opp["mu"], opp["sigma"])
    return {
        "matchupId": mid,
        "targetWeek": target_week,
        "me": {"proj": me["mu"], "winProb": calcs.js_round(p_me * 100)},
        "opp": {
            "rosterId": opp_id,
            "name": opp["name"],
            "proj": opp["mu"],
            "winProb": calcs.js_round(p_opp * 100),
        },
    }


# Flatten a starter/bench player to the matchup-detail view shape (queries.js matchupPlayerView,
# l.921): median tick + 25-75 range for the gauge. Bench players have no filled slot → null.
def matchup_player_view(p) -> dict:
    return {
        "sleeperId": p["sleeperId"],
        "name": p["name"],
        "pos": p["position"],
        "nflTeam": p["nflTeam"] if p.get("nflTeam") is not None else None,
        "slot": p.get("slot"),
        "proj": calcs.round1(p["pts"]) if p["hasProj"] else None,
        "p25": p["p25"],
        "p50": p["p50"],
        "p75": p["p75"],
        "hasProj": p["hasProj"],
    }
