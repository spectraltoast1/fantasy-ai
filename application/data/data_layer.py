import json
import os
import time
from pathlib import Path

import polars as pl

_HERE = Path(__file__).resolve().parent
_SNAPSHOT_DIR = _HERE / "snapshots"
_CACHE_DIR = _HERE / "cache"


# --- Snapshot storage backend (P1/S1: hosted collectors write off-laptop) ---
# The daily "bank it or lose it" collectors (leaguelogs, news) historically wrote parquet to
# the local `snapshots/` tree. A hosted/diskless CI runner has no persistent disk, so the
# raw-collection write/read is routed through an env-selected backend: `local` (the laptop —
# unchanged, the default) or `supabase` (a durable Supabase Storage bucket, S3-compatible).
# ONE seam, both environments — the same fetcher code writes to the bucket in CI and to local
# `snapshots/` on a laptop. Only the two raw collector series are wired through it (see below);
# every other read/write in this module keeps its direct local-path IO. `backend` is chosen
# env-first (mirrors application/api/settings.py) so nothing changes unless SNAPSHOT_BACKEND is
# set — which happens only in the collector CI job.

def _snapshot_conf(name: str):
    """Return env var `name` first, else `application.config.<name>`, else None."""
    val = os.environ.get(name)
    if val:
        return val
    try:
        from application import config
    except Exception:
        return None
    return getattr(config, name, None)


def _require_conf(name: str) -> str:
    val = _snapshot_conf(name)
    if not val:
        raise RuntimeError(
            f"{name} is required for the 'supabase' snapshot backend; "
            f"set it as an env var (CI secret) or in application/config.py."
        )
    return str(val)


def snapshot_backend() -> str:
    """The active snapshot backend: 'local' (default) or 'supabase'."""
    return (_snapshot_conf("SNAPSHOT_BACKEND") or "local").lower()


# --- The store boundary (P5/S3: the laptop stops being infrastructure) ------------------------
# ADR: context/appendices/store-boundary.md (ACCEPTED, option (b)). Data flows ONE DIRECTION:
# the laptop authors the shared substrate, every other machine reads it.
#
# The rule is NOT "laptop vs worker". There are already three machines that run this pipeline —
# the laptop, the Fly worker, and the GitHub Actions runner — so the boundary is stated as
# **one writer, everything else reads**. Anything that is not the authoring laptop sets
# STORE_ROLE=worker and gets a read-only view of the shared substrate.
#
# Why this is enforced HERE. The CODING_BIBLE names data_layer "the only code that knows where
# data lives", so it is the one seam every write already passes through — the same shape as
# S2b's authorization seam: one predicate, one place, no caller repeats it. Enforcement by
# OMISSION was checked and is unavailable: `data/corpus/` holds both `harvest`/`compute_spine`
# (which the worker must run) and the ledger writers, so the package straddles the boundary and
# cannot simply be left out of the worker image.
#
# Why a raise and not a read-only mount. An OSError surfacing from inside a transform reads as a
# bug and sends the next person debugging filesystem permissions. A raise names the boundary,
# the reason and the remedy — this is what Will reads at the annual re-tune, at 2am, in February.
#
# ALLOW-LIST, not deny-list. The worker may write only what the ADR grants it; every other
# destination raises, including ones nobody has classified yet and any writer added later. That
# is the same default-deny posture S2b established for reads, applied to writes.

class StoreBoundaryError(RuntimeError):
    """A machine that does not own an artifact tried to write it. See the store-boundary ADR."""


# The artifacts the AUTHORING LAPTOP owns — every one of these raises under STORE_ROLE=worker.
# Grouped by why, because the reasons are different and a future reader needs the reason more
# than the list. This constant is THE single source of truth for the set: the guard consumes it,
# and so do the three rescore gates that each used to carry their own hand-maintained copy.
#
# Those three copies had already drifted, which is what turns this from tidiness into a bug fix:
# check_debias had 4 entries, check_band_honesty 5, check_center_shrink 6 — so two of the three
# would NOT have caught a `write_center_gap` call during a rescore.
LAPTOP_OWNED_WRITERS: tuple[str, ...] = (
    # derived/ledger — the certification spine. Immutable, append-only, never leaves the laptop.
    "write_predictions", "write_outcomes", "write_resolutions", "write_engine_scorecard",
    "write_tune_proposals", "write_center_gap",
    # derived/scoring — SHARED by every league on a scoring key, and built under engine
    # constants, which are propose-only and human-promoted. A machine rebuilding these
    # unattended is promoting constants for every user at once.
    "write_projection_consensus", "write_ros_player_band",
    # derived/adp_points_curve — the leak-free per-holdout curve; corpus-shaped, not per-league.
    "write_adp_points_curve",
    # The corpus manifests — corpus selection is a human, versioned decision.
    "write_corpus_discovery", "write_corpus_manifest", "write_corpus_two_way_flags",
    # The registries. All three OVERWRITE the whole file on a fixed schema, so a worker calling
    # one would replace the shared artifact with only what that machine knows. The SHAPE of the
    # writer is what is wrong for a worker, not its owner — which is why P5/S4a could add a
    # twelfth, WORKER-owned destination (`write_connected_league`) without moving this line: it
    # replaces exactly one (league_id, season) row, so there is no shrink to cause.
    #
    # `write_leagues` is NOT on the connected-league path and was not touched in S4a. Every
    # reader of leagues.parquet (`_active_league`, `_active_league_any`, `league_resolver`)
    # filters `is_mine` first, so a stranger row would be read by nothing — the wall S4 hit was
    # the CATALOG, not the registry. See context/appendices/store-boundary.md.
    "write_leagues", "write_demo_manifest", "write_synthetic_catalog",
    # The PINNED players snapshot is an immutable versioned event (it already refuses to
    # overwrite). The routine `write_sleeper_players` / `write_player_id_map` refresh is NOT
    # here: the worker fetches from Sleeper and must be able to keep its own cache current.
    "write_sleeper_players_snapshot",
)


def store_role() -> str:
    """The active store role: 'laptop' (default, authors the shared substrate) or 'worker'.

    Read PER CALL and deliberately not memoised, unlike `_store()`'s lazy singleton. That cache
    exists to avoid reconstructing a boto3 client; there is nothing to construct here, and a
    memoised flag would make an in-process env flip a no-op — which is exactly how a guard test
    passes while proving nothing.
    """
    return (_snapshot_conf("STORE_ROLE") or "laptop").lower()


# The three reasons, written once. Each laptop-owned writer passes the pair that applies to it.
_WHY_LEDGER = ("derived/ledger is the immutable certification spine the engine is graded against; "
               "it is append-only and never leaves the authoring machine.")
_FIX_LEDGER = "run the backfill/rescore on the laptop. Nothing on the worker needs the ledger."

_WHY_SCORING = ("derived/scoring is SHARED by every league on this scoring key, and it is built "
                "under engine constants, which are propose-only and human-promoted. Rebuilding it "
                "here would promote constants for every user at once, unattended.")
_FIX_SCORING = ("rebuild it on the laptop and push it up to the worker's volume BEFORE onboarding "
                "leagues on this scoring key — e.g. `python -m application.data.transforms."
                "compute_ros_player_band --season <YYYY> --scoring-key <key>`, then re-seed.")

_WHY_REGISTRY = ("this is a shared registry/manifest written as a WHOLE-FILE overwrite, so a "
                 "machine that knows about fewer leagues than the laptop would silently shrink it.")
_FIX_REGISTRY = "run it on the laptop and re-seed the worker's volume."


def canonical_rows(rows: list[dict]) -> list[str]:
    """Order-insensitive canonical form of a row set — a sorted multiset of JSON-encoded rows. JSONB
    columns arrive as Python objects; dates/Decimals fall back to str. Robust to COPY's row-order
    nondeterminism and to empty tables (which polars sort-by-all-columns cannot handle).

    Lives here as of P5/S3 so both consumers share ONE comparator: ``check_scoped_reload`` (whose
    parity oracle this was written for) and the store-boundary band check below. The dependency
    could only run this way — ``check_scoped_reload`` imports ``build_db``, which imports this
    module — so moving it down was the only way to avoid a second copy.

    **Value equality, never byte equality.** Polars' parquet writer is physically non-deterministic,
    so a byte or frame comparison false-positives on layout, column order and row order that carry
    no information. Sorting the keys neutralises column order; sorting the list neutralises row
    order; ``default=str`` keeps dates and Decimals comparable.
    """
    return sorted(json.dumps(r, sort_keys=True, default=str) for r in rows)


def rows_equal(a: list[dict], b: list[dict]) -> bool:
    return canonical_rows(a) == canonical_rows(b)


def _verify_band_unchanged(df: "pl.DataFrame", path: Path, season: int, scoring_key: str) -> None:
    """The worker's read-only check on the shared band — see ``write_ros_player_band``.

    Returns quietly when the recomputed band matches the seeded one; raises ``StoreBoundaryError``
    when it is stale or absent, with the operator step in the message.
    """
    rebuild = (f"on the LAPTOP run `application/venv/bin/python -m "
               f"application.data.transforms.compute_ros_player_band --season {season} "
               f"--scoring-key {scoring_key}`, then re-seed the worker's volume "
               f"(see OPERATIONS.md → 'Seeding the worker volume').")
    if not path.exists():
        raise StoreBoundaryError(
            f"write_ros_player_band() is refused on this machine: STORE_ROLE=worker.\n"
            f"  The rest-of-season band for {scoring_key} {season} is MISSING from this volume, so "
            f"there is nothing to verify against and the worker may not author it.\n"
            f"  {_WHY_SCORING}\n"
            f"  Remedy: {rebuild}"
        )
    on_disk = pl.read_parquet(path)
    if rows_equal(df.to_dicts(), on_disk.to_dicts()):
        return
    raise StoreBoundaryError(
        f"write_ros_player_band() is refused on this machine: STORE_ROLE=worker.\n"
        f"  The rest-of-season band for {scoring_key} {season} recomputes DIFFERENTLY here than the "
        f"copy on this volume ({on_disk.height} rows on disk vs {df.height} recomputed), so the "
        f"seeded substrate is STALE — most likely the engine constants moved (the annual re-tune) "
        f"and the volume has not been re-seeded since.\n"
        f"  {_WHY_SCORING}\n"
        f"  Remedy: {rebuild}\n"
        f"  Until then this worker will not refresh leagues on the {scoring_key} key. That refusal "
        f"is deliberate: a loud stop beats silently serving numbers built from a recipe nobody "
        f"approved."
    )


def _require_laptop(writer: str, what: str, remedy: str) -> None:
    """Refuse a laptop-owned write when this machine is not the laptop.

    `what` names the artifact and why it is shared; `remedy` is the runnable next step. Both are
    passed by the caller because a generic message ("permission denied") is what sends somebody
    debugging the filesystem instead of reading the boundary.
    """
    if store_role() != "worker":
        return
    raise StoreBoundaryError(
        f"{writer}() is refused on this machine: STORE_ROLE=worker.\n"
        f"  {what}\n"
        f"  The store boundary is one-directional — the laptop authors the shared substrate and "
        f"every other machine reads it (context/appendices/store-boundary.md).\n"
        f"  Remedy: {remedy}"
    )


class _LocalSnapshotStore:
    """The laptop / on-disk backend — the historical behavior, unchanged. `flush()` is a no-op."""

    def exists(self, path: Path) -> bool:
        return path.exists()

    def read_parquet(self, path: Path) -> pl.DataFrame:
        return pl.read_parquet(path)

    def write_parquet(self, df: pl.DataFrame, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(path)

    def read_bytes(self, path: Path) -> bytes:
        return path.read_bytes()

    def write_bytes(self, data: bytes, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def flush(self) -> None:
        return None


class _SupabaseSnapshotStore:
    """Durable object-store backend for the diskless CI collectors (Supabase Storage, S3-compatible).

    The runner's ephemeral disk is a *working copy*: an object is downloaded on first access (priming
    the read-modify-write append) and operated on locally exactly as the local backend does. Writes go
    to the working copy and mark the key *dirty*; **uploads happen once, at `flush()` (end of run)** —
    P1/S2's batching (a daily bank doesn't need per-item upload, and news wrote ~96×/run). A run that
    dies before `flush()` uploads nothing that run — the same-day catch-up cron re-collects (collectors
    de-dup by date), so nothing is lost. The object key is the snapshot path relative to `_SNAPSHOT_DIR`,
    so the on-disk hierarchy maps 1:1 to bucket keys. `boto3` is imported lazily so the local backend
    never needs it.
    """

    def __init__(self):
        import boto3  # lazy — only the CI backend pulls this in

        self._bucket = _require_conf("SUPABASE_STORAGE_BUCKET")
        endpoint = _snapshot_conf("SUPABASE_S3_ENDPOINT")
        if not endpoint:
            endpoint = _require_conf("SUPABASE_URL").rstrip("/") + "/storage/v1/s3"
        self._s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=_require_conf("SUPABASE_S3_ACCESS_KEY_ID"),
            aws_secret_access_key=_require_conf("SUPABASE_S3_SECRET_ACCESS_KEY"),
            region_name=_snapshot_conf("SUPABASE_S3_REGION") or "us-east-1",
        )
        self._dirty: set[Path] = set()   # working-copy paths written this run, uploaded on flush()

    def _key(self, path: Path) -> str:
        return str(Path(path).relative_to(_SNAPSHOT_DIR))

    def _download(self, path: Path) -> bool:
        """Fetch the object into the local working copy. True iff it exists remotely."""
        from botocore.exceptions import ClientError

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._s3.download_file(self._bucket, self._key(path), str(path))
            return True
        except ClientError as err:
            code = err.response.get("Error", {}).get("Code")
            if code in ("404", "NoSuchKey", "NoSuchBucket"):
                return False
            raise

    def exists(self, path: Path) -> bool:
        if path.exists():
            return True
        return self._download(path)  # prime the working copy on a hit

    def read_parquet(self, path: Path) -> pl.DataFrame:
        if not path.exists():
            self._download(path)
        return pl.read_parquet(path)

    def write_parquet(self, df: pl.DataFrame, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(path)
        self._dirty.add(path)   # uploaded on flush()

    def read_bytes(self, path: Path) -> bytes:
        if not path.exists():
            self._download(path)
        return path.read_bytes()

    def write_bytes(self, data: bytes, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self._dirty.add(path)   # uploaded on flush()

    def flush(self) -> None:
        """Upload every working copy written this run to the bucket, then clear the dirty set."""
        for path in sorted(self._dirty):
            self._s3.upload_file(str(path), self._bucket, self._key(path))
        self._dirty.clear()


_STORE = None


def _store():
    """The active snapshot store (lazy singleton — never constructs boto3 on the local backend)."""
    global _STORE
    if _STORE is None:
        _STORE = _SupabaseSnapshotStore() if snapshot_backend() == "supabase" else _LocalSnapshotStore()
    return _STORE


def flush_snapshots() -> None:
    """Upload any buffered snapshot writes to the durable store (no-op on the local backend).

    The supabase backend batches writes to a working copy and uploads once here (P1/S2). The collector
    dispatcher calls this at the end of a run, after the collect + metadata sidecar are written.
    """
    _store().flush()


# --- Player ID Map ---

def _player_id_map_path() -> Path:
    return _CACHE_DIR / "player_id_map.parquet"


def write_player_id_map(df: pl.DataFrame) -> None:
    """Write the gsis_id → sleeperPlayerId mapping to cache (overwrite).

    Refreshed on every nflreadpy fetch run (see fetchers/nfl_stats.py).
    """
    path = _player_id_map_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_player_id_map() -> pl.DataFrame:
    return pl.read_parquet(_player_id_map_path())


# --- Sleeper Players Registry ---

def _sleeper_players_path() -> Path:
    return _CACHE_DIR / "sleeper" / "players.parquet"


def write_sleeper_players(df: pl.DataFrame) -> None:
    """Cache the Sleeper /players/nfl registry (overwrite; current-state cache).

    The caller builds `df` — the fetcher normalises the endpoint down to the kept
    columns and constructs the frame with infer_schema_length=None (the mostly-null
    injury/depth-chart fields need a full scan to type correctly). This only persists it.
    """
    path = _sleeper_players_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_sleeper_players() -> pl.DataFrame:
    """Read the cached Sleeper /players/nfl registry.

    Raises FileNotFoundError if fetch_players() has not been run yet.
    """
    path = _sleeper_players_path()
    if not path.exists():
        raise FileNotFoundError(
            f"Sleeper players cache not found at {path}. "
            "Run: python3 -m application.data.fetchers.sleeper fetch-players"
        )
    return pl.read_parquet(path)


def sleeper_players_exists() -> bool:
    return _sleeper_players_path().exists()


def sleeper_players_age_seconds() -> float | None:
    """Age of the players cache in seconds, or None if it does not exist yet.

    Lets the fetcher/auditor apply their own freshness policy (the 24h cache TTL)
    without constructing a cache path themselves.
    """
    path = _sleeper_players_path()
    if not path.exists():
        return None
    return time.time() - path.stat().st_mtime


# --- Sleeper Players Registry: pinned snapshot (Session 1.7 — roster reproducibility) ---
#
# players.parquet above is a current-state cache refreshed every 24h. Resolving a rostered player's
# skill-ELIGIBILITY from a moving cache makes join_season non-reproducible: a two-way player (Travis
# Hunter — nflreadpy CB, Sleeper WR) enters/leaves the roster substrate with the registry's label on
# rebuild day, and every league-scoped read is built on it. The pinned snapshot is an IMMUTABLE, versioned
# copy the join / audit / market_vor position resolution reads instead of "today's" cache. Bumping
# ACTIVE_PLAYERS_SNAPSHOT is a DELIBERATE versioned event (→ rebuild + no-regression review), never
# ambient drift. Eligibility ("what slot does a rostered player fill?") is a fantasy question answered by
# this registry; stats ("what did he produce?") stay an nflreadpy question.

ACTIVE_PLAYERS_SNAPSHOT = "2026-07-14"  # tracked reproducibility anchor; the snapshot parquet is gitignored runtime


def _sleeper_players_snapshot_path(snapshot_id: str) -> Path:
    return _CACHE_DIR / "sleeper" / f"players_snapshot_{snapshot_id}.parquet"


def write_sleeper_players_snapshot(df: pl.DataFrame, snapshot_id: str) -> None:
    """Persist an IMMUTABLE, versioned copy of the Sleeper players registry (write-once).

    Refuses to overwrite an existing id — a pinned snapshot is immutable by contract; a new registry state
    must get a NEW id (a deliberate versioned event), never silently replace an old one.
    """
    _require_laptop("write_sleeper_players_snapshot", _WHY_REGISTRY, _FIX_REGISTRY)
    path = _sleeper_players_snapshot_path(snapshot_id)
    if path.exists():
        raise FileExistsError(
            f"Players snapshot {snapshot_id!r} already exists at {path}. Pinned snapshots are immutable — "
            "allocate a NEW ACTIVE_PLAYERS_SNAPSHOT id instead of overwriting."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_sleeper_players_snapshot(snapshot_id: str) -> pl.DataFrame:
    path = _sleeper_players_snapshot_path(snapshot_id)
    if not path.exists():
        raise FileNotFoundError(
            f"Pinned players snapshot {snapshot_id!r} not found at {path}. "
            "Create it with: python3 -m application.data.fetchers.sleeper capture-players-snapshot"
        )
    return pl.read_parquet(path)


def read_pinned_sleeper_players() -> pl.DataFrame:
    """The ACTIVE pinned Sleeper players snapshot — the authoritative, reproducible registry that
    skill-eligibility (join_nfl_sleeper_weekly, audit_join) and the market_vor position join resolve
    against, in place of the moving 24h players.parquet cache."""
    return read_sleeper_players_snapshot(ACTIVE_PLAYERS_SNAPSHOT)


def sleeper_players_snapshot_exists(snapshot_id: str | None = None) -> bool:
    return _sleeper_players_snapshot_path(snapshot_id or ACTIVE_PLAYERS_SNAPSHOT).exists()


def capture_players_snapshot(snapshot_id: str | None = None) -> Path:
    """Pin the current live players.parquet into an immutable versioned snapshot (write-once).

    The one deliberate capture step: freezes today's registry into the named id. Idempotent — if the id
    already exists it is left untouched (a re-capture would raise on the write-once guard)."""
    snapshot_id = snapshot_id or ACTIVE_PLAYERS_SNAPSHOT
    path = _sleeper_players_snapshot_path(snapshot_id)
    if path.exists():
        return path
    write_sleeper_players_snapshot(read_sleeper_players(), snapshot_id)
    return path


# --- League-scoped RAW directories (L0 keying, Session 3a) ---
# The raw fetched + join layer is partitioned by league_id so a second league can never overwrite the
# first (audit S1.3) — the raw analog of `_league_dir` (derived side, Session 1). Every raw/join
# read/write/path helper takes a `league_id=None` kwarg that default-resolves to the is_mine league
# (`_active_league`), so single-league callers are unchanged and only the corpus harvest passes explicit
# keys. `_active_league` is defined below (resolved at call time), so referencing it here is fine.

def _sleeper_league_dir(season: int, league_id) -> Path:
    """Directory for a league-scoped raw Sleeper entity — `sleeper/<season>/league/<league_id>/`."""
    return _SNAPSHOT_DIR / "sleeper" / str(season) / "league" / str(league_id)


def _join_league_dir(league_id) -> Path:
    """Directory for the league-scoped NFL+Sleeper join — `nfl_sleeper_weekly_joined/league/<league_id>/`."""
    return _SNAPSHOT_DIR / "nfl_sleeper_weekly_joined" / "league" / str(league_id)


# --- Sleeper Teams (roster_id → names) ---

def _sleeper_teams_path(season: int, league_id) -> Path:
    return _sleeper_league_dir(season, league_id) / f"teams_{season}.parquet"


def write_sleeper_teams(df: pl.DataFrame, season: int, *, league_id=None) -> None:
    """Write the roster_id → team/owner name map for a league season (overwrite).

    Roster identities are effectively fixed once a season is frozen, so this is a
    single overwrite file per league season rather than an appended time-series.
    """
    league_id = league_id or _active_league(season)[0]
    path = _sleeper_teams_path(season, league_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_sleeper_teams(season: int, *, league_id=None) -> pl.DataFrame:
    league_id = league_id or _active_league(season)[0]
    return pl.read_parquet(_sleeper_teams_path(season, league_id))


# --- Sleeper Roster Positions (league starting-lineup config) ---

def _roster_positions_path(season: int, league_id) -> Path:
    return _sleeper_league_dir(season, league_id) / f"roster_positions_{season}.parquet"


def write_roster_positions(df: pl.DataFrame, season: int, *, league_id=None) -> None:
    """Write the league's raw roster_positions slot list for a league season (overwrite).

    One row per slot, in Sleeper's declared order (slot_index, slot). This is the
    source of truth straight from the league object — derive_lineup_slots shapes it
    into the starting skill-slot requirements the optimal-lineup calc consumes.
    Like team identities, league lineup config is fixed once a season is frozen, so
    this is a single overwrite file per league season, not an appended time-series.
    """
    league_id = league_id or _active_league(season)[0]
    path = _roster_positions_path(season, league_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_roster_positions(season: int, *, league_id=None) -> pl.DataFrame:
    league_id = league_id or _active_league(season)[0]
    return pl.read_parquet(_roster_positions_path(season, league_id))


# --- Lineup Slots (derived starting skill-slot requirements) ---

def _lineup_slots_path(season: int, league_id) -> Path:
    return _sleeper_league_dir(season, league_id) / f"lineup_slots_{season}.parquet"


def write_lineup_slots(df: pl.DataFrame, season: int, *, league_id=None) -> None:
    """Write the derived starting skill-slot requirements for a league season (overwrite).

    Output of transforms/derive_lineup_slots.py: one row per distinct starting slot
    type (slot, count, eligible) covering only slots a QB/RB/WR/TE can fill. Consumed
    by the front-end optimal-lineup ("perfect lineup") calculation.
    """
    league_id = league_id or _active_league(season)[0]
    path = _lineup_slots_path(season, league_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_lineup_slots(season: int, *, league_id=None) -> pl.DataFrame:
    league_id = league_id or _active_league(season)[0]
    return pl.read_parquet(_lineup_slots_path(season, league_id))


# --- League Settings (scoring_settings + playoff/league config) ---
# The league's real scoring and playoff configuration, pulled from the same Sleeper /league
# object that yields roster_positions. Persisted so transforms drive behavior from the league's
# actual rules instead of hardcoded/generic assumptions: the scoring dispatcher (transforms/
# _scoring.py) selects the projection column from scoring_settings, and compute_bracket_sim reads
# playoff_teams / playoff_week_start. Tall (section, key, value) so any scoring or league key is a
# lookup, not a schema change. Fixed once a season is frozen → single overwrite file, like
# roster_positions.


def _league_settings_path(season: int, league_id) -> Path:
    return _sleeper_league_dir(season, league_id) / f"league_settings_{season}.parquet"


def write_league_settings(df: pl.DataFrame, season: int, *, league_id=None) -> None:
    """Write the league's settings (scoring + playoff/league config) for a league season (overwrite).

    Tall frame: section ∈ {"scoring", "league"}, key (the Sleeper setting name), value (float —
    scoring values and league settings are all numeric on Sleeper). Output of
    `python3 -m application.data.fetchers.sleeper fetch-league-config`.
    """
    league_id = league_id or _active_league(season)[0]
    path = _league_settings_path(season, league_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_league_settings(season: int, *, league_id=None) -> pl.DataFrame:
    league_id = league_id or _active_league(season)[0]
    return pl.read_parquet(_league_settings_path(season, league_id))


def read_scoring_settings(season: int, *, league_id=None) -> dict:
    """The league's scoring_settings as a {key: float} dict (the `scoring` section)."""
    df = read_league_settings(season, league_id=league_id).filter(pl.col("section") == "scoring")
    return {r["key"]: float(r["value"]) for r in df.iter_rows(named=True)}


def read_playoff_settings(season: int, *, league_id=None) -> dict:
    """The league's playoff/league config as a {key: value} dict (the `league` section)."""
    df = read_league_settings(season, league_id=league_id).filter(pl.col("section") == "league")
    return {r["key"]: r["value"] for r in df.iter_rows(named=True)}


# --- NFL Stats ---

def _nfl_stats_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "nflreadpy" / f"nfl_stats_{season}.parquet"


def write_nfl_stats(df: pl.DataFrame, season: int, week: int | None = None) -> None:
    """Write the nflreadpy player-week stats for a season.

    A full-season write (week=None) overwrites the file. A single-week refresh (week
    given) replaces just that week's rows in the existing season file — read, drop the
    week, concat (diagonal, since weeks can differ in columns), write. Mirrors
    write_join_nfl_sleeper_weekly's dedup guard.
    """
    path = _nfl_stats_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    if week is not None and path.exists():
        existing = pl.read_parquet(path).filter(pl.col("week") != week)
        df = pl.concat([existing, df], how="diagonal")
    df.write_parquet(path)


def read_nfl_stats(season: int) -> pl.DataFrame:
    return pl.read_parquet(_nfl_stats_path(season))


def read_nfl_stats_or_empty(season: int) -> pl.DataFrame:
    """The season's realized stats, or a correctly-TYPED empty frame when the season has none yet.

    A forward season has no parquet at all — preseason, and again at kickoff week before nflreadpy
    publishes. Callers that must keep running on projections-only (the join's zero-fill, the player-signal
    positional baseline) need an empty frame carrying the REAL column set: a schema-less one breaks the
    left-join and every downstream filter. So borrow the schema from the newest season that does exist and
    return it with no rows — "there are no results yet", stated in the shape the pipeline already speaks.
    """
    path = _nfl_stats_path(season)
    if path.exists():
        return pl.read_parquet(path)
    banked = sorted((_SNAPSHOT_DIR / "nflreadpy").glob("nfl_stats_*.parquet"))
    return pl.read_parquet(banked[-1], n_rows=0) if banked else pl.DataFrame()


# --- Preseason ADP (FantasyPros consensus, historical) ---
# The preseason-limits source for the §2 ROS bull/bear anchor (DECISION_READS.md §2). One tall
# file, `season` a COLUMN (the projections "source-as-a-column" idiom) so the historical
# curve-fit spans every season in one read and the current-season anchor is a filter. Fetched by
# `application/data/fetchers/adp.py backfill` from nflreadpy.load_ff_rankings — the latest August
# (pre-kickoff) redraft-overall snapshot per season, id-bridged FantasyPros→sleeper. Preseason ADP
# for a season is fixed once drafted, so a re-fetch replaces that season's slice (dedup-by-season),
# mirroring write_projections.


def _adp_preseason_path() -> Path:
    return _SNAPSHOT_DIR / "nflreadpy" / "adp_preseason.parquet"


def write_adp_preseason(df: pl.DataFrame, season: int) -> None:
    """Append one season's preseason ADP slice to the single history file (replace-by-season).

    `df` is treated as the COMPLETE set of rows for `season`. If the file exists, that season's
    rows are dropped first so a re-fetch replaces rather than duplicates; other seasons (which the
    live scrape can no longer reproduce) are preserved. One row per (season, sleeper_player_id):
    ecr / best / worst / sd (FantasyPros consensus rank + range) + pos_ecr_rank (rank of ecr within
    position at that snapshot).
    """
    path = _adp_preseason_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = pl.read_parquet(path).filter(pl.col("season") != season)
        df = pl.concat([existing, df], how="diagonal")
    df.write_parquet(path)


def read_adp_preseason(season: int | None = None) -> pl.DataFrame:
    """Read the preseason ADP history, optionally filtered to one season (default = all seasons)."""
    df = pl.read_parquet(_adp_preseason_path())
    if season is not None:
        df = df.filter(pl.col("season") == season)
    return df


def adp_preseason_exists() -> bool:
    return _adp_preseason_path().exists()


# --- ADP Points Curve (historical rank -> realized-points floor/center/ceiling) ---
# The empirical anchor for the §2 ROS bull/bear range (DECISION_READS.md §2): "what does a player
# drafted at positional ADP rank r ACTUALLY produce in realized season points?" Fit by
# transforms/compute_adp_points_curve.py over prior seasons (preseason positional ADP rank ↔ realized
# season-total fantasy_points_ppr), one row per (position, pos_ecr_rank) carrying the P10/P50/P90 =
# floor/center/ceiling. **Persisted PER HELD-OUT TARGET SEASON** (Session 2): `holdout_{S}.parquet`
# is fit on every season EXCEPT S, so the anchor a season-S band reads has never seen S — a multi-
# season corpus grading §2 on 2023 must not fit the anchor on 2023's own outcomes (silent optimism).
# Callers pass the season they are computing as `holdout`. Gated by check_adp_curve_leakage.py.


def _adp_points_curve_path(holdout: int) -> Path:
    return _SNAPSHOT_DIR / "derived" / "adp_points_curve" / f"holdout_{holdout}.parquet"


def write_adp_points_curve(df: pl.DataFrame, holdout: int) -> None:
    """Write the ADP rank→realized-points curve fit with season `holdout` excluded (overwrite).

    Output of transforms/compute_adp_points_curve.py: one row per (position, pos_ecr_rank) with the
    smoothed floor_ppr / center_ppr / ceiling_ppr (P10/P50/P90 of realized full-season PPR over a
    rolling rank window across the training seasons) + the bin sample count n + provenance
    (holdout_season / train_seasons). Written to derived/adp_points_curve/holdout_{holdout}.parquet.
    """
    _require_laptop("write_adp_points_curve", _WHY_LEDGER, _FIX_LEDGER)
    path = _adp_points_curve_path(holdout)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_adp_points_curve(holdout: int) -> pl.DataFrame:
    """The leak-free curve for a season: fit with `holdout` (that season) excluded from the fit."""
    return pl.read_parquet(_adp_points_curve_path(holdout))


def adp_points_curve_exists(holdout: int) -> bool:
    return _adp_points_curve_path(holdout).exists()


# --- Sleeper Matchups ---

def _sleeper_matchups_path(season: int, week: int, league_id) -> Path:
    return _sleeper_league_dir(season, league_id) / f"matchups_week_{week:02d}.parquet"


def write_sleeper_matchups(df: pl.DataFrame, season: int, week: int, *, league_id=None) -> None:
    """Write one week's matchup snapshot for a league season (overwrite)."""
    league_id = league_id or _active_league(season)[0]
    path = _sleeper_matchups_path(season, week, league_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_sleeper_matchups(season: int, week: int, *, league_id=None) -> pl.DataFrame:
    league_id = league_id or _active_league(season)[0]
    return pl.read_parquet(_sleeper_matchups_path(season, week, league_id))


def read_season_matchups(season: int, through_week: int = 18, *, league_id=None) -> pl.DataFrame:
    """Stack every available weekly matchup snapshot into one (week, roster_id, matchup_id,
    points) frame — the schedule (matchup_id pairs two teams per week) + actual results, the
    seam the bracket-math sim reads for standings and the remaining schedule. Skips weeks whose
    snapshot is missing (offseason / not yet fetched)."""
    league_id = league_id or _active_league(season)[0]
    frames = []
    for week in range(1, through_week + 1):
        path = _sleeper_matchups_path(season, week, league_id)
        if not path.exists():
            continue
        frames.append(
            pl.read_parquet(path)
            .select("roster_id", "matchup_id", "points")
            .with_columns(pl.lit(week).alias("week"))
        )
    return pl.concat(frames) if frames else pl.DataFrame(
        schema={"roster_id": pl.Int64, "matchup_id": pl.Int64, "points": pl.Float64, "week": pl.Int32}
    )


# --- Schedule (derived front-end export) ---
# The pairing-only slice of the weekly matchup snapshots — (week, roster_id, matchup_id), with the
# `points` column deliberately DROPPED so actual results never reach the client. The Matchups surface
# is a forward slate (as-of week N shows week N+1 pairings with *projected* totals); the pairings are
# known in advance, but their scores are the future the season replay is pretending not to know.
# Feeds queries.loadMatchups. Written by transforms/export_schedule.py.
#
# League-scoped (L0 keying, Stage-B B1): `roster_id`/`matchup_id` are only unique *within* a league,
# so the schedule lives under `derived/league/<league_id>/` and carries a `league_id` column — like
# every other league-scoped derived read. (Before B1 it sat league-agnostically at the `derived/` root,
# so two same-season leagues would overwrite each other.) Defaults to the is_mine league of the season.

def _schedule_path(season: int, league_id) -> Path:
    return _league_dir(league_id) / f"schedule_{season}.parquet"


def write_schedule(df: pl.DataFrame, season: int, *, league_id=None) -> None:
    """Write the pairing-only schedule for a league season (overwrite)."""
    league_id = league_id or _active_league(season)[0]
    path = _schedule_path(season, league_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_schedule(season: int, *, league_id=None) -> pl.DataFrame:
    league_id = league_id or _active_league(season)[0]
    return pl.read_parquet(_schedule_path(season, league_id))


def schedule_exists(season: int, *, league_id=None) -> bool:
    league_id = league_id or _active_league(season)[0]
    return _schedule_path(season, league_id).exists()


# --- Sleeper Transactions ---

def _sleeper_transactions_path(season: int, week: int, league_id) -> Path:
    return _sleeper_league_dir(season, league_id) / f"transactions_week_{week:02d}.parquet"


def write_sleeper_transactions(df: pl.DataFrame, season: int, week: int, *, league_id=None) -> None:
    """Write one week's transaction snapshot for a league season (overwrite)."""
    league_id = league_id or _active_league(season)[0]
    path = _sleeper_transactions_path(season, week, league_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_sleeper_transactions(season: int, week: int, *, league_id=None) -> pl.DataFrame:
    league_id = league_id or _active_league(season)[0]
    return pl.read_parquet(_sleeper_transactions_path(season, week, league_id))


# --- Join: NFL + Sleeper Weekly ---

def _join_season_path(season: int, league_id) -> Path:
    return _join_league_dir(league_id) / f"season_{season}.parquet"


def read_join_season(season: int, *, league_id=None) -> pl.DataFrame:
    """Read the full season join file (all weeks)."""
    league_id = league_id or _active_league(season)[0]
    return pl.read_parquet(_join_season_path(season, league_id))


def write_join_season(df: pl.DataFrame, season: int, *, league_id=None) -> None:
    """Overwrite the whole season join file (all weeks) for a league.

    Unlike `write_join_nfl_sleeper_weekly` (per-week append with a dedup guard), this replaces the entire
    file — used by the corpus harvest to carry an added column (e.g. the `is_two_way` flag) across every
    week of an already-built join without re-running the per-week join.
    """
    league_id = league_id or _active_league(season)[0]
    path = _join_season_path(season, league_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def join_season_exists(season: int, *, league_id=None) -> bool:
    league_id = league_id or _active_league(season)[0]
    return _join_season_path(season, league_id).exists()


def read_join_nfl_sleeper_weekly(season: int, week: int, *, league_id=None) -> pl.DataFrame:
    """Read a single week's slice from the season join file."""
    return read_join_season(season, league_id=league_id).filter(
        (pl.col("season") == season) & (pl.col("week") == week)
    )


def write_join_nfl_sleeper_weekly(df: pl.DataFrame, season: int, week: int, *, league_id=None) -> None:
    """Append a week's rows to the single season join file.

    `df` is treated as the complete set of rows for (season, week). If the
    season file already exists, any rows matching the (season, week) combo are
    dropped first (dedup guard) so re-running a week replaces it rather than
    duplicating. Otherwise the week's rows seed a new season file.
    """
    league_id = league_id or _active_league(season)[0]
    path = _join_season_path(season, league_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = pl.read_parquet(path).filter(
            ~((pl.col("season") == season) & (pl.col("week") == week))
        )
        # Align columns across the append (how="diagonal") rather than a strict vertical concat: an
        # in-season incremental advance may add a week under a slightly evolved schema (e.g. the
        # corpus-era is_mine season carries an `is_two_way` flag the live join doesn't emit). Diagonal
        # unions the columns, filling a column absent from one side with null, so the loader stays
        # additive instead of crashing on drift; dtypes stay strict, so a genuine type change still surfaces.
        df = pl.concat([existing, df], how="diagonal")
    df.write_parquet(path)


# --- Join Remainders ---

def _remainders_path(season: int, week: int, league_id) -> Path:
    return _join_league_dir(league_id) / f"remainders_{season}_w{week:02d}.parquet"


def write_join_remainders(df: pl.DataFrame, season: int, week: int, *, league_id=None) -> None:
    """Write unresolved Sleeper players to a remainders file.

    An empty DataFrame written here signals a clean join with no unknowns.
    """
    league_id = league_id or _active_league(season)[0]
    path = _remainders_path(season, week, league_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_join_remainders(season: int, week: int, *, league_id=None) -> pl.DataFrame:
    league_id = league_id or _active_league(season)[0]
    path = _remainders_path(season, week, league_id)
    if not path.exists():
        raise FileNotFoundError(f"Remainders file not found: {path}")
    return pl.read_parquet(path)


def remainders_exist(season: int, week: int, *, league_id=None) -> bool:
    league_id = league_id or _active_league(season)[0]
    return _remainders_path(season, week, league_id).exists()


# --- LeagueLogs Market Values ---

def _leaguelogs_market_path() -> Path:
    return _SNAPSHOT_DIR / "leaguelogs" / "market_values.parquet"


def read_leaguelogs_market() -> pl.DataFrame:
    """Read the full LeagueLogs market-value snapshot history (all dates, all profiles)."""
    return _store().read_parquet(_leaguelogs_market_path())


def leaguelogs_market_exists() -> bool:
    return _store().exists(_leaguelogs_market_path())


def write_leaguelogs_market_snapshot(df: pl.DataFrame, snapshot_date) -> None:
    """Append one day's market snapshot (all profiles) to the single history file.

    `df` is treated as the complete set of rows for `snapshot_date`. If the file
    already exists, any rows for that date are dropped first (dedup guard), so a
    same-day re-run replaces the day rather than duplicating it. History for other
    dates is never touched — it cannot be re-fetched, so it is preserved.
    """
    store = _store()
    path = _leaguelogs_market_path()
    if store.exists(path):
        existing = store.read_parquet(path).filter(pl.col("snapshot_date") != snapshot_date)
        df = pl.concat([existing, df])
    store.write_parquet(df, path)


# Fetch-timestamp metadata sidecar (P1/S2): a small JSON beside the series in the store recording
# *when* the last run fetched + its status/count. The cache records what was fetched, not when; the
# coverage gate reads this to report last-fetch age + run status. One sidecar per banked series.

def _leaguelogs_market_meta_path() -> Path:
    return _SNAPSHOT_DIR / "leaguelogs" / "market_values.meta.json"


def write_leaguelogs_market_metadata(meta: dict) -> None:
    _store().write_bytes(json.dumps(meta, indent=2, sort_keys=True).encode(), _leaguelogs_market_meta_path())


def read_leaguelogs_market_metadata() -> dict | None:
    path = _leaguelogs_market_meta_path()
    if not _store().exists(path):
        return None
    return json.loads(_store().read_bytes(path))


# --- Player News (news collector, DECISION_READS.md §2 aggregation half) ---
# The aggregation half of the §2 ROS AI-interpretation layer: a live, scheduled RSS
# collector (fetchers/news.py) banks current NFL player news as a de-duplicated,
# player-resolved, source-attributed time-series that the future on-demand AI synthesis
# call reads. Live-acquired like manager_activity — the forward pipeline, NOT tied to the
# frozen-2025 league; it resolves against whatever skill players are on an NFL roster now.
# One growing file (like leaguelogs market_values). Grain: one row per (news item ×
# resolved player) — a multi-player item is one row per player. Items are immutable once
# collected, so the writer is APPEND-ONLY-OF-NEW (anti-join on item_id): re-polling a feed
# (the same articles reappear every run) adds nothing, and a re-run is idempotent. Only the
# compact item is stored (headline / summary / url + provenance), never the article body —
# url + collected_at are the recall path (Wayback) and it sidesteps copyright/ToS on text.

def _player_news_path() -> Path:
    return _SNAPSHOT_DIR / "news" / "player_news.parquet"


def write_player_news(df: pl.DataFrame) -> None:
    """Append only the genuinely-new items to the growing history file (idempotent by item_id).

    `df` is a batch of collected (item × player) rows. It is de-duplicated on `item_id`, then
    any item_id already on disk is dropped, so re-polling a feed never duplicates — the file
    grows only by new items. Existing history is never rewritten (news can't be re-fetched once
    gone). Concat is diagonal so a later schema tweak doesn't break the append.
    """
    path = _player_news_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    df = df.unique(subset="item_id", keep="first")
    if path.exists():
        existing = pl.read_parquet(path)
        df = df.filter(~pl.col("item_id").is_in(existing["item_id"]))
        df = pl.concat([existing, df], how="diagonal")
    df.write_parquet(path)


def read_player_news(season: int | None = None) -> pl.DataFrame:
    """Read the collected player-news history, optionally filtered to one season."""
    df = pl.read_parquet(_player_news_path())
    if season is not None:
        df = df.filter(pl.col("season") == season)
    return df


def player_news_exists() -> bool:
    return _player_news_path().exists()


# --- Team News Raw (per-team article collection, §2 news pipeline Stage A) ---
# The team-centric successor to player_news: the collector (fetchers/news.py) now pulls
# per-NFL-team RSS from three native sources per team (SB Nation + FanSided + the official
# team site) and banks the RAW ARTICLES (feed-provided content — not just headlines, because
# the weekly AI extraction step needs the text; feed-provided only, no scraping). Grain is one
# row per ARTICLE (team-tagged); player resolution has moved downstream to extraction/slice.
# One growing file. Immutable-once-collected, so the writer is APPEND-ONLY-OF-NEW by article_id
# (idempotent re-runs; cross-poll duplicates collapse). Superseded player_news is left in place
# as legacy. Consumed by the weekly team-dossier extraction (Stage B).


def _team_news_raw_path() -> Path:
    return _SNAPSHOT_DIR / "news" / "team_news_raw.parquet"


def write_team_news_raw(df: pl.DataFrame) -> None:
    """Append only the genuinely-new articles to the growing store (idempotent by article_id).

    `df` is a batch of collected article rows. De-duplicated on `article_id`, then any article_id
    already on disk is dropped, so re-polling a feed never duplicates — the store grows only by new
    articles. Concat is diagonal so a later schema tweak doesn't break the append.
    """
    store = _store()
    path = _team_news_raw_path()
    df = df.unique(subset="article_id", keep="first")
    if store.exists(path):
        existing = store.read_parquet(path)
        df = df.filter(~pl.col("article_id").is_in(existing["article_id"]))
        df = pl.concat([existing, df], how="diagonal")
    store.write_parquet(df, path)


def read_team_news_raw(team: str | None = None, season: int | None = None) -> pl.DataFrame:
    """Read the collected raw team articles, optionally filtered to one team and/or season."""
    df = _store().read_parquet(_team_news_raw_path())
    if team is not None:
        df = df.filter(pl.col("team") == team)
    if season is not None:
        df = df.filter(pl.col("season") == season)
    return df


def team_news_raw_exists() -> bool:
    return _store().exists(_team_news_raw_path())


def prune_team_news_raw_content(cutoff_date: str, *, dry_run: bool = False) -> dict:
    """Null the heavy `content` of raw articles older than `cutoff_date`, KEEPING the row.

    Retention for the growing raw store (§2 Stage C). The Stage-B extraction only ever reads a ~2-week
    window, so an article's `content` is dead weight once it's well past that — but the row itself is
    still worth keeping. This nulls `content` where `published_at < cutoff_date` (a YYYY-MM-DD string)
    and leaves everything else intact: `article_id` / `team` / `source_type` / `title` / `url` /
    `published_at` all survive, so the derived claims (which cite `article_id`, never the text) and the
    url+date Wayback-recall path are untouched. Idempotent (already-null content stays null; a re-poll
    can't restore it — the append-writer dedups on `article_id`). Rows with a null/undatable
    `published_at` are never pruned (can't be dated → kept conservatively).

    Returns a report dict; `dry_run=True` computes it without writing (the numbers to eyeball first).
    """
    empty = {"total": 0, "eligible": 0, "to_null": 0, "chars_freed": 0,
             "oldest": None, "cutoff": cutoff_date, "written": False}
    store = _store()
    path = _team_news_raw_path()
    if not store.exists(path):
        return empty
    df = store.read_parquet(path)
    if df.is_empty():
        return empty
    day = pl.col("published_at").str.slice(0, 10)
    old = day < cutoff_date
    has_content = pl.col("content").is_not_null() & (pl.col("content").str.len_chars() > 0)
    to_null = df.filter(old & has_content)
    report = {
        "total": df.height,
        "eligible": df.filter(old).height,                       # rows older than the cutoff
        "to_null": to_null.height,                               # rows whose content actually changes
        "chars_freed": int(to_null.select(pl.col("content").str.len_chars().sum()).item() or 0),
        "oldest": df.select(day.min()).item(),
        "cutoff": cutoff_date,
        "written": False,
    }
    if dry_run or to_null.height == 0:
        return report
    pruned = df.with_columns(
        pl.when(old).then(pl.lit(None, dtype=pl.Utf8)).otherwise(pl.col("content")).alias("content")
    )
    store.write_parquet(pruned, path)
    report["written"] = True
    return report


def _team_news_raw_meta_path() -> Path:
    return _SNAPSHOT_DIR / "news" / "team_news_raw.meta.json"


def write_team_news_raw_metadata(meta: dict) -> None:
    _store().write_bytes(json.dumps(meta, indent=2, sort_keys=True).encode(), _team_news_raw_meta_path())


def read_team_news_raw_metadata() -> dict | None:
    path = _team_news_raw_meta_path()
    if not _store().exists(path):
        return None
    return json.loads(_store().read_bytes(path))


# --- Team News Dossier (weekly per-team synthesis, §2 news pipeline Stage B) ---
# Stage B distills team_news_raw (Stage A) into a compact, situation/security-focused
# "news sheet" per team-week: a set of scope-tagged claims (player / position_group / unit),
# each clustered across the 3 sources with a synthesized note + provenance. The scope tags are
# what let Stage C slice a team sheet down to a single player by inheritance. Written by the AI
# layer (application/ai/write_team_news_dossier.py) via Claude Haiku — NOT the raw articles;
# the deterministic resolver (fetchers/news.py) attaches sleeper_player_id to player-scope claims.
# Grain = one claim row per (season, week, team, claim); one growing file, tall over the team-weeks.
# The writer is REPLACE-BY (season, week, team): re-running a team-week overwrites just its rows
# (idempotent; a single-team verify run touches only that team), like manager_activity's
# replace-by-owner_id. A team-week with no fantasy-relevant news gets one explicit is_empty row.


def _team_news_dossier_path() -> Path:
    return _SNAPSHOT_DIR / "news" / "team_news_dossier.parquet"


def write_team_news_dossier(df: pl.DataFrame) -> None:
    """Replace the (season, week, team) slices present in `df`, leaving other team-weeks intact.

    `df` is the freshly-synthesized claim rows for one or more team-weeks. Every (season, week,
    team) tuple appearing in `df` is dropped from the store first, then the new rows appended — so
    a re-run of a team-week overwrites it (idempotent) and a single-team run replaces only that
    team. Concat is diagonal so a later schema tweak doesn't break the append.
    """
    path = _team_news_dossier_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = df.select("season", "week", "team").unique()
    if path.exists():
        existing = pl.read_parquet(path)
        existing = existing.join(keys, on=["season", "week", "team"], how="anti")
        df = pl.concat([existing, df], how="diagonal")
    df.write_parquet(path)


def read_team_news_dossier(team: str | None = None, season: int | None = None,
                           week: int | None = None) -> pl.DataFrame:
    """Read the synthesized team news-sheet claims, optionally filtered by team / season / week."""
    df = pl.read_parquet(_team_news_dossier_path())
    if team is not None:
        df = df.filter(pl.col("team") == team)
    if season is not None:
        df = df.filter(pl.col("season") == season)
    if week is not None:
        df = df.filter(pl.col("week") == week)
    return df


def team_news_dossier_exists() -> bool:
    return _team_news_dossier_path().exists()


# --- Player News Slice (per-player inheritance view, §2 news pipeline Stage C) ---
# Stage C collapses each team's Stage-B news sheet (`team_news_dossier`) down to ONE player by
# INHERITANCE: a skill player inherits his own resolved `player` claims + his `position_group`
# claims (his position, plus team-wide offensive context) + his team's `unit` claims (offense +
# the one condensed defense note). Deterministic reshape — no AI. The per-player consumable the
# §2 synthesis (QUEUED #2) reads next to the ros_outcome_shape anchors. Every on-team skill player
# is present; one who inherits nothing gets an explicit is_empty "no-signal" row (honest-zero) so
# thinness is queryable, not an inferred absence. Each row carries a `signal_tier` (rich/thin/none)
# + counts (the thinness tripwire). Grain = one inherited-claim row per (season, week, player,
# claim). One growing file, tall over player-weeks. Writer is REPLACE-BY (season, week): the whole
# week's slice is a pure function of that week's dossier, so a re-run regenerates it wholesale.


def _player_news_slice_path() -> Path:
    return _SNAPSHOT_DIR / "news" / "player_news_slice.parquet"


def write_player_news_slice(df: pl.DataFrame) -> None:
    """Replace the (season, week) slices present in `df`, leaving other weeks intact.

    Every (season, week) tuple appearing in `df` is dropped from the store first, then the new rows
    appended — so a re-run of a week overwrites it (idempotent). Concat is diagonal so a later schema
    tweak doesn't break the append.
    """
    path = _player_news_slice_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = df.select("season", "week").unique()
    if path.exists():
        existing = pl.read_parquet(path)
        existing = existing.join(keys, on=["season", "week"], how="anti")
        df = pl.concat([existing, df], how="diagonal")
    df.write_parquet(path)


def read_player_news_slice(sleeper_player_id: str | None = None, season: int | None = None,
                           week: int | None = None) -> pl.DataFrame:
    """Read the per-player inherited news slice, optionally filtered by player / season / week."""
    df = pl.read_parquet(_player_news_slice_path())
    if sleeper_player_id is not None:
        df = df.filter(pl.col("sleeper_player_id") == sleeper_player_id)
    if season is not None:
        df = df.filter(pl.col("season") == season)
    if week is not None:
        df = df.filter(pl.col("week") == week)
    return df


def player_news_slice_exists() -> bool:
    return _player_news_slice_path().exists()


# --- Projections (multi-source: Sleeper now, FantasyPros in-season) ---
# The borrowed forward prior every Phase-2 read rests on (Product Roadmap Phase 2).
# Normalized, source-agnostic entity: one growing file per season, with `source` as a
# COLUMN (not a directory) — so consensus + disagreement across providers is a group-by
# and "pick a source" is a filter, and adding FantasyPros later is a new `source` value,
# not a schema change. Snapshot/append (mirrors write_leaguelogs_market_snapshot): a
# re-fetch of a (season, week, source) slice replaces it rather than duplicating. Rows
# carry snapshot_date + source_updated_at so an in-season daily history of how a
# projection moved can extend the dedup key later without a rewrite.


def _projections_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "projections" / f"projections_{season}.parquet"


def write_projections(df: pl.DataFrame, season: int, week: int, source: str) -> None:
    """Append one (season, week, source) projection slice to the season file.

    `df` is treated as the complete set of rows for (season, week, source). If the
    season file already exists, any rows matching that combo are dropped first (dedup
    guard) so re-running a week/source replaces it rather than duplicating. Concat is
    diagonal so a future source carrying extra component columns doesn't break the append.
    """
    path = _projections_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = pl.read_parquet(path).filter(
            ~(
                (pl.col("season") == season)
                & (pl.col("week") == week)
                & (pl.col("source") == source)
            )
        )
        df = pl.concat([existing, df], how="diagonal")
    df.write_parquet(path)


def read_projections(season: int, week: int | None = None, source: str | None = None) -> pl.DataFrame:
    """Read the season projections file, optionally filtered by week and/or source.

    `source=None` returns every source (the multi-source read the consensus/disagreement
    transform consumes); passing a source is the "pick a provider" selection seam.
    """
    df = pl.read_parquet(_projections_path(season))
    if week is not None:
        df = df.filter(pl.col("week") == week)
    if source is not None:
        df = df.filter(pl.col("source") == source)
    return df


def projections_exist(season: int) -> bool:
    return _projections_path(season).exists()


# --- Derived Analytics ---
# Pre-computed Team Overview analytics, promoted out of the front-end seam
# (queries.js) into polars transforms. Each is now a tall snapshot file per season,
# grain (season, as_of_week, entity): the dashboard as it would have read through each
# week N, every analytic recomputed on weeks ≤ N (the Season-replay dimension). One row
# per (as_of_week, roster_id/player), derived columns the front end reads directly. The
# read fns below take an optional `as_of_week` (default = latest), so existing callers
# get the current-week slice unchanged. When a server arrives, these become API
# endpoints that serve the same parquet — no JS math to port.


def _as_of_slice(df: pl.DataFrame, as_of_week) -> pl.DataFrame:
    """Filter a tall derived-analytics frame to a single as-of week (default = latest).

    `as_of_week="all"` returns the whole tall frame — for a consumer that re-aggregates every
    week's slice (e.g. compute_true_rank reading all of Production VOR) rather than viewing one."""
    if as_of_week == "all":
        return df
    if as_of_week is None:
        as_of_week = df["as_of_week"].max()
    return df.filter(pl.col("as_of_week") == as_of_week)

def _league_dir(league_id) -> Path:
    """Directory for a league-scoped derived entity — `derived/league/<league_id>/` (L0 keying)."""
    return _SNAPSHOT_DIR / "derived" / "league" / str(league_id)


def _scoring_dir(scoring_key) -> Path:
    """Directory for a scoring-scoped derived entity — `derived/scoring/<scoring_key>/` (L0 keying)."""
    return _SNAPSHOT_DIR / "derived" / "scoring" / str(scoring_key)


def _player_signal_path(season: int, league_id) -> Path:
    return _league_dir(league_id) / f"player_signal_{season}.parquet"


def write_player_signal(df: pl.DataFrame, season: int, *, league_id=None) -> None:
    """Write the per-player spike signal-quality read for a league season (overwrite).

    Output of transforms/compute_player_signal.py: one row per rostered skill player
    carrying the recent per-game production, the opportunity vs efficiency
    decomposition (opp_g, ppo, regression_risk), the TD share of scoring, a
    sample-gated categorical read, and the per-week points/opportunity series
    (serialised JSON). The first decision-critique engine slice ("is this production
    real, or noise?").
    """
    league_id = league_id or _active_league(season)[0]
    path = _player_signal_path(season, league_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_player_signal(season: int, *, league_id=None, as_of_week=None) -> pl.DataFrame:
    """Read the per-player signal-quality read for one as-of week (default = latest)."""
    league_id = league_id or _active_league(season)[0]
    return _as_of_slice(pl.read_parquet(_player_signal_path(season, league_id)), as_of_week)


def _projection_consensus_path(season: int, scoring_key) -> Path:
    return _scoring_dir(scoring_key) / f"projection_consensus_{season}.parquet"


def write_projection_consensus(df: pl.DataFrame, season: int, *, scoring_key=None) -> None:
    """Write the per-(week, player) projection consensus + spread band for a scoring profile (overwrite).

    Output of transforms/compute_projection_consensus.py: one row per (week,
    sleeper_player_id) over the whole skill pool, carrying the borrowed consensus center
    (median proj across sources), a percentile band (p25/p50/p75) whose width is the
    player's residual std shrunk toward a positional prior, and the cross-source
    disagreement column (null until a 2nd source lands). The Phase-2 forward prior /
    law-2 confidence band (DECISION_READS.md §3).

    Unlike the other derived analytics this is NOT tall over as_of_week: a projection for
    week W is a fixed forward statement, and its band uses only history from weeks < W —
    the as-of information is baked into the projected week, so the read is keyed on `week`
    (like the projections entity it derives from), not on an as_of_week slice. Scoring-scoped: two
    leagues on the same scoring profile share one file (audit S3.1), defaulting to the is_mine profile.
    """
    _require_laptop("write_projection_consensus", _WHY_SCORING, _FIX_SCORING)
    scoring_key = scoring_key or _active_league(season)[1]
    path = _projection_consensus_path(season, scoring_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_projection_consensus(season: int, *, scoring_key=None, week: int | None = None) -> pl.DataFrame:
    """Read the projection consensus + spread for a scoring profile, optionally filtered to one week."""
    scoring_key = scoring_key or _active_league(season)[1]
    df = pl.read_parquet(_projection_consensus_path(season, scoring_key))
    if week is not None:
        df = df.filter(pl.col("week") == week)
    return df


# --- Production VOR ---
# The first read that *consumes* the projection substrate (DECISION_READS.md §4):
# rest-of-season production value per rostered player, anchored so the waiver line = 0 and
# normalised by the pool spread (top rosterable − waiver). Tall over as_of_week like the
# three team/player analytics — for each cutoff N the ROS value sums the borrowed weekly
# centres over the *remaining* schedule (weeks > N) and the waiver line is resolved against
# the roster-as-of-N, so the read plugs into the same "As of" week selector. Only Production
# VOR here; Market VOR (LeagueLogs) + the trade gap are V4.


def _production_vor_path(season: int, league_id) -> Path:
    return _league_dir(league_id) / f"production_vor_{season}.parquet"


def write_production_vor(df: pl.DataFrame, season: int, *, league_id=None) -> None:
    """Write the per-(as_of_week, player) Production VOR read for a league season (overwrite).

    Output of transforms/compute_production_vor.py: one row per rostered skill player per
    as-of week, carrying the rest-of-season production value (sum of borrowed weekly
    projection centres over the remaining schedule), the pool waiver line + top used to
    normalise it, and the resulting vor (waiver = 0, negative = dead weight, ~1 = a top
    rosterable player at that pool). QB is its own pool; RB/WR/TE share one flex pool.
    """
    league_id = league_id or _active_league(season)[0]
    path = _production_vor_path(season, league_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_production_vor(season: int, *, league_id=None, as_of_week=None) -> pl.DataFrame:
    """Read the Production VOR read for one as-of week (default = latest)."""
    league_id = league_id or _active_league(season)[0]
    return _as_of_slice(pl.read_parquet(_production_vor_path(season, league_id)), as_of_week)


# --- Market VOR ---
# The market-value twin of Production VOR (DECISION_READS.md §4): the same waiver = 0 ÷ pool-spread
# VOR, computed on the LeagueLogs market value instead of the borrowed projection, so both land on one
# comparable scale and the gap between them is the trade signal. Output of
# transforms/compute_market_vor.py: one row per (snapshot_date, rostered skill player), carrying the
# borrowed market value, the pool waiver/top used to normalise it, the resulting market_vor, and the
# joined Production VOR + trade_gap. TALL over `snapshot_date` (the market's own time axis — the analog
# of Production VOR's as_of_week), so the un-backdatable market series is banked in derived form.
# TIME-WORLD NOTE: the market series only serves "now", so against a PAST league season the gap is
# cross-time — every row carries `is_cross_time` + `market_season` so it is never silently fused, and
# the app gates the market panel off whenever the flag is true (api/reads._market_panel). A current
# season prices its own rosters: the flag goes false and the panel renders.


def _market_vor_path(season: int, league_id) -> Path:
    return _league_dir(league_id) / f"market_vor_{season}.parquet"


def write_market_vor(df: pl.DataFrame, season: int, *, league_id=None) -> None:
    """Write the per-(snapshot_date, player) Market VOR read for a league season (overwrite)."""
    league_id = league_id or _active_league(season)[0]
    path = _market_vor_path(season, league_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_market_vor(season: int, *, league_id=None, snapshot_date=None) -> pl.DataFrame:
    """Read the Market VOR read for one market snapshot (default = latest banked date)."""
    league_id = league_id or _active_league(season)[0]
    df = pl.read_parquet(_market_vor_path(season, league_id))
    if snapshot_date is None:
        return df.filter(pl.col("snapshot_date") == df["snapshot_date"].max())
    return df.filter(pl.col("snapshot_date") == pl.lit(snapshot_date).str.to_date())


def market_vor_exists(season: int, *, league_id=None) -> bool:
    league_id = league_id or _active_league(season)[0]
    return _market_vor_path(season, league_id).exists()


# --- True Rank ---
# The team-level aggregation of the Value read (DECISION_READS.md §5, first half): sum the
# borrowed ROS production value of each team's *optimal* (lineup-slot-aware) lineup → a
# record-independent measure of how good a roster is, ranked within the league. No new engine —
# it re-aggregates Production VOR over the optimal-lineup rules. Tall over as_of_week like the
# other derived analytics, so it plugs into the same "As of" week selector. The integration
# precursor the Phase-4 bracket-math Monte Carlo (§5 full) will sit on top of.


def _true_rank_path(season: int, league_id) -> Path:
    return _league_dir(league_id) / f"true_rank_{season}.parquet"


def write_true_rank(df: pl.DataFrame, season: int, *, league_id=None) -> None:
    """Write the per-(as_of_week, roster_id) True Rank read for a league season (overwrite).

    Output of transforms/compute_true_rank.py: one row per team per as-of week, carrying the
    optimal-lineup ROS strength (sum of the borrowed weekly projection centres over the
    remaining schedule for each optimal starter), the bench value behind it, the within-league
    rank (1 = strongest), and a league-relative 0–1 spectrum position. Record-independent.
    """
    league_id = league_id or _active_league(season)[0]
    path = _true_rank_path(season, league_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_true_rank(season: int, *, league_id=None, as_of_week=None) -> pl.DataFrame:
    """Read the True Rank read for one as-of week (default = latest)."""
    league_id = league_id or _active_league(season)[0]
    return _as_of_slice(pl.read_parquet(_true_rank_path(season, league_id)), as_of_week)


# --- Positional Depth ---
# The Value read (DECISION_READS.md §6) re-sliced *per position*, benchmarked against the league:
# a team's positional surplus (startable-quality depth = trade capital) vs. gaps (a starting slot
# filled at ~replacement level). No new engine — it re-aggregates Production VOR per position,
# net of the position's starting requirement. Tall over as_of_week like the other derived
# analytics, so it plugs into the same "As of" week selector. Closes the Phase-3 read set.


def _positional_depth_path(season: int, league_id) -> Path:
    return _league_dir(league_id) / f"positional_depth_{season}.parquet"


def write_positional_depth(df: pl.DataFrame, season: int, *, league_id=None) -> None:
    """Write the per-(as_of_week, roster_id, position) Positional Depth read for a league season (overwrite).

    Output of transforms/compute_positional_depth.py: one row per team per position (QB/RB/WR/TE)
    per as-of week, carrying the position's rostered + starter ROS value, the surplus beyond the
    starting requirement (depth / trade capital), the marginal starter's VOR (the gap indicator),
    a league-relative 0–1 spectrum position within that position's cohort, and an advisory
    surplus/adequate/gap shape. A re-slice of Production VOR — borrows the value, builds no prior.
    """
    league_id = league_id or _active_league(season)[0]
    path = _positional_depth_path(season, league_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_positional_depth(season: int, *, league_id=None, as_of_week=None) -> pl.DataFrame:
    """Read the Positional Depth read for one as-of week (default = latest)."""
    league_id = league_id or _active_league(season)[0]
    return _as_of_slice(pl.read_parquet(_positional_depth_path(season, league_id)), as_of_week)


# --- Bracket Odds ---
# The bracket-math half of the Posture read (DECISION_READS.md §5): a Monte Carlo season
# simulation that turns the forward reads into playoff odds. Team weekly score distributions
# (mean = optimal-lineup projected points, spread = the §3 weekly band) drive per-matchup win
# probabilities; simulating the remaining real schedule → playoff odds + projected wins/seed +
# magic number. With True Rank (§5 first half) it completes Posture. Tall over as_of_week like
# the other derived analytics, so it plugs into the same "As of" week selector.


def _bracket_odds_path(season: int, league_id) -> Path:
    return _league_dir(league_id) / f"bracket_odds_{season}.parquet"


def write_bracket_odds(df: pl.DataFrame, season: int, *, league_id=None) -> None:
    """Write the per-(as_of_week, roster_id) Bracket Odds read for a league season (overwrite).

    Output of transforms/compute_bracket_sim.py: one row per team per as-of week, carrying the
    Monte Carlo playoff odds, projected regular-season wins, average final seed, magic number,
    and the current (as-of-N) wins/points-for the sim starts from.
    """
    league_id = league_id or _active_league(season)[0]
    path = _bracket_odds_path(season, league_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_bracket_odds(season: int, *, league_id=None, as_of_week=None) -> pl.DataFrame:
    """Read the Bracket Odds read for one as-of week (default = latest)."""
    league_id = league_id or _active_league(season)[0]
    return _as_of_slice(pl.read_parquet(_bracket_odds_path(season, league_id)), as_of_week)


# --- ROS Player Band (scoring-scoped half of the old §2 ROS Outcome Shape) ---
# The forward player read's roster-free skeleton (DECISION_READS.md §2), split out in L0 keying
# (audit S3.2). Per (as_of_week, player): the borrowed ROS centre (Σ weekly consensus centres over the
# remaining schedule) ± the accumulated bull/bear band (√Σ of the §3 weekly band² over those weeks,
# floored at 0) and its preseason-ADP anchor evidence. It needs NO roster, so it is SCORING-scoped —
# two leagues on the same scoring profile share one file. Output of transforms/compute_ros_player_band.py,
# over the whole projected pool. Tall over as_of_week (default = latest).


def _ros_player_band_path(season: int, scoring_key) -> Path:
    return _scoring_dir(scoring_key) / f"ros_player_band_{season}.parquet"


def write_ros_player_band(df: pl.DataFrame, season: int, *, scoring_key=None) -> None:
    """Write the per-(as_of_week, player) ROS bull/bear band for a scoring profile (overwrite).

    Output of transforms/compute_ros_player_band.py: one row per projected skill player per as-of week,
    carrying the borrowed ROS centre (ros_center), the bull/bear rest-of-season band
    (ros_bull/ros_bear = centre ± bull_z·ros_sigma, floored at 0), the accumulated band std
    (ros_sigma = √Σ weekly band² over the remaining schedule) + relative dispersion (ros_cv), the number
    of remaining projected weeks, and the preseason-ADP anchor evidence. Roster-free → scoring-scoped.

    **On a worker this is a VERIFY, not a write** (P5/S3). It is the one laptop-owned writer that
    cannot simply raise: ``weekly_refresh`` rebuilds the band unconditionally for
    ``season >= FIRST_HONEST_BAND_SEASON`` — deliberately, because an existence check would pass on a
    STALE file — so a blanket refusal would break every 2026 refresh rather than only the unsafe
    ones, and the worker could never onboard a real league at all.

    So the incoming frame is compared with the one on the volume and the three outcomes are
    distinguished, which is what makes the ADR's "if it is stale or missing, it fails loudly"
    literally true rather than aspirational:

      - **identical** — nothing upstream moved, so there was nothing to write. Return quietly; the
        caller reports it (see ``weekly_refresh``). Not silent: a skip nobody logs is
        indistinguishable from a step that never ran.
      - **different** — the worker's substrate is genuinely stale (realistically the annual re-tune
        moved the engine constants). Refuse, and say what to do about it.
      - **missing** — the volume was never seeded, or seeded without this scoring key.

    The comparison is **value**-identical via ``canonical_rows``; a byte comparison would fail on
    polars' non-deterministic parquet layout and block the worker for no reason.
    """
    scoring_key = scoring_key or _active_league(season)[1]
    path = _ros_player_band_path(season, scoring_key)
    if store_role() == "worker":
        _verify_band_unchanged(df, path, season, scoring_key)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_ros_player_band(season: int, *, scoring_key=None, as_of_week=None) -> pl.DataFrame:
    """Read the ROS player band for one as-of week (default = latest)."""
    scoring_key = scoring_key or _active_league(season)[1]
    return _as_of_slice(pl.read_parquet(_ros_player_band_path(season, scoring_key)), as_of_week)


def ros_player_band_exists(season: int, *, scoring_key=None) -> bool:
    scoring_key = scoring_key or _active_league(season)[1]
    return _ros_player_band_path(season, scoring_key).exists()


# --- ROS League View (league-scoped half of the old §2 ROS Outcome Shape) ---
# The roster-relative half split from ROS Outcome Shape in L0 keying (audit S3.2). Per (as_of_week,
# roster_id, player): the league-relative bull spectrum position within the player's position cohort and
# the structured situation/security evidence (Sleeper security tier + the player_signal trust axis
# direction/reliability). Roster membership makes it LEAGUE-scoped. Output of
# transforms/compute_ros_league_view.py; joined to ros_player_band on sleeper_player_id it reconstitutes
# the old ros_outcome_shape frame. Tall over as_of_week (default = latest).


def _ros_league_view_path(season: int, league_id) -> Path:
    return _league_dir(league_id) / f"ros_league_view_{season}.parquet"


def write_ros_league_view(df: pl.DataFrame, season: int, *, league_id=None) -> None:
    """Write the per-(as_of_week, roster_id, player) ROS league view for a league season (overwrite)."""
    league_id = league_id or _active_league(season)[0]
    path = _ros_league_view_path(season, league_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_ros_league_view(season: int, *, league_id=None, as_of_week=None) -> pl.DataFrame:
    """Read the ROS league view for one as-of week (default = latest)."""
    league_id = league_id or _active_league(season)[0]
    return _as_of_slice(pl.read_parquet(_ros_league_view_path(season, league_id)), as_of_week)


def ros_league_view_exists(season: int, *, league_id=None) -> bool:
    league_id = league_id or _active_league(season)[0]
    return _ros_league_view_path(season, league_id).exists()


# --- ROS Synthesis (the §2 AI interpretation) ---
# The interpretation half of §2 (DECISION_READS.md §2) — the last mile compute_ros_player_band.py
# defers ("the AI narrative + 1-10 grade roll-up is Phase 6"). Per player, one Claude call fuses the
# quantitative anchor (ros_player_band ⋈ ros_league_view) with the situation news (player_news_slice)
# into three 1-10 grades (bull / bear / situation) EACH with a prose note, consolidated headlines
# (grounded in the cited claims), and a confidence flag. Keyed by the NEWS (season, week) = the current
# world; the ros anchor is a by-id lookup carrying anchor_season / anchor_is_prior_season so a
# prior-season anchor is flagged, never silently fused. Written by application/ai/write_ros_synthesis.py
# via Claude Haiku; a player with no anchor AND no news gets a hardcoded "insufficient data" row
# (is_zero_signal, AI skipped). LEAGUE-scoped in L0: its stored grades depend on league-relative anchor
# inputs (spectrum_pos / security / direction), so a scoring-agnostic store would collide at n=2 same-
# scoring leagues (audit S3.2). One file per (league, season); REPLACE-BY (season, week,
# sleeper_player_id) so a single-player re-run overwrites just his row (news_content_hash is the seam).
# Season-scope note (S1.6): the file's `season` is the NEWS world (e.g. 2026), which OUTRUNS the
# registry's latest league season — a redraft league gets a new Sleeper league_id each year, so there is
# no 2026 league to key on. The read's league membership is inherited from its prior-season anchor (2025),
# so these three accessors resolve via `_active_league_any` (falls back to the latest is_mine season ≤
# the news season), NOT strict `_active_league` — which correctly stays strict for every per-season entity.


def _ros_synthesis_path(season: int, league_id) -> Path:
    return _league_dir(league_id) / f"ros_synthesis_{season}.parquet"


def write_ros_synthesis(df: pl.DataFrame, *, league_id=None) -> None:
    """Replace the (season, week, sleeper_player_id) rows present in `df`, per-player idempotent.

    A re-run of a player overwrites just his row (idempotent) and a single-player verify run replaces
    only that player, leaving the rest of the week intact. One file per (league, season) — league-scoped.
    Concat is diagonal so a later schema tweak doesn't break the append.
    """
    for season in df.select("season").unique().to_series().to_list():
        part = df.filter(pl.col("season") == season)
        lid = league_id or _active_league_any(season)[0]
        path = _ros_synthesis_path(season, lid)
        path.parent.mkdir(parents=True, exist_ok=True)
        keys = part.select("season", "week", "sleeper_player_id").unique()
        if path.exists():
            existing = pl.read_parquet(path)
            existing = existing.join(keys, on=["season", "week", "sleeper_player_id"], how="anti")
            part = pl.concat([existing, part], how="diagonal")
        part.write_parquet(path)


def read_ros_synthesis(season: int, week: int | None = None,
                       sleeper_player_id: str | None = None, *, league_id=None) -> pl.DataFrame:
    """Read the per-player §2 ROS synthesis for a league season, optionally one week / player."""
    league_id = league_id or _active_league_any(season)[0]
    df = pl.read_parquet(_ros_synthesis_path(season, league_id))
    if week is not None:
        df = df.filter(pl.col("week") == week)
    if sleeper_player_id is not None:
        df = df.filter(pl.col("sleeper_player_id") == sleeper_player_id)
    return df


def ros_synthesis_exists(season: int, *, league_id=None) -> bool:
    league_id = league_id or _active_league_any(season)[0]
    return _ros_synthesis_path(season, league_id).exists()


# --- Manager Activity (cross-league, DECISION_READS.md §7) ---
# The FIRST cross-league / user-keyed entity — every other store is single-league,
# per-season. Acquired by sleeper.py's `fetch-manager-activity` mode: for each manager in
# the target league, their behaviour across their *comparable* other Sleeper leagues (same
# scoring profile + size + QB structure + format). `owner_id` (Sleeper user_id) is the
# identity key and `source_league_id` / `source_season` are COLUMNS (the projections
# "source-as-a-column" idiom) so one tall file spans every manager, league, and season.
# Two row kinds share the file (a `kind` column): "league" markers (one per searched
# comparable league — so a league a manager was inactive in still counts toward signal
# depth) and "txn" rows (one per that manager's transaction). Written INCREMENTALLY per
# manager (replace-by-owner_id), so a mid-fan-out failure leaves completed managers on disk
# and a re-run is idempotent — the leaguelogs reliability lesson applied to an expensive
# once-a-season fan-out. Consumed by compute_manager_features.py.


def _manager_activity_path(season: int, league_id) -> Path:
    return _SNAPSHOT_DIR / "sleeper" / str(season) / "league" / str(league_id) / f"manager_activity_{season}.parquet"


def write_manager_activity(df: pl.DataFrame, season: int, owner_id: str, *, league_id=None) -> None:
    """Append one manager's complete activity slice to the league-season file (replace-by-owner_id).

    `df` is treated as the COMPLETE set of rows for `owner_id` (their league markers + txn
    rows). If the file exists, any existing rows for that owner_id are dropped first
    so re-fetching a manager replaces their slice rather than duplicating (and a stale
    no-longer-comparable league can't linger). Concat is diagonal so a schema tweak on a
    later run doesn't break the append. League-scoped (keyed on the *target* league whose
    managers were fanned out), so the read-modify-write stays bounded to one league's file.
    """
    league_id = league_id or _active_league(season)[0]
    path = _manager_activity_path(season, league_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = pl.read_parquet(path).filter(pl.col("owner_id") != owner_id)
        df = pl.concat([existing, df], how="diagonal")
    df.write_parquet(path)


def read_manager_activity(season: int, owner_id: str | None = None, *, league_id=None) -> pl.DataFrame:
    """Read the cross-league manager activity for a league season, optionally one manager."""
    league_id = league_id or _active_league(season)[0]
    df = pl.read_parquet(_manager_activity_path(season, league_id))
    if owner_id is not None:
        df = df.filter(pl.col("owner_id") == owner_id)
    return df


def manager_activity_exists(season: int, *, league_id=None) -> bool:
    league_id = league_id or _active_league(season)[0]
    return _manager_activity_path(season, league_id).exists()


# --- Manager Features (cross-league behavioural profile, DECISION_READS.md §7) ---
# The deterministic feature extraction over manager_activity — one row per manager (owner_id):
# FAAB aggression, waiver/free-agent mix, waiver success rate, add/drop churn, trade frequency,
# positional lean of adds, plus the signal-depth counts (n_leagues / n_seasons / n_transactions)
# Phase B gates AI confidence on. Rate/lean features are null when undefined (thin sample), never
# a fabricated 0. This is the pre-filtered, credit-free AI input for the Phase-B Haiku dossier
# writer (never raw transaction logs — credit optimization, principle #5). A computed analytic,
# so it lives in derived/ alongside the other compute_* outputs; overwrite per run.


def _manager_features_path(season: int, league_id) -> Path:
    return _league_dir(league_id) / f"manager_features_{season}.parquet"


def write_manager_features(df: pl.DataFrame, season: int, *, league_id=None) -> None:
    """Write the per-manager behavioural feature profile for a league season (overwrite).

    Output of transforms/compute_manager_features.py: one row per league manager (owner_id),
    carrying the deterministic behavioural features + signal-depth counts + an is_primary flag
    (the primary user gets a blindspot-scoped dossier in Phase B).
    """
    league_id = league_id or _active_league(season)[0]
    path = _manager_features_path(season, league_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_manager_features(season: int, owner_id: str | None = None, *, league_id=None) -> pl.DataFrame:
    """Read the per-manager feature profile for a league season, optionally one manager."""
    league_id = league_id or _active_league(season)[0]
    df = pl.read_parquet(_manager_features_path(season, league_id))
    if owner_id is not None:
        df = df.filter(pl.col("owner_id") == owner_id)
    return df


def manager_features_exists(season: int, *, league_id=None) -> bool:
    league_id = league_id or _active_league(season)[0]
    return _manager_features_path(season, league_id).exists()


# --- Manager Dossiers (AI-written cross-league behavioural profiles, DECISION_READS.md §7) ---
# The Phase-B AI layer's output: one qualitative dossier per manager (owner_id), synthesised by
# Claude Haiku from the deterministic manager_features (never raw logs). The project's first
# AI-written entity. Tendencies-not-verdicts, fixed schema (headline / waiver_faab / trade_tendency /
# positional_lean / roster_construction / edge_or_blindspot / confidence_note) so dossiers read side
# by side; blindspot framing for the primary user, exploitable-edge for opponents. A zero-comparable-
# league manager gets a hardcoded "no intel" dossier (is_zero_signal=True) with the AI skipped. Rows
# carry the signal-depth echo + provenance (model, generated_at). Written by application/ai/
# write_manager_dossiers.py; overwrite per run (run-once-per-season unless --force).


def _manager_dossiers_path(season: int, league_id) -> Path:
    return _league_dir(league_id) / f"manager_dossiers_{season}.parquet"


def write_manager_dossiers(df: pl.DataFrame, season: int, *, league_id=None) -> None:
    """Write the per-manager AI dossiers for a league season (overwrite)."""
    league_id = league_id or _active_league(season)[0]
    path = _manager_dossiers_path(season, league_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_manager_dossiers(season: int, owner_id: str | None = None, *, league_id=None) -> pl.DataFrame:
    """Read the per-manager AI dossiers for a league season, optionally one manager."""
    league_id = league_id or _active_league(season)[0]
    df = pl.read_parquet(_manager_dossiers_path(season, league_id))
    if owner_id is not None:
        df = df.filter(pl.col("owner_id") == owner_id)
    return df


def manager_dossiers_exist(season: int, *, league_id=None) -> bool:
    league_id = league_id or _active_league(season)[0]
    return _manager_dossiers_path(season, league_id).exists()


# --- League Corpus (Session 0.5): discovery crawl + the selected league registry ---
#
# Two additive, cross-season entities under snapshots/corpus/ — NOT keyed by season (the corpus
# spans 2020-2025 in one file each). corpus_discovery is the full classified BFS crawl (one row per
# (league_id, season), free classification, no game data); corpus_manifest is the SELECTED league
# registry the L0 keying sessions consume. Both written whole (overwrite) — the discovery crawl holds
# the full deduped set in memory and rewrites it each checkpoint (the leaguelogs.snapshot() precedent).
# Purely additive: no existing entity, path, or transform is touched here.

def _corpus_discovery_path() -> Path:
    return _SNAPSHOT_DIR / "corpus" / "corpus_discovery.parquet"


def write_corpus_discovery(df: pl.DataFrame) -> None:
    """Write the full deduped discovery crawl (one row per (league_id, season)); overwrite."""
    _require_laptop("write_corpus_discovery", _WHY_REGISTRY, _FIX_REGISTRY)
    path = _corpus_discovery_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_corpus_discovery() -> pl.DataFrame:
    return pl.read_parquet(_corpus_discovery_path())


def corpus_discovery_exists() -> bool:
    return _corpus_discovery_path().exists()


def _corpus_manifest_path() -> Path:
    return _SNAPSHOT_DIR / "corpus" / "corpus_manifest.parquet"


def write_corpus_manifest(df: pl.DataFrame) -> None:
    """Write the selected league registry (one row per narrowed candidate); overwrite."""
    _require_laptop("write_corpus_manifest", _WHY_REGISTRY, _FIX_REGISTRY)
    path = _corpus_manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_corpus_manifest() -> pl.DataFrame:
    return pl.read_parquet(_corpus_manifest_path())


def corpus_manifest_exists() -> bool:
    return _corpus_manifest_path().exists()


# corpus_two_way_flags (Session 2.5): the ~4-6/season cross-position "two-way" players — rostered at a
# SKILL position by the pinned registry but scored under a NON-skill nfl_stats line (Hunter: WR / CB).
# A FLAG reference (not an exclusion), so the scorer can slice their cross-position answer-key points out.
def _corpus_two_way_flags_path() -> Path:
    return _SNAPSHOT_DIR / "corpus" / "corpus_two_way_flags.parquet"


def write_corpus_two_way_flags(df: pl.DataFrame) -> None:
    """One row per (season, sleeper_player_id) material two-way player; overwrite."""
    _require_laptop("write_corpus_two_way_flags", _WHY_REGISTRY, _FIX_REGISTRY)
    path = _corpus_two_way_flags_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_corpus_two_way_flags() -> pl.DataFrame:
    return pl.read_parquet(_corpus_two_way_flags_path())


def corpus_two_way_flags_exists() -> bool:
    return _corpus_two_way_flags_path().exists()


# --- Predictions ledger (Improvement-Loop L2, Session 4a) ---
# The first L2 entity: every engine read reshaped into an explicit, immutable CLAIM row — "what did the
# engine predict, and how confident was it?". One file per season holding ALL leagues' claims for that
# season; `league_id` is nullable (null for the scoring-scoped `ros_player_band`, set for the 5
# league-scoped reads). Grain is one row per (read, subject, as_of_week) claim family. This session
# backfills the frozen corpus spine as `served=false` reconstructions; the live 2026 path reuses the
# SAME columns with `served=true`. APPEND-ONLY + IMMUTABLE by `prediction_id` (which folds in
# `code_version`, so a spine recompute under new constants writes a distinguishable parallel population
# instead of overwriting) — the one thing this entity must make impossible is a silent overwrite.
# Law 1 is structural: this entity holds claims only — no grade / verdict / resolution column exists
# (the scorer, Session 5, is the first thing that judges). See corpus/backfill_predictions.py (writer),
# corpus/check_predictions.py (gate), corpus/constants_snapshot.py (the `constants_hash` provenance).
def _predictions_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "derived" / "ledger" / f"predictions_{season}.parquet"


def write_predictions(df: pl.DataFrame, season: int) -> None:
    """Append only genuinely-new claim rows to the season's ledger (idempotent by `prediction_id`).

    Immutable-append, mirroring `write_team_news_raw`: the batch is de-duplicated on `prediction_id`,
    then any `prediction_id` already on disk is dropped, so the file only GROWS — a re-run under the
    same `code_version` (⇒ same ids) appends nothing, and a re-run under a new `code_version` (⇒ new
    ids) appends a parallel population while keeping the old. Concat is diagonal so a later schema tweak
    doesn't break the append. Never overwrites an existing row.
    """
    _require_laptop("write_predictions", _WHY_LEDGER, _FIX_LEDGER)
    path = _predictions_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = df.unique(subset="prediction_id", keep="first")
    if path.exists():
        existing = pl.read_parquet(path)
        df = df.filter(~pl.col("prediction_id").is_in(existing["prediction_id"]))
        df = pl.concat([existing, df], how="diagonal")
    df.write_parquet(path)


def read_predictions(season: int, *, league_id=None, read: str | None = None) -> pl.DataFrame:
    """Read a season's prediction claims, optionally filtered to one league and/or one read.

    `league_id` filters to that league's rows (the scoring-scoped band, whose `league_id` is null, is
    excluded by an equality filter — use `read="ros_player_band"` to reach the band population)."""
    df = pl.read_parquet(_predictions_path(season))
    if league_id is not None:
        df = df.filter(pl.col("league_id") == str(league_id))
    if read is not None:
        df = df.filter(pl.col("read") == read)
    return df


def predictions_exists(season: int) -> bool:
    return _predictions_path(season).exists()


# --- Outcomes ledger (Improvement-Loop L2, Session 4b) ---
# The second L2 entity: one row per REALIZED FACT that a claim resolves against — "what actually
# happened?". Derived from the FROZEN persisted sources (`join_season` for player/roster points,
# `matchups` + the division-aware seeding for standings/made-playoffs, `league_settings` for the
# playoff config); never a re-fetch. `league_id` is nullable BY SCOPE: null for scoring-scoped player
# facts (weekly points are identical across leagues of a scoring_key — stored ONCE), set for
# league-scoped roster facts (wins / standing / made-playoffs — `roster_id` is only unique within a
# league). Outcomes are realized truth, not model output, so there is no `code_version` / `constants_hash`;
# `data_source` marks the derivation and `recorded_at` is left null (a wall-clock stamp would break the
# twice-derive value-identity the gate proves). APPEND-ONLY + IMMUTABLE by `outcome_id`. Law 1 holds:
# outcomes are facts, not grades — the grading primitives live in `resolutions` (compute_resolutions.py),
# and no verdict exists in either. See corpus/backfill_outcomes.py (writer), corpus/check_resolutions.py (gate).
def _outcomes_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "derived" / "ledger" / f"outcomes_{season}.parquet"


def write_outcomes(df: pl.DataFrame, season: int) -> None:
    """Append only genuinely-new realized-fact rows to the season's outcomes ledger (idempotent by
    `outcome_id`). Immutable-append, mirroring `write_predictions`: de-duplicate the batch on
    `outcome_id`, drop any id already on disk, diagonal-concat so the file only GROWS — a re-derive from
    the same frozen sources appends nothing. Never overwrites an existing row."""
    _require_laptop("write_outcomes", _WHY_LEDGER, _FIX_LEDGER)
    path = _outcomes_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = df.unique(subset="outcome_id", keep="first")
    if path.exists():
        existing = pl.read_parquet(path)
        df = df.filter(~pl.col("outcome_id").is_in(existing["outcome_id"]))
        df = pl.concat([existing, df], how="diagonal")
    df.write_parquet(path)


def read_outcomes(season: int, *, league_id=None, outcome_type: str | None = None) -> pl.DataFrame:
    """Read a season's realized facts, optionally filtered to one league and/or one outcome_type.

    `league_id` filters to that league's roster facts (scoring-scoped player facts, whose `league_id`
    is null, are excluded by the equality filter — use `outcome_type="player_weekly_pts"` to reach
    them)."""
    df = pl.read_parquet(_outcomes_path(season))
    if league_id is not None:
        df = df.filter(pl.col("league_id") == str(league_id))
    if outcome_type is not None:
        df = df.filter(pl.col("outcome_type") == outcome_type)
    return df


def outcomes_exists(season: int) -> bool:
    return _outcomes_path(season).exists()


# --- Resolutions ledger (Improvement-Loop L2, Session 4b) ---
# The `predictions ⋈ outcomes` join: one row per RESOLVED claim, carrying the GRADING PRIMITIVES
# (`error`/`abs_error`, `in_band`, `pit`, `brier`, `rank_error`, `direction_hit`) plus the realized
# `truth` and the claim's full provenance (so a resolution is always traceable to the exact claim + code
# + constants that made it). The primitives are the raw material the scorer (Session 5) judges —
# NOT verdicts: a per-row `pit=0.97` is a primitive, and this entity emits NO aggregate score, per-read
# pass/fail, `claim_correct`, or `suppress` flag (the scorer is the first thing that judges). PIT is the
# unifying calibration primitive, defined only where the claim states a distribution (interval +
# probability); point/ordinal/direction get their native primitive and `pit=null`. Unresolved claims are
# kept (with a `unresolved_reason`), never dropped, never a fake zero. APPEND-ONLY + IMMUTABLE by
# `resolution_id` (= the claim's `prediction_id`, a 1:1 join). See corpus/compute_resolutions.py (writer),
# corpus/check_resolutions.py (gate).
def _resolutions_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "derived" / "ledger" / f"resolutions_{season}.parquet"


def write_resolutions(df: pl.DataFrame, season: int) -> None:
    """Append only genuinely-new resolution rows to the season's ledger (idempotent by `resolution_id`).
    Immutable-append, mirroring `write_predictions`/`write_outcomes`: de-duplicate on `resolution_id`,
    drop any id already on disk, diagonal-concat so the file only GROWS. Never overwrites an existing row."""
    _require_laptop("write_resolutions", _WHY_LEDGER, _FIX_LEDGER)
    path = _resolutions_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = df.unique(subset="resolution_id", keep="first")
    if path.exists():
        existing = pl.read_parquet(path)
        df = df.filter(~pl.col("resolution_id").is_in(existing["resolution_id"]))
        df = pl.concat([existing, df], how="diagonal")
    df.write_parquet(path)


def read_resolutions(season: int, *, league_id=None, read: str | None = None) -> pl.DataFrame:
    """Read a season's resolutions, optionally filtered to one league and/or one read."""
    df = pl.read_parquet(_resolutions_path(season))
    if league_id is not None:
        df = df.filter(pl.col("league_id") == str(league_id))
    if read is not None:
        df = df.filter(pl.col("read") == read)
    return df


def resolutions_exists(season: int) -> bool:
    return _resolutions_path(season).exists()


# --- Engine scorecard (Improvement-Loop L3, Session 5) ---
# The first entity allowed to JUDGE — but only distributions, never a single claim. One row per
# (read, claim_type, slice_dim, slice_val) AGGREGATE verdict over the frozen `resolutions`, carrying the
# four metric families (skill vs a declared naive baseline · calibration = PIT/coverage/Brier ·
# confidence-honesty = is error monotone in the read's own stated confidence · discrimination = Spearman).
# Law 1 holds STRUCTURALLY here too: the grain is a slice, never a `prediction_id` — no single-claim
# pass/fail exists, by construction. The model verdict (`slice_dim='overall'`) is computed over
# `inputs_ok=true ∧ resolved=true` ONLY; `inputs_ok=false` and unresolved are their own quarantined slices,
# never blended in. APPEND-ONLY + IMMUTABLE by `scorecard_id` (which folds in `code_version`, so a re-score
# under a new scorer or new constants writes a distinguishable parallel population — the L2 discipline,
# reused). Each row carries the LEDGER's `constants_hash` (which model made the claims it scored) and the
# scorer's `code_version`. The front end does NOT read it (the "what we'd tell a user" line is copy for
# later). See corpus/compute_engine_scorecard.py (writer), corpus/check_scorecard.py (gate),
# corpus/scorecard_registry.py (the declared naive-baseline + confidence-signal registry).
def _engine_scorecard_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "derived" / "ledger" / f"engine_scorecard_{season}.parquet"


def write_engine_scorecard(df: pl.DataFrame, season: int) -> None:
    """Append only genuinely-new scorecard rows to the season's file (idempotent by `scorecard_id`).
    Immutable-append, mirroring `write_resolutions`: de-duplicate on `scorecard_id`, drop any id already on
    disk, diagonal-concat so the file only GROWS — a re-score under the same scorer `code_version` appends
    nothing; a re-score under a new one appends a parallel population. Never overwrites an existing row."""
    _require_laptop("write_engine_scorecard", _WHY_LEDGER, _FIX_LEDGER)
    path = _engine_scorecard_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = df.unique(subset="scorecard_id", keep="first")
    if path.exists():
        existing = pl.read_parquet(path)
        df = df.filter(~pl.col("scorecard_id").is_in(existing["scorecard_id"]))
        df = pl.concat([existing, df], how="diagonal")
    df.write_parquet(path)


def read_engine_scorecard(season: int, *, read: str | None = None,
                          slice_dim: str | None = None) -> pl.DataFrame:
    """Read a season's scorecard, optionally filtered to one read and/or one slice dimension."""
    df = pl.read_parquet(_engine_scorecard_path(season))
    if read is not None:
        df = df.filter(pl.col("read") == read)
    if slice_dim is not None:
        df = df.filter(pl.col("slice_dim") == slice_dim)
    return df


def engine_scorecard_exists(season: int) -> bool:
    return _engine_scorecard_path(season).exists()


# --- Tuner proposals (Improvement-Loop L4) ---
# The L4 Tuner's only write: one row per (constant, asof_date) sweep decision — current → proposed with its
# train-vs-holdout evidence, coupled-gate deltas, effect size, inputs_ok, and a RECOMMEND/HOLD verdict.
# NOT season-partitioned (a proposal spans the split); keyed by `proposal_id`. Immutable-append like the
# scorecard: a re-run at the same asof over the same frozen baseline appends nothing (determinism); the
# human reads the co-rendered markdown and promotes in a normal worktree session ("auto-tune, human
# promotes"). The tuner never edits a transform or merges a constant.

def _tune_proposals_path() -> Path:
    return _SNAPSHOT_DIR / "derived" / "ledger" / "tune_proposals.parquet"


def write_tune_proposals(df: pl.DataFrame) -> None:
    """Append only genuinely-new proposals (idempotent by `proposal_id`). De-dup on proposal_id, drop ids
    already on disk, diagonal-concat so the file only GROWS — a re-run at the same asof_date over the same
    frozen inputs appends nothing; a new asof or a changed baseline appends a parallel population. Never
    overwrites (immutable-append, mirroring `write_engine_scorecard`)."""
    _require_laptop("write_tune_proposals", _WHY_LEDGER, _FIX_LEDGER)
    path = _tune_proposals_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    df = df.unique(subset="proposal_id", keep="first")
    if path.exists():
        existing = pl.read_parquet(path)
        df = df.filter(~pl.col("proposal_id").is_in(existing["proposal_id"]))
        df = pl.concat([existing, df], how="diagonal")
    df.write_parquet(path)


def read_tune_proposals(asof_date: str | None = None) -> pl.DataFrame:
    """All proposals, optionally filtered to one asof_date."""
    df = pl.read_parquet(_tune_proposals_path())
    if asof_date is not None:
        df = df.filter(pl.col("asof_date") == asof_date)
    return df


def tune_proposals_exists() -> bool:
    return _tune_proposals_path().exists()


# --- Center-gap delta-tracking (Improvement-Loop Session 7, the de-bias) ---
# Per (season, scoring_key): the predicted-vs-realized ROS-centre gap — the SYSTEMATIC optimism magnitude
# each season (positive = the borrowed centre runs high). The substrate for a future SEASONAL auto-update of
# FORM_ANCHOR_W (re-fit the dial when a season resolves — the optimism is a slow structural bias, so a
# season-cadence re-fit, not a twitchy weekly one). Immutable-append like tune_proposals / the scorecard:
# keyed by `gap_id` (season|scoring_key|as_of_week|code_version), a re-run over the same frozen inputs
# appends nothing. Provenanced to the FROZEN L3 baseline (std instr 8) — this is a measurement, never a fit.

def _center_gap_path() -> Path:
    return _SNAPSHOT_DIR / "derived" / "ledger" / "center_gap.parquet"


def write_center_gap(df: pl.DataFrame) -> None:
    """Append only genuinely-new gap rows (idempotent by `gap_id`). De-dup on gap_id, drop ids already on
    disk, diagonal-concat so the file only GROWS — never overwrites (immutable-append, mirroring
    write_tune_proposals). A re-run at the same code_version over the same frozen inputs appends nothing."""
    _require_laptop("write_center_gap", _WHY_LEDGER, _FIX_LEDGER)
    path = _center_gap_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    df = df.unique(subset="gap_id", keep="first")
    if path.exists():
        existing = pl.read_parquet(path)
        df = df.filter(~pl.col("gap_id").is_in(existing["gap_id"]))
        df = pl.concat([existing, df], how="diagonal")
    df.write_parquet(path)


def read_center_gap(season: int | None = None) -> pl.DataFrame:
    """All center-gap rows, optionally filtered to one season."""
    df = pl.read_parquet(_center_gap_path())
    if season is not None:
        df = df.filter(pl.col("season") == season)
    return df


def center_gap_exists() -> bool:
    return _center_gap_path().exists()


# --- League registry (Improvement-Loop L0 keying) ---
# The single source of truth for "which leagues exist and how each is keyed", replacing the implicit
# config.SLEEPER_LEAGUE_ID single-league assumption (audit S1.3 — league #2 silently overwriting #1).
# One row per (league_id, season): its scoring_key + shape_key (the scopes derived analytics partition
# on), whether it is mine (the served/live league vs a corpus backfill league), when it was onboarded,
# and its pilot cohort. Built by shared/league_registry.py as a projection of the corpus manifest
# unioned with the live config league; read by shared/league_resolver and by the scope-defaulting
# derived read/write functions (`_active_league`). Written whole (overwrite) — small, rebuilt from source.

_LEAGUES_COLS = ["league_id", "season", "scoring_key", "shape_key", "is_mine",
                 "onboarded_at", "pilot_cohort"]


def _leagues_path() -> Path:
    return _SNAPSHOT_DIR / "leagues.parquet"


def write_leagues(df: pl.DataFrame) -> None:
    """Write the league registry (one row per (league_id, season)); overwrite. Enforces the schema order."""
    _require_laptop("write_leagues", _WHY_REGISTRY, _FIX_REGISTRY)
    path = _leagues_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.select(_LEAGUES_COLS).write_parquet(path)


def read_leagues() -> pl.DataFrame:
    return pl.read_parquet(_leagues_path())


def leagues_exists() -> bool:
    return _leagues_path().exists()


def _active_league(season: int) -> tuple[str, str]:
    """(league_id, scoring_key) for the is_mine league in `season` — the scope every derived read/write
    defaults to when a caller passes no explicit league_id/scoring_key. Raises if the registry is missing
    or has no is_mine row for the season (build it: `python3 -m application.shared.league_registry build`)."""
    if not leagues_exists():
        raise ValueError(
            "leagues.parquet not found — run `python3 -m application.shared.league_registry build` "
            "before reading/writing scoped derived entities."
        )
    df = read_leagues().filter(pl.col("is_mine") & (pl.col("season") == season))
    if df.is_empty():
        raise ValueError(f"No is_mine league for season {season} in leagues.parquet.")
    r = df.row(0, named=True)
    return str(r["league_id"]), str(r["scoring_key"])


def _active_league_any(season: int) -> tuple[str, str]:
    """(league_id, scoring_key) for the is_mine league that OWNS a *current-world* read whose `season`
    may exceed the registry's latest league season. Unlike `_active_league` (strict per-season), this
    resolves the is_mine row for `season` if present, else falls back to the most-recent is_mine season
    **not exceeding it**. A redraft league is a continuing entity — a NEW Sleeper `league_id` each year —
    so a 2026 news-world read anchored on the 2025 league legitimately resolves to that 2025 league, and
    there is no 2026 `league_id` to key on. Used ONLY by ros_synthesis (news-season-keyed, its league
    membership inherited from its prior-season anchor); every other entity keeps `_active_league`'s strict
    resolution so a genuinely missing season stays a hard error, not a silently-masked one."""
    if not leagues_exists():
        raise ValueError(
            "leagues.parquet not found — run `python3 -m application.shared.league_registry build` "
            "before reading/writing scoped derived entities."
        )
    mine = read_leagues().filter(pl.col("is_mine"))
    exact = mine.filter(pl.col("season") == season)
    if not exact.is_empty():
        r = exact.row(0, named=True)
        return str(r["league_id"]), str(r["scoring_key"])
    prior = mine.filter(pl.col("season") <= season).sort("season", descending=True)
    if prior.is_empty():
        raise ValueError(f"No is_mine league at or before season {season} in leagues.parquet.")
    r = prior.row(0, named=True)
    return str(r["league_id"]), str(r["scoring_key"])


# --- Demo manifest (Stage-B B0): the recorded demo slate ---
# The authoritative demo set the multi-league phase serves: one row per demo (league_id, season) slice
# carrying its root-keyed lineage_id (the earliest league in the redraft chain — globally unique, never
# collides), a pinned viewer_roster_id ("you" for that slice), and the panel-gating policy (which analytic
# panels are honest for the slice — market/ros are "right now" reads only the live is_mine 2025 slice has).
# Built by corpus/build_demo_manifest.py from demo_slate.csv; read by the B3 loader + /api/leagues catalog.
# Kept separate from leagues.parquet (whose write_leagues enforces a fixed 7-col schema). Overwrite whole.

_DEMO_MANIFEST_COLS = ["lineage_id", "league_id", "season", "name", "scoring_key", "num_teams",
                       "is_mine", "previous_league_id", "viewer_roster_id",
                       "panels_market", "panels_ros", "panels_manager"]


def _demo_manifest_path() -> Path:
    return _SNAPSHOT_DIR / "demo_manifest.parquet"


def write_demo_manifest(df: pl.DataFrame) -> None:
    """Write the demo slate (one row per demo (league_id, season)); overwrite. Enforces the column order."""
    _require_laptop("write_demo_manifest", _WHY_REGISTRY, _FIX_REGISTRY)
    path = _demo_manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.select(_DEMO_MANIFEST_COLS).write_parquet(path)


def read_demo_manifest() -> pl.DataFrame:
    return pl.read_parquet(_demo_manifest_path())


def demo_manifest_exists() -> bool:
    return _demo_manifest_path().exists()


# --- Synthetic leagues (P5/S2d): the generated demo clone ------------------------------------
# A synthetic league is GENERATED, not harvested: `serve/build_demo_clone.py` reads a frozen corpus
# slice and writes a re-keyed, anonymised copy under its own league_id. It exists so the public demo
# is not Will's real league with ten real managers' Sleeper handles on it.
#
# THE RULE, and it is the whole reason this lives here rather than as scattered checks:
#
#     A synthetic league is visible to everything that READS FOR SERVING (the loader, the API) and
#     invisible to everything that WRITES OR COMPUTES (harvest, weekly_refresh, the corpus builders,
#     league_registry).
#
# Producers consult `is_synthetic()` and refuse. The hazard is concrete rather than theoretical: the
# clone is in the loader's work-list, so `weekly_refresh --league DEMO-2025` would otherwise try to
# fetch a league that does not exist on Sleeper. Scattered `if league_id != DEMO` checks are how one
# of those gets missed, so there is exactly one predicate and every producer calls it.
#
# A committed literal, not a lookup: the set is reviewable in one line, cannot drift from a generated
# artifact, and needs no I/O on a hot path. `check_demo_clone` asserts it agrees with the catalog.
# The ids are deliberately NOT Sleeper-shaped — a Sleeper league_id is an 18-19 digit snowflake, so
# anything that mistakes `DEMO-2025` for a real league fails loudly instead of silently succeeding.
SYNTHETIC_LEAGUE_IDS = frozenset({"DEMO-2025"})


def is_synthetic(league_id) -> bool:
    """True if this league is generated rather than harvested — see SYNTHETIC_LEAGUE_IDS."""
    return str(league_id) in SYNTHETIC_LEAGUE_IDS


# The synthetic slices' catalog rows — same 12 columns as the demo manifest, its OWN artifact.
#
# Deliberately NOT appended to demo_manifest.parquet. That parquet is the frozen CORPUS slate (31
# rows) that `compute_demo_slices`, `check_matchup_result` and the L2 ledger all count on; the clone
# is a SERVE-layer artifact. Keeping them separate is what lets the corpus stay 31 while the served
# `league_catalog` table becomes 32, and it is why the table was renamed in the same session.
def _synthetic_catalog_path() -> Path:
    return _SNAPSHOT_DIR / "synthetic_catalog.parquet"


def write_synthetic_catalog(df: pl.DataFrame) -> None:
    """Write the synthetic slices' catalog rows; overwrite. Same column order as the demo manifest,
    because `build_db` concatenates the two into one table."""
    _require_laptop("write_synthetic_catalog", _WHY_REGISTRY, _FIX_REGISTRY)
    path = _synthetic_catalog_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.select(_DEMO_MANIFEST_COLS).write_parquet(path)


def read_synthetic_catalog() -> pl.DataFrame:
    """The synthetic catalog rows, or an EMPTY frame with the right schema when none exist.

    Empty-not-absent on purpose: every caller concatenates this with the demo manifest, and a store
    that has never generated a clone must still load cleanly rather than special-casing the absence.
    """
    path = _synthetic_catalog_path()
    if not path.exists():
        return read_demo_manifest().clear()
    return pl.read_parquet(path)


def synthetic_catalog_exists() -> bool:
    return _synthetic_catalog_path().exists()


# --- Connected leagues (P5/S4a): the catalog a stranger's league can legally live in ----------
# The THIRD catalog source, and the first one a machine other than the laptop may write.
#
# Why a third artifact rather than a row in one of the other two. `demo_manifest.parquet` is the
# frozen 31-row CORPUS slate that `compute_demo_slices`, `check_matchup_result` and the immutable L2
# ledger all count on; `synthetic_catalog.parquet` is for GENERATED clones whose ids are deliberately
# not Sleeper-shaped. A connected league is a third kind of thing — harvested from Sleeper, owned by
# a real user, arriving one at a time forever — so it gets its own file: 31 + 1 + N.
#
# THE SHAPE IS WHY A WORKER MAY HOLD THIS PEN. The other three catalog writers overwrite the whole
# file on a fixed schema, so a machine that knows about fewer leagues than the laptop would silently
# shrink the shared registry — that is what makes them laptop-owned (see LAPTOP_OWNED_WRITERS). This
# one writes or replaces exactly ONE (league_id, season) row and leaves every other row alone, so
# there is no shrink to cause. The ADR's objection was never the owner; it was the shape.
def _connected_catalog_path() -> Path:
    return _SNAPSHOT_DIR / "connected_catalog.parquet"


def write_connected_league(df: pl.DataFrame, league_id: str, season: int) -> None:
    """Write or REPLACE exactly one connected league's catalog row; every other row is untouched.

    Idempotent by `(league_id, season)`: re-onboarding the same league replaces its row rather than
    duplicating it, and the file is sorted by `(season, league_id)` so a re-onboard cannot reorder
    the others either. Both properties are load-bearing — this is the one catalog writer a worker is
    allowed to call, and "append-shaped" is the entire justification.

    **Dtypes are cast, not merely selected.** `build_db._catalog()` concatenates the three catalog
    sources with `how="vertical"`, which is polars' STRICT variant: it requires identical names,
    order AND dtypes. A row built in Python arrives with `viewer_roster_id: Null` when the seat is
    absent and can arrive with `season: Int32`, either of which raises `SchemaError` for the whole
    catalog — i.e. it would break the demo for everyone, not just this league. The other three
    writers enforce column order only, which is safe for them because they are written from frames
    that already came off disk. This one is written from a dict, so it enforces both.

    Takes `league_id` and `season` positionally on purpose (CODING_BIBLE §5): a writer that can be
    aimed at a throwaway id is one `check_store_boundary --prove-bites` can drive for real.
    """
    schema = read_demo_manifest().schema        # the canonical 12 columns AND their dtypes
    row = df.select(_DEMO_MANIFEST_COLS).cast(schema)
    keep = read_connected_catalog().filter(
        ~((pl.col("league_id").cast(str) == str(league_id)) & (pl.col("season") == int(season))))
    out = pl.concat([keep, row], how="vertical").sort(["season", "league_id"])
    path = _connected_catalog_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    out.write_parquet(path)


def read_connected_catalog() -> pl.DataFrame:
    """The connected leagues' catalog rows, or an EMPTY frame with the right schema when none exist.

    Empty-not-absent, exactly as `read_synthetic_catalog` is and for the same reason: every caller
    concatenates this with the demo manifest, and a store that has never onboarded anyone — which is
    every store until the first connect — must still load cleanly rather than special-casing it.
    """
    path = _connected_catalog_path()
    if not path.exists():
        return read_demo_manifest().clear()
    return pl.read_parquet(path)


def connected_catalog_exists() -> bool:
    return _connected_catalog_path().exists()
