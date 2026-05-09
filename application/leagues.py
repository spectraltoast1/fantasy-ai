"""
League type detection and strategy doc loading.

Sleeper's settings.type field distinguishes redraft (0) from dynasty/keeper (2),
but cannot differentiate salary cap keeper leagues from standard dynasty leagues.
Use LEAGUE_TYPES in config.py to override detection for ambiguous leagues.
"""

import os

DOCS_DIR = "docs"

_TYPE_NAMES = {
    "redraft": "Redraft",
    "dynasty": "Dynasty",
    "salary_cap": "Salary Cap",
}

_STRATEGY_DOC_PATHS = {
    "redraft": os.path.join(DOCS_DIR, "strategy_redraft.md"),
    "dynasty": os.path.join(DOCS_DIR, "strategy_dynasty.md"),
    "salary_cap": os.path.join(DOCS_DIR, "strategy_salary_cap.md"),
}


def get_league_type(league_detail):
    """Detect league type from Sleeper league detail response.

    Detection order:
    1. Check LEAGUE_TYPES config override (keyed by league_id)
    2. settings.type == 0  → redraft
    3. settings.type == 2 + taxi_slots > 0  → dynasty
    4. settings.type == 2 + taxi_slots == 0  → salary_cap (keeper; Sleeper can't distinguish further)
    """
    try:
        from config import LEAGUE_TYPES
    except ImportError:
        LEAGUE_TYPES = {}

    league_id = league_detail.get("league_id")
    if league_id and league_id in LEAGUE_TYPES:
        return LEAGUE_TYPES[league_id]

    settings = league_detail.get("settings", {})
    sleeper_type = settings.get("type", 0)
    taxi_slots = settings.get("taxi_slots", 0)

    if sleeper_type == 0:
        return "redraft"
    if sleeper_type == 2 and taxi_slots and taxi_slots > 0:
        return "dynasty"
    # type 2 without taxi — treat as salary_cap/keeper; config override recommended
    return "salary_cap"


def load_strategy_doc(league_type):
    """Load the strategy markdown doc for a given league type.

    Returns the doc content as a string, or None if the file doesn't exist yet.
    """
    path = _STRATEGY_DOC_PATHS.get(league_type)
    if not path:
        return None
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return None


def league_type_label(league_type):
    return _TYPE_NAMES.get(league_type, league_type)


if __name__ == "__main__":
    from sleeper import get_sleeper_user, get_sleeper_league, get_league
    from config import SLEEPER_USERNAME

    user = get_sleeper_user(SLEEPER_USERNAME)
    leagues = get_sleeper_league(user["user_id"])

    for l in leagues:
        detail = get_league(l["league_id"])
        ltype = get_league_type(detail)
        doc = load_strategy_doc(ltype)
        doc_status = "loaded" if doc else "not found"
        print(f"  {detail['name']}: {league_type_label(ltype)} (strategy doc: {doc_status})")
