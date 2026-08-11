"""The ``/api`` read endpoints (store-migration Session 3; parameterized on league_id in B4).

Thin HTTP layer over ``reads.py`` — each route returns its ``queries.js`` loader's shape
verbatim (plain dicts/lists, FastAPI auto-JSON; no Pydantic models so nothing coerces or
reorders the payload). Week-scoped routes take ``?as_of_week=N`` and default to the latest.

Stage-B B4: every read route also accepts an OPTIONAL ``?league_id=`` (+ ``?season=``) via the
``slice_params`` dependency. Passing a corpus ``league_id`` scopes the read to that slice; an
unknown ``league_id`` 404s.

P5/S2a scoped ``/api/leagues`` — the catalog — so a caller could not *discover* someone else's
league, and made an omitted ``league_id`` resolve to ``DEMO_LEAGUE_ID`` explicitly instead of
falling through ``MY_USERNAME`` to the is_mine slice.

**P5/S2b closes access.** ``slice_params`` now takes the caller's identity and applies the
visibility predicate, so all eleven per-panel reads inherit it from one place. Knowing a
``league_id`` is no longer enough to read it; an unowned league answers with exactly the 404 a
nonexistent one does.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from application.api import auth, db, rate_limit, reads, settings, signup

_LOG = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


# ONE refusal string, reached by both branches, interpolating nothing. It used to echo the
# league_id back — which meant an unowned league and a nonexistent one could never produce the same
# bytes, and the whole no-enumeration design rests on them being indistinguishable. The caller's own
# input tells them nothing they didn't already know, but a body that varies with it is a body an
# attacker can measure, and it also stopped the two responses being comparable at all.
_UNKNOWN_LEAGUE = "unknown league_id"


def slice_params(league_id: str | None = None, season: int | None = None,
                 viewer_roster_id: int | None = None,
                 user: dict | None = Depends(auth.optional_user)) -> dict:
    """The slice selector shared by every read route — and, as of P5/S2b, **the one authorization
    seam**. Every one of the eleven per-panel reads inherits it; none repeats the check.

    S2a scoped the catalog, so you could not *discover* someone else's league. This closes *access*:
    until now a caller who already knew a ``league_id`` could pass it here and read the league.

    A thin adapter on purpose. The decision lives in ``reads.authorize_slice``, which is pure and
    injectable so ``check_isolation`` can drive the whole matrix from fixtures — an isolation gate
    that can only run against two live accounts is one that stops being run. This function's only
    job is turning its two exceptions into HTTP:

    - ``SliceRefused`` → **404**, the same status *and the same body* a nonexistent league gets.
      A 403 would confirm the league exists; Sleeper ids are guessable, so a refusal that varies by
      case is an enumeration oracle.
    - ``SliceUnavailable`` → **503**. A broken demo config or a league with two seasons in the store
      is a deploy problem, and dressing it as "unknown league_id" would hide an outage behind an
      authorization message.

    ``season`` is still carried, never a SQL filter (a redraft ``league_id`` already pins one
    ``(league, season)`` slice). The returned dict is built explicitly, with exactly the three keys
    the loaders accept — ``user`` is a dependency, not a slice field, and one stray key would make
    ``**slice`` a 500 on all eleven routes at once.
    """
    try:
        return reads.authorize_slice(
            league_id, season, viewer_roster_id,
            user_id=(user or {}).get("id"),
            demo_league_id=settings.demo_league_id(),
        )
    except reads.SliceRefused:
        raise HTTPException(status_code=404, detail=_UNKNOWN_LEAGUE) from None
    except reads.SliceUnavailable as exc:
        _LOG.error("slice unavailable — this is a deploy/data problem, not a caller problem: %s",
                   exc)
        raise HTTPException(status_code=503, detail="this league cannot be served") from exc


_UPSERT_APP_USER = """
INSERT INTO public.app_users (id, email) VALUES (%(id)s, %(email)s)
ON CONFLICT (id) DO NOTHING
"""


@router.get("/me")
def me(user: dict = Depends(auth.current_user)) -> dict:
    """The authenticated caller's identity — the one endpoint S1 gates.

    Every OTHER read stays open this session, deliberately. Authentication without per-user
    scoping is a half-gate that looks like security while every caller still sees every
    league; closing and scoping the reads is one coherent change with one coherent proof, and
    that is S2.

    Recording the profile row here — rather than in a database trigger on ``auth.users`` — keeps
    the behavior in reviewable code instead of invisible DDL, and costs one no-op INSERT per
    call. Deliberately narrow: id and email only, because the user→league ownership model is
    S2's and inventing it early guarantees rework.
    """
    db.execute(_UPSERT_APP_USER, {"id": user["id"], "email": user["email"]})
    return {"id": user["id"], "email": user["email"]}


@router.post("/signup")
def signup_request(request: Request, body: dict = Body(...)) -> dict:
    """Request a sign-in link. The API's first write endpoint, and its only unauthenticated one.

    Takes ``{email, code}``. The access code is required on every request from everyone — see
    ``signup.py`` for why that is the property worth having rather than a friction to remove.

    Deliberately NOT taking ``slice_params``: this has nothing to do with which league you are
    looking at, and merging the slice into it would put a ``league_id`` on an auth call.

    The response is the same whether or not the address already had an account, so it can't be
    used to enumerate who is registered.
    """
    email = str(body.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")

    # Check the limit BEFORE doing any work, then record the attempt whatever the outcome — so a
    # wrong code still counts against the budget. Recording only successes would leave the
    # brute-force door open, which is the main thing this is defending.
    rate_limit.check(request, email)
    try:
        signup.request_link(email, body.get("code"))
    except Exception:
        rate_limit.record(request, email, ok=False)
        raise
    rate_limit.record(request, email, ok=True)
    return {"sent": True}


@router.get("/weeks")
def weeks(slice: dict = Depends(slice_params)) -> dict:
    return reads.load_weeks(**slice)


@router.get("/league-meta")
def league_meta(as_of_week: int | None = None, slice: dict = Depends(slice_params)) -> dict:
    return reads.load_league_meta(as_of_week, **slice)


@router.get("/players")
def players(as_of_week: int | None = None, slice: dict = Depends(slice_params)) -> list[dict]:
    return reads.load_players(as_of_week, **slice)


@router.get("/players/{sleeper_id}")
def player_card(sleeper_id: str, as_of_week: int | None = None,
                slice: dict = Depends(slice_params)) -> dict:
    return reads.load_player_card(sleeper_id, as_of_week, **slice)


@router.get("/standings")
def standings(as_of_week: int | None = None, slice: dict = Depends(slice_params)) -> list[dict]:
    return reads.load_standings(as_of_week, **slice)


@router.get("/teams/{roster_id}")
def team_detail(roster_id: int, as_of_week: int | None = None,
                slice: dict = Depends(slice_params)):
    # Returns null (200) for an unknown roster, matching loadTeamDetail's shape.
    return reads.load_team_detail(roster_id, as_of_week, **slice)


@router.get("/managers/{roster_id}")
def manager_dossier(roster_id: int, slice: dict = Depends(slice_params)) -> dict:
    return reads.load_manager_dossier(roster_id, **slice)


@router.get("/league")
def league(as_of_week: int | None = None, slice: dict = Depends(slice_params)) -> dict:
    return reads.load_league(as_of_week, **slice)


@router.get("/positional-talent")
def positional_talent(slice: dict = Depends(slice_params)) -> dict:
    return reads.load_positional_talent(**slice)


@router.get("/matchups")
def matchups(as_of_week: int | None = None, slice: dict = Depends(slice_params)) -> dict:
    return reads.load_matchups(as_of_week, **slice)


@router.get("/matchups/{matchup_id}")
def matchup_detail(matchup_id: int, as_of_week: int | None = None,
                   slice: dict = Depends(slice_params)):
    # Returns null (200) when the game/week doesn't resolve, matching loadMatchupDetail.
    return reads.load_matchup_detail(matchup_id, as_of_week, **slice)


@router.get("/leagues")
def leagues(user: dict | None = Depends(auth.optional_user)) -> dict:
    """The lineage catalog (Stage-B B3), scoped to the caller as of P5/S2a.

    Signed out → the demo alone. Signed in → the demo plus your own current-season leagues, yours
    first. This was the ONE unscoped read, and it is the catalog, so it is the right first thing
    to close: every other surface is navigated from this list.

    Two properties the SPA depends on, both easy to break and neither loud when broken:
    it must never 401 (``loadLeagues()`` only console.errors, leaving a permanent "Loading…"),
    and it must never return zero leagues (``if (lgs.length)`` guards the only slice selection).
    The demo term is what guarantees the second — see ``reads.build_catalog``.
    """
    return reads.load_leagues(user_id=(user or {}).get("id"))
