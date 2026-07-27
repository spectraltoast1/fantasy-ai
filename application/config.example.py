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

# Snapshot storage backend for the daily collectors (P1/S1). Defaults to "local" — the laptop
# writes parquet to application/data/snapshots/ as before. Set to "supabase" ONLY in the hosted
# collector CI job (via env), where a diskless runner writes to a durable Supabase Storage bucket.
# The bucket credentials below are read env-first (CI secrets), config.py second — leave them here
# only if you want to test the "supabase" backend locally; NEVER commit real keys.
SNAPSHOT_BACKEND = "local"
# SUPABASE_URL = "https://[PROJECT-REF].supabase.co"      # S3 endpoint derived as .../storage/v1/s3
# SUPABASE_STORAGE_BUCKET = "snapshots"
# SUPABASE_S3_ACCESS_KEY_ID = "your-storage-scoped-access-key"       # Supabase dashboard -> Storage -> S3 Access Keys
# SUPABASE_S3_SECRET_ACCESS_KEY = "your-storage-scoped-secret-key"
# SUPABASE_S3_REGION = "us-east-1"                          # your project's region
