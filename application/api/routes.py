"""The ``/api`` read endpoints (store-migration Session 3; parameterized on league_id in B4).

Thin HTTP layer over ``reads.py`` — each route returns its ``queries.js`` loader's shape
verbatim (plain dicts/lists, FastAPI auto-JSON; no Pydantic models so nothing coerces or
reorders the payload). Week-scoped routes take ``?as_of_week=N`` and default to the latest.

Stage-B B4: every read route also accepts an OPTIONAL ``?league_id=`` (+ ``?season=``) via the
``slice_params`` dependency, defaulting to the is_mine slice (``settings.league_id()``). Omitting
them reproduces today's behavior byte-for-byte (parity); passing a corpus ``league_id`` scopes the
read to that slice. An unknown ``league_id`` 404s. ``load_leagues`` is the one unscoped catalog read.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from application.api import auth, db, reads

router = APIRouter(prefix="/api")


def slice_params(league_id: str | None = None, season: int | None = None,
                 viewer_roster_id: int | None = None) -> dict:
    """The optional slice selector shared by every read route. Validates a non-None ``league_id``
    against the demo_manifest catalog (404 on an unknown slice); ``None`` → the is_mine default
    (resolved inside each ``load_*``). ``season`` is carried for validation/future dynasty, never a
    SQL filter (a redraft ``league_id`` already pins one ``(league, season)`` slice).
    ``viewer_roster_id`` (Stage-B B5) selects the "you" roster; ``None`` → ``MY_USERNAME``'s roster
    (parity). Returned as a kwargs dict so routes forward it with ``**slice``."""
    if league_id is not None and not reads.slice_exists(league_id):
        raise HTTPException(status_code=404, detail=f"unknown league_id {league_id}")
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
def leagues() -> dict:
    # The lineage catalog (Stage-B B3) — unscoped; feeds the B5 league/season switcher.
    return reads.load_leagues()
