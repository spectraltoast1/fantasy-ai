"""Pure corpus helpers — stratum predicates + keys, shared by discover / select / check.

No I/O, no polars. The single source of truth for "what is the matched stratum", so the crawl's
stopping rule, the selection, and the gate can never drift from one another (the _manager.py /
_scoring.py precedent). Reuses transforms/_scoring.scoring_profile for the scoring label.
"""
import hashlib
import json

# The corpus window (Session 0 confirmed projections back to 2020, matching the nfl_stats backfill).
SEASONS = list(range(2025, 2019, -1))   # 2025 .. 2020

# --- The matched stratum: the product's shape (PPR/half · 1QB · redraft · 10-14 teams) -----------
MATCHED_SCORINGS = ("ppr", "half")
MATCHED_TEAMS_MIN, MATCHED_TEAMS_MAX = 10, 14


def is_matched_eligible(scoring_profile, qb_structure, league_format, num_teams) -> bool:
    """Classification-only matched predicate (the filter + scoreability are applied later).

    matched = scoring ∈ {ppr, half} · 1qb · redraft · 10-14 teams. This is the ONLY stratum that
    tunes/gates, so it must be exactly the product's shape."""
    return (
        scoring_profile in MATCHED_SCORINGS
        and qb_structure == "1qb"
        and league_format == "redraft"
        and num_teams is not None
        and MATCHED_TEAMS_MIN <= int(num_teams) <= MATCHED_TEAMS_MAX
    )


def is_generalization_eligible(scoring_profile, qb_structure, has_divisions, num_teams) -> bool:
    """A deliberate robustness spread — the exotic shapes that exercise the any-league code paths
    (superflex pools · division seeding · custom scoring · exotic sizes incl. 32-team). Never tuned."""
    exotic_size = num_teams is None or not (MATCHED_TEAMS_MIN <= int(num_teams) <= MATCHED_TEAMS_MAX)
    return bool(
        qb_structure == "sf"
        or has_divisions
        or scoring_profile == "custom"
        or exotic_size
    )


# --- Keys (per IMPROVEMENT_LOOP L0) ---------------------------------------------------------------

def scoring_key(scoring_profile: str, scoring_settings: dict | None) -> str:
    """`ppr`/`half`/`std` for canned profiles; `cust-<8-char hash of the normalised scoring dict>` for
    custom — so two identically-scored custom leagues share one key (keeps AI cost flat as L0 wires it)."""
    if scoring_profile in ("ppr", "half", "std"):
        return scoring_profile
    norm = json.dumps(scoring_settings or {}, sort_keys=True, separators=(",", ":"))
    return "cust-" + hashlib.sha1(norm.encode()).hexdigest()[:8]


def shape_key(num_teams, qb_structure: str, league_format: str) -> str:
    """A compact roster-shape signature, e.g. `12t-1qb-redraft`."""
    n = f"{int(num_teams)}t" if num_teams is not None else "NAt"
    return f"{n}-{qb_structure}-{league_format}"
