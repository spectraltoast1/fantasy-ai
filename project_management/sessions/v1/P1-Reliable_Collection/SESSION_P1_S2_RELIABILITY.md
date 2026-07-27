# V1 · Project 1 · Session S2 — Collection reliability + observability — a brief for Code

**Last reviewed:** 2026-07-27 · **Status:** Ready to build (the ≥95% *proof* needs S1's cutover live — see
Sequencing) · **Owner:** Code drives; Will confirms the alert channel + does the S1 cutover. **Project:**
`projects/v1/P1_RELIABLE_COLLECTION.md` (S2 of 2 — closes P1).

> **What this session does:** make the now-hosted daily collectors **trustworthy** — record *when* each fetch
> happened, retry the misses that used to go silent, make a missed day **loud** instead of invisible, and
> prove **≥95% coverage over a rolling two weeks**. S1 moved collection off the laptop; S2 is what lets us
> actually *trust* the 2026 market + news history the live trade read (P2) and AI outlook (P4) depend on.
> `P1_RELIABLE_COLLECTION.md` · builds on the S1 seam + `check_collectors.py`.

## Sequencing (important)
The **code** in S2 (timestamps, retry, coverage alert) can be built anytime. The **≥95% proof** is a two-week
soak that only counts *hosted* runs — so it can't start until Will's S1 cutover is live (bucket + secrets +
proven run). Practical order: Will does the cutover → Code builds the S2 hardening → the 2-week soak runs on
the hardened, hosted collectors → P1 is done. **The soak clock is the long pole of P1 now, so the cutover
timing gates it.**

## Your part, Will (~5 min)
One decision — the **alert channel** (how you find out a day was missed; I recommend leaning on GitHub's
built-in workflow-failure email, below). And, the gating item: **do the S1 cutover** so the soak can start.

## Decisions I made for you (Code: follow unless you hit a reason not to)

1. **Fetch-timestamp metadata — a sidecar next to each series in the store.** The cache records *what* was
   fetched, not *when*. Write a small `metadata.json` (or `<series>.meta.json`) beside each series' parquet in
   the bucket on every run: last-fetch UTC timestamp, row/​item count, and the run's status. Read it in the
   coverage check. This is the "before in-season use" item — keep it simple, one sidecar per series.
2. **Retry the misses that used to be silent — a same-day catch-up run.** The audited laptop misses were
   ~8 laptop-off days (S1 fixed) **+ ~7 no-retry days** (S2 fixes). `_http` already makes each *call*
   resilient; S2 adds *run-level* recovery: a **second, later catch-up cron** per collector (e.g. a few hours
   after the primary) that is a **no-op if the day already banked** (the collectors already de-dup by date, so
   a re-run is idempotent) and otherwise fills the gap. This directly converts "no-retry day → miss" into
   "recovered," which is most of what's between ~71% and ≥95%.
3. **Make a miss LOUD — coverage check that fails the workflow (recommended alert path).** Extend
   `check_collectors.py` into a daily coverage gate (its own scheduled job, or a step after each collector)
   that reads the metadata sidecar + the series and **exits non-zero when the latest expected day is missing or
   short** (leaguelogs: profiles/day; news: recency). A failing job triggers **GitHub's built-in
   workflow-failure email to you** — no new alerting infra. *(If you want a richer ping — Slack/push — a
   webhook step is a small add, but I'd start with the native email and only add more if it's too quiet.)*
4. **Batch the bucket uploads if run-time/egress warrants (S1 flagged it).** The S1 working-copy backend
   uploads after *every* write (news ~96/run). If a hosted run is slow or egress-heavy, switch to **flush-once
   at end-of-run** (one upload per series) — faster and cleaner, at the cost of per-item mid-run crash
   resilience, which a daily bank doesn't need. Measure first; change only if it's a real cost.
5. **Prove ≥95% over a rolling two-week window** on the hosted, hardened collectors — the coverage check's own
   report is the evidence. Account for the two known reliability facts in the target: GitHub cron can be
   delayed/skipped under load (the catch-up run + alert cover this), and the ET schedule shifts ~1h after DST
   ends in early November (documented in the workflow).
6. **Scope guard — collection only.** Same as S1: do **not** touch the app, served Postgres, transforms, or
   the on-demand Sleeper/nflreadpy pulls. This is timestamps + retry + a coverage gate + the soak.

## The brief to paste to Code

```
Goal: V1 Project 1, Session S2 (projects/v1/P1_RELIABLE_COLLECTION.md) — collection reliability + observability
for the two hosted daily collectors (leaguelogs, news): fetch-timestamp metadata, run-level retry, a loud
coverage alert, and a two-week soak proving >=95% coverage. Builds on the S1 storage seam + check_collectors.py.
Scope: collection only — do NOT touch the app, served Postgres, transforms, or Sleeper/nfl_stats.

Part 1 — metadata timestamp sidecar:
- On every collector run, write a small metadata sidecar beside the series in the store (local + supabase
  backends): last-fetch UTC timestamp, item/row count, run status. The coverage check reads it. One sidecar
  per series (leaguelogs/market_values, news/team_news_raw).

Part 2 — run-level retry (the "no-retry day" fix):
- Add a same-day catch-up cron per collector (later than the primary) that is idempotent — a no-op if the day
  already banked (collectors de-dup by date), else it fills the gap. _http keeps per-call resilience; this adds
  per-run recovery.

Part 3 — loud coverage gate (alert):
- Extend check_collectors.py into a daily coverage check (scheduled job or post-collector step) that reads the
  metadata + series and EXITS NON-ZERO when the latest expected day is missing/short (leaguelogs: profiles/day;
  news: recency). Rely on GitHub Actions' built-in workflow-failure email as the alert (confirm channel with
  Will). Optional: a webhook (Slack/push) step if richer alerting is wanted.

Part 4 — batching (only if warranted):
- If hosted run time/egress is high, switch the supabase backend from upload-after-each-write to flush-once at
  end-of-run (one upload per series). Measure first; leave per-write if it's cheap.

Part 5 — prove it:
- Run a rolling two-week soak on the hosted, hardened collectors; the coverage report is the >=95% evidence.
  Note the GitHub-cron delay/skip + the post-DST ~1h ET shift in the coverage expectations.

Follow SESSION_GUIDE: fresh worktree, worktree-setup.sh, 3-commit cap, update STATUS.md, close/merge, push.
Suggested commits: (1) metadata sidecar + catch-up retry cron; (2) coverage gate + alert wiring (+ batching if
needed); (3) the two-week soak result + STATUS. Show me: a coverage report over the soak window and a
deliberately-forced miss producing an alert.

Close: update STATUS.md (P1 COMPLETE: collectors hosted + timestamped + retried + alerted, >=95% over 2 weeks;
next = P2 go-live 2026). Merge/push.
```

## Definition of done (S2 → closes P1)
✅ Every fetch is **timestamped** (metadata sidecar); a **catch-up retry** recovers a missed primary run; a
missed/short day **fails loudly** and reaches Will (native workflow-failure email, or the confirmed channel);
uploads are batched if run-time/egress warranted it; and a **rolling two-week soak proves ≥95% coverage** on
the hosted collectors. Scope stayed collection-only. STATUS updated → **P1 COMPLETE, P2 next.**

## Notes / gotchas
- **The soak is calendar time.** Two weeks of hosted runs is the gate — so the earlier the S1 cutover lands,
  the earlier P1 truly closes. With ~6 weeks to Week 1, this is comfortable but not something to sit on.
- **Idempotency is the safety net for retry** — the catch-up run is only safe because the collectors de-dup by
  date (S1 verified). Keep it that way; don't let a retry double-append.
- **Don't over-build the alert.** Native GitHub failure email covers the "a day was missed" need with zero new
  infra; add Slack/push only if you find yourself missing the email.
- **Ops awareness for later (not S2 scope):** GitHub disables scheduled workflows after ~60 days of repo
  inactivity — a non-issue during active V1 build, worth a note in P6 hardening for the quiet post-launch
  stretch.
- **After S2, P1 is done** — the 2026 market + news history is banking reliably, unblocking the live market
  read (P2) and the live AI outlook (P4).
