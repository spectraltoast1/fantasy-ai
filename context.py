import json
from datetime import date
from sleeper import (
    get_sleeper_user, get_sleeper_league, get_sleeper_roster,
    get_league, get_nfl_state, get_matchups
)
from config import SLEEPER_USERNAME

SKILL_POSITIONS = {"QB", "RB", "WR", "TE", "K"}


def load_players():
    with open("data/players.json") as f:
        data = json.load(f)

    updated = data.get("updated_at")
    if updated:
        days_old = (date.today() - date.fromisoformat(updated)).days
        if days_old > 1:
            print(f"Warning: players.json is {days_old} days old — consider refreshing.")

    players = {}
    for pid, p in data["players"].items():
        if not p.get("team") or p.get("position") not in SKILL_POSITIONS:
            continue
        players[pid] = {
            "name": p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
            "position": p.get("position"),
            "team": p.get("team"),
            "injury_status": p.get("injury_status"),
            "depth_chart_order": p.get("depth_chart_order"),
        }
    return players


def _enrich_player(pid, players):
    if pid in players:
        return players[pid]
    # Team defense IDs are short uppercase strings like "CLE", "NE"
    if len(pid) <= 3 and pid.isupper():
        return {"name": f"{pid} Defense", "position": "DEF", "team": pid, "injury_status": None, "depth_chart_order": None}
    return {"name": f"Unknown ({pid})", "position": None, "team": None, "injury_status": None, "depth_chart_order": None}


def build_roster_context(roster, players):
    starters = roster.get("starters") or []
    all_players = roster.get("players") or []
    bench = [pid for pid in all_players if pid not in starters]
    return {
        "starters": [_enrich_player(pid, players) for pid in starters],
        "bench": [_enrich_player(pid, players) for pid in bench],
    }


def build_league_context(league_detail, rosters, user_owner_id):
    scoring = league_detail.get("scoring_settings", {})
    rec = scoring.get("rec", 0)
    if rec == 1.0:
        scoring_type = "PPR"
    elif rec == 0.5:
        scoring_type = "Half-PPR"
    else:
        scoring_type = "Standard"

    # Strip bench spots from the displayed roster positions
    roster_positions = [p for p in (league_detail.get("roster_positions") or []) if p != "BN"]

    standings = []
    for r in rosters:
        s = r.get("settings", {})
        standings.append({
            "roster_id": r.get("roster_id"),
            "owner_id": r.get("owner_id"),
            "wins": s.get("wins", 0),
            "losses": s.get("losses", 0),
            "ties": s.get("ties", 0),
            "fpts": round(s.get("fpts", 0) + s.get("fpts_decimal", 0) / 100, 2),
            "is_me": r.get("owner_id") == user_owner_id,
        })
    standings.sort(key=lambda x: (-x["wins"], -x["fpts"]))

    my_roster = next((r for r in rosters if r.get("owner_id") == user_owner_id), None)

    return {
        "name": league_detail.get("name"),
        "scoring_type": scoring_type,
        "roster_positions": roster_positions,
        "total_teams": league_detail.get("total_rosters"),
        "standings": standings,
        "my_roster_id": my_roster.get("roster_id") if my_roster else None,
    }


def assemble_prompt_context(league_id=None):
    user = get_sleeper_user(SLEEPER_USERNAME)
    user_id = user["user_id"]

    leagues = get_sleeper_league(user_id)
    if not leagues:
        raise ValueError("No leagues found for user")

    if league_id is None:
        target_league_id = leagues[0]["league_id"]
    else:
        target_league_id = league_id
        if not any(l["league_id"] == league_id for l in leagues):
            raise ValueError(f"League {league_id} not found for this user")

    league_detail = get_league(target_league_id)
    rosters = get_sleeper_roster(target_league_id)
    state = get_nfl_state()
    players = load_players()

    my_roster = next((r for r in rosters if r.get("owner_id") == user_id), None)
    if my_roster is None:
        raise ValueError(f"No roster found for user {user_id} in league {target_league_id}")

    week = state.get("week") or 0
    league_ctx = build_league_context(league_detail, rosters, user_id)
    roster_ctx = build_roster_context(my_roster, players)

    matchup_ctx = None
    if week > 0:
        matchups = get_matchups(target_league_id, week)
        my_matchup_id = next(
            (m["matchup_id"] for m in matchups if m.get("roster_id") == my_roster["roster_id"]),
            None,
        )
        if my_matchup_id:
            opponent = next(
                (m for m in matchups
                 if m.get("matchup_id") == my_matchup_id and m.get("roster_id") != my_roster["roster_id"]),
                None,
            )
            if opponent:
                matchup_ctx = {
                    "week": week,
                    "opponent_roster_id": opponent.get("roster_id"),
                    "opponent_starters": [
                        _enrich_player(pid, players) for pid in (opponent.get("starters") or [])
                    ],
                }

    return {
        "season": state.get("season"),
        "week": week,
        "season_type": state.get("season_type"),
        "league": league_ctx,
        "my_roster": roster_ctx,
        "matchup": matchup_ctx,
    }


if __name__ == "__main__":
    ctx = assemble_prompt_context()
    print(json.dumps(ctx, indent=2))
