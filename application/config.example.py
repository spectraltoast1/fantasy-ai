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

# --- Auth (P5/S1, S1b) -------------------------------------------------------------------
# All three are read env-first (a Fly secret / CI env wins), config.py second — the same
# precedence as DATABASE_URL above. The deployed image ships no config.py, so on Fly these are
# env vars; these entries are what makes a fresh laptop or worktree runnable.
#
# SUPABASE_URL is needed in TWO places for two different reasons and it is easy to set only one:
# the API resolves it at RUNTIME (to derive the JWKS endpoint + expected token issuer), and the
# SPA needs it at BUILD time, where it arrives as a Docker build arg from fly.toml — not from
# here, because .dockerignore strips config.py and .env from the build context.
SUPABASE_URL = "https://[PROJECT-REF].supabase.co"

# Publishable (public by design — it ships in the JS bundle either way). Supabase's CURRENT key
# names; `anon` / `service_role` are the legacy JWTs these replaced.
SUPABASE_PUBLISHABLE_KEY = "sb_publishable_..."

# Secret — ADMIN-GRADE. The signup endpoint creates users with it, so unlike S1 it now also
# lives in the deployed environment as a Fly secret. Never in git, never in the SPA bundle,
# never a Docker build arg (those are readable in image history).
SUPABASE_SECRET_KEY = "sb_secret_..."

# The shared access code, required on EVERY sign-in request (P5/S1b). Rotation is one change
# here (and `fly secrets set ACCESS_CODE=...`): the old value stops working immediately, with
# no table to migrate. Pick something sayable out loud — it gets texted, not pasted.
ACCESS_CODE = "some-sayable-phrase"

# --- Ownership + visibility (P5/S2a) -----------------------------------------------------
# The ONE public league. Everything else is private and requires an ownership grant
# (`scripts/users.py --grant`). Config rather than a table: with a single public league a table
# buys nothing and cannot drift. Points at real LoRP 2025 today; repointing it at the anonymized
# demo clone later is this one line (or the fly.toml [env] value in production).
DEMO_LEAGUE_ID = "1182101676608823296"

# NOT settable here, and that is deliberate — documented so you don't go looking.
# CURRENT_SEASON is a process-ENV-ONLY override for the current season, which otherwise comes from
# Sleeper's /v1/state/nfl. It exists to run the ownership proofs against real deployed code (the
# corpus tops out at 2025 while Sleeper says 2026), so it must be visible where it is set — in a
# shell, or plain [env] in fly.toml. An override that can hide in this gitignored file is exactly
# the failure mode. See application/api/nfl_state.py.

# Snapshot storage backend for the daily collectors (P1/S1). Defaults to "local" — the laptop
# writes parquet to application/data/snapshots/ as before. Set to "supabase" ONLY in the hosted
# collector CI job (via env), where a diskless runner writes to a durable Supabase Storage bucket.
# The bucket credentials below are read env-first (CI secrets), config.py second — leave them here
# only if you want to test the "supabase" backend locally; NEVER commit real keys.
SNAPSHOT_BACKEND = "local"
# (SUPABASE_URL is set above under Auth — the storage backend derives its S3 endpoint from the
#  same value, .../storage/v1/s3, so don't define it twice.)
# SUPABASE_STORAGE_BUCKET = "snapshots"
# SUPABASE_S3_ACCESS_KEY_ID = "your-storage-scoped-access-key"       # Supabase dashboard -> Storage -> S3 Access Keys
# SUPABASE_S3_SECRET_ACCESS_KEY = "your-storage-scoped-secret-key"
# SUPABASE_S3_REGION = "us-east-1"                          # your project's region
