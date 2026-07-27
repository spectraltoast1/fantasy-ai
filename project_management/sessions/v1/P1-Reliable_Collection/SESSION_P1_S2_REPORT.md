# V1 · P1 · S2 — Collection reliability + observability: session report

**Ran:** 2026-07-27 · **Brief:** `SESSION_P1_S2_RELIABILITY.md` · **Outcome:** the reliability hardening is
built and locally verified on the (now-live) hosted collectors; **the only thing left to close P1 is the
rolling two-week ≥95% soak**, which accrues on the hosted collectors over calendar time.

## What shipped (2 code commits on `claude/p1-s2-reliability`)

1. **Python hardening** (`data_layer.py`, `run.py`, `check_collectors.py`):
   - **Fetch-timestamp sidecar** — `<series>.meta.json` beside each parquet in the store (last-fetch UTC, as-of
     date, row count, strict completeness status). Written post-collect by `dispatch` →
     `check_collectors.record_run()`. Store gained `read_bytes`/`write_bytes`; REGISTRY coverage blocks gained
     `meta_read`/`meta_write`.
   - **Flush-at-end batching** (supabase backend) — writes buffer to the working copy, upload once on `flush()`
     (dispatch calls `data_layer.flush_snapshots()`). news ~96 uploads (~163 MB) → 1. Local backend unchanged
     (flush = no-op) → parity + the P2 read path stay byte-identical.
   - **Sidecar-aware coverage gate** — `certify()` reports last-run age + status; **news gates on the sidecar's
     last-RUN time** (a run happened) instead of the series' last-ARTICLE date, which lags in a quiet news week
     and would false-alarm. `main()` still exits non-zero on a gap.
2. **Workflow** (`.github/workflows/collectors.yml`):
   - **Catch-up retry** — each collector gets a later idempotent catch-up cron (leaguelogs 08:00+14:00 UTC, news
     09:00+15:00 UTC). Recovers a missed/failed primary; also the safety net that makes flush-at-end safe.
   - **Coverage-gate alert** — a daily `coverage` job (18:00 UTC) runs `check_collectors`; a non-zero exit fails
     the job → **GitHub's native workflow-failure email** (Will-confirmed channel; no new infra/secret). Added
     `coverage` to the dispatch options.

## Verified in-session (local backend)

- Both sidecars land with correct fields (leaguelogs `status=ok, expected=5, today_count=5`; news
  `status=ok, today_count=3265`) and read back via `data_layer`.
- **Coverage gate exit codes** (the alert mechanism): full gate on real data → **PASS, exit 0**; a wide-window
  forced miss (`check_collectors leaguelogs --since 40`, spanning the real historical gaps) → **FAIL, exit 1** —
  no data mutation.
- **Flush-at-end** unit-checked (stubbed S3): writes buffer (no upload), one upload per dirty key on `flush()`,
  dirty cleared; local `flush()` is a no-op. **S1 read parity holds** (leaguelogs 152,432 rows, news series).
- `--today` freshness unchanged; scope-guard diff = only `data_layer` / `run.py` / `check_collectors` /
  `collectors.yml` + docs.

## Gated / accrues after merge (Will- or `gh`-verifiable)

- **Hosted proof** (once merged+pushed — the workflow is already live): dispatch the collectors → confirm a
  **single upload per series** (flush) + the sidecar objects in the bucket; dispatch the `coverage` job on
  healthy data → green; force a miss → red → **failure email** lands.
- **≥95% soak (calendar):** the daily `coverage` report over a rolling two-week window is the evidence. **P1
  closes when it clears.** Watch the known facts: GitHub cron delay/skip (catch-up + alert cover it) and the
  post-DST ~1h ET shift (documented in the workflow).

## Notes

- **Flush-at-end + catch-up are a pair:** batching drops per-item upload crash-resilience, but the same-day
  catch-up cron re-collects a run that died before flush (collectors de-dup by date) — net reliability up, egress
  ~96× down.
- **`gh` is not installed on the laptop** — the hosted-run/alert proof is Will-driven (Actions UI) or needs `gh`
  installed to script.
