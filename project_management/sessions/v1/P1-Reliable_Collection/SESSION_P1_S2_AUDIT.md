# P1 · S2 Audit — Collection reliability + observability

**Reviewed:** 2026-07-27 · **By:** PM (live git + the workflow + the seam/gate changes). Three commits
(`68fc15d` sidecar/batching/gate, `86fa12a` workflow crons+coverage job, `8ee7597` docs) + merge `83e46ed` on
`main` (local **4 ahead of origin** — Will pushes). Report:
`sessions/v1/P1-Reliable_Collection/SESSION_P1_S2_REPORT.md`.

**Bottom line: clean and complete on the code side — endorse. Every S2 item shipped: fetch-timestamp sidecars,
an idempotent catch-up-retry cron, a daily coverage gate that fails → GitHub failure email (the channel you
confirmed), and the optional flush-at-end batching (news went from ~96 uploads/run to 1). Scope stayed
collection-only; the design is sound. The only thing left for P1 is the 2-week ≥95% soak — pure calendar time
on the now-live collectors — plus a ~10-minute hosted spot-check you can do whenever. P1 is effectively
"done building," now in its "prove it holds" window. It does NOT block starting P2.**

## Verified

- **Scope safe.** Only `collectors.yml`, `data_layer.py` (sidecar read/write + flush), `check_collectors.py`
  (the gate), `run.py` (dispatch calls record-run + flush), and docs. No app, no served Postgres, no
  transforms.
- **Retry is safe.** Each collector gets a later catch-up cron (leaguelogs 08:00+14:00 UTC, news 09:00+15:00),
  idempotent because the collectors de-dup by date (verified in S1) — a no-op if the day already banked, else
  it recovers the miss. This is what converts the old "no-retry day → permanent hole" (≈half the 71%→95% gap)
  into "recovered."
- **Batching is safe.** Flush-at-end (supabase backend only) uploads once per series instead of after every
  write — a real egress win (news ~163 MB → one upload). It's safe precisely because a run that dies before
  flush is caught by the catch-up cron. The **local backend is unchanged** (flush is a no-op), so the P2 read
  path stays byte-identical.
- **One genuinely smart call:** the news coverage check gates on the sidecar's last-*run* timestamp ("did a
  collection happen"), not the last-*article* date — which lags in a quiet news week and would fire a false
  alarm. That's the kind of foot-gun that only shows up in production; good that Code pre-empted it.
- **Local verification is real:** sidecars land with correct fields, the gate exits 0 on healthy data and 1 on
  a forced wide-window miss (the alert path), flush buffers then uploads once per key, read parity holds.

## Open items (none block the endorsement)

1. **The 2-week soak (calendar).** The daily coverage job's rolling report is the ≥95% evidence; it accrues on
   the live collectors starting now. **P1 formally closes when it clears** (~mid-August) — comfortably before
   in-season, when it matters.
2. **A ~10-min hosted spot-check (yours, whenever):** dispatch the collectors and confirm a single upload per
   series + the sidecar objects in the bucket; dispatch the `coverage` job on healthy data (green); then
   **force a miss and confirm the failure email actually lands in your inbox.** That last one matters — the
   whole alert rests on you *receiving* GitHub's notification, so it's worth proving once rather than assuming.
   (Check GitHub → Settings → Notifications has Actions failure emails on.)
3. **Minor, cosmetic:** S2 did not bump the workflow's `actions/checkout@v4` / `setup-python@v5` to clear the
   Node-20 deprecation notice (I'd suggested folding it in). Harmless — GitHub auto-runs them on Node 24 — so
   it's a one-line cleanup to ride along with P6 hardening or any future workflow touch, not worth its own trip.

## Recommendation

**Endorse S2 — P1's build is done.** Collection is off the laptop, hardened (retry + alert + batching +
timestamps), and now proving itself over the soak window. The soak is a background watch, not a gate on the
next project. **P1 stays formally "open until the soak clears," but we can move to P2 in parallel now** — the
bucket P2's weekly refresh reads from is live and being fed. See the reassessment for the P2 sequencing call.
