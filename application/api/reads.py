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

from application.api import calcs, db, settings

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
