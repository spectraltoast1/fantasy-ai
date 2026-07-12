"""
Collector registry + dispatcher — the one consistent "run a banked daily collection" process.

Separation of concerns (with `_http`): `_http` makes each CALL resilient; this makes each COLLECTION
uniform. The `REGISTRY` declares each banked daily collector once — its run entrypoint, cadence, and the
data-layer series + coverage shape the health gate (`check_collectors`) certifies. The dispatcher is what
an external meter invokes: `python3 -m application.data.fetchers.run <name>`. It does NOT schedule
anything itself — cadence is *declared* here; the OS/CI *enforces* it (launchd now → GitHub Actions at
deployment, which will call this same dispatcher — so none of it is wasted by the hosting decision).

Only the banked, un-backfillable DAILY series live here (leaguelogs, news) — a missed run is permanent.
`sleeper` is on-demand across the app, not a metered series, so it is NOT a collector (it still shares
`_http` for resilience).

Usage:
    python3 -m application.data.fetchers.run --list
    python3 -m application.data.fetchers.run leaguelogs      # run one, then a freshness check
    python3 -m application.data.fetchers.run --all
"""

import argparse
import sys

from application.data import data_layer
from application.data.fetchers import leaguelogs, news

# One entry per banked daily collector. `coverage` is the shape the health gate certifies: which
# data-layer series, the per-day date column, and the completeness column (distinct count per day) —
# or `card_col=None` for an append-only series with no fixed daily cardinality (recency-checked instead).
REGISTRY = {
    "leaguelogs": {
        "run": leaguelogs.snapshot,
        "cadence": "daily",
        "series": "market_values",
        "coverage": {
            "read": data_layer.read_leaguelogs_market,
            "exists": data_layer.leaguelogs_market_exists,
            "date_col": "snapshot_date",   # pl.Date
            "card_col": "profile",         # distinct profiles/day = completeness
            "mode": "strict",
        },
    },
    "news": {
        "run": news.snapshot,
        "cadence": "daily",
        "series": "team_news_raw",
        "coverage": {
            "read": data_layer.read_team_news_raw,
            "exists": data_layer.team_news_raw_exists,
            "date_col": "collected_at",    # ISO string; date = first 10 chars
            "card_col": None,              # append-only → recency mode
            "mode": "recency",
        },
    },
}


def dispatch(name: str) -> None:
    """Run one collector through the uniform process: header → collect → post-run freshness check."""
    entry = REGISTRY[name]
    print(f"=== run collector '{name}' (cadence={entry['cadence']}, series={entry['series']}) ===")
    entry["run"]()
    # Lazy import avoids a module-load cycle (check_collectors imports REGISTRY from here).
    from application.data.fetchers import check_collectors
    print()
    check_collectors.freshness(name)


def main() -> None:
    p = argparse.ArgumentParser(description="Run a banked daily collector through the shared process.")
    p.add_argument("name", nargs="?", help="collector name (see --list)")
    p.add_argument("--all", action="store_true", help="run every registered collector")
    p.add_argument("--list", action="store_true", help="list registered collectors + cadence")
    args = p.parse_args()

    if args.list or (not args.name and not args.all):
        print("Registered banked daily collectors (the meter — launchd/GitHub Actions — calls these):")
        for n, e in REGISTRY.items():
            print(f"  {n:<12} cadence={e['cadence']:<6} series={e['series']}")
        return

    names = list(REGISTRY) if args.all else [args.name]
    unknown = [n for n in names if n not in REGISTRY]
    if unknown:
        print(f"unknown collector(s): {', '.join(unknown)}; known: {', '.join(REGISTRY)}")
        sys.exit(2)
    for n in names:
        dispatch(n)


if __name__ == "__main__":
    main()
