# Data Token Vocabulary

This is the **contract** between the strategy markdown file (output of Pass 2 + Pass 3) and your Python data orchestrator. Every token defined here must map to a Python fetcher function. Every token used in the strategy file must be defined here.

Data stack assumed (see `data_sources.txt` for full reference):
- **LeagueLogs API** — market values, player metadata, blurbs, NFL state
- **Sleeper API** — league/roster/matchup data, weekly projections
- **nfl_data_py** — production stats, snap counts, target share, NGS, EPA
- **The Odds API** — Vegas lines (free) + player props (paid budget)
- **FantasyPros API** — projections (PPR/half/standard) + news
- **NFL official** — practice participation, injury designations, inactives
- **datawithbliss** — historical weather (forecast source TBD — NWS recommended)

---

## How to use this file

For each token:
- **Token name**: snake_case identifier used in `{needs: ...}` blocks. Match exactly to your Python fetcher function naming or argument schema.
- **Description**: one-sentence definition.
- **Source**: which fetcher/API returns this.
- **Availability**: `available` / `paywalled` / `unavailable` / `gap` — used by Pass 3 to flag rules.
- **Cadence**: `realtime` / `weekly` / `static` / `historical`.

---

## Player Identity & Roster Status

| Token | Description | Source | Availability | Cadence |
|---|---|---|---|---|
| `player_id` | Sleeper player ID (canonical join key) | LeagueLogs / Sleeper | available | static |
| `player_name` | Display name | LeagueLogs | available | static |
| `player_position` | QB/RB/WR/TE only (no K/DEF in market) | LeagueLogs | available | static |
| `player_team` | Current NFL team | LeagueLogs | available | weekly |
| `player_age` | Player age | LeagueLogs | available | static |
| `player_height_weight` | Height (inches), weight (lbs) | LeagueLogs | available | static |
| `years_exp` | Years of NFL experience | LeagueLogs | available | static |
| `depth_chart_position` | Starter/RB1/RB2/etc | Sleeper | available | weekly |
| `roster_status` | active/inactive/IR/suspended/practice_squad | LeagueLogs | available | weekly |

---

## Injury & Practice Status

| Token | Description | Source | Availability | Cadence |
|---|---|---|---|---|
| `injury_status` | Q/D/O/IR designation | NFL official / Sleeper | available | realtime |
| `practice_participation` | DNP/Limited/Full (Wed/Thu/Fri) | NFL official | available | weekly (practice days) |
| `gameday_inactive` | Inactive list at 90 min before kickoff | NFL official | available | realtime |
| `qb_status` | Identity and health of starting QB | NFL official + depth chart | available | realtime |
| `o_line_health` | OL injury status (uses positional injury reports) | NFL official | available | weekly |
| `blurb` | LeagueLogs LLM-generated 1–3 sentence status note | LeagueLogs | available | realtime |
| `blurb_signals` | Tags on blurb: injury/transaction/depth-chart/returning/inactive | LeagueLogs | available | realtime |

---

## Player-Level Usage (nfl_data_py)

| Token | Description | Source | Availability | Cadence |
|---|---|---|---|---|
| `snap_pct` | Offensive snap percentage | nfl_data_py | available | weekly |
| `snap_pct_4w` | 4-week rolling snap % | nfl_data_py | available | weekly |
| `snap_pct_trend` | Snap % change over recent N weeks (derived) | nfl_data_py | available | weekly |
| `target_share` | Targets / team targets | nfl_data_py | available | weekly |
| `target_share_4w` | 4-week rolling target share | nfl_data_py | available | weekly |
| `air_yards_share` | Player air yards / team air yards | nfl_data_py | available | weekly |
| `route_participation` | Routes run / team dropbacks | nfl_data_py | available | weekly |
| `rush_attempt_share` | Player carries / team carries | nfl_data_py | available | weekly |
| `redzone_targets` | Targets inside the 20 | nfl_data_py | available | weekly |
| `redzone_carries` | Carries inside the 20 | nfl_data_py | available | weekly |
| `goal_line_carries` | Carries inside the 5 | nfl_data_py | available | weekly |
| `adot` | Average depth of target | nfl_data_py | available | weekly |
| `team_pass_rate` | Team pass-play rate (neutral) | nfl_data_py | available | weekly |
| `team_rush_rate` | Team rush-play rate (neutral) | nfl_data_py | available | weekly |

---

## Player-Level Efficiency (nfl_data_py + NGS)

| Token | Description | Source | Availability | Cadence |
|---|---|---|---|---|
| `epa_per_play` | EPA per play, player-attributed | nfl_data_py | available | weekly |
| `success_rate` | Success rate, player-attributed | nfl_data_py | available | weekly |
| `ypc` | Yards per carry | nfl_data_py | available | weekly |
| `ngs_separation` | Avg separation at catch | nfl_data_py (NGS) | available | weekly |
| `ngs_cpoe` | Completion % above expected (QB) | nfl_data_py (NGS) | available | weekly |
| `ngs_time_to_throw` | Time to throw (QB) | nfl_data_py (NGS) | available | weekly |
| `ngs_intended_air_yards` | Avg intended air yards (QB) | nfl_data_py (NGS) | available | weekly |

---

## Defense / Matchup

| Token | Description | Source | Availability | Cadence |
|---|---|---|---|---|
| `def_rank_vs_pos` | Defensive rank vs position by FP allowed | nfl_data_py (derived) | available | weekly |
| `def_epa_per_play_allowed` | EPA/play allowed (overall, vs pass, vs rush) | nfl_data_py | available | weekly |
| `def_pressure_rate` | Pass-rush pressure rate | nfl_data_py | available | weekly |
| `def_yards_allowed_pos` | Yards allowed to position | nfl_data_py | available | weekly |
| `def_pass_rate_allowed` | Opponent pass rate when leading/trailing | nfl_data_py | available | weekly |
| `def_coverage_man_pct` | Man coverage frequency | PFF | paywalled | weekly |
| `def_coverage_zone_pct` | Zone coverage frequency | PFF | paywalled | weekly |
| `wr_man_success_rate` | WR success rate vs man coverage | PFF | paywalled | weekly |
| `wr_vs_cb_grade` | WR vs specific CB matchup grade | PFF | paywalled | weekly |

---

## Game Environment (Vegas / Weather)

| Token | Description | Source | Availability | Cadence |
|---|---|---|---|---|
| `vegas_spread` | Game spread | Odds API (free) | available | realtime |
| `vegas_total` | Game over/under | Odds API (free) | available | realtime |
| `vegas_implied_total` | Team implied points | Odds API (derived) | available | realtime |
| `vegas_movement_24h` | Line movement in last 24h | Odds API (derived) | available | realtime |
| `player_prop_rec_yards` | Receiving yards prop O/U | Odds API (paid) | paywalled-budgeted | on-demand |
| `player_prop_rush_yards` | Rushing yards prop O/U | Odds API (paid) | paywalled-budgeted | on-demand |
| `player_prop_anytime_td` | Anytime TD odds | Odds API (paid) | paywalled-budgeted | on-demand |
| `weather_wind_mph` | Game-day wind speed forecast | NWS API | gap-low-effort | realtime |
| `weather_temp_f` | Game-day temperature forecast | NWS API | gap-low-effort | realtime |
| `weather_precip` | Precipitation forecast | NWS API | gap-low-effort | realtime |
| `weather_indoor` | Indoor stadium flag (short-circuits forecast lookup) | static stadiums.json | available | static |
| `stadium_lat_lng` | Stadium coordinates (seed for NWS forecast call) | static stadiums.json | available | static |

---

## Market & Consensus (LeagueLogs)

| Token | Description | Source | Availability | Cadence |
|---|---|---|---|---|
| `market_value` | LeagueLogs market value, 0–100 normalized within profile. Anchored on consensus ADP across major formats; projection-based fallback for deep-roster players past ADP coverage. | LeagueLogs | available | every 6h |
| `market_value_quality` | Whether the value is consensus-derived (top ~150) or projection-fallback (deeper) — affects trust weight in trade calls (DERIVE LOCALLY using overall_rank threshold) | derived | available-derived | every 6h |
| `market_raw_value` | Unnormalized score (comparable across players in same snapshot) | LeagueLogs | available | every 6h |
| `market_overall_rank` | Rank across all positions in profile | LeagueLogs | available | every 6h |
| `market_position_rank` | Rank within position in profile | LeagueLogs | available | every 6h |
| `market_value_trend` | Change in market value across recent snapshots (DERIVE LOCALLY — LeagueLogs trend fields currently stubbed at zero) | derived from local snapshot history | available-derived | weekly |
| `rookie_pick_value` | Dynasty rookie pick market value (incl. future-pick discounting) | LeagueLogs | available | every 6h |

Note: `market_value` is profile-specific. When invoking, the Python orchestrator must
specify which profile (redraft-1qb-12t-ppr1, dynasty-2qb-12t-ppr1, etc.) based on
league_format and league_scoring.

---

## Projections (Sleeper + FantasyPros)

| Token | Description | Source | Availability | Cadence |
|---|---|---|---|---|
| `sleeper_projection` | Sleeper weekly projection | Sleeper | available | weekly |
| `fp_projection_ppr` | FantasyPros PPR projection | FantasyPros | available | weekly |
| `fp_projection_half` | FantasyPros Half-PPR projection | FantasyPros | available | weekly |
| `fp_projection_standard` | FantasyPros Standard projection | FantasyPros | available | weekly |
| `projection_consensus` | Multi-source projection mean (derived) | derived | available | weekly |
| `projection_variance` | Disagreement between projection sources (derived) | derived | available | weekly |

---

## News & Status Notes

| Token | Description | Source | Availability | Cadence |
|---|---|---|---|---|
| `fp_news_recent` | FantasyPros news with fantasy impact (last 14 days) | FantasyPros | available | every 6h |
| `news_keywords` | News headline keyword extraction (derived) | derived | available | every 6h |

---

## League / Format / User Context

| Token | Description | Source | Availability | Cadence |
|---|---|---|---|---|
| `nfl_state_season` | Current season year | LeagueLogs | available | static (per season) |
| `nfl_state_week` | Current week | LeagueLogs | available | weekly |
| `nfl_state_phase` | pre/regular/post/off | LeagueLogs | available | weekly |
| `league_format` | redraft / dynasty / keeper | user config | available | static |
| `league_scoring` | PPR / Half / Standard / Custom | user config | available | static |
| `league_size` | Number of teams | user config | available | static |
| `league_starters` | Lineup requirements (QB count, flex count, etc.) | user config | available | static |
| `league_qbs` | 1QB or Superflex | user config | available | static |
| `user_roster` | What the user owns | Sleeper | available | weekly |
| `user_record` | Win-loss record | Sleeper | available | weekly |
| `user_competitive_window` | Contender / Bubble / Rebuilder (derived) | derived | available | weekly |
| `user_waiver_pool` | Available waiver players | Sleeper | available | weekly |

---

## Historical / Static (set once, rarely refreshed)

| Token | Description | Source | Availability | Cadence |
|---|---|---|---|---|
| `nfl_draft_capital` | Player's NFL draft round/pick | nfl_data_py | available | static |
| `combine_forty` | Combine 40-yard time | nfl_data_py | available | static |
| `combine_ras` | Relative Athletic Score | nfl_data_py | available | static |
| `combine_speed_score` | Weight-adjusted speed score | derived | available | static |
| `college_yprr` | College YPRR | manual / draft analytics | partial | historical |
| `college_dominator` | College dominator rating | manual / draft analytics | partial | historical |
| `college_team_strength` | Power Four vs Group of Five | manual | available | historical |

---

## Coaching & Scheme (manual maintenance)

| Token | Description | Source | Availability | Cadence |
|---|---|---|---|---|
| `coach_pass_rate_neutral` | Coach's neutral-script pass rate | nfl_data_py (derived) | available | weekly |
| `coach_red_zone_run_rate` | Coach's RZ run rate | nfl_data_py (derived) | available | weekly |
| `coach_play_action_rate` | Play-action rate | nfl_data_py | available | weekly |
| `coordinator_change_recent` | Recent coordinator change flag | manual | available | static-per-season |
| `coaching_tendency_notes` | Manual coaching tendency notes (file lookup) | static | available | static |

---

## Data Coverage Notes for Pass 3

When tagging rules in Pass 3:

**Use `[paywalled]` for tokens marked paywalled here.** Pass 3 should also flag the rule with a note that without coverage data, the rule is partially evaluable via NGS separation as a proxy.

**Use `[gap]` for the weather forecast tokens** until the NWS (or alternative) integration is implemented. Once implemented, mark them `available`.

**Use `[paywalled-budgeted]` for player props.** These are available but constrained to a 500 credit/month budget. Pass 3 should flag rules dependent on props so the orchestrator can decide whether to spend budget on this query.

---

## Currently UNAVAILABLE (no acceptable source in current stack)

| Token | Description | Why missing |
|---|---|---|
| `def_coverage_man_pct` | Man coverage frequency | PFF only — paywalled |
| `def_coverage_zone_pct` | Zone coverage frequency | PFF only — paywalled |
| `wr_man_success_rate` | WR success rate vs man coverage | PFF only — paywalled |
| `wr_vs_cb_grade` | WR vs CB matchup grade | PFF only — paywalled |
| `route_concept_chart` | Route concept tagging per play | PFF / SIS — paywalled |
| `o_line_grades` | OL pass-block / run-block grades | PFF — paywalled |
| `clutch_situational_tendencies` | Coach play-call in 4th-quarter close games | derivable from PBP with effort |

---

## Sanity check before running Pass 3

- [ ] Have you defined a Python fetcher for every `available` token?
- [ ] Is the NWS weather forecast integration scoped (or have you decided to mark all `weather_*` rules as `[gap]` for now)?
- [ ] Are token names consistent between this file and your fetcher function signatures?
- [ ] Have you decided how to handle paywalled rules: keep with proxy / strip / retain with confidence flag?
- [ ] Have you decided how to handle paywalled-budgeted rules (player props): always-skip / budget-aware / always-fetch?

---

## How to extend this vocabulary

When Pass 3 surfaces a token in its Data Coverage Summary that's NOT defined here:
1. Decide if it's evaluable with current data — add it as `available`
2. If it requires a source you don't have, add it as `unavailable` or `paywalled`
3. Update the corresponding Python fetcher to support it (or document why you're skipping)
4. Re-run Pass 3 if the change affects how rules are tagged
