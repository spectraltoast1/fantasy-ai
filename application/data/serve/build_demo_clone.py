"""Generate the public demo league — an anonymised clone of a frozen slice (P5/S2d).

    application/venv/bin/python -m application.data.serve.build_demo_clone
    application/venv/bin/python -m application.data.serve.build_demo_clone --check

**Why this exists.** Until S2d the public demo *was* LoRP 2025 — Will's real league, with ten real
managers' Sleeper handles on a page anyone could load. None of them signed up for anything. It is
also his live lineage, so once his 2026 league is onboarded the catalog fuses the two into one
switcher entry and the demo becomes unreachable from his own account (S2b audit, F3).

**GENERATED, not inserted, and that distinction is the design.** A script that INSERTs rows under a
new id works right up until the next full ``--load``, which DROPs and recreates every table it names
— and then the public landing page silently renders blank, for a person changing the schema who had
no reason to be thinking about the demo. That is exactly how ``ros_player_band`` lost its RLS. So the
clone is an *artifact the loader re-materialises*, not rows typed in once: this module writes
parquet, ``build_db`` loads it like any other slice, and a ``--load`` reproduces the clone from
source rather than from anyone's memory.

**It recomputes NOTHING.** It reads finished output rows and swaps identifiers and names — the same
"(1+2) becomes 3" a hand-written copy would do. The frozen corpus is read, never written; the clone
lands beside it under its own ``league_id``.

**Where it writes: the standard ``data_layer`` paths, keyed on the new id, in both trees** — the raw
Sleeper tree for ``teams`` / ``lineup_slots`` / ``league_settings``, ``derived/`` for the rest. That
is what makes ``build_db.DATASETS`` need zero changes: the path lambdas resolve by ``league_id``, so
a league whose files sit where a league's files go loads with no special-casing. The alternative —
per-table path overrides for one league — would put a permanent ``if demo`` inside the publish seam.

**What it does NOT do:** populate the AI outlook. ``ros_synthesis`` and ``ros_player_band`` have no
2025 file, so skip-if-absent leaves those panels empty by construction — which is the deferred
behaviour, achieved by doing nothing. P4 retires the placeholder anyway.
"""

from __future__ import annotations

import argparse
import shutil

import polars as pl

from application.data import data_layer as dl
from application.data.serve import build_db as B

# --- what the clone IS -----------------------------------------------------------------------
# Source: the frozen LoRP 2025 slice at its week-5 join freeze.
SRC_LEAGUE = "1182101676608823296"
SRC_SEASON = 2025
SRC_SCORING_KEY = "ppr"

# Identifiers a human never sees, so they are deliberately NOT Sleeper-shaped (an 18-19 digit
# snowflake). Anything that mistakes these for a real league id fails loudly and immediately.
CLONE_LEAGUE = "DEMO-2025"
CLONE_LINEAGE = "DEMO"

# The league name says what it is. This is a deliberate departure from "make it look real", and it
# resolves the tension in that rule: realistic TEAM names stop the demo reading as a mock-up, while a
# realistic LEAGUE name would invite "whose league is this?" — the exact question this exists to stop.
CLONE_NAME = "DEMO League"

# --- the anonymisation map -------------------------------------------------------------------
# A COMMITTED LITERAL, not a hash and not a generated scheme. Ten entries, reviewable in ten seconds
# before they go on the landing page — a hash could produce something offensive or accidentally real
# and could not be eyeballed. It is also what makes the check total: every displayed name in the
# clone must appear in this dict's VALUES, and no value may equal any key. That is a positive
# assertion (the mapping was APPLIED) rather than an absence check for ten known strings, which could
# only ever prove those ten are gone.
#
# Realistic invented names, because the demo IS the landing page and a mock-up answers the trust
# question the wrong way. Player names are NOT here and are never rewritten — they are real NFL
# players and they are the demo's actual content. Anonymise the managers, never the roster.
OWNER_NAMES = {
    "TheDundle":      "mackzilla",
    "reeschilling":   "hollowpoint7",
    "jmtimmel":       "jtparker",
    "Bski":           "dmoss",
    "Mr1854":         "coachcarver",
    "Febreze15":      "ninebelow",
    "yentk":          "rjhalstead",
    "spectraltoast1": "quietriot88",
    "megandaniel92":  "samvoss",
    "dschill8":       "bteller",
}

# Keyed by roster_id, because roster 4's team_name is NULL in the source and a null key is no key.
# The clone fills it: a blank team name on the public landing page reads as broken, and a NULL has no
# entry in the value set the total check runs against.
TEAM_NAMES = {
    1:  "No Punt Intended",
    2:  "Cool Runnings",
    3:  "Bijan Mustard",
    4:  "The Replacements",     # NULL in the source
    5:  "Scoop and Score",
    6:  "Sunday Scaries",
    7:  "Forty Yard Trash",
    8:  "Certified Lads",
    9:  "Waiver Wire Fire",
    10: "Comeback Szn",
}

# owner_id is an internal join key (teams <-> manager_dossiers) and reaches NO payload — verified:
# it appears nowhere in application/api/ or the frontend. So it follows the identifier rule, not the
# display rule: synthetic, obviously non-Sleeper, fails loudly if anything treats it as real.
OWNER_IDS = {real: f"DEMO-OWNER-{i:02d}" for i, real in enumerate(sorted(OWNER_NAMES), start=1)}


def _display_values() -> set[str]:
    """Every string the clone is allowed to show for a manager or a team."""
    return set(OWNER_NAMES.values()) | set(TEAM_NAMES.values())


# --- the rewrite -----------------------------------------------------------------------------

def _rekey_and_anonymise(df: pl.DataFrame) -> pl.DataFrame:
    """Re-key the league and rewrite whichever identity columns this frame has; everything else
    passes through untouched.

    Identity rewriting applies to `teams` and `manager_dossiers` — the only two served tables
    carrying manager or team identities. (`season` and `player_signal` carry PLAYER names; those are
    real and stay.) The dossiers' seven free-text LLM prose fields were checked and carry no handles
    or team names, only behavioural prose, so they need no rewriting — but `--check` re-asserts that
    rather than trusting it, because a future re-generation of those fields could change the answer.

    **The re-key is not cosmetic.** `schedule` carries its own `league_id` column (B1), and
    `build_db._copy_slice` asserts that column equals the slice it is loading before dropping it. A
    clone that kept the source id would fail the load — which is how `--check` found this: it swept
    every cloned parquet for the source league id, not just the ones with names in them.
    """
    out = df
    if "league_id" in out.columns:
        out = out.with_columns(pl.lit(CLONE_LEAGUE).cast(out.schema["league_id"]).alias("league_id"))
    if "owner_name" in out.columns:
        out = out.with_columns(pl.col("owner_name").replace_strict(OWNER_NAMES, default=None))
    if "owner_id" in out.columns and "owner_name" in df.columns:
        # Keyed off the ORIGINAL owner_name, so teams and dossiers cannot drift apart.
        out = out.with_columns(
            df["owner_name"].replace_strict(OWNER_IDS, default=None).alias("owner_id"))
    if "team_name" in out.columns and "roster_id" in out.columns:
        out = out.with_columns(pl.col("roster_id").replace_strict(TEAM_NAMES, default=None)
                               .cast(pl.Utf8).alias("team_name"))
    return out


def _catalog_row() -> pl.DataFrame:
    """The clone's one row for the served `league_catalog` table.

    `is_mine` FALSE and `viewer_roster_id` NULL are both load-bearing: they are the two independent
    routes to a "you" highlight. A seat here would be honoured by `authorize_slice` as a
    caller-supplied viewer regardless of names, and `resolve_viewer`'s fallback matches `MY_USERNAME`
    against `teams.owner_name` — which the map has already made impossible. Both must hold.
    """
    src = dl.read_demo_manifest().filter(
        (pl.col("league_id") == SRC_LEAGUE) & (pl.col("season") == SRC_SEASON)).row(0, named=True)
    return pl.DataFrame([{
        "lineage_id": CLONE_LINEAGE,
        "league_id": CLONE_LEAGUE,
        "season": SRC_SEASON,
        "name": CLONE_NAME,
        "scoring_key": SRC_SCORING_KEY,
        "num_teams": src["num_teams"],
        "is_mine": False,
        "previous_league_id": None,
        "viewer_roster_id": None,
        # Panel gating copied from the source: the clone has exactly the same reads available, and
        # `market` is still gated OFF downstream by the read's own is_cross_time flag.
        "panels_market": src["panels_market"],
        "panels_ros": src["panels_ros"],
        "panels_manager": src["panels_manager"],
    }], schema={k: dl.read_demo_manifest().schema[k] for k in dl._DEMO_MANIFEST_COLS})


def generate() -> dict:
    """Write the clone. Deterministic: same inputs -> same values, every run."""
    report: dict = {"league_id": CLONE_LEAGUE, "written": [], "skipped": []}

    for ds in B.DATASETS:
        src = ds.path(SRC_SEASON, SRC_LEAGUE, SRC_SCORING_KEY)
        dst = ds.path(SRC_SEASON, CLONE_LEAGUE, SRC_SCORING_KEY)
        if not src.exists():
            report["skipped"].append((ds.table, "no source parquet"))
            continue
        if src == dst:
            # A scoring-keyed dataset (projection_consensus, ros_player_band): shared across every
            # league and stamped per slice at load. The clone inherits it by being in the load span;
            # copying it would be writing the same bytes to the same path.
            report["skipped"].append((ds.table, "scoring-keyed, shared"))
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        df = pl.read_parquet(src)
        anon = _rekey_and_anonymise(df)
        if anon.equals(df):
            shutil.copy2(src, dst)          # byte-faithful when nothing needed rewriting
        else:
            anon.write_parquet(dst)
        report["written"].append((ds.table, anon.height))

    dl.write_synthetic_catalog(_catalog_row())
    report["catalog"] = str(dl._synthetic_catalog_path())
    return report


# --- the check -------------------------------------------------------------------------------

_failures: list[str] = []


def _ok(msg: str) -> None:
    print(f"  ok  {msg}")


def _fail(msg: str) -> None:
    _failures.append(msg)
    print(f"  ✗   {msg}")


def check() -> int:
    """Assert the clone is anonymous, is not the source, and is invisible to the engine."""
    print("=== check_demo_clone: is the public demo actually anonymous? ===")

    print("\nthe map itself")
    overlap = _display_values() & (set(OWNER_NAMES) | set(_source_team_names()))
    if overlap:
        _fail(f"a map VALUE equals a real name: {sorted(overlap)} — that name would survive")
    else:
        _ok("no fake name collides with any real one")
    if len(set(OWNER_NAMES.values())) != len(OWNER_NAMES):
        _fail("duplicate fake owner names — two managers would render identically")
    elif len(set(TEAM_NAMES.values())) != len(TEAM_NAMES):
        _fail("duplicate fake team names")
    else:
        _ok(f"{len(OWNER_NAMES)} owners + {len(TEAM_NAMES)} teams, all distinct")

    print("\nthe clone's displayed names are TOTAL against the map's value set")
    allowed = _display_values()
    for table, path in (("teams", dl._sleeper_teams_path(SRC_SEASON, CLONE_LEAGUE)),
                        ("manager_dossiers", dl._manager_dossiers_path(SRC_SEASON, CLONE_LEAGUE))):
        if not path.exists():
            _fail(f"{table}: the clone has no parquet — run without --check first")
            continue
        df = pl.read_parquet(path)
        shown = {v for c in ("owner_name", "team_name") if c in df.columns
                 for v in df[c].to_list() if v is not None}
        stray = shown - allowed
        nulls = sum(df[c].null_count() for c in ("owner_name", "team_name") if c in df.columns)
        if stray:
            _fail(f"{table}: {sorted(stray)} are NOT in the map's value set — unmapped identities")
        elif nulls:
            _fail(f"{table}: {nulls} NULL name(s) — a blank name is not an anonymised one")
        else:
            _ok(f"{table}: every displayed name is a mapped value ({len(shown)} distinct)")

    print("\nno real identity survives anywhere in the clone's parquet")
    real = set(OWNER_NAMES) | set(_source_team_names()) | {SRC_LEAGUE}
    for ds in B.DATASETS:
        p = ds.path(SRC_SEASON, CLONE_LEAGUE, SRC_SCORING_KEY)
        if not p.exists() or "derived/scoring" in str(p):
            continue
        df = pl.read_parquet(p)
        hits = sorted({r for c in df.columns if df.schema[c] == pl.Utf8
                       for v in df[c].drop_nulls().unique().to_list()
                       for r in real if r in v})
        if hits:
            _fail(f"{ds.table}: real identities present: {hits}")
    if not [f for f in _failures if "real identities present" in f]:
        _ok("zero real handles, team names or source league ids across every cloned table")

    print("\nno 'you' highlight for a signed-out visitor")
    cat = dl.read_synthetic_catalog()
    if cat.height and cat["viewer_roster_id"].null_count() == cat.height:
        _ok("catalog seat is NULL (a seat would be honoured as a caller-supplied viewer)")
    else:
        _fail("the clone's catalog row pins a viewer_roster_id — every visitor gets a 'you'")
    if cat.height and not any(cat["is_mine"].to_list()):
        _ok("is_mine is False")
    else:
        _fail("the clone is flagged is_mine")

    print("\nthe clone is INVISIBLE to the engine (it is a serve-layer artifact)")
    _check_absent_from_engine()

    print("\nthe predicate agrees with the artifact")
    ids = set(dl.read_synthetic_catalog()["league_id"].to_list())
    if ids == set(dl.SYNTHETIC_LEAGUE_IDS):
        _ok(f"SYNTHETIC_LEAGUE_IDS == the synthetic catalog's ids ({sorted(ids)})")
    else:
        _fail(f"predicate {sorted(dl.SYNTHETIC_LEAGUE_IDS)} != catalog {sorted(ids)} — a producer "
              "would guard the wrong set")

    if _failures:
        print(f"\n✗ {len(_failures)} FAILURE(S):")
        for f in _failures:
            print(f"  - {f}")
        return 1
    print("\nALL GREEN — the demo carries no real manager, no real team, no 'you', and appears in "
          "zero engine artifacts.")
    return 0


def _source_team_names() -> set[str]:
    df = pl.read_parquet(dl._sleeper_teams_path(SRC_SEASON, SRC_LEAGUE))
    return {v for v in df["team_name"].to_list() if v}


def _check_absent_from_engine(extra_ids: set[str] | None = None) -> None:
    """The clone id must appear in ZERO engine-side artifacts. A boundary nothing enforces is a
    convention, and conventions erode."""
    ids = set(dl.SYNTHETIC_LEAGUE_IDS) | (extra_ids or set())
    checks = [
        ("demo_manifest.parquet (the frozen corpus slate)",
         lambda: set(dl.read_demo_manifest()["league_id"].to_list())),
        ("corpus_manifest.parquet (the 271-league corpus)",
         lambda: set(dl.read_corpus_manifest()["league_id"].to_list())),
        ("demo_slate.csv",
         lambda: set(pl.read_csv(B._REPO_ROOT / "application/data/corpus/demo_slate.csv",
                                 schema_overrides={"league_id": pl.Utf8})["league_id"].to_list())),
        # The L0 registry is a projection of the corpus manifest unioned with the live config league,
        # so a synthetic id cannot reach it. Asserted rather than guarded: there is no producer path
        # to block, and a check that bites is worth more than a branch that never runs.
        ("leagues.parquet (the L0 registry)",
         lambda: set(dl.read_leagues()["league_id"].cast(str).to_list())),
    ]
    for label, get in checks:
        try:
            present = get() & ids
        except Exception as exc:  # noqa: BLE001 — an unreadable artifact is a skip, not a pass
            print(f"  --  {label}: SKIPPED ({exc})")
            continue
        if present:
            _fail(f"{label} contains {sorted(present)} — the clone has leaked into the engine")
        else:
            _ok(f"{label}: absent")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="assert the clone, do not regenerate it")
    ap.add_argument("--prove-bites", action="store_true",
                    help="inject the clone id into the engine check and require it to FAIL")
    a = ap.parse_args()

    if a.prove_bites:
        print("=== prove-it-bites: a clone id in an engine artifact must be caught ===")
        before = len(_failures)
        # The real artifacts are untouched; the id under test is one the check is told to look for,
        # and demo_slate.csv genuinely contains it — so a passing check here would mean the sweep
        # never looked.
        _check_absent_from_engine(extra_ids={SRC_LEAGUE})
        caught = len(_failures) - before
        del _failures[before:]
        print(f"\n{'  ok  ' if caught else '  ✗   '}the engine sweep catches {caught} leak(s), as it must")
        return 0 if caught else 1

    if a.check:
        return check()

    rep = generate()
    print(f"=== generated {rep['league_id']} ===")
    for t, n in rep["written"]:
        print(f"  wrote   {t:22s} {n:>6d} rows")
    for t, why in rep["skipped"]:
        print(f"  skipped {t:22s} ({why})")
    print(f"  catalog {rep['catalog']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
