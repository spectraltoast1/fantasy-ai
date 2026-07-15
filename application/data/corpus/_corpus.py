"""Pure corpus helpers — stratum predicates + keys, shared by discover / select / check.

No I/O, no polars at import. The single source of truth for "what is the matched stratum", so the
crawl's stopping rule, the selection, and the gate can never drift from one another (the _manager.py /
_scoring.py precedent). The scope keys live in transforms/_keys.py and are re-exported below.
"""
# The corpus window (Session 0 confirmed projections back to 2020, matching the nfl_stats backfill).
SEASONS = list(range(2025, 2019, -1))   # 2025 .. 2020

# --- The matched stratum: the product's shape (PPR/half · 1QB · redraft · 10-14 teams) -----------
MATCHED_SCORINGS = ("ppr", "half")
MATCHED_TEAMS_MIN, MATCHED_TEAMS_MAX = 10, 14

# The generalization stratum's SHARED budget constants (Session 2.5). Single source of truth so
# select.py (which enforces them) and check_corpus.py (which gates them) can never drift — the
# _manager.py / _scoring.py precedent. The gen set exercises CODE PATHS (superflex / divisions /
# custom scoring / exotic sizes), not representativeness, so *shape* coverage matters and volume
# does not; the custom-key cap keeps the scoring-scoped substrate compute bounded.
GEN_SEASON_MIN = 6          # every season 2020-2025 must carry ≥ this many gen leagues (hard-gated)
GEN_CUSTOM_KEY_CAP = 12     # distinct custom scoring_keys in the gen stratum ≤ this (substrate budget)


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
# Home moved to transforms/_keys.py in the L0 keying session, so the data layer and transforms can key
# scoped parquet without a transforms<->corpus cycle. Re-exported here unchanged so select/discover/check
# keep importing `_corpus.scoring_key` / `_corpus.shape_key`.
from application.data.transforms._keys import scoring_key, shape_key  # noqa: F401  (re-export)
