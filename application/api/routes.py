"""The ``/api`` read endpoints (store-migration Session 3).

Thin HTTP layer over ``reads.py`` — each route returns its ``queries.js`` loader's shape
verbatim (plain dicts/lists, FastAPI auto-JSON; no Pydantic models so nothing coerces or
reorders the payload). Week-scoped routes take ``?as_of_week=N`` and default to the latest.
"""

from __future__ import annotations

from fastapi import APIRouter

from application.api import reads

router = APIRouter(prefix="/api")


@router.get("/weeks")
def weeks() -> dict:
    return reads.load_weeks()


@router.get("/league-meta")
def league_meta(as_of_week: int | None = None) -> dict:
    return reads.load_league_meta(as_of_week)


@router.get("/players")
def players(as_of_week: int | None = None) -> list[dict]:
    return reads.load_players(as_of_week)


@router.get("/players/{sleeper_id}")
def player_card(sleeper_id: str, as_of_week: int | None = None) -> dict:
    return reads.load_player_card(sleeper_id, as_of_week)


@router.get("/standings")
def standings(as_of_week: int | None = None) -> list[dict]:
    return reads.load_standings(as_of_week)


@router.get("/teams/{roster_id}")
def team_detail(roster_id: int, as_of_week: int | None = None):
    # Returns null (200) for an unknown roster, matching loadTeamDetail's shape.
    return reads.load_team_detail(roster_id, as_of_week)


@router.get("/managers/{roster_id}")
def manager_dossier(roster_id: int) -> dict:
    return reads.load_manager_dossier(roster_id)


@router.get("/matchups")
def matchups(as_of_week: int | None = None) -> dict:
    return reads.load_matchups(as_of_week)


@router.get("/matchups/{matchup_id}")
def matchup_detail(matchup_id: int, as_of_week: int | None = None):
    # Returns null (200) when the game/week doesn't resolve, matching loadMatchupDetail.
    return reads.load_matchup_detail(matchup_id, as_of_week)
