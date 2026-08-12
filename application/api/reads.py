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

import logging

from application.api import calcs, db, projections, settings

POS = ["QB", "RB", "WR", "TE"]

_LOG = logging.getLogger(__name__)


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


def _as_of_pinned_to_production(n):
    """One as-of slice from a tall table, pinned to ``production_vor``'s week rather than its own.

    ``ros_player_band`` is NFL-global: it runs the whole projected season (as_of 1..17), while
    ``production_vor`` stops at the league's played weeks. Letting the band take its own max() would
    serve a week-17 row — nearly no schedule remaining, so a tiny centre — beside a week-5 VOR, and the
    two numbers are supposed to be the same quantity. Pin to the league's clock instead.
    (`ai/write_ros_synthesis._read_anchor` pins the same way, for the same reason.)
    """
    if n is None:
        return ("as_of_week = (SELECT max(as_of_week) FROM production_vor "
                "WHERE league_id = %(lid)s)")
    return "as_of_week = %(n)s"


def _require_league(lid):
    """The league id, or a loud failure — never a silent default (P5/S2b).

    Every loader used to open with ``lid = league_id or settings.league_id()``: a missing league
    quietly became *whichever league the owner's Sleeper credentials name*. That was harmless only
    because ``DEMO_LEAGUE_ID`` and ``SLEEPER_LEAGUE_ID`` are the same string today — and S2d
    repoints the demo at the anonymised clone, at which point every one of these paths would have
    started resolving to **Will's real, private league**. That is precisely the bug S2a's
    ``slice_params`` docstring claims to have fixed, re-entering by the back door with a date on it.

    Authorization now happens in ``authorize_slice``, which always returns a concrete id, so
    reaching here with ``None`` means a caller bypassed the seam. Fail loudly instead of serving
    somebody's league.
    """
    if lid is None:
        raise SliceUnavailable(
            "a read was called with no league_id — every read must come through authorize_slice")
    return lid


def _params(n=None, lid=None, **extra):
    """Base bind dict every query shares: league id + optional as-of week + extras.

    Callers resolve the league once and pass it here as ``lid``; it is required, for the reason
    ``_require_league`` explains.
    """
    p = {"lid": _require_league(lid), "n": n}
    p.update(extra)
    return p


# `slice_exists` lived here until P5/S2b. It read `demo_manifest`, which made *catalog membership*
# double as the authorization boundary — correct only by the coincidence that the manifest happens
# to hold exactly the demo set, and a coincidence that dies at S4 when a real user's league has data
# before it is catalogued. Existence now comes from `teams` inside `authorize_slice`'s single
# lookup. Deleted rather than left behind: a function named "exists" that used to mean "authorised"
# is the kind of thing a later session calls by its name.


def resolve_viewer(lid, viewer_roster_id=None):
    """The "you" roster for a league (Stage-B B5). Given ``viewer_roster_id`` → that roster; else
    resolve it from ``MY_USERNAME`` for this league exactly as today (the same teams lookup
    ``load_league_meta`` already does) → the is_mine default. Returns an ``int`` roster_id, or None
    when the viewer isn't in the league (→ no "me" highlight, same as today's owner-not-found).

    Parity: when ``viewer_roster_id`` is None this returns today's ``my_roster_id`` (roster 8 for the
    is_mine league = ``MY_USERNAME``'s roster), so the ``roster_id == viewer`` test yields the identical
    isMe set as the old ``owner_name == MY_USERNAME`` test."""
    if viewer_roster_id is not None:
        return int(viewer_roster_id)
    rows = db.fetch_all(
        "SELECT roster_id FROM teams WHERE league_id = %(lid)s AND owner_name = %(me)s",
        {"lid": lid, "me": settings.my_username()},
    )
    return int(rows[0]["roster_id"]) if rows else None


# ---------------------------------------------------------------------------
# Shared reads — weeks selector + league-meta chrome.
# ---------------------------------------------------------------------------

def load_weeks(league_id=None, season=None, viewer_roster_id=None) -> dict:
    """The league's weeks: every loaded one, which weeks actually have RESULTS, and the default (latest).

    ``weeks`` is every week in the store — it drives the week selector, which should still offer a week
    that has been loaded. ``played`` is the honest clock, and the two are NOT the same: a projections-only
    week (preseason, or kickoff before the stats land) is joined into ``season`` with ``sleeper_points``
    zero-FILLED rather than null, so counting loaded weeks reports "1 week of data" for a league that has
    played nothing. Derive played-ness from the points themselves — a week counts only if somebody scored —
    so preseason reads as 0 weeks no matter what has been joined.

    (``viewer_roster_id`` accepted for a uniform slice signature; weeks have no "me" flag.)
    """
    lid = _require_league(league_id)
    rows = db.fetch_all(
        "SELECT week, max(coalesce(roster_total_points, 0)) AS pts FROM season "
        "WHERE league_id = %(lid)s GROUP BY week ORDER BY week",
        _params(lid=lid),
    )
    weeks = [int(r["week"]) for r in rows]
    played = [int(r["week"]) for r in rows if float(r["pts"] or 0) > 0]
    return {"weeks": weeks, "played": played, "latest": weeks[-1] if weeks else None}


def load_league_meta(as_of_week=None, league_id=None, season=None, viewer_roster_id=None) -> dict:
    """Top-bar chrome: "10-tm · PPR · 1QB" label + the user's record. Mirrors loadLeagueMeta (l.659)."""
    lid = _require_league(league_id)
    viewer = resolve_viewer(lid, viewer_roster_id)
    p = _params(as_of_week, lid=lid)
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
        # The viewer's team row (record + "myOwner" chrome), keyed on the resolved viewer roster
        # (= MY_USERNAME's roster by default). `roster_id = NULL` matches nothing when the viewer
        # isn't in the league — same as today's owner-not-found.
        me_rows = q(
            "SELECT roster_id, owner_name FROM teams "
            "WHERE league_id = %(lid)s AND roster_id = %(viewer)s",
            {"viewer": viewer},
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

        # The user's record as of week N (one W/L/T per team-week; NULL where the week has no
        # gradeable matchup, which the FILTERs drop from every bucket — see _sql_standings_weeks).
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
                "       count(*) FILTER (WHERE result = 'L') AS l,"
                "       count(*) FILTER (WHERE result = 'T') AS t "
                "FROM tw WHERE roster_id = %(rid)s",
                {"rid": my_roster_id},
            )
            if rows and rows[0]["w"] is not None:
                record = calcs.format_record(rows[0]["w"], rows[0]["l"], rows[0]["t"])

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


def load_players(as_of_week=None, league_id=None, season=None, viewer_roster_id=None) -> list[dict]:
    """The Players table: rostered skill players priced by PROD VOR. Mirrors loadPlayers (l.87)."""
    lid = _require_league(league_id)
    viewer = resolve_viewer(lid, viewer_roster_id)
    rows = db.fetch_all(_sql_players(as_of_week), _params(as_of_week, lid=lid))
    return [
        {
            "sleeperId": r["sleeper_id"],
            "name": r["name"],
            "pos": r["position"],
            "nflTeam": r["nfl_team"] if r["nfl_team"] is not None else None,
            "rosterId": int(r["roster_id"]),
            "teamName": r["team_name"] or r["owner_name"] or None,
            "isMe": int(r["roster_id"]) == viewer,
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


def load_player_card(sleeper_id, as_of_week=None, league_id=None, season=None,
                     viewer_roster_id=None) -> dict:
    """The full player card (Value·VOR + Opportunity + ROS shape). Mirrors loadPlayerCard (l.120)."""
    lid = _require_league(league_id)
    viewer = resolve_viewer(lid, viewer_roster_id)
    p = _params(as_of_week, lid=lid, sid=str(sleeper_id))
    prod_cutoff = "TRUE" if as_of_week is None else "as_of_week <= %(n)s"

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
        band_rows = q(
            "SELECT ros_center, ros_bull, ros_bear, ros_sigma, n_weeks, in_calibrated_pool "
            "FROM ros_player_band WHERE league_id = %(lid)s AND sleeper_player_id = %(sid)s "
            "AND " + _as_of_pinned_to_production(as_of_week)
        )
        team_rows = q("SELECT roster_id, team_name, owner_name FROM teams WHERE league_id = %(lid)s")

    ident = ident_rows[0] if ident_rows else None
    if ident is None and not prod_rows:
        return {"missing": True}

    # Identity + roster status.
    roster_id = int(ident["roster_id"]) if ident and ident["roster_id"] is not None else None
    team_by_id = {int(t["roster_id"]): t for t in team_rows}
    my_team = team_by_id.get(roster_id)
    on_yours = roster_id is not None and roster_id == viewer
    if on_yours:
        status = "On your roster"
    elif my_team:
        status = f"Rostered · {my_team['team_name'] or my_team['owner_name']}"
    else:
        status = "Rostered"

    # Value·VOR series (oldest -> newest) + value/delta.
    prod = calcs.series_read([float(r["vor"]) for r in prod_rows])
    mkt = calcs.series_read([float(r["market_vor"]) for r in mkt_rows])
    # The requested (or latest) week's ROS points — prod_rows is ordered ascending under the same cutoff,
    # so [-1] is the week `series_read` reports as `value`. Nullable column, hence calcs.num.
    ros_points = calcs.num(prod_rows[-1]["ros_value"]) if prod_rows else None

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

    # Opportunity axes (player_signal). Two fields are withheld on a thin sample rather than stated —
    # law 2's "a missing signal is reported as null, never fabricated". The threshold isn't invented here:
    # `low_sample` is the engine's own (games < MIN_GAMES or no opportunity).
    #   * trustDir — `_direction` returns the string "steady" at n < 2, which is indistinguishable from a
    #     genuine flat trend and is the one player_signal field with no null option of its own. It is also
    #     in NO_CONFIDENCE_FAMILIES, so nothing downstream flags it.
    #   * regressionRisk — the one player_signal confidence the trust report grades honest, BUT it computes
    #     to 0.0 with no realized points, and under strength "neg" that reads as MAXIMUM confidence. Serving
    #     it early would state the opposite of the truth, so it is withheld exactly where it inverts.
    # `games` ships unconditionally: the sample size is a fact, and stating N is the honest alternative to
    # asserting a confidence the engine has never measured.
    s = sig_rows[0] if sig_rows else None
    thin = bool(s["low_sample"]) if s else False
    opportunity = (
        {
            "qualityRate": calcs.num(s["quality_rate"]),
            "effRatio": calcs.num(s["eff_ratio"]),
            "volumePct": calcs.num(s["opp_pct"]),
            "oppG": calcs.num(s["opp_g"]),
            "trustDir": (s["direction"] if s["direction"] is not None else None) if not thin else None,
            "reliability": calcs.num(s["reliability"]),
            "pointCorr": calcs.num(s["point_correlation"]),
            "regressionRisk": calcs.num(s["regression_risk"]) if not thin else None,
            "games": calcs.num(s["games"]),
            "luck": calcs.num(s["luck"]),
            "recentPpg": calcs.num(s["recent_ppg"]),
            "expectedPpg": calcs.num(s["expected_ppg"]),
            "read": s["read"] if s["read"] is not None else None,
            "security": s["security"] if s["security"] is not None else None,
            "lowSample": thin,
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

    # Rest-of-season range (ros_player_band) — the DETERMINISTIC band, a different object from the AI
    # `ros` block above: calibrated points, always available where the season's band is honest, null on
    # the frozen 2020-2025 seasons (build_db.FIRST_HONEST_BAND_SEASON keeps those out of the store).
    # No confidence label: the band's WIDTH is its confidence (law 2), and the percentage `ros_cv` that
    # would have supplied one was measured INVERTED in S5 and retired to an audit column in 8c.
    b = band_rows[0] if band_rows else None
    ros_range = (
        {
            "center": calcs.num(b["ros_center"]),
            "bull": calcs.num(b["ros_bull"]),
            "bear": calcs.num(b["ros_bear"]),
            "sigma": calcs.num(b["ros_sigma"]),
            "weeks": calcs.num(b["n_weeks"]),
            "calibrated": bool(b["in_calibrated_pool"]),
        }
        if b
        else None
    )

    return {
        "sleeperId": sleeper_id,
        "name": ident["name"] if ident and ident["name"] is not None else sleeper_id,
        "pos": ident["position"] if ident else None,
        "nflTeam": ident["nfl_team"] if ident else None,
        "status": status,
        "onYours": on_yours,
        # rosPoints = production_vor.ros_value, the ROS points `vor` is the normalised form of. It is the
        # SAME number as rosRange.center by construction — the band imports _ros_values rather than
        # re-deriving it — so surfacing it makes that identity visible on the card, not just provable.
        "prod": {**prod, "rosPoints": ros_points},
        "mkt": {**mkt, "crossTime": cross_time},
        "lean": lean,
        "opportunity": opportunity,
        "ros": ros,
        "rosRange": ros_range,
    }


# ---------------------------------------------------------------------------
# Teams tab — the standings table + team detail + manager dossier.
# ---------------------------------------------------------------------------

# One row per (team, week): total points + W/L/T, weeks <= N. Feeds the real record and the
# all-play "true record". any_value(col) -> max(col) (the value is constant per team-week).
#
# The max() is load-bearing in two ways now that `matchup_result` is four-valued. It is still a true
# any_value — `transforms/_matchup` grades a whole matchup at once, so every row of a team-week carries
# the same verdict and the lexicographic order ('W' > 'T' > 'L') never gets to matter. And Postgres
# max() SKIPS nulls, returning NULL only when every row is NULL — which is exactly the ungraded week
# (unplayed / bye / no matchup_id). So an ungraded week arrives as `result IS NULL` and falls through
# every branch downstream, counting nowhere, which is the intended behaviour rather than a coincidence.
# (One caveat this also absorbs: `audit_join`'s repair rows carry a null result on an otherwise graded
# team-week; max() ignores them and the real verdict still wins.)
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


def load_standings(as_of_week=None, league_id=None, season=None, viewer_roster_id=None) -> list[dict]:
    """The Teams standings: record + all-play + playoff odds/series. Mirrors loadStandings (l.278).

    No `posture` since P5/S2e — see the note at the row build below.
    """
    lid = _require_league(league_id)
    viewer = resolve_viewer(lid, viewer_roster_id)
    p = _params(as_of_week, lid=lid)
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
    # The record tally lives in projections.records_by_roster — one home, so a tie can't reach the
    # matchup surfaces and not the standings.
    record = projections.records_by_roster(team_weeks)
    by_week: dict[int, list] = {}
    for r in team_weeks:
        by_week.setdefault(int(r["week"]), []).append(
            {"rosterId": int(r["roster_id"]), "pts": float(r["pts"]), "result": r["result"]}
        )

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
        rec = record.get(rid, projections.EMPTY_RECORD)
        last = o["last"] if o else None
        playoff_pct = float(last["playoff_odds"]) * 100 if last and last["playoff_odds"] is not None else None
        all_play_pct = (ap["w"] / (ap["w"] + ap["l"])) * 100 if (ap["w"] + ap["l"]) else 0
        out.append({
            "rosterId": rid,
            "name": (t["team_name"] or t["owner_name"] or f"Team {rid}") if t else f"Team {rid}",
            "owner": t["owner_name"] if t else None,
            "isMe": rid == viewer,
            "wins": rec["w"],
            "losses": rec["l"],
            "ties": rec["t"],
            # The rendered string, built server-side so all five record surfaces share one formatter.
            # `wins`/`losses` stay in the payload: they are a different fact (a count, not a label).
            "record": calcs.format_record(rec["w"], rec["l"], rec["t"]),
            "allPlayW": ap["w"],
            "allPlayL": ap["l"],
            "playoffPct": playoff_pct,
            "allPlayPct": all_play_pct,
            "seed": calcs.js_round(float(last["avg_seed"])) if last and last["avg_seed"] is not None else None,
            "magicWins": int(last["magic_wins"]) if last and last["magic_wins"] is not None else None,
            "remainingGames": int(last["remaining_games"]) if last and last["remaining_games"] is not None else None,
            "oddsSeries": o["series"] if o else [],
            # `posture` is WITHHELD as of P5/S2e — the key is absent, not null, because we are not
            # failing to compute it, we are declining to serve it. `calcs.derive_posture` stays put
            # for the session that fixes the metric.
            #
            # Measured 2026-08-12 on the live demo, and it is inverted for EVERY league, not just
            # this one: `gap = all_play_pct - playoff_odds_pct` compares two quantities that are not
            # the same unit — odds saturate toward 0 and 100 while all-play compresses toward 50 —
            # so the gap tracks the shape of the odds curve rather than luck. With BAND = 9 and the
            # smallest |gap| in the league at 12.0, every team read Riding luck or Unlucky,
            # Contender/Rebuild/On pace were unreachable, and the highest all-play team in the
            # league was labelled sell. That is a correctness defect, not a calibration one, so
            # retuning BAND cannot fix it and this is a withholding rather than a retune.
            #
            # One line closes it everywhere: this is derive_posture's only caller, and it reaches
            # both /api/standings and /api/league (which nests the same object again under `me`).
            # It also retires a latent — nothing here gates on season shape, so an all-play record
            # of 0/0 coerces to 0 above and manufactured "Riding luck" at week 0/1; only the
            # client's `hasShape` was holding that back, and two colour sites bypassed it.
        })

    # Rank by playoff odds desc (nulls -> -1), then all-play % as the tiebreak.
    out.sort(key=lambda r: (r["playoffPct"] if r["playoffPct"] is not None else -1, r["allPlayPct"]), reverse=True)
    for i, r in enumerate(out):
        r["rank"] = i + 1
    return out


def load_team_detail(roster_id, as_of_week=None, league_id=None, season=None, viewer_roster_id=None):
    """Team detail: stat blocks, positional depth, roster split. Mirrors loadTeamDetail (l.448).

    The ``thisWeek`` projection/win-prob bar (opponent + both projected totals + win %) comes
    from the shared engine's ``team_matchup_summary`` (Session 4) — ``None`` when there is no
    next game.
    """
    lid = _require_league(league_id)
    viewer = resolve_viewer(lid, viewer_roster_id)
    rid = int(roster_id)
    p = _params(as_of_week, lid=lid, rid=rid)
    prod_cutoff = "TRUE" if as_of_week is None else "as_of_week <= %(n)s"

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
    team_by_id = {int(t["roster_id"]): t for t in team_rows}
    me_team = team_by_id.get(rid)
    if me_team is None and not roster_rows:
        return None

    # Record + all-play + points-for, from the team-week scores.
    by_week: dict[int, list] = {}
    for r in team_weeks:
        by_week.setdefault(int(r["week"]), []).append(
            {"rosterId": int(r["roster_id"]), "pts": float(r["pts"]), "result": r["result"]}
        )
    rec = projections.records_by_roster(team_weeks).get(rid, projections.EMPTY_RECORD)
    # Points/week averages over GRADED weeks only. An ungraded week (unplayed, bye, no matchup_id)
    # contributes 0.0 points and would otherwise drag the average down — a freshly drafted league,
    # whose whole slate is joined at 0.0 from the draft on, rendered "Pts/Wk 0.0". Same class of
    # fabrication as the phantom W/L this fix removes, so it is gated on the same signal.
    pts_for = 0.0
    games = 0
    for rows in by_week.values():
        mine = next((x for x in rows if x["rosterId"] == rid), None)
        if mine is None or mine["result"] is None:
            continue
        games += 1
        pts_for += mine["pts"]
    ap = _all_play_record(by_week, rid)

    odds = odds_rows[0] if odds_rows else None
    stats = {
        "record": calcs.format_record(rec["w"], rec["l"], rec["t"]),
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
        "onYours": rid == viewer,
        "stats": stats,
        "thisWeek": projections.team_matchup_summary(rid, as_of_week, lid=lid),
        "depth": depth,
        "roster": {"starters": starters, "bench": bench},
    }


def load_manager_dossier(roster_id, league_id=None, season=None, viewer_roster_id=None) -> dict:
    """The Manager Dossier for one roster — a clean 1:1 passthrough. Mirrors loadManagerDossier (l.583).
    (``viewer_roster_id`` accepted for a uniform slice signature; the dossier has no "me" flag.)"""
    lid = _require_league(league_id)
    rows = db.fetch_all(
        "SELECT owner_name, team_name, headline, waiver_faab, trade_tendency, positional_lean,"
        "       roster_construction, edge_or_blindspot, confidence_note, depth_tier,"
        "       n_leagues, n_seasons, n_transactions, is_zero_signal, model, generated_at "
        "FROM manager_dossiers WHERE league_id = %(lid)s AND roster_id = %(rid)s",
        _params(lid=lid, rid=int(roster_id)),
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

def load_league(as_of_week=None, league_id=None, season=None, viewer_roster_id=None) -> dict:
    """The League surface: full standings + the "me" row + the real playoff cut / team count.

    Light — wraps the already-ported ``load_standings(N)`` and one ``league_settings`` read.
    Mirrors loadLeague (l.370).
    """
    lid = _require_league(league_id)
    standings = load_standings(as_of_week, league_id=lid, season=season, viewer_roster_id=viewer_roster_id)
    cfg_rows = db.fetch_all(
        "SELECT key, value FROM league_settings "
        "WHERE league_id = %(lid)s AND section = 'league' AND key IN ('playoff_teams', 'num_teams')",
        _params(lid=lid),
    )
    cfg = {r["key"]: (None if r["value"] is None else float(r["value"])) for r in cfg_rows}
    return {
        "standings": standings,
        "me": next((s for s in standings if s["isMe"]), None),
        "playoffCut": calcs.js_round(cfg["playoff_teams"]) if cfg.get("playoff_teams") is not None else None,
        "nTeams": calcs.js_round(cfg["num_teams"]) if cfg.get("num_teams") is not None else len(standings),
    }


def load_positional_talent(league_id=None, season=None, viewer_roster_id=None) -> dict:
    """Positional Talent: teams ranked per position by the Market VOR they hold (sum of positive
    ``market_vor`` at the latest snapshot). Not week-scoped. Mirrors loadPositionalTalent (l.396)."""
    lid = _require_league(league_id)
    viewer = resolve_viewer(lid, viewer_roster_id)
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
        _params(lid=lid),
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
            "isMe": rid == viewer,
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

def load_matchups(as_of_week=None, league_id=None, season=None, viewer_roster_id=None) -> dict:
    """The Matchups slate: the upcoming week's head-to-head games. Mirrors loadMatchups (l.878)."""
    lid = _require_league(league_id)
    viewer = resolve_viewer(lid, viewer_roster_id)
    target_week = projections.target_week_for(as_of_week, lid=lid)
    sched_rows = []
    if target_week is not None:
        sched_rows = db.fetch_all(
            "SELECT roster_id, matchup_id FROM schedule "
            "WHERE league_id = %(lid)s AND week = %(tw)s AND matchup_id IS NOT NULL "
            "ORDER BY matchup_id, roster_id",
            {"lid": lid, "tw": target_week},
        )
    if not sched_rows:
        return {"targetWeek": target_week, "games": [], "myGameId": None, "empty": True}

    teams = projections.team_projections(as_of_week, target_week, lid=lid, viewer=viewer)
    week_rows = db.fetch_all(_sql_standings_weeks(as_of_week), _params(as_of_week, lid=lid))
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
            r = rec.get(rid, projections.EMPTY_RECORD)
            sides.append({**t, "record": calcs.format_record(r["w"], r["l"], r["t"])})
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


def load_matchup_detail(matchup_id, as_of_week=None, league_id=None, season=None, viewer_roster_id=None):
    """One matchup's full breakdown: win prob, Score Range, per-starter gauges. Mirrors loadMatchupDetail (l.942)."""
    lid = _require_league(league_id)
    viewer = resolve_viewer(lid, viewer_roster_id)
    mid = int(matchup_id)
    target_week = projections.target_week_for(as_of_week, lid=lid)
    if target_week is None:
        return None

    teams = projections.team_projections(as_of_week, target_week, lid=lid, viewer=viewer)
    sched_rows = db.fetch_all(
        "SELECT roster_id FROM schedule "
        "WHERE league_id = %(lid)s AND week = %(tw)s AND matchup_id = %(mid)s ORDER BY roster_id",
        {"lid": lid, "tw": target_week, "mid": mid},
    )
    week_rows = db.fetch_all(_sql_standings_weeks(as_of_week), _params(as_of_week, lid=lid))
    rids = [int(r["roster_id"]) for r in sched_rows]
    if len(rids) < 2 or rids[0] not in teams or rids[1] not in teams:
        return None
    rec = projections.records_by_roster(week_rows)

    sides = []
    for rid in rids:
        t = teams[rid]
        r = rec.get(rid, projections.EMPTY_RECORD)
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
            "record": calcs.format_record(r["w"], r["l"], r["t"]),
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


# ---------------------------------------------------------------------------
# Catalog — the lineage -> seasons -> slice tree (Stage-B B3; the B5 switcher reads this).
# ---------------------------------------------------------------------------

def _market_panel(panels_market, cross_time_by: dict, league_id: str) -> bool:
    """Whether the market panel may render for a slice — the manifest flag AND the read's honesty.

    ``demo_manifest.panels_market`` is STRUCTURAL: "this slice has a market_vor read at all". It stays
    that way on purpose — ``build_db._ref()`` picks its --emit schema reference via
    ``is_mine & panels_market``, and ``compute_demo_slices`` existence-checks it, so flipping the
    column would break the loader, not just the UI.

    The honesty term is the read's own ``is_cross_time``: a cross-time slice priced this season's
    roster with a DIFFERENT season's market (2025 production x 2026 prices), which is a POC, not a
    live trade call. BUILD_ORDER's locked policy is "never show the old cross-time POC" — so the
    panel gates OFF whenever the read is cross-time, and turns back on by itself when the read
    becomes contemporaneous (production season == market season). A slice with the flag set but no
    market_vor rows at all gates off too — a panel with nothing behind it is not a panel.
    """
    if not panels_market:
        return False
    cross_time = cross_time_by.get(league_id)
    return cross_time is False


_OWNED_LEAGUES = "SELECT league_id, roster_id FROM public.user_leagues WHERE user_id = %(uid)s"


def owned_seats(user_id) -> dict:
    """``{league_id: roster_id or None}`` for one account. Empty for an anonymous caller.

    Read per request rather than carried in the token: a revoke has to bite immediately, and a
    grant baked into a JWT would keep working for the hour until it expired.

    Returns the seat alongside the id (P5/S2b) because the catalog has to *hand the client* the
    right roster. Membership tests still work on it unchanged — ``x in owned`` reads the keys.
    """
    if not user_id:
        return {}
    return {str(r["league_id"]): r["roster_id"]
            for r in db.fetch_all(_OWNED_LEAGUES, {"uid": str(user_id)})}


def visible(league_id, season, *, demo_league_id, owned, current_season) -> bool:
    """THE visibility predicate (P5/S2a) — one function, so there is one place to get it wrong.

        visible(league) = (league_id == DEMO_LEAGUE_ID) OR (owned by caller AND season == current)

    **The demo term comes first and is season-independent, deliberately.** The demo is a 2025
    league living in the 2026 season; written as a global ``season = current`` filter it would
    vanish, and a missing demo reads as an auth bug rather than as the filter it actually is.

    **An unresolvable ``current_season`` denies the owned term.** That is the predicate's contract,
    stated in its signature rather than inferred from today's callers: it stays total for every
    input, and the deny direction is the safe one. No live caller can pass ``None`` since S2c made
    the season a local derivation — but "unreachable" is a claim about every caller, and this
    function is pure, public and freshly acquired eleven call sites. Two lines are cheaper than
    being wrong about that, and the alternative is not even a clean error: ``int(None)`` raises
    *inside an authorization predicate*, which is a 500 on a read.

    **Both sides of the ownership test are normalised to text (P5/S2b).** The row's ``league_id``
    was already stringified; the ``owned`` members were not, so an int-typed set silently matched
    nothing. No live caller did that — ``owned_league_ids`` builds strings — but S2a's audit (F4)
    flagged it as a trap laid for exactly this session, which gives the function eleven new call
    sites. It stays fail-closed either way: the bug loses a user their own league, it never hands
    anyone someone else's.
    """
    owned = {str(x) for x in owned}
    if demo_league_id is not None and str(league_id) == str(demo_league_id):
        return True
    if str(league_id) not in owned:
        return False
    if current_season is None:
        return False
    return int(season) == int(current_season)


class SliceRefused(Exception):
    """This caller may not have this slice — **or it does not exist**. Deliberately one exception.

    The two cases are indistinguishable on purpose and the route turns both into the identical
    404. A 403 (or a different message, or a different body length) would confirm that a league
    exists, and Sleeper ids are guessable, so a refusal that varies is an enumeration oracle.
    Keeping it one exception type means there is no branch that *could* drift apart.
    """


class SliceUnavailable(Exception):
    """The store cannot answer for this slice — a deploy or data problem, not a caller problem.

    Kept separate from ``SliceRefused`` because collapsing them would hide a broken deployment
    behind an authorization message: every read would answer "unknown league_id" and look exactly
    like someone probing. Surfaced as a 503, the same split S1 drew between "bad credential" (401)
    and "verifier unreachable" (503).
    """


# ONE round trip, and every subquery runs regardless of the outcome — that is what makes the work
# symmetric. A nonexistent league and an existing-but-unowned one cost the same lookups, so the
# response time cannot leak what the status code deliberately does not.
#
# Existence + season come from `teams`, NOT `demo_manifest`. `slice_exists` used to read the
# manifest, which made catalog membership double as the authorization boundary — true only by the
# coincidence that the manifest currently holds exactly the demo set. That coincidence dies at S4,
# when a real user's league has data long before it is catalogued. Verified the swap is
# behaviour-identical today: both tables hold the same 31 league_ids, each with exactly one season,
# and `check_isolation` asserts that agreement so it stays a property rather than a measurement.
_SLICE_LOOKUP = """
SELECT (SELECT count(DISTINCT season) FROM teams WHERE league_id = %(lid)s)::int AS n_seasons,
       (SELECT min(season) FROM teams WHERE league_id = %(lid)s)::int            AS season,
       (SELECT count(*) FROM public.user_leagues
         WHERE user_id = %(uid)s::uuid AND league_id = %(lid)s)::int             AS owned,
       (SELECT roster_id FROM public.user_leagues
         WHERE user_id = %(uid)s::uuid AND league_id = %(lid)s)                  AS grant_roster
"""

_ROSTER_IN_LEAGUE = """
SELECT 1 FROM teams WHERE league_id = %(lid)s AND roster_id = %(rid)s LIMIT 1
"""

# Denied reads, counted and never acted on (P5/S2b, settled with Will 2026-08-11). No cap and no
# blocking: blind enumeration of 19-digit ids is implausible, the realistic attacker knows one id
# and needs one request, and a limiter keyed on caller-supplied input is the S1b bug. It is an
# in-process integer rather than a row because a DB write on an unauthenticated path is
# attacker-triggerable write amplification — and because a counter that fired on *unowned* but not
# on *nonexistent* would rebuild the very timing oracle the single lookup above exists to prevent.
# Both refusal branches increment it identically.
#
# READ IT AS A FLOOR (S2c audit). It is per-PROCESS and there are TWO Fly machines (measured
# 2026-08-11, `fly scale show`), so this number is roughly half the real total and which half
# depends on routing. That is a consequence of the in-process decision above, not a defect in it —
# but a counter nobody knows is halved is a number that will eventually be quoted as if it weren't.
_denied_reads = 0


def denied_reads() -> int:
    """Slice requests refused since this process started — a FLOOR: per-process, and two machines run."""
    return _denied_reads


def slice_lookup(league_id, user_id) -> dict:
    """Existence, season, ownership and the granted seat for one league — in one query."""
    rows = db.fetch_all(_SLICE_LOOKUP, {"lid": str(league_id), "uid": user_id})
    return rows[0]


def roster_in_league(league_id, roster_id) -> bool:
    """Whether a roster actually sits in a league. Only ever called on an ALREADY-visible slice."""
    return bool(db.fetch_all(_ROSTER_IN_LEAGUE, {"lid": str(league_id), "rid": int(roster_id)}))


def authorize_slice(league_id, season, viewer_roster_id, *, user_id, demo_league_id,
                    lookup=None, current_season_fn=None, roster_exists=None) -> dict:
    """THE authorization seam (P5/S2b) — every read passes through here, exactly once.

    Returns the kwargs dict the eleven ``load_*`` functions take, or raises. Kept **pure and
    injectable** rather than written inline in the FastAPI dependency, for one concrete reason:
    ``check_ownership`` is a usable gate because ``visible``/``build_catalog`` can be driven from
    fixtures with no server and no accounts. Burying this logic in a dependency would have made the
    isolation matrix runnable only against two live accounts — and a check that needs a fixture of
    that size stops being run. ``slice_params`` is the thin adapter that turns these exceptions
    into HTTP.

    **The season is resolved LAST, and only when it can still change the answer.** ``visible``
    short-circuits: the demo is allowed without a season, an unowned league is refused without one,
    which is also what keeps the two refusal branches timing-identical.

    That ordering was written when resolving the season meant a network call, and S2b's audit was
    right that it narrowed audit F6 without fixing it. **S2c fixed it at the source** — the season
    is now a local derivation from the calendar, with no I/O to be slow — so the ordering here is
    no longer load-bearing for latency. It stays because the timing symmetry of the two refusals
    still is.
    """
    global _denied_reads
    lookup = lookup or slice_lookup
    current_season_fn = current_season_fn or settings.current_season
    roster_exists = roster_exists if roster_exists is not None else roster_in_league

    # Default resolution, not authorization — the predicate still runs on the result below.
    lid = league_id if league_id is not None else demo_league_id
    if lid is None:
        raise SliceUnavailable("DEMO_LEAGUE_ID is unset, so there is no default slice to serve")

    info = lookup(lid, user_id)
    exists = int(info["n_seasons"] or 0) >= 1
    owned = bool(info["owned"])
    is_demo = demo_league_id is not None and str(lid) == str(demo_league_id)

    if exists and int(info["n_seasons"]) > 1:
        # A redraft league_id pins exactly one (league, season) slice. More than one means the
        # store is wrong, and guessing which season to authorize against would be worse than
        # refusing to answer.
        raise SliceUnavailable(f"league {lid} has {info['n_seasons']} seasons in `teams`")
    if is_demo and not exists:
        # The configured public league has no data. That is a deploy failure, and answering
        # "unknown league_id" would disguise it as a caller problem for as long as nobody checks.
        raise SliceUnavailable(f"the demo league {lid} has no rows in `teams`")

    # `visible` is still THE predicate; the two short-circuits above it are only there so the
    # season lookup happens last. They re-test what `visible` re-tests, which is cheap and keeps
    # the season term in exactly one place.
    if is_demo:
        allowed = True
    elif not exists or not owned:
        allowed = False
    else:
        allowed = visible(lid, info["season"], demo_league_id=demo_league_id,
                          owned={str(lid)}, current_season=current_season_fn())

    if not allowed:
        _denied_reads += 1
        _LOG.info("slice refused (league_id=%s, signed_in=%s, exists=%s, owned=%s) — refusals "
                  "since boot: %d", lid, bool(user_id), exists, owned, _denied_reads)
        raise SliceRefused(lid)

    # The seat, resolved ONCE here rather than per-loader. Precedence: what the caller asked for,
    # then the seat their grant records, then `MY_USERNAME` (left to `resolve_viewer`, which is
    # what preserves the demo's behaviour exactly). Caller-supplied wins on purpose — viewing your
    # own league "as" another manager is a feature the dossiers depend on; reaching into a league
    # you cannot see was the bug, and that was settled two branches ago.
    seat = viewer_roster_id
    if seat is not None:
        # Strictly AFTER the visibility decision: run earlier, this would answer "is roster N in
        # league X" for leagues the caller cannot see — a roster-existence oracle.
        if not roster_exists(lid, seat):
            _denied_reads += 1
            _LOG.info("slice refused (league_id=%s, bad viewer_roster_id=%s)", lid, seat)
            raise SliceRefused(lid)
        seat = int(seat)
    elif owned and info.get("grant_roster") is not None:
        seat = int(info["grant_roster"])

    return {"league_id": str(lid), "season": season, "viewer_roster_id": seat}


def build_catalog(rows, weeks_by, cross_time_by, *, demo_league_id, owned, current_season) -> dict:
    """Shape + filter + order the catalog. Pure, so ``check_ownership`` can drive it with fixtures.

    Ordering is not cosmetic: the SPA lands on ``leagues[0]`` and its latest season, so **a
    caller's own leagues come first and the demo last** is what makes a signed-in user with a
    league land on THEIR league instead of the demo. Seasons stay DESC for the same reason.
    """
    # `owned` is a {league_id: roster_id} map in production and may be a bare set of ids in a
    # fixture; normalise so the seat lookup below works either way.
    seats = owned if isinstance(owned, dict) else {str(x): None for x in owned}

    lineages: dict = {}
    order: list = []
    owned_lineages: set = set()
    for r in rows:
        if not visible(r["league_id"], r["season"], demo_league_id=demo_league_id,
                       owned=owned, current_season=current_season):
            continue
        key = r["lineage_id"]
        if key not in lineages:
            lineages[key] = {
                "lineage_id": r["lineage_id"],
                "name": r["name"],
                "scoring_key": r["scoring_key"],
                "is_mine": bool(r["is_mine"]),
                "seasons": [],
            }
            order.append(key)
        if str(r["league_id"]) in owned:
            owned_lineages.add(key)
        # The seat the CALLER should occupy, which is why this is a user × league property now
        # (P5/S2b). Their grant wins over the manifest's league-wide default; without this the
        # `roster_id` column could never take effect through the UI, because the client sends back
        # whatever the catalog told it and `authorize_slice` honours a caller-supplied seat.
        seat = seats.get(str(r["league_id"]))
        if seat is None:
            seat = r["viewer_roster_id"]
        lineages[key]["seasons"].append({
            "season": int(r["season"]),
            "league_id": r["league_id"],
            "weeks_available": weeks_by.get((r["league_id"], int(r["season"])), []),
            "viewer_roster_id": int(seat) if seat is not None else None,
            "panels": {
                "market": _market_panel(r["panels_market"], cross_time_by, r["league_id"]),
                "manager": bool(r["panels_manager"]),
                "ros_synthesis": bool(r["panels_ros"]),
            },
        })

    leagues = [lineages[k] for k in order]
    # Owned first, everything else (i.e. the demo) last; stable within each group. Replaces the
    # is_mine-first sort, which was a stand-in for "the viewer's league" back when there was only
    # one viewer. A lineage that is BOTH owned and the demo counts as owned — it is your league.
    leagues.sort(key=lambda lg: lg["lineage_id"] not in owned_lineages)

    if not leagues:
        # The SPA's only applySlice call is guarded by `if (lgs.length)`, so an empty catalog is
        # not a blank slate — it is a permanent "Loading…" with no error state. The demo term is
        # supposed to make this unreachable, so reaching it means DEMO_LEAGUE_ID is unset or is
        # missing from league_catalog. Loud, because the symptom is silent.
        _LOG.error("EMPTY league catalog — demo_league_id=%r is unset or absent from "
                   "league_catalog. The app will hang on 'Loading…' for every visitor.",
                   demo_league_id)
    return {"leagues": leagues}


def load_leagues(user_id=None) -> dict:
    """The catalog, scoped to the caller (P5/S2a): the demo always, plus their own current-season
    leagues. Signed out (``user_id`` None) that is the demo alone.

    Was the one deliberately unscoped read, and it is the right first thing to close: it is the
    list every other surface is navigated from, and until S2b scopes the individual panels it is
    also the only thing standing between a visitor and the knowledge that 31 leagues exist.

    ``weeks_available`` is derived at query time from the loaded ``season`` (the PLAYED weeks — the
    same source ``load_weeks`` uses — so a frozen slice like is_mine 2025 reports [1..4], not the
    schedule's full forward [1..18]). Name + viewer mirror the manifest exactly. Shape is unchanged
    from the B3 contract; only the row set and the ordering move.

    ``panels.market`` is the ONE flag not taken straight from the manifest — see ``_market_panel``.
    """
    demo_league_id = settings.demo_league_id()
    current_season = settings.current_season()
    owned = owned_seats(user_id)

    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT lineage_id, league_id, season, name, scoring_key, is_mine, "
            "viewer_roster_id, panels_market, panels_manager, panels_ros "
            "FROM league_catalog ORDER BY lineage_id, season DESC"
        )
        rows = cur.fetchall()
        cur.execute(
            "SELECT league_id, season, array_agg(DISTINCT week ORDER BY week) AS weeks "
            "FROM season GROUP BY league_id, season"
        )
        weeks_by = {(w["league_id"], int(w["season"])): [int(x) for x in w["weeks"]]
                    for w in cur.fetchall()}
        # The honesty term for panels.market. NULL (a league whose rows all state nothing) counts as
        # cross-time — unknown provenance gates OFF, it never gates on.
        cur.execute(
            "SELECT league_id, coalesce(bool_or(is_cross_time), true) AS cross_time "
            "FROM market_vor GROUP BY league_id"
        )
        cross_time_by = {c["league_id"]: bool(c["cross_time"]) for c in cur.fetchall()}

    return build_catalog(rows, weeks_by, cross_time_by, demo_league_id=demo_league_id,
                         owned=owned, current_season=current_season)
