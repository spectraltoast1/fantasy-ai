"""Server-side data reads — the Python mirror of ``application/frontend/src/queries.js``.

One function per panel, each returning the *same shape* its ``queries.js`` loader returns
today (field names, nulls, ordering) so the Session-5 frontend swap is drop-in. The DuckDB
SQL is ported to Postgres (``arg_max``/``QUALIFY``/``any_value`` -> ``DISTINCT ON`` / window /
``max``); the inline JS calculations live in ``calcs.py``. Every query is scoped to the active
league (a no-op filter with one league today; the Stage-B seam).

Store tables map 1:1 to the DuckDB logical names: ``'season.parquet'`` -> ``season``,
``'slots.parquet'`` -> ``lineup_slots``, etc.
"""

from __future__ import annotations

from application.api import calcs, db, projections, settings

POS = ["QB", "RB", "WR", "TE"]


# --- the season-replay week seam (queries.js l.632/636), as Postgres fragments ------------
# Named-parameter placeholders (%(n)s / %(lid)s) so fragments compose without arg ordering.

def _week_cutoff(n):
    """Bound an inline ``season`` read to weeks <= N (or all weeks when N is null)."""
    return "TRUE" if n is None else "week <= %(n)s"


def _as_of_slice(table, n):
    """Pick one as-of slice from a tall derived table: the latest, or exactly week N."""
    if n is None:
        return f"as_of_week = (SELECT max(as_of_week) FROM {table} WHERE league_id = %(lid)s)"
    return "as_of_week = %(n)s"


def _le_cutoff(n):
    """A ``as_of_week <= N`` cutoff (weekly series), or all rows when N is null."""
    return "TRUE" if n is None else "as_of_week <= %(n)s"


def _params(n=None, **extra):
    """Base bind dict every query shares: league id + optional as-of week + extras."""
    p = {"lid": settings.league_id(), "n": n}
    p.update(extra)
    return p


# ---------------------------------------------------------------------------
# Shared reads — weeks selector + league-meta chrome.
# ---------------------------------------------------------------------------

def load_weeks() -> dict:
    """Weeks played + the default (latest). Mirrors loadWeeks (l.644)."""
    rows = db.fetch_all(
        "SELECT DISTINCT week FROM season WHERE league_id = %(lid)s ORDER BY week",
        _params(),
    )
    weeks = [int(r["week"]) for r in rows]
    return {"weeks": weeks, "latest": weeks[-1] if weeks else None}


def load_league_meta(as_of_week=None) -> dict:
    """Top-bar chrome: "10-tm · PPR · 1QB" label + the user's record. Mirrors loadLeagueMeta (l.659)."""
    p = _params(as_of_week)
    with db.connect() as conn:
        def q(sql, extra=None):
            with conn.cursor() as cur:
                cur.execute(sql, {**p, **(extra or {})})
                return cur.fetchall()

        team_rows = q("SELECT count(*)::int AS n FROM teams WHERE league_id = %(lid)s")
        rec_rows = q(
            "SELECT value FROM league_settings "
            "WHERE league_id = %(lid)s AND section = 'scoring' AND key = 'rec'"
        )
        slot_rows = q("SELECT slot, count, eligible FROM lineup_slots WHERE league_id = %(lid)s")
        me_rows = q(
            "SELECT roster_id, owner_name FROM teams "
            "WHERE league_id = %(lid)s AND owner_name = %(me)s",
            {"me": settings.my_username()},
        )

        team_count = int(team_rows[0]["n"]) if team_rows else 0

        # Scoring label from the reception value (1 -> PPR, 0.5 -> Half, 0 -> Std).
        rec = float(rec_rows[0]["value"]) if rec_rows else None
        if rec == 1:
            scoring = "PPR"
        elif rec == 0.5:
            scoring = "Half-PPR"
        elif rec == 0:
            scoring = "Std"
        elif rec is not None:
            scoring = f"{rec:g}-PPR"
        else:
            scoring = "—"

        # QB structure from the lineup slots: a QB-eligible flex reads as SF, else the count
        # of dedicated QB slots.
        qb_slots = 0
        superflex = False
        for s in slot_rows:
            elig = str(s["eligible"] or "").upper()
            if elig == "QB":
                qb_slots += int(s["count"])
            elif "QB" in elig.split(","):
                superflex = True
        qb = "SF" if superflex else f"{qb_slots or 1}QB"

        # The user's record as of week N (one W/L per team-week).
        record = None
        my_roster_id = int(me_rows[0]["roster_id"]) if me_rows else None
        if my_roster_id is not None:
            rows = q(
                "WITH tw AS ("
                "  SELECT roster_id, week, max(matchup_result) AS result"
                "  FROM season WHERE league_id = %(lid)s AND " + _week_cutoff(as_of_week) +
                "  GROUP BY roster_id, week"
                ") "
                "SELECT count(*) FILTER (WHERE result = 'W') AS w,"
                "       count(*) FILTER (WHERE result = 'L') AS l "
                "FROM tw WHERE roster_id = %(rid)s",
                {"rid": my_roster_id},
            )
            if rows and rows[0]["w"] is not None:
                record = f"{int(rows[0]['w'])}-{int(rows[0]['l'])}"

    return {
        "name": None,
        "label": f"{team_count}-tm · {scoring} · {qb}",
        "record": record,
        "myOwner": me_rows[0]["owner_name"] if me_rows else None,
    }


# ---------------------------------------------------------------------------
# Players tab — the VOR-anchored player table + the player card.
# ---------------------------------------------------------------------------

# The Postgres equivalent of DuckDB's arg_max(col, week): the latest-week *non-null* value
# per player. arg_max ignores rows where the arg is null, so a null team in the newest week
# must fall back to the last week the player had one — DISTINCT ON can't do that per column.
def _latest(col):
    return f"(array_agg({col} ORDER BY week DESC) FILTER (WHERE {col} IS NOT NULL))[1]"


# One row per rostered skill player, assembling the four reads (queries.js SQL_PLAYERS, l.36).
#   arg_max(col, week)                       -> _latest(col) (latest non-null, per column)
#   QUALIFY row_number() OVER (... week DESC) -> DISTINCT ON (sleeper_player_id) ... ORDER BY week DESC
#   ORDER BY vor DESC                         -> ... DESC NULLS LAST (DuckDB nulls-last default)
#                                               + sleeper_player_id, a deterministic tiebreak
def _sql_players(n):
    return (
        "WITH ident AS ("
        "  SELECT sleeper_player_id,"
        f"         {_latest('player_display_name')} AS name,"
        f"         {_latest('team')} AS nfl_team,"
        f"         {_latest('position')} AS position"
        "  FROM season"
        "  WHERE league_id = %(lid)s AND position IN ('QB','RB','WR','TE') AND " + _week_cutoff(n) +
        "  GROUP BY sleeper_player_id"
        "), pv AS ("
        "  SELECT sleeper_player_id, roster_id, position, vor, ros_value"
        "  FROM production_vor WHERE league_id = %(lid)s AND " + _as_of_slice("production_vor", n) +
        "), mv AS ("
        "  SELECT sleeper_player_id, market_vor, trade_gap, is_cross_time"
        "  FROM market_vor WHERE league_id = %(lid)s"
        "    AND snapshot_date = (SELECT max(snapshot_date) FROM market_vor WHERE league_id = %(lid)s)"
        "), rs AS ("
        "  SELECT DISTINCT ON (sleeper_player_id) sleeper_player_id,"
        "         bull_grade, bear_grade, situation_grade"
        "  FROM ros_synthesis WHERE league_id = %(lid)s"
        "  ORDER BY sleeper_player_id, week DESC"
        ") "
        "SELECT pv.sleeper_player_id AS sleeper_id,"
        "       coalesce(ident.name, pv.sleeper_player_id) AS name,"
        "       coalesce(ident.position, pv.position) AS position,"
        "       ident.nfl_team, pv.roster_id,"
        "       pv.vor AS prod_vor, mv.market_vor AS mkt_vor, mv.trade_gap, mv.is_cross_time,"
        "       rs.bull_grade, rs.bear_grade, rs.situation_grade,"
        "       t.team_name, t.owner_name "
        "FROM pv "
        "LEFT JOIN ident USING (sleeper_player_id) "
        "LEFT JOIN mv ON mv.sleeper_player_id = pv.sleeper_player_id "
        "LEFT JOIN rs ON rs.sleeper_player_id = pv.sleeper_player_id "
        "LEFT JOIN teams t ON t.roster_id = pv.roster_id AND t.league_id = %(lid)s "
        "ORDER BY pv.vor DESC NULLS LAST, pv.sleeper_player_id"
    )


def load_players(as_of_week=None) -> list[dict]:
    """The Players table: rostered skill players priced by PROD VOR. Mirrors loadPlayers (l.87)."""
    me = settings.my_username()
    rows = db.fetch_all(_sql_players(as_of_week), _params(as_of_week))
    return [
        {
            "sleeperId": r["sleeper_id"],
            "name": r["name"],
            "pos": r["position"],
            "nflTeam": r["nfl_team"] if r["nfl_team"] is not None else None,
            "rosterId": int(r["roster_id"]),
            "teamName": r["team_name"] or r["owner_name"] or None,
            "isMe": r["owner_name"] == me,
            "prodVor": calcs.num(r["prod_vor"]),
            "mktVor": calcs.num(r["mkt_vor"]),
            "tradeGap": calcs.num(r["trade_gap"]),
            "mktCrossTime": bool(r["is_cross_time"]),
            "bull": calcs.num(r["bull_grade"]),
            "bear": calcs.num(r["bear_grade"]),
            "sit": calcs.num(r["situation_grade"]),
        }
        for r in rows
    ]


def load_player_card(sleeper_id, as_of_week=None) -> dict:
    """The full player card (Value·VOR + Opportunity + ROS shape). Mirrors loadPlayerCard (l.120)."""
    p = _params(as_of_week, sid=str(sleeper_id))
    prod_cutoff = "TRUE" if as_of_week is None else "as_of_week <= %(n)s"
    me_name = settings.my_username()

    with db.connect() as conn:
        def q(sql):
            with conn.cursor() as cur:
                cur.execute(sql, p)
                return cur.fetchall()

        # arg_max(col, week) over one player -> the latest *non-null* value per column
        # (aggregate form: always one row, all-null if the player has no rows — matches the JS,
        # where identRows[0] is always defined so the "missing" check hinges on prod below).
        ident_rows = q(
            f"SELECT {_latest('player_display_name')} AS name, {_latest('team')} AS nfl_team,"
            f"       {_latest('position')} AS position, {_latest('roster_id')} AS roster_id "
            "FROM season WHERE league_id = %(lid)s AND sleeper_player_id = %(sid)s "
            "AND " + _week_cutoff(as_of_week)
        )
        prod_rows = q(
            "SELECT as_of_week, vor, ros_value FROM production_vor "
            "WHERE league_id = %(lid)s AND sleeper_player_id = %(sid)s AND " + prod_cutoff +
            " ORDER BY as_of_week"
        )
        mkt_rows = q(
            "SELECT snapshot_date, market_vor, trade_gap, is_cross_time FROM market_vor "
            "WHERE league_id = %(lid)s AND sleeper_player_id = %(sid)s ORDER BY snapshot_date"
        )
        sig_rows = q(
            "SELECT recent_ppg, expected_ppg, opp_g, opp_pct, td_share, eff_ratio, regression_risk,"
            "       read, quality_rate, luck, direction, reliability, point_correlation, security,"
            "       games, low_sample "
            "FROM player_signal WHERE league_id = %(lid)s AND sleeper_player_id = %(sid)s "
            "AND " + _as_of_slice("player_signal", as_of_week)
        )
        ros_rows = q(
            "SELECT bull_grade, bull_note, bear_grade, bear_note, situation_grade, situation_note,"
            "       confidence, confidence_note, signal_tier, has_news, has_ros_anchor,"
            "       anchor_is_prior_season "
            "FROM ros_synthesis WHERE league_id = %(lid)s AND sleeper_player_id = %(sid)s "
            "ORDER BY week DESC LIMIT 1"
        )
        team_rows = q("SELECT roster_id, team_name, owner_name FROM teams WHERE league_id = %(lid)s")

    ident = ident_rows[0] if ident_rows else None
    if ident is None and not prod_rows:
        return {"missing": True}

    # Identity + roster status.
    roster_id = int(ident["roster_id"]) if ident and ident["roster_id"] is not None else None
    team_by_id = {}
    my_roster_id = None
    for t in team_rows:
        team_by_id[int(t["roster_id"])] = t
        if t["owner_name"] == me_name:
            my_roster_id = int(t["roster_id"])
    my_team = team_by_id.get(roster_id)
    on_yours = roster_id is not None and roster_id == my_roster_id
    if on_yours:
        status = "On your roster"
    elif my_team:
        status = f"Rostered · {my_team['team_name'] or my_team['owner_name']}"
    else:
        status = "Rostered"

    # Value·VOR series (oldest -> newest) + value/delta.
    prod = calcs.series_read([float(r["vor"]) for r in prod_rows])
    mkt = calcs.series_read([float(r["market_vor"]) for r in mkt_rows])

    # Trade lean off the current Production-Market gap (cross-time today).
    last = mkt_rows[-1] if mkt_rows else None
    gap = float(last["trade_gap"]) if last and last["trade_gap"] is not None else None
    cross_time = bool(last["is_cross_time"]) if last else False
    lean = None
    if gap is not None:
        if gap > calcs.TRADE_GAP_T:
            lean = {"call": "SELL", "why": "Market values him above his production."}
        elif gap < -calcs.TRADE_GAP_T:
            lean = {"call": "BUY", "why": "Production beats his current market price."}
        else:
            lean = {"call": "HOLD", "why": "Market and production roughly agree."}
        lean["gap"] = gap
        lean["crossTime"] = cross_time

    # Opportunity axes (player_signal).
    s = sig_rows[0] if sig_rows else None
    opportunity = (
        {
            "qualityRate": calcs.num(s["quality_rate"]),
            "effRatio": calcs.num(s["eff_ratio"]),
            "volumePct": calcs.num(s["opp_pct"]),
            "oppG": calcs.num(s["opp_g"]),
            "trustDir": s["direction"] if s["direction"] is not None else None,
            "reliability": calcs.num(s["reliability"]),
            "pointCorr": calcs.num(s["point_correlation"]),
            "luck": calcs.num(s["luck"]),
            "recentPpg": calcs.num(s["recent_ppg"]),
            "expectedPpg": calcs.num(s["expected_ppg"]),
            "read": s["read"] if s["read"] is not None else None,
            "security": s["security"] if s["security"] is not None else None,
            "lowSample": bool(s["low_sample"]),
        }
        if s
        else None
    )

    # ROS Outcome Shape (ros_synthesis) — sparse; null when no AI read exists.
    r = ros_rows[0] if ros_rows else None
    ros = (
        {
            "bull": calcs.num(r["bull_grade"]),
            "bear": calcs.num(r["bear_grade"]),
            "situation": calcs.num(r["situation_grade"]),
            "bullNote": r["bull_note"],
            "bearNote": r["bear_note"],
            "situationNote": r["situation_note"],
            "confidence": r["confidence"],
            "confidenceNote": r["confidence_note"],
            "signalTier": r["signal_tier"],
            "priorSeason": bool(r["anchor_is_prior_season"]),
        }
        if r
        else None
    )

    return {
        "sleeperId": sleeper_id,
        "name": ident["name"] if ident and ident["name"] is not None else sleeper_id,
        "pos": ident["position"] if ident else None,
        "nflTeam": ident["nfl_team"] if ident else None,
        "status": status,
        "onYours": on_yours,
        "prod": prod,
        "mkt": {**mkt, "crossTime": cross_time},
        "lean": lean,
        "opportunity": opportunity,
        "ros": ros,
    }


# ---------------------------------------------------------------------------
# Teams tab — the standings table + team detail + manager dossier.
# ---------------------------------------------------------------------------

# One row per (team, week): total points + W/L, weeks <= N. Feeds the real record and the
# all-play "true record". any_value(col) -> max(col) (the value is constant per team-week).
def _sql_standings_weeks(n):
    return (
        "SELECT roster_id, week, max(roster_total_points) AS pts, max(matchup_result) AS result "
        "FROM season WHERE league_id = %(lid)s AND " + _week_cutoff(n) +
        " GROUP BY roster_id, week"
    )


def _all_play_record(by_week, rid):
    """all-play W/L for one roster: its weekly pts vs every *other* team. queries.js l.496-505."""
    ap = {"w": 0, "l": 0}
    for rows in by_week.values():
        mine = next((x for x in rows if x["rosterId"] == rid), None)
        if mine is None:
            continue
        for b in rows:
            if b["rosterId"] == rid:
                continue
            if mine["pts"] > b["pts"]:
                ap["w"] += 1
            elif mine["pts"] < b["pts"]:
                ap["l"] += 1
    return ap


def load_standings(as_of_week=None) -> list[dict]:
    """The Teams standings: record + all-play + playoff odds/series + posture. Mirrors loadStandings (l.278)."""
    p = _params(as_of_week)
    me = settings.my_username()
    with db.connect() as conn:
        def q(sql):
            with conn.cursor() as cur:
                cur.execute(sql, p)
                return cur.fetchall()

        team_weeks = q(_sql_standings_weeks(as_of_week))
        odds_rows = q(
            "SELECT as_of_week, roster_id, playoff_odds, avg_seed, magic_wins, remaining_games "
            "FROM bracket_odds WHERE league_id = %(lid)s AND " + _le_cutoff(as_of_week) +
            " ORDER BY roster_id, as_of_week"
        )
        team_rows = q("SELECT roster_id, team_name, owner_name FROM teams WHERE league_id = %(lid)s")

    # Records + all-play, from the team-week scores (insertion order = first-seen roster order).
    by_week: dict[int, list] = {}
    record: dict[int, dict] = {}
    for r in team_weeks:
        rid = int(r["roster_id"])
        row = {"rosterId": rid, "pts": float(r["pts"]), "result": r["result"]}
        by_week.setdefault(int(r["week"]), []).append(row)
        rec = record.setdefault(rid, {"w": 0, "l": 0})
        if row["result"] == "W":
            rec["w"] += 1
        elif row["result"] == "L":
            rec["l"] += 1

    all_play: dict[int, dict] = {}
    for rows in by_week.values():
        for a in rows:
            rec = all_play.setdefault(a["rosterId"], {"w": 0, "l": 0})
            for b in rows:
                if b["rosterId"] == a["rosterId"]:
                    continue
                if a["pts"] > b["pts"]:
                    rec["w"] += 1
                elif a["pts"] < b["pts"]:
                    rec["l"] += 1

    # Odds: the weekly playoff-odds series (x100) + the latest slice (rows ordered by as_of_week).
    odds_by_team: dict[int, dict] = {}
    for r in odds_rows:
        rid = int(r["roster_id"])
        o = odds_by_team.setdefault(rid, {"series": [], "last": None})
        o["series"].append(float(r["playoff_odds"]) * 100)
        o["last"] = r

    name_of = {int(t["roster_id"]): t for t in team_rows}

    out = []
    for rid in all_play:  # Object.keys(allPlay) order = first-seen roster order
        t = name_of.get(rid)
        o = odds_by_team.get(rid)
        ap = all_play[rid]
        rec = record.get(rid, {"w": 0, "l": 0})
        last = o["last"] if o else None
        playoff_pct = float(last["playoff_odds"]) * 100 if last and last["playoff_odds"] is not None else None
        all_play_pct = (ap["w"] / (ap["w"] + ap["l"])) * 100 if (ap["w"] + ap["l"]) else 0
        out.append({
            "rosterId": rid,
            "name": (t["team_name"] or t["owner_name"] or f"Team {rid}") if t else f"Team {rid}",
            "owner": t["owner_name"] if t else None,
            "isMe": (t["owner_name"] == me) if t else False,
            "wins": rec["w"],
            "losses": rec["l"],
            "allPlayW": ap["w"],
            "allPlayL": ap["l"],
            "playoffPct": playoff_pct,
            "allPlayPct": all_play_pct,
            "seed": calcs.js_round(float(last["avg_seed"])) if last and last["avg_seed"] is not None else None,
            "magicWins": int(last["magic_wins"]) if last and last["magic_wins"] is not None else None,
            "remainingGames": int(last["remaining_games"]) if last and last["remaining_games"] is not None else None,
            "oddsSeries": o["series"] if o else [],
            "posture": calcs.derive_posture(playoff_pct, all_play_pct) if playoff_pct is not None else None,
        })

    # Rank by playoff odds desc (nulls -> -1), then all-play % as the tiebreak.
    out.sort(key=lambda r: (r["playoffPct"] if r["playoffPct"] is not None else -1, r["allPlayPct"]), reverse=True)
    for i, r in enumerate(out):
        r["rank"] = i + 1
    return out


def load_team_detail(roster_id, as_of_week=None):
    """Team detail: stat blocks, positional depth, roster split. Mirrors loadTeamDetail (l.448).

    The ``thisWeek`` projection/win-prob bar (opponent + both projected totals + win %) comes
    from the shared engine's ``team_matchup_summary`` (Session 4) — ``None`` when there is no
    next game.
    """
    rid = int(roster_id)
    p = _params(as_of_week, rid=rid)
    prod_cutoff = "TRUE" if as_of_week is None else "as_of_week <= %(n)s"
    me = settings.my_username()

    with db.connect() as conn:
        def q(sql):
            with conn.cursor() as cur:
                cur.execute(sql, p)
                return cur.fetchall()

        team_weeks = q(_sql_standings_weeks(as_of_week))
        odds_rows = q(
            "SELECT playoff_odds, avg_seed FROM bracket_odds "
            "WHERE league_id = %(lid)s AND roster_id = %(rid)s AND " + _as_of_slice("bracket_odds", as_of_week)
        )
        # positional_depth is LEAGUE-WIDE here (all rosters) — needed for the per-position rank.
        depth_rows = q(
            "SELECT roster_id, position, starter_value, surplus_value, marginal_vor, spectrum_pos, shape "
            "FROM positional_depth WHERE league_id = %(lid)s AND " + _as_of_slice("positional_depth", as_of_week)
        )
        roster_rows = q(
            "WITH latest AS ("
            "  SELECT sleeper_player_id,"
            f"    {_latest('roster_id')} AS roster_id, {_latest('is_starter')} AS is_starter,"
            f"    {_latest('player_display_name')} AS name, {_latest('position')} AS position,"
            f"    {_latest('team')} AS nfl_team"
            "  FROM season"
            "  WHERE league_id = %(lid)s AND position IN ('QB','RB','WR','TE') AND " + _week_cutoff(as_of_week) +
            "  GROUP BY sleeper_player_id"
            ") SELECT * FROM latest WHERE roster_id = %(rid)s ORDER BY sleeper_player_id"
        )
        prod_rows = q(
            "SELECT sleeper_player_id, as_of_week, vor FROM production_vor "
            "WHERE league_id = %(lid)s AND roster_id = %(rid)s AND " + prod_cutoff +
            " ORDER BY sleeper_player_id, as_of_week"
        )
        mkt_rows = q(
            "SELECT sleeper_player_id, snapshot_date, market_vor FROM market_vor "
            "WHERE league_id = %(lid)s AND roster_id = %(rid)s ORDER BY sleeper_player_id, snapshot_date"
        )
        team_rows = q("SELECT roster_id, team_name, owner_name FROM teams WHERE league_id = %(lid)s")

    # Identity / "you".
    team_by_id = {}
    my_roster_id = None
    for t in team_rows:
        team_by_id[int(t["roster_id"])] = t
        if t["owner_name"] == me:
            my_roster_id = int(t["roster_id"])
    me_team = team_by_id.get(rid)
    if me_team is None and not roster_rows:
        return None

    # Record + all-play + points-for, from the team-week scores.
    by_week: dict[int, list] = {}
    for r in team_weeks:
        by_week.setdefault(int(r["week"]), []).append(
            {"rosterId": int(r["roster_id"]), "pts": float(r["pts"]), "result": r["result"]}
        )
    w = l = 0
    pts_for = 0.0
    games = 0
    for rows in by_week.values():
        mine = next((x for x in rows if x["rosterId"] == rid), None)
        if mine is None:
            continue
        games += 1
        pts_for += mine["pts"]
        if mine["result"] == "W":
            w += 1
        elif mine["result"] == "L":
            l += 1
    ap = _all_play_record(by_week, rid)

    odds = odds_rows[0] if odds_rows else None
    stats = {
        "record": f"{w}-{l}",
        "trueRec": f"{ap['w']}-{ap['l']}",
        "playoffPct": float(odds["playoff_odds"]) * 100 if odds and odds["playoff_odds"] is not None else None,
        "seed": calcs.js_round(float(odds["avg_seed"])) if odds and odds["avg_seed"] is not None else None,
        "ptsWk": calcs.round1(pts_for / games) if games else None,
    }

    # Positional depth per position, with league rank (by starter_value) + the shape chip.
    by_pos: dict[str, list] = {}
    for d in depth_rows:
        by_pos.setdefault(d["position"], []).append(d)
    depth = []
    for pos in POS:
        allp = sorted(by_pos.get(pos, []), key=lambda d: float(d["starter_value"]), reverse=True)
        idx = next((i for i, d in enumerate(allp) if int(d["roster_id"]) == rid), -1)
        if idx < 0:
            continue
        d = allp[idx]
        depth.append({
            "position": pos,
            "starterValue": float(d["starter_value"]),
            "surplusValue": float(d["surplus_value"]),
            "marginalVor": float(d["marginal_vor"]),
            "spectrumPos": float(d["spectrum_pos"]),
            "shape": calcs.SHAPE_LABEL.get(d["shape"], d["shape"]),
            "rank": idx + 1,
            "nTeams": len(allp),
        })

    # Per-player VOR series, keyed by sleeper_player_id.
    prod_by: dict[str, list] = {}
    for r in prod_rows:
        prod_by.setdefault(r["sleeper_player_id"], []).append(float(r["vor"]))
    mkt_by: dict[str, list] = {}
    for r in mkt_rows:
        mkt_by.setdefault(r["sleeper_player_id"], []).append(float(r["market_vor"]))

    players = [
        {
            "sleeperId": pr["sleeper_player_id"],
            "name": pr["name"],
            "pos": pr["position"],
            "nflTeam": pr["nfl_team"] if pr["nfl_team"] is not None else None,
            "isStarter": bool(pr["is_starter"]),
            "prod": calcs.series_read(prod_by.get(pr["sleeper_player_id"], [])),
            "mkt": calcs.series_read(mkt_by.get(pr["sleeper_player_id"], [])),
        }
        for pr in roster_rows
    ]

    def by_value(pl):
        return sorted(
            pl,
            key=lambda x: x["prod"]["value"] if x["prod"]["value"] is not None else float("-inf"),
            reverse=True,
        )

    starters = by_value([pp for pp in players if pp["isStarter"]])
    bench = by_value([pp for pp in players if not pp["isStarter"]])

    return {
        "rosterId": rid,
        "name": (me_team["team_name"] or me_team["owner_name"] or f"Team {rid}") if me_team else f"Team {rid}",
        "owner": me_team["owner_name"] if me_team else None,
        "onYours": rid == my_roster_id,
        "stats": stats,
        "thisWeek": projections.team_matchup_summary(rid, as_of_week),
        "depth": depth,
        "roster": {"starters": starters, "bench": bench},
    }


def load_manager_dossier(roster_id) -> dict:
    """The Manager Dossier for one roster — a clean 1:1 passthrough. Mirrors loadManagerDossier (l.583)."""
    rows = db.fetch_all(
        "SELECT owner_name, team_name, headline, waiver_faab, trade_tendency, positional_lean,"
        "       roster_construction, edge_or_blindspot, confidence_note, depth_tier,"
        "       n_leagues, n_seasons, n_transactions, is_zero_signal, model, generated_at "
        "FROM manager_dossiers WHERE league_id = %(lid)s AND roster_id = %(rid)s",
        _params(rid=int(roster_id)),
    )
    d = rows[0] if rows else None
    if not d:
        return {"missing": True}
    return {
        "owner": d["owner_name"],
        "teamName": d["team_name"] or d["owner_name"],
        "isZeroSignal": bool(d["is_zero_signal"]),
        "headline": d["headline"],
        "tendencies": {
            "waiverFaab": d["waiver_faab"],
            "tradeTendency": d["trade_tendency"],
            "positionalLean": d["positional_lean"],
            "rosterConstruction": d["roster_construction"],
            "edgeOrBlindspot": d["edge_or_blindspot"],
        },
        "depthTier": d["depth_tier"],
        "nLeagues": int(d["n_leagues"]),
        "nSeasons": int(d["n_seasons"]),
        "nTransactions": int(d["n_transactions"]),
        "confidenceNote": d["confidence_note"],
        "model": d["model"],
        "generatedAt": d["generated_at"],
    }


# ---------------------------------------------------------------------------
# League tab — the standings-backed race view + positional talent (market VOR).
# ---------------------------------------------------------------------------

def load_league(as_of_week=None) -> dict:
    """The League surface: full standings + the "me" row + the real playoff cut / team count.

    Light — wraps the already-ported ``load_standings(N)`` and one ``league_settings`` read.
    Mirrors loadLeague (l.370).
    """
    standings = load_standings(as_of_week)
    cfg_rows = db.fetch_all(
        "SELECT key, value FROM league_settings "
        "WHERE league_id = %(lid)s AND section = 'league' AND key IN ('playoff_teams', 'num_teams')",
        _params(),
    )
    cfg = {r["key"]: (None if r["value"] is None else float(r["value"])) for r in cfg_rows}
    return {
        "standings": standings,
        "me": next((s for s in standings if s["isMe"]), None),
        "playoffCut": calcs.js_round(cfg["playoff_teams"]) if cfg.get("playoff_teams") is not None else None,
        "nTeams": calcs.js_round(cfg["num_teams"]) if cfg.get("num_teams") is not None else len(standings),
    }


def load_positional_talent() -> dict:
    """Positional Talent: teams ranked per position by the Market VOR they hold (sum of positive
    ``market_vor`` at the latest snapshot). Not week-scoped. Mirrors loadPositionalTalent (l.396)."""
    me = settings.my_username()
    rows = db.fetch_all(
        "WITH latest AS ("
        "  SELECT roster_id, position,"
        "         sum(greatest(market_vor, 0)) AS pos_vor,"
        "         bool_or(is_cross_time)        AS is_cross_time"
        "  FROM market_vor"
        "  WHERE league_id = %(lid)s"
        "    AND snapshot_date = (SELECT max(snapshot_date) FROM market_vor WHERE league_id = %(lid)s)"
        "    AND position IN ('QB','RB','WR','TE')"
        "  GROUP BY roster_id, position"
        ") "
        "SELECT l.roster_id, l.position, l.pos_vor, l.is_cross_time, t.team_name, t.owner_name "
        "FROM latest l "
        "LEFT JOIN teams t ON t.roster_id = l.roster_id AND t.league_id = %(lid)s",
        _params(),
    )
    by_pos: dict[str, list] = {p: [] for p in POS}
    cross_time = False
    for r in rows:
        if r["is_cross_time"]:
            cross_time = True
        rid = int(r["roster_id"])
        by_pos.setdefault(r["position"], []).append({
            "rosterId": rid,
            "name": r["team_name"] or r["owner_name"] or f"Team {rid}",
            "isMe": r["owner_name"] == me,
            "vor": float(r["pos_vor"]),
        })
    for pos in POS:
        # Sort by VOR desc; roster_id breaks ties deterministically (cosmetic — the app ties
        # arbitrarily; see Session-3 audit finding 6).
        by_pos[pos].sort(key=lambda x: (-x["vor"], x["rosterId"]))
        for i, x in enumerate(by_pos[pos]):
            x["rank"] = i + 1
    return {"byPos": by_pos, "isCrossTime": cross_time}


# ---------------------------------------------------------------------------
# Matchups tab — the week-N+1 slate + one game's full breakdown. The projection
# math lives in projections.py (shared with team-detail's thisWeek bar).
# ---------------------------------------------------------------------------

def load_matchups(as_of_week=None) -> dict:
    """The Matchups slate: the upcoming week's head-to-head games. Mirrors loadMatchups (l.878)."""
    target_week = projections.target_week_for(as_of_week)
    sched_rows = []
    if target_week is not None:
        sched_rows = db.fetch_all(
            "SELECT roster_id, matchup_id FROM schedule "
            "WHERE league_id = %(lid)s AND week = %(tw)s ORDER BY matchup_id, roster_id",
            {"lid": settings.league_id(), "tw": target_week},
        )
    if not sched_rows:
        return {"targetWeek": target_week, "games": [], "myGameId": None, "empty": True}

    teams = projections.team_projections(as_of_week, target_week)
    week_rows = db.fetch_all(_sql_standings_weeks(as_of_week), _params(as_of_week))
    rec = projections.records_by_roster(week_rows)

    # Group roster ids by matchup (schedule ordered by matchup_id, roster_id → ascending ids,
    # first-seen order preserved for the within-game default sort before the win-prob sort).
    by_matchup: dict[int, list] = {}
    for s in sched_rows:
        by_matchup.setdefault(int(s["matchup_id"]), []).append(int(s["roster_id"]))

    games = []
    for mid, rids in by_matchup.items():
        sides = []
        for rid in rids:
            t = teams.get(rid) or {
                "rosterId": rid, "name": f"Team {rid}", "owner": None,
                "isMe": False, "mu": 0, "sigma": 0,
            }
            r = rec.get(rid, {"w": 0, "l": 0})
            sides.append({**t, "record": f"{r['w']}-{r['l']}"})
        probs = [None] * len(sides)
        if len(sides) == 2:
            probs = projections.matchup_win_probs(
                sides[0]["mu"], sides[0]["sigma"], sides[1]["mu"], sides[1]["sigma"]
            )
        out = [
            {
                "rosterId": s["rosterId"],
                "name": s["name"],
                "owner": s["owner"],
                "isMe": s["isMe"],
                "record": s["record"],
                "proj": s["mu"],
                "winProb": None if probs[i] is None else calcs.js_round(probs[i] * 100),
            }
            for i, s in enumerate(sides)
        ]
        # My team first, else higher win prob first (null win prob sorts as 0).
        out.sort(key=lambda t: (t["isMe"], t["winProb"] if t["winProb"] is not None else 0), reverse=True)
        games.append({"matchupId": mid, "teams": out, "isMine": any(t["isMe"] for t in out)})

    # My game first, else by matchup_id ascending.
    games.sort(key=lambda g: (not g["isMine"], g["matchupId"]))
    my_game_id = next((g["matchupId"] for g in games if g["isMine"]), None)
    return {"targetWeek": target_week, "games": games, "myGameId": my_game_id, "empty": False}


def load_matchup_detail(matchup_id, as_of_week=None):
    """One matchup's full breakdown: win prob, Score Range, per-starter gauges. Mirrors loadMatchupDetail (l.942)."""
    mid = int(matchup_id)
    target_week = projections.target_week_for(as_of_week)
    if target_week is None:
        return None

    teams = projections.team_projections(as_of_week, target_week)
    sched_rows = db.fetch_all(
        "SELECT roster_id FROM schedule "
        "WHERE league_id = %(lid)s AND week = %(tw)s AND matchup_id = %(mid)s ORDER BY roster_id",
        {"lid": settings.league_id(), "tw": target_week, "mid": mid},
    )
    week_rows = db.fetch_all(_sql_standings_weeks(as_of_week), _params(as_of_week))
    rids = [int(r["roster_id"]) for r in sched_rows]
    if len(rids) < 2 or rids[0] not in teams or rids[1] not in teams:
        return None
    rec = projections.records_by_roster(week_rows)

    sides = []
    for rid in rids:
        t = teams[rid]
        r = rec.get(rid, {"w": 0, "l": 0})
        # Team Score Range = Σ starters' quantiles; a starter without a projection falls back to
        # its μ term (p25 ?? pts) so the band stays coherent.
        p25 = sum((p["p25"] if p["p25"] is not None else p["pts"]) for p in t["starters"])
        p50 = sum((p["p50"] if p["p50"] is not None else p["pts"]) for p in t["starters"])
        p75 = sum((p["p75"] if p["p75"] is not None else p["pts"]) for p in t["starters"])
        sides.append({
            "rosterId": rid,
            "name": t["name"],
            "owner": t["owner"],
            "isMe": t["isMe"],
            "record": f"{r['w']}-{r['l']}",
            "proj": t["mu"],
            "sigma": t["sigma"],
            "range": {"p25": calcs.round1(p25), "p50": calcs.round1(p50), "p75": calcs.round1(p75)},
            "starters": [projections.matchup_player_view(p) for p in t["starters"]],
            "bench": [projections.matchup_player_view(p) for p in t["bench"]],
        })

    probs = projections.matchup_win_probs(
        sides[0]["proj"], sides[0]["sigma"], sides[1]["proj"], sides[1]["sigma"]
    )
    for i, s in enumerate(sides):
        s["winProb"] = calcs.js_round(probs[i] * 100)
    # "You" first, else higher win prob first.
    sides.sort(key=lambda s: (s["isMe"], s["winProb"]), reverse=True)

    return {"matchupId": mid, "targetWeek": target_week, "teams": sides}
