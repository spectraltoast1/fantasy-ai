"""The ``/api`` read endpoints (store-migration Session 3; parameterized on league_id in B4).

Thin HTTP layer over ``reads.py`` — each route returns its ``queries.js`` loader's shape
verbatim (plain dicts/lists, FastAPI auto-JSON; no Pydantic models so nothing coerces or
reorders the payload). Week-scoped routes take ``?as_of_week=N`` and default to the latest.

Stage-B B4: every read route also accepts an OPTIONAL ``?league_id=`` (+ ``?season=``) via the
``slice_params`` dependency. Passing a corpus ``league_id`` scopes the read to that slice; an
unknown ``league_id`` 404s.

P5/S2a changed two things here. An omitted ``league_id`` now resolves to ``DEMO_LEAGUE_ID``
explicitly rather than falling through ``MY_USERNAME`` to the is_mine slice — the same league
today, but decided rather than inherited. And ``/api/leagues``, which was the one unscoped read,
is now scoped to the caller: the demo always, plus their own current-season leagues. The eleven
per-panel reads are still open; closing them is S2b, and the split is deliberate so a green run
can be attributed to one half or the other.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from application.api import auth, db, rate_limit, reads, settings, signup

router = APIRouter(prefix="/api")


def slice_params(league_id: str | None = None, season: int | None = None,
                 viewer_roster_id: int | None = None) -> dict:
    """The optional slice selector shared by every read route. Validates a non-None ``league_id``
    against the demo_manifest catalog (404 on an unknown slice). ``season`` is carried for
    validation/future dynasty, never a SQL filter (a redraft ``league_id`` already pins one
    ``(league, season)`` slice). ``viewer_roster_id`` (Stage-B B5) selects the "you" roster;
    ``None`` → ``MY_USERNAME``'s roster (parity). Returned as a kwargs dict so routes forward it
    with ``**slice``.

    **P5/S2a — an omitted ``league_id`` now resolves to the DEMO explicitly.** It used to fall
    through to ``settings.league_id()`` inside each ``load_*``, i.e. to whichever league the owner's
    Sleeper credentials happened to name: an anonymous visitor landed on Will's real league by
    accident of name resolution rather than by anyone deciding they should. The default is now the
    one league that is deliberately public. ``MY_USERNAME`` stays, but only as the resolver for
    Will's own viewer seat (``reads.resolve_viewer``), which is what it was always for.

    Note this is *default resolution*, not authorization — a caller can still ask for any catalogued
    ``league_id`` here. Moving the visibility predicate into this function so every read inherits it
    is S2b; keeping the two changes separate is what lets each one's proof mean something.
    """
    if league_id is not None and not reads.slice_exists(league_id):
        raise HTTPException(status_code=404, detail=f"unknown league_id {league_id}")
    if league_id is None:
        league_id = settings.demo_league_id()
    return {"league_id": league_id, "season": season, "viewer_roster_id": viewer_roster_id}


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
