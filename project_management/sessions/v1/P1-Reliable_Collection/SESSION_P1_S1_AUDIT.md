# P1 · S1 Audit — Host the daily collectors off-laptop

**Reviewed:** 2026-07-27 · **By:** PM (live git + the workflow + the `data_layer` seam). **Quick audit** —
small, low-risk infra session. Three commits (`2fa0b85` seam, `f460511` workflow, `6c27bda` docs) + merge
`365b17a` on `main` (local **4 ahead of origin** — Will pushes). Report:
`sessions/v1/P1-Reliable_Collection/SESSION_P1_S1_REPORT.md`.

**Bottom line: clean, correctly scoped, and safe — endorse. The off-laptop machinery (a `data_layer` storage
seam + a GitHub Actions workflow) is built and locally verified, with no secrets committed and zero impact on
the app/build path. But S1 is NOT live yet — the production cutover is a ~15-minute runbook only you can do
(create the Supabase bucket + set the secrets + prove one hosted run + retire the laptop jobs). Until you do
that, collection is still on your laptop and the "bank it or lose it" clock is still running — so the one real
action here is: do the cutover soon.**

## Verified

- **Scope is safe.** The only code file touched is `data_layer.py` (the storage seam); everything else is the
  new `.github/` workflow, `requirements.txt` (+boto3), `config.example.py` placeholders, and docs. The
  fetchers themselves, the app, the served Postgres, the loader, the transforms, and Sleeper/nflreadpy are all
  untouched.
- **The seam can't regress anything.** It's env-selected and **defaults to `local`** (`SNAPSHOT_BACKEND or
  "local"`), and only the two raw collector series (leaguelogs market values, news) route through it — so on a
  laptop and in the P2 build path, behavior is byte-identical (Code verified: 152,432 leaguelogs rows / 46
  dates and 5,022 news rows read identically; both collectors ran end-to-end and banked today's real data).
  `boto3` is lazy-imported, so nothing else even loads it.
- **No secrets committed.** The workflow references `${{ secrets.* }}` only; the sole secret is the Supabase
  storage credential. Good find by Code: neither collector needs auth (LeagueLogs is an open API, news is
  public RSS), so the brief's assumed "LeagueLogs access" secret doesn't exist — one fewer thing for you.
- **Cutover is sequenced safely.** The launchd plists stay live until a hosted run is proven landing data, so
  there's no collection gap during the switch — retiring them is the explicit last step.

## What I could NOT verify (inherent, not a gap)

The **Supabase side is only exercised once you provision the bucket + secrets** — there's literally nothing
hosted to observe yet. Code verified the local backend byte-for-byte and the store round-trip on a scratch
path, but the real S3 upload/download path gets its first true test at *your* dispatch run (runbook step 4) —
which is correctly placed *before* the plists are retired, so if the boto3 wiring has any wrinkle it surfaces
with the laptop still safely banking. That's the right sequencing, not a hole.

## Your cutover runbook (from the report — ~15 min; do it soon)

1. Create a **private Supabase Storage bucket** + storage-scoped S3 access keys (Supabase dashboard → Storage).
2. Set the repo **secrets** (Settings → Secrets → Actions): `SUPABASE_URL`, `SUPABASE_STORAGE_BUCKET`,
   `SUPABASE_S3_ACCESS_KEY_ID`, `SUPABASE_S3_SECRET_ACCESS_KEY`, `SUPABASE_S3_REGION` (+ optional
   `SUPABASE_S3_ENDPOINT`).
3. **Seed the bucket once** from your current local snapshots (command in `scheduler/README.md`).
4. **Prove:** `gh workflow run collectors.yml -f collector=all` → both jobs green + objects in the bucket;
   confirm a re-run is idempotent.
5. **Then retire the launchd plists.**

## Recommendation

**Endorse S1.** The machinery is correct, scoped, and safe; the honest "built-not-live, cutover-is-yours"
framing is the right call (Code can't hold your Supabase bucket/secrets). **Do the cutover soon** — every day
until then is a permanent hole in the 2026 series, which is the whole reason P1 went first. S2 (the reliability
hardening + the two-week ≥95% proof) is drafted and can build in parallel, but its soak clock only starts once
the cutover is live.
