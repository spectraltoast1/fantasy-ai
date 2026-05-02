import json
import math
import warnings
from datetime import date

warnings.filterwarnings("ignore", category=FutureWarning)
import nfl_data_py as nfl

SKILL_POSITIONS = {"QB", "RB", "WR", "TE"}
CACHE_PATH = "data/nfl_stats_{year}.json"
L4W = 4  # rolling window size


def _cache_path(year):
    return CACHE_PATH.format(year=year)


def refresh_nfl_stats(year):
    print(f"Fetching nfl_data_py weekly data for {year}...")
    weekly = None
    for attempt in range(3):
        try:
            weekly = nfl.import_weekly_data([year])
            break
        except Exception:
            print(f"  {year} not available yet — trying {year - 1}.")
            year -= 1
    if weekly is None:
        raise RuntimeError("Could not fetch nfl_data_py weekly data for the last 3 years.")
    weekly = weekly[
        (weekly["season_type"] == "REG") &
        (weekly["position"].isin(SKILL_POSITIONS))
    ].copy()

    print(f"Fetching snap counts for {year}...")
    try:
        snaps = nfl.import_snap_counts([year])
    except Exception:
        print(f"  Snap counts for {year} unavailable — snap data will be empty.")
        snaps = None
    if snaps is not None:
        snaps = snaps[snaps["game_type"] == "REG"].copy()

    print("Fetching ID mapping table...")
    ids = nfl.import_ids()
    # Build pfr_id → gsis_id lookup (drop rows missing either)
    id_map = (
        ids[ids["pfr_id"].notna() & ids["gsis_id"].notna()]
        .set_index("pfr_id")["gsis_id"]
        .to_dict()
    )

    if snaps is not None:
        snaps["gsis_id"] = snaps["pfr_player_id"].map(id_map)
        snaps = snaps[snaps["gsis_id"].notna()]
        snap_season = (
            snaps.groupby("gsis_id")["offense_pct"]
            .mean()
            .to_dict()
        )
    else:
        snap_season = {}

    # Compute team rush attempt totals per week for rush share denominator
    team_rush_by_week = (
        weekly.groupby(["recent_team", "week"])["carries"]
        .sum()
        .reset_index()
        .rename(columns={"carries": "team_carries"})
    )
    weekly = weekly.merge(team_rush_by_week, on=["recent_team", "week"], how="left")
    weekly["rush_share"] = weekly.apply(
        lambda r: (r["carries"] / r["team_carries"]) if r["team_carries"] > 0 else 0.0,
        axis=1,
    )

    all_weeks = sorted(weekly["week"].unique())
    last4 = all_weeks[-L4W:] if len(all_weeks) >= L4W else all_weeks

    def _clean(v):
        return None if (isinstance(v, float) and math.isnan(v)) else v

    def _clean_list(lst):
        return [_clean(v) for v in lst]

    stats = {}
    for gsis_id, group in weekly.groupby("player_id"):
        group = group.sort_values("week")
        recent = group[group["week"].isin(last4)]

        # Season averages
        ts_season = round(float(group["target_share"].mean()), 3)
        rs_season = round(float(group["rush_share"].mean()), 3)
        fp_season = round(float(group["fantasy_points_ppr"].mean()), 2)
        snap_s = round(snap_season.get(gsis_id, 0.0), 3)

        # Last-4-week lists (one value per week played in that window)
        ts_l4w = [round(float(v), 3) for v in recent["target_share"].tolist()]
        rs_l4w = [round(float(v), 3) for v in recent["rush_share"].tolist()]
        fp_l4w = [round(float(v), 2) for v in recent["fantasy_points_ppr"].tolist()]

        snap_l4w = []
        if snaps is not None and gsis_id in id_map.values():
            snap_rows = snaps[
                (snaps["gsis_id"] == gsis_id) & (snaps["week"].isin(last4))
            ].sort_values("week")
            snap_l4w = [round(float(v), 3) for v in snap_rows["offense_pct"].tolist()]

        row = group.iloc[-1]
        stats[gsis_id] = {
            "name": row["player_display_name"],
            "position": row["position"],
            "team": row["recent_team"],
            "snap_pct_season": _clean(snap_s),
            "target_share_season": _clean(ts_season),
            "rush_share_season": _clean(rs_season),
            "fantasy_points_ppr_season": _clean(fp_season),
            "snap_pct_l4w": _clean_list(snap_l4w),
            "target_share_l4w": _clean_list(ts_l4w),
            "rush_share_l4w": _clean_list(rs_l4w),
            "fantasy_points_ppr_l4w": _clean_list(fp_l4w),
            "weeks_played": int(len(group)),
        }

    cache = {"updated_at": str(date.today()), "year": year, "players": stats}
    path = _cache_path(year)
    with open(path, "w") as f:
        json.dump(cache, f)

    print(f"Cached {len(stats)} players to {path}")
    return cache


def load_nfl_stats(year):
    path = _cache_path(year)
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"No cache found at {path} — run refresh_nfl_stats({year}) first.")
        return {}

    updated = data.get("updated_at")
    if updated:
        days_old = (date.today() - date.fromisoformat(updated)).days
        if days_old > 7:
            print(f"Warning: nfl_stats_{year}.json is {days_old} days old.")

    return data.get("players", {})


if __name__ == "__main__":
    import sys
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
    cache = refresh_nfl_stats(year)
    players = cache["players"]
    weeks = set()
    for p in players.values():
        weeks.add(p["weeks_played"])
    print(f"\nSummary: {len(players)} players, weeks played range {min(weeks)}–{max(weeks)}")
    # Print a sample
    sample_id = next(iter(players))
    print(f"\nSample ({sample_id}):")
    print(json.dumps(players[sample_id], indent=2))
