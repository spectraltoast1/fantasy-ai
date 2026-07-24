# Sleeper
SLEEPER_USERNAME = "your_sleeper_username"
SLEEPER_LEAGUE_ID = "your_league_id_here"  # the league the assistant runs against (shared.league_resolver reads this)

# Anthropic
ANTHROPIC_API_KEY = "your-key-here"

# The Odds API (https://the-odds-api.com) — 500 credits/month on free tier
THE_ODDS_API_KEY = "your-key-here"

#FantasyPros
FANTASY_PROS_API_KEY = "your-key-here"

# Supabase Postgres (store migration) — the SESSION-POOLER connection string.
# Durable secret home: lives here in config.py (gitignored, symlinked into worktrees).
# The FastAPI app + the parquet->Postgres loader read it via application.api.db.database_url().
# On Fly it is set as a secret env var instead. Slot your DB password in for [YOUR-PASSWORD].
DATABASE_URL = "postgresql://postgres.[PROJECT-REF]:[YOUR-PASSWORD]@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
