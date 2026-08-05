"""One-off record-parity check for the matchup-tie fix (P2, 2026-08-05).

NOT a gate — it needs two git refs and a live DB, so it cannot live in `check_*`. Run it once per
checkout and diff the two JSON files: every PRE-EXISTING record-bearing field must be identical.

    cd <main-checkout>     && PYTHONPATH=$PWD application/api/.venv/bin/python \
        project_management/sessions/v1/P2-Go_Live_2026/verify_record_parity.py /tmp/before.json
    cd <fix-checkout>      && PYTHONPATH=$PWD application/api/.venv/bin/python \
        project_management/sessions/v1/P2-Go_Live_2026/verify_record_parity.py /tmp/after.json
    diff /tmp/before.json /tmp/after.json      # expected: identical

It deliberately selects only the fields that existed BEFORE the fix. `load_standings` additionally
gains `ties` and `record` by design, so dumping the whole payload would show a diff that is a feature,
not a regression — the claim being tested is that no pre-existing VALUE moved.

Read-only: opens no writes and touches no parquet.
"""
import csv
import json
import os
import sys

from application.api import reads

out = {}
# Read the slate from the git-tracked CSV, not the parquet manifest: the API venv has no polars.
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(reads.__file__))))
with open(os.path.join(_root, "application/data/corpus/demo_slate.csv")) as fh:
    slices = sorted(csv.DictReader(fh), key=lambda r: (int(r["season"]), str(r["league_id"])))
# A spread of slices/seasons rather than one league: 2020 -> 2025, both scoring keys.
picks = [slices[0], slices[len(slices) // 3], slices[2 * len(slices) // 3], slices[-1]]

for s in picks:
    lid, season = str(s["league_id"]), int(s["season"])
    key = f"{lid}:{season}"
    weeks = reads.load_weeks(league_id=lid, season=season)["weeks"]
    if not weeks:
        continue
    for n in (weeks[0], weeks[len(weeks) // 2], weeks[-1], None):
        tag = f"{key}@{n}"
        try:
            meta = reads.load_league_meta(as_of_week=n, league_id=lid, season=season)
            standings = reads.load_standings(as_of_week=n, league_id=lid, season=season)
            out[f"meta {tag}"] = meta.get("record")
            out[f"standings {tag}"] = [
                {"rosterId": r["rosterId"], "wins": r["wins"], "losses": r["losses"],
                 "allPlayW": r["allPlayW"], "allPlayL": r["allPlayL"], "rank": r["rank"],
                 "playoffPct": r["playoffPct"], "allPlayPct": r["allPlayPct"]}
                for r in standings
            ]
            rid = standings[0]["rosterId"] if standings else None
            if rid is not None:
                td = reads.load_team_detail(rid, as_of_week=n, league_id=lid, season=season)
                out[f"teamdetail {tag}"] = td["stats"] if td else None
            mus = reads.load_matchups(as_of_week=n, league_id=lid, season=season)
            games = (mus or {}).get("games", [])
            out[f"matchups {tag}"] = [
                {"matchupId": g.get("matchupId"),
                 "records": [t["record"] for t in g.get("teams", [])]}
                for g in games
            ]
            if games and games[0].get("matchupId") is not None:
                md = reads.load_matchup_detail(games[0]["matchupId"], as_of_week=n,
                                               league_id=lid, season=season)
                out[f"matchupdetail {tag}"] = [t["record"] for t in md["teams"]] if md else None
        except Exception as e:  # noqa: BLE001 — a read that raises is itself a parity fact
            out[f"ERROR {tag}"] = f"{type(e).__name__}: {e}"

json.dump(out, open(sys.argv[1], "w"), indent=1, sort_keys=True, default=str)
print(f"wrote {len(out)} payload entries -> {sys.argv[1]}")
