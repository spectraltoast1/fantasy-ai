# Sleeper
SLEEPER_USERNAME = "your_sleeper_username"

# Anthropic
ANTHROPIC_API_KEY = "your-key-here"

# The Odds API (https://the-odds-api.com) — 500 credits/month on free tier
THE_ODDS_API_KEY = "your-key-here"

#FantasyPros
FANTASY_PROS_API_KEY = "your-key-here"

# League type overrides — map Sleeper league_id to "redraft", "dynasty", or "salary_cap"
# Sleeper cannot distinguish salary_cap keeper leagues from dynasty via its API,
# so any type-2 league without a taxi squad defaults to "salary_cap" unless overridden here.
LEAGUE_TYPES = {
    "your_league_id_here": "redraft",
    "your_league_id_here": "dynasty",
    "your_league_id_here": "salary_cap",
}

# League IDs to exclude from the assistant (e.g. test leagues, inactive leagues)
EXCLUDED_LEAGUES = set()

# League IDs
