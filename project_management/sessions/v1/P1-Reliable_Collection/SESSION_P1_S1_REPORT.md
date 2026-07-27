# V1 · P1 · S1 — Host the daily collectors: session report

**Ran:** 2026-07-27 · **Brief:** `SESSION_P1_S1_HOST_COLLECTORS.md` · **Outcome:** off-laptop machinery built
and locally verified; **go-live gated on Will provisioning the bucket + CI secrets and proving one hosted run.**

## What shipped (2 commits on `claude/p1-s1-host-collectors`)

1. **Storage-backend seam in `data_layer`** — a `_SnapshotStore` chosen env-first by `SNAPSHOT_BACKEND`
   (`local` default; `supabase` in CI). `_LocalSnapshotStore` = unchanged on-disk behavior;
   `_SupabaseSnapshotStore` = Supabase Storage's S3-compatible endpoint via `boto3` (lazy-imported),
   working-copy model (download-on-access, upload-after-write; object key = path relative to the snapshots
   root). Only the **two raw collector series** are wired through it — `leaguelogs/market_values.parquet` and
   `news/team_news_raw.parquet` (read/write/exists/prune); everything else keeps its direct local-path IO
   (scope guard). `boto3==1.43.56` added; `SNAPSHOT_BACKEND`/`SUPABASE_*` placeholders in `config.example.py`.
2. **`.github/workflows/collectors.yml`** — two jobs invoking the existing dispatcher (`python -m
   application.data.fetchers.run leaguelogs|news`) with `SNAPSHOT_BACKEND=supabase`. Independent UTC crons
   (`0 8` = 4am EDT leaguelogs, `0 9` = 5am EDT news) + `workflow_dispatch` (collector = leaguelogs|news|all)
   to prove a run before trusting the cron. Slim pip install; `nflreadpy` not needed. `scheduler/README.md`
   got a SUPERSEDED banner + the cutover runbook.

## Key finding

**Neither collector needs auth** — LeagueLogs is an open developer API (no key/cookie), news is public RSS
(only a User-Agent). So the brief's "LeagueLogs access" secret does not exist; the **only** secret is the
storage-scoped Supabase S3 credential.

## Verified in-session (local backend)

- Read-path parity byte-identical to direct `pl.read_parquet` (leaguelogs 152,432 rows / 46 dates; news 5,022
  rows) — the seam is transparent on `local`, so the laptop path and P2 reads are unchanged.
- Both collectors ran end-to-end through the store: **leaguelogs ✓ 5/5 profiles**, **news ✓ 96/96 feeds**
  (store 5,022 → 8,232 rows), both freshness checks green. (These runs also banked today's real data.)
- Store write/exists/read round-trip on a scratch path; `_key()` maps to `leaguelogs/market_values.parquet` /
  `news/team_news_raw.parquet`.
- Scope-guard diff: only `data_layer` (the seam + 7 raw fns, signatures intact), `requirements.txt`,
  `config.example.py`, and the new `.github/` — no app / served Postgres / transforms / sleeper|nfl_stats.

## Gated on Will (then S1 is done)

1. Create a **private Supabase Storage bucket** + **storage-scoped S3 access keys** (dashboard → Storage).
2. Set repo **secrets** (Settings → Secrets → Actions): `SUPABASE_URL`, `SUPABASE_STORAGE_BUCKET`,
   `SUPABASE_S3_ACCESS_KEY_ID`, `SUPABASE_S3_SECRET_ACCESS_KEY`, `SUPABASE_S3_REGION` (optional
   `SUPABASE_S3_ENDPOINT`).
3. **Seed the bucket once** from the laptop's current local snapshots (command in `scheduler/README.md`) so
   hosted runs append onto real history.
4. **Prove:** `gh workflow run collectors.yml -f collector=all` → both jobs green + objects land in the bucket;
   confirm a re-run is idempotent.
5. **Only then retire the launchd plists** (runbook step 5). Until then the laptop keeps banking — no gap.

## Notes for S2

- **Upload chattiness:** the working-copy backend uploads after *each* write (leaguelogs ~5/run, news ~96/run)
  to preserve per-item crash-resilience. If run time/egress is a problem, S2 can flush once at end-of-run.
- **Actions cron** can be delayed/skipped under load, and shifts ~1h in ET after DST ends (early Nov) — both
  factor into S2's ≥95% coverage target + the coverage alert.
- S2 scope (unchanged): `metadata.json` fetch-timestamp sidecar, retry/backoff, daily coverage alert, 2-week soak.
