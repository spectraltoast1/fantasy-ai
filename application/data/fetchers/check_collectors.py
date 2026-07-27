"""
Collector coverage/health gate — certify a banked daily series is trustworthy as an official source.

Reads ONLY the persisted series via `data_layer` (no network), so it's free + repeatable. Two banked,
un-backfillable series (a missed run is permanent, no historical endpoint): leaguelogs market values
(**strict** daily coverage — every day should carry every profile) and news team articles (append-only,
so **recency** — did a collection run recently, and were the latest run's feeds healthy).

Historical powered-off gaps are permanent, so failing on *any* past gap would fail forever and be
useless. The HARD certification criterion is a **recent window** (default last 7 completed days,
excluding today): non-zero if a recent day is missing/partial. The full-span history prints as evidence
(this is what reproduces the 63%/71% audit). `--today` is the monitoring check (is today present +
complete?), reused by `run.py`'s post-run hook.

Usage:
    python3 -m application.data.fetchers.check_collectors                 # certify all (exit 0 iff healthy)
    python3 -m application.data.fetchers.check_collectors leaguelogs      # one
    python3 -m application.data.fetchers.check_collectors --since 14      # recent window = last 14 days
    python3 -m application.data.fetchers.check_collectors --today         # freshness/monitoring only
"""

import argparse
import sys
from datetime import date, datetime, timedelta, timezone

import polars as pl

from application.data.fetchers.run import REGISTRY

RECENT_WINDOW_DAYS = 7      # the hard-certification window; permanent historical gaps don't fail forever
NEWS_STALE_DAYS = 2         # news recency tolerance (a run at least this often)


def _today() -> date:
    """UTC 'today' — the collectors bank snapshot_date / collected_at in UTC, so the gate must match
    (a local date.today() is off by a day whenever the machine's TZ is behind UTC)."""
    return datetime.now(timezone.utc).date()


def _daily_counts(df: pl.DataFrame, cov: dict) -> dict[str, int]:
    """{date_str -> completeness count for that day}: distinct `card_col` per day (strict), else row
    count (recency). Normalizes both a pl.Date column and an ISO-string column to 'YYYY-MM-DD'."""
    if df.is_empty():
        return {}
    day = pl.col(cov["date_col"]).cast(pl.Utf8).str.slice(0, 10).alias("d")
    agg = (pl.col(cov["card_col"]).n_unique() if cov["card_col"] else pl.len()).alias("n")
    g = df.group_by(day).agg(agg)
    return {r["d"]: r["n"] for r in g.iter_rows(named=True)}


def _span(start: str, end: str) -> list[str]:
    d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
    return [(d0 + timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]


def _recent_days(since_days: int) -> list[str]:
    """The last `since_days` COMPLETED days (ending yesterday — today may be mid-collection)."""
    today = _today()
    return [(today - timedelta(days=i)).isoformat() for i in range(since_days, 0, -1)]


def _age_days(iso_utc: str | None) -> float | None:
    """Whole+fractional days since an ISO-8601 UTC timestamp (None if absent/unparseable)."""
    if not iso_utc:
        return None
    try:
        ts = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - ts).total_seconds() / 86400


def _read_meta(cov: dict) -> dict | None:
    reader = cov.get("meta_read")
    return reader() if reader else None


def record_run(name: str) -> None:
    """Write the fetch-timestamp metadata sidecar after a collect (P1/S2).

    Records WHEN the run fetched — independent of net-new data, which matters for news: the series'
    'recency' reflects the last NEW article and lags in a quiet news week, whereas the last-RUN
    timestamp says a collection actually happened. Also banks the row count + (strict) today's
    completeness status. The coverage gate reads it back. Called post-collect by run.py's dispatch.
    """
    cov = REGISTRY[name]["coverage"]
    if not cov.get("meta_write"):
        return
    df = cov["read"]()
    counts = _daily_counts(df, cov)
    today = _today().isoformat()
    got = counts.get(today, 0)
    if cov["mode"] == "strict":
        expected = max(counts.values()) if counts else 0
        status = "ok" if got and got >= expected else "partial"
    else:
        expected = None            # append-only: no fixed daily cardinality
        status = "ok"              # the run completed; net-new (may be 0 in a quiet week) is today_count
    cov["meta_write"]({
        "series": REGISTRY[name]["series"],
        "last_fetch_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "as_of_date": today,
        "rows": int(df.height),
        "today_count": int(got),
        "expected": (int(expected) if expected is not None else None),
        "status": status,
    })


def _certify_strict(name: str, cov: dict, since_days: int) -> bool:
    counts = _daily_counts(cov["read"](), cov)
    if not counts:
        print(f"  {name}: series empty — FAIL")
        return False
    days = sorted(counts)
    span = _span(days[0], days[-1])
    expected = max(counts.values())                      # a "full" day = every profile present
    complete = sum(1 for d in span if counts.get(d, 0) == expected)
    partial = sum(1 for d in span if 0 < counts.get(d, 0) < expected)
    missing = sum(1 for d in span if counts.get(d, 0) == 0)
    print(f"  {name}: span {span[0]}→{span[-1]} ({len(span)}d), expected {expected}/day")
    print(f"    full-span: {complete} complete · {partial} partial · {missing} missing  "
          f"→ {100 * complete / len(span):.0f}% complete / {100 * (complete + partial) / len(span):.0f}% any-data")

    recent = _recent_days(since_days)
    bad = [d for d in recent if counts.get(d, 0) < expected]
    ok = not bad
    detail = "all present + complete" if ok else ", ".join(
        f"{d}={'missing' if counts.get(d, 0) == 0 else f'{counts[d]}/{expected}'}" for d in bad)
    print(f"    recent {since_days}d (excl. today): {detail}  {'PASS' if ok else 'FAIL'}")

    meta = _read_meta(cov)   # P1/S2 sidecar: report last-run age + status; fail on an error status
    if meta:
        age = _age_days(meta.get("last_fetch_utc"))
        age_s = f"{age:.1f}d ago" if age is not None else "?"
        print(f"    last RUN {meta.get('last_fetch_utc')} ({age_s}), status={meta.get('status')}, "
              f"rows={meta.get('rows')}")
        if meta.get("status") == "error":
            ok = False
    else:
        print("    metadata: (no sidecar yet — pre-S2 history or not yet run)")
    return ok


def _certify_recency(name: str, cov: dict, stale_days: int) -> bool:
    df = cov["read"]()
    counts = _daily_counts(df, cov)
    meta = _read_meta(cov)

    # P1/S2: prefer the sidecar's last-RUN timestamp as the recency signal. The series' article-recency
    # reflects the last NEW article, which lags in a quiet news week even though runs are still happening
    # — so gating on it would false-alarm. Fall back to article-recency only when no sidecar exists.
    if meta and meta.get("last_fetch_utc"):
        age = _age_days(meta["last_fetch_utc"])
        ok = age is not None and age <= stale_days and meta.get("status") != "error"
        age_s = f"{age:.1f}d ago" if age is not None else "?"
        print(f"  {name}: last RUN {meta['last_fetch_utc']} ({age_s}), status={meta.get('status')}  "
              f"{'PASS' if ok else f'STALE (>{stale_days}d) / ERROR'}")
    elif not counts:
        print(f"  {name}: series empty + no run metadata — FAIL")
        return False
    else:
        last = sorted(counts)[-1]
        days_since = (_today() - date.fromisoformat(last)).days
        ok = days_since <= stale_days
        print(f"  {name}: (no sidecar) {len(counts)} collection day(s), last article {last}, "
              f"{days_since}d ago  {'PASS' if ok else f'STALE (>{stale_days}d)'}")

    # Soft evidence: net-new articles on the latest date. NOTE the store is append-only, so this counts
    # only NET-NEW articles (not which feeds ran) — feed health (the 2/3 floor) is reported live by the
    # collector at snapshot time, and can't be reliably reconstructed from the store.
    if counts:
        last = sorted(counts)[-1]
        latest = df.filter(pl.col(cov["date_col"]).cast(pl.Utf8).str.slice(0, 10) == last)
        n_teams = latest.select("team").n_unique()
        print(f"    latest article date {last}: {latest.height} net-new article(s) across {n_teams} "
              f"team(s) (append-only — net-new only, not feed health)")
    return ok


def certify(name: str, *, since_days: int) -> bool:
    cov = REGISTRY[name]["coverage"]
    if not cov["exists"]():
        print(f"  {name}: no series on disk — FAIL")
        return False
    if cov["mode"] == "strict":
        return _certify_strict(name, cov, since_days)
    return _certify_recency(name, cov, NEWS_STALE_DAYS)


def freshness(name: str) -> None:
    """Monitoring: is TODAY present + complete? A warning (not a hard gate) — used post-run + by --today."""
    cov = REGISTRY[name]["coverage"]
    if not cov["exists"]():
        print(f"  ⚠ {name}: no series on disk yet")
        return
    counts = _daily_counts(cov["read"](), cov)
    today = _today().isoformat()
    if cov["mode"] == "strict":
        expected = max(counts.values()) if counts else 0
        got = counts.get(today, 0)
        if got == 0:
            print(f"  ⚠ {name}: no snapshot for today ({today}) yet")
        elif got < expected:
            print(f"  ⚠ {name}: today PARTIAL — {got}/{expected} profiles ({today})")
        else:
            print(f"  ✓ {name}: today complete — {got}/{expected} profiles ({today})")
    else:
        last = max(counts) if counts else None
        if last == today:
            print(f"  ✓ {name}: collected today ({today})")
        else:
            print(f"  ⚠ {name}: last collection {last} — nothing collected today ({today})")


def main() -> None:
    p = argparse.ArgumentParser(description="Certify banked daily collectors' coverage/health.")
    p.add_argument("name", nargs="?", help="collector name (default: all)")
    p.add_argument("--since", type=int, default=RECENT_WINDOW_DAYS,
                   help=f"recent-window size in days for the hard criterion (default {RECENT_WINDOW_DAYS})")
    p.add_argument("--today", action="store_true", help="freshness/monitoring only (is today done?)")
    args = p.parse_args()

    names = [args.name] if args.name else list(REGISTRY)
    unknown = [n for n in names if n not in REGISTRY]
    if unknown:
        print(f"unknown collector(s): {', '.join(unknown)}; known: {', '.join(REGISTRY)}")
        sys.exit(2)

    if args.today:
        print("=== collector freshness (today) ===")
        for n in names:
            freshness(n)
        return

    print(f"=== collector coverage gate (recent window = {args.since}d) ===")
    results = [certify(n, since_days=args.since) for n in names]   # certify ALL (no short-circuit)
    ok = all(results)
    print()
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} — recent coverage "
          f"{'is healthy' if ok else 'has gaps (see FAIL lines)'}.")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
