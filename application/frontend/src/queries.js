// Front-end data-access layer.
//
// This is the single place that knows HOW the front end gets and shapes data.
// Today it runs DuckDB-WASM SQL directly against the parquet (see db.js). If we
// later move to a server/API, only the bodies of these functions change — their
// return shapes stay the same, so the view components (App.jsx, panels) don't
// touch. It is the front-end mirror of the backend's data_layer.py.
//
// One exported function per panel; each returns view-ready objects.

import { query } from './db.js';

export const POS = ['QB', 'RB', 'WR', 'TE'];

// Who "you" are in this league. Mirrors config.SLEEPER_USERNAME (Python-side, so
// not readable here); the value matches teams_2025.parquet's owner_name. Identity
// seam: the cleaner long-term move is to bake an `is_me` flag into the teams
// parquet at fetch time so this constant can go away.
export const MY_USERNAME = 'spectraltoast1';

// Team-week score collapses per-player rows to one row per (team, week), since
// roster_total_points / matchup_result repeat across a team's players. Bounded to
// weeks ≤ N by the week selector (n == null → all weeks, the latest-week default).
const SQL_TEAMS = (n) => `
  WITH team_week AS (
    SELECT roster_id, week,
           any_value(roster_total_points) AS team_pts,
           any_value(matchup_result)      AS result
    FROM 'season.parquet'
    WHERE ${weekCutoff(n)}
    GROUP BY roster_id, week
  ),
  agg AS (
    SELECT roster_id,
           round(avg(team_pts), 2)                      AS avg_pts,
           round(coalesce(stddev_samp(team_pts), 0), 2) AS pts_std,
           sum(result = 'W')::INT                        AS wins,
           sum(result = 'L')::INT                        AS losses,
           count(*)::INT                                 AS games
    FROM team_week
    GROUP BY roster_id
  )
  SELECT a.*, t.team_name, t.owner_name
  FROM agg a
  LEFT JOIN 'teams.parquet' t USING (roster_id)
  ORDER BY a.avg_pts DESC
`;

// Average starter points by position per team (QB/RB/WR/TE) — the strength breakdown.
const SQL_POSITIONS = (n) => `
  WITH pos_week AS (
    SELECT roster_id, week, position, sum(sleeper_points) AS pos_pts
    FROM 'season.parquet'
    WHERE is_starter AND position IN ('QB','RB','WR','TE') AND ${weekCutoff(n)}
    GROUP BY roster_id, week, position
  )
  SELECT roster_id, position, round(avg(pos_pts), 2) AS avg_pos_pts
  FROM pos_week
  GROUP BY roster_id, position
`;

/**
 * Power Rankings: teams ranked by avg PPG, with positional strength breakdown,
 * record, week-to-week consistency, and a 0-100 power score vs. the leader.
 * @param {number} [asOfWeek] view as of week N (weeks ≤ N); omit for the latest week
 * @returns {Promise<{teams: object[], maxStarterTotal: number, season: number, weeks: number[]}>}
 */
export async function loadPowerRankings(asOfWeek) {
  const [teams, positions, weekRows, seasonRows] = await Promise.all([
    query(SQL_TEAMS(asOfWeek)),
    query(SQL_POSITIONS(asOfWeek)),
    query(`SELECT DISTINCT week FROM 'season.parquet' WHERE ${weekCutoff(asOfWeek)} ORDER BY week`),
    query(`SELECT DISTINCT season FROM 'season.parquet'`),
  ]);

  // Index positional breakdown by team.
  const posByTeam = {};
  for (const r of positions) {
    (posByTeam[r.roster_id] ??= {})[r.position] = Number(r.avg_pos_pts);
  }

  const maxAvg = Math.max(...teams.map((t) => Number(t.avg_pts)));
  const maxStarterTotal = Math.max(
    ...teams.map((t) =>
      POS.reduce((s, p) => s + (posByTeam[t.roster_id]?.[p] ?? 0), 0),
    ),
  );

  const ranked = teams.map((t, i) => {
    const breakdown = posByTeam[t.roster_id] ?? {};
    const starterTotal = POS.reduce((s, p) => s + (breakdown[p] ?? 0), 0);
    const cv = Number(t.avg_pts) ? Number(t.pts_std) / Number(t.avg_pts) : 0;
    return {
      rank: i + 1,
      rosterId: t.roster_id,
      // Display name: custom team name, then Sleeper handle, then a roster-id stub.
      name: t.team_name || t.owner_name || `Team ${t.roster_id}`,
      avgPts: Number(t.avg_pts),
      std: Number(t.pts_std),
      cv,
      wins: Number(t.wins),
      losses: Number(t.losses),
      // Power score: avg PPG scaled to 0-100 against the league leader.
      powerScore: Math.round((Number(t.avg_pts) / maxAvg) * 100),
      breakdown,
      starterTotal,
    };
  });

  return {
    teams: ranked,
    maxStarterTotal,
    season: seasonRows[0]?.season,
    weeks: weekRows.map((w) => Number(w.week)),
  };
}

// ---------------------------------------------------------------------------
// Team drill-down (drawer) — deeper per-team detail than the ranking card.
// ---------------------------------------------------------------------------

// One row per (team, week): the team's total points and W/L that week.
const SQL_TEAM_WEEK = (n) => `
  SELECT roster_id, week,
         any_value(roster_total_points) AS pts,
         any_value(matchup_result)      AS result
  FROM 'season.parquet'
  WHERE ${weekCutoff(n)}
  GROUP BY roster_id, week
  ORDER BY roster_id, week
`;

// Pre-computed Team Overview analytics, promoted out of this seam into Python
// transforms (compute_team_form.py / compute_team_leakage.py). The front end reads
// them directly — one row per roster_id, the heavy math already done. The JSON
// blobs carry view-ready camelCase keys so consuming them is JSON.parse, nothing more.
//
// These parquets are now tall, grain (as_of_week, roster_id): the Season-replay
// dimension. The week selector parameterises which as-of slice is read — asOfSlice(n)
// picks week N, and n == null defaults to the latest as_of_week, so the dashboard
// renders the current week exactly as before.
const SQL_TEAM_FORM = (n) => `SELECT * FROM 'team_form.parquet'
  WHERE ${asOfSlice('team_form.parquet', n)}`;
const SQL_TEAM_LEAKAGE = (n) => `SELECT * FROM 'team_leakage.parquet'
  WHERE ${asOfSlice('team_leakage.parquet', n)}`;
// The drawer only displays efficiency, so it reads just those two columns rather
// than the full leakage row (which the Team Overview lens needs in whole).
const SQL_TEAM_EFFICIENCY = (n) => `SELECT roster_id, pct, points_left FROM 'team_leakage.parquet'
  WHERE ${asOfSlice('team_leakage.parquet', n)}`;

// Per team & position: total starter points and number of starter-slots used,
// so per-start output can be compared like-for-like against the league.
const SQL_POS_STARTS = (n) => `
  SELECT roster_id, position,
         sum(sleeper_points) AS tot,
         count(*)            AS starts
  FROM 'season.parquet'
  WHERE is_starter AND position IN ('QB','RB','WR','TE') AND ${weekCutoff(n)}
  GROUP BY roster_id, position
`;

/**
 * Per-team drill-down detail, computed once for every team:
 *   - allPlay: record as if each team played all others every week (luck-stripped)
 *   - efficiency: actual starter points vs. the optimal possible lineup (manager
 *     skill) — read from the pre-computed leakage parquet; the drawer displays it,
 *     it no longer computes it (the optimal-lineup pass lives in Python now)
 *   - weeks: per-week points, result, and whether they beat the league median
 * @param {number} [asOfWeek] view as of week N (weeks ≤ N); omit for the latest week
 * @returns {Promise<Object<number, object>>} keyed by roster_id
 */
export async function loadTeamDetails(asOfWeek) {
  const [teamWeeks, posStarts, effRows] = await Promise.all([
    query(SQL_TEAM_WEEK(asOfWeek)),
    query(SQL_POS_STARTS(asOfWeek)),
    query(SQL_TEAM_EFFICIENCY(asOfWeek)),
  ]);

  // Efficiency (actual vs optimal lineup) is pre-computed by compute_team_leakage.py.
  const effByTeam = {};
  for (const r of effRows) effByTeam[Number(r.roster_id)] = r;

  // Index team-week scores by week (for all-play + median) and by team.
  const byWeek = {};
  const byTeam = {};
  for (const r of teamWeeks) {
    const row = { rosterId: Number(r.roster_id), week: Number(r.week), pts: Number(r.pts), result: r.result };
    (byWeek[row.week] ??= []).push(row);
    (byTeam[row.rosterId] ??= []).push(row);
  }

  // Per-week league median (10 teams → avg of the two middle scores).
  const medianByWeek = {};
  for (const [wk, rows] of Object.entries(byWeek)) {
    const sorted = rows.map((r) => r.pts).sort((a, b) => a - b);
    const m = sorted.length;
    medianByWeek[wk] = m % 2 ? sorted[(m - 1) / 2] : (sorted[m / 2 - 1] + sorted[m / 2]) / 2;
  }

  // All-play: per week, count teams each team outscored / lost to.
  const allPlay = {};
  for (const rows of Object.values(byWeek)) {
    for (const a of rows) {
      const rec = (allPlay[a.rosterId] ??= { w: 0, l: 0 });
      for (const b of rows) {
        if (b.rosterId === a.rosterId) continue;
        if (a.pts > b.pts) rec.w++;
        else if (a.pts < b.pts) rec.l++;
      }
    }
  }

  // Per-team, per-position output per starter-slot (neutralises lineup-slot counts
  // so QB/RB/WR/TE compare like-for-like), then the league per-slot benchmark.
  const perSlotByTeam = {};
  const perSlotSums = {};
  const perSlotN = {};
  for (const r of posStarts) {
    const rid = Number(r.roster_id);
    const perSlot = Number(r.tot) / Number(r.starts);
    (perSlotByTeam[rid] ??= {})[r.position] = perSlot;
    perSlotSums[r.position] = (perSlotSums[r.position] ?? 0) + perSlot;
    perSlotN[r.position] = (perSlotN[r.position] ?? 0) + 1;
  }
  const leaguePerSlot = {};
  for (const p of POS) leaguePerSlot[p] = perSlotSums[p] ? perSlotSums[p] / perSlotN[p] : 0;

  const details = {};
  for (const rosterId of Object.keys(byTeam).map(Number)) {
    const weeks = byTeam[rosterId]
      .slice()
      .sort((a, b) => a.week - b.week)
      .map((r) => ({
        week: r.week,
        pts: r.pts,
        result: r.result,
        beatMedian: r.pts > medianByWeek[r.week],
      }));

    const ap = allPlay[rosterId] ?? { w: 0, l: 0 };

    // Consistency: coefficient of variation of weekly team scores (low = steady).
    const ptsList = weeks.map((w) => w.pts);
    const consistencyCv = cv(ptsList);

    // Positional shape: each position's per-slot output as a ratio to the league
    // benchmark (1.0 = league-average). Concentration of those ratios = hero index.
    const ratios = {};
    for (const p of POS) {
      const v = perSlotByTeam[rosterId]?.[p];
      ratios[p] = v != null && leaguePerSlot[p] ? v / leaguePerSlot[p] : null;
    }
    const heroCv = cv(Object.values(ratios).filter((r) => r != null));

    const eff = effByTeam[rosterId];
    details[rosterId] = {
      allPlay: { wins: ap.w, losses: ap.l, pct: ap.w + ap.l ? ap.w / (ap.w + ap.l) : 0 },
      efficiency: {
        pct: eff ? Number(eff.pct) : 0,
        pointsLeft: eff ? Number(eff.points_left) : 0,
      },
      weeks,
      consistency: { cv: consistencyCv },
      shape: { heroCv, ratios },
    };
  }

  // League-relative marker position (0–1) for each spectrum, so a team reads as
  // "where it sits in this league" rather than against an abstract threshold.
  attachSpectrumPos(details, (d) => d.consistency.cv, (d, t) => (d.consistency.pos = t));
  attachSpectrumPos(details, (d) => d.shape.heroCv, (d, t) => (d.shape.pos = t));

  return details;
}

// ---------------------------------------------------------------------------
// Team tab — roster construction (depth, star dependence, lineup/roster signals).
// ---------------------------------------------------------------------------

// One row per (team, player): season-window totals. Bench rows are kept (the
// whole point of the depth view), so this looks at every skill player who logged
// a game, not just starters. starter_pts isolates output that actually counted
// toward the team's score — the basis for the star-dependence read.
const SQL_ROSTER = (n) => `
  SELECT roster_id,
         player_display_name           AS name,
         any_value(position)           AS position,
         count(*)                      AS games,
         sum(is_starter::INT)          AS starts,
         round(sum(sleeper_points), 1) AS total,
         round(sum(CASE WHEN is_starter THEN sleeper_points ELSE 0 END), 1) AS starter_pts
  FROM 'season.parquet'
  WHERE position IN ('QB','RB','WR','TE') AND ${weekCutoff(n)}
  GROUP BY roster_id, name
`;

// Each player's CURRENT team = the roster they belong to in their latest week ≤ N
// (arg_max over week, bounded by the selector). roster_id is per-week in the join, so
// a traded/dropped player lands here on whoever rostered them as of week N — letting a
// former team's view mark him as departed while still crediting the weeks he played
// there. This `week ≤ N` cutoff is the front-end half of the roster-as-of-N fix; it
// mirrors the same filter the derived transforms apply in Python.
const SQL_CURRENT_TEAM = (n) => `
  SELECT player_display_name AS name, arg_max(roster_id, week) AS cur_roster
  FROM 'season.parquet'
  WHERE position IN ('QB','RB','WR','TE') AND ${weekCutoff(n)}
  GROUP BY name
`;

const SQL_TEAM_NAMES = `SELECT roster_id, team_name, owner_name FROM 'teams.parquet'`;

// Below this many games a per-game rate is too noisy to trust (one big week
// distorts it), so such players are flagged low-confidence and kept out of the
// auto-surfaced signals and the bar scale.
const MIN_GAMES = 2;

/**
 * Per-team roster construction, computed once for every team. Powers the Team
 * Overview's "how this team is built" section:
 *   - byPosition: players grouped QB/RB/WR/TE, reliable players by per-game rate
 *     (quality, not availability), low-sample ones pushed to the bottom; each
 *     carries `current`/`departedTo`/`lowSample`/`startShare` flags
 *   - posMax: per-position top reliable rate, so depth bars scale within their
 *     position (a cliff reads clearly; QBs don't squash TEs)
 *   - reliance: single-player exposure — top-1 share of starting points, league-
 *     relative marker (`pos`), and the named star
 *   - signals: lineup calls (a benched player out-rating a starter — fixable in
 *     house) and roster holes (a position whose best option trails the league —
 *     needs an outside upgrade)
 *   - form: recent trajectory — a recency-weighted (half-life 2wk) points/week
 *     `slope`, a direction read (rising/fading/steady), the last-two record, the
 *     weekly series (with beat-median flags + per-week weight), and a league-
 *     relative Fading↔Surging marker
 *   - leakage: lineup inefficiency framed for improvement — efficiency % (league-
 *     relative Leaky↔Optimal marker) leads; the points left split into coachable
 *     (a repeatable bench-over-starter fix, still rostered) vs variance (one-week
 *     spikes, not a real mistake); named repeatable fixes; per-week leak series
 * @param {number} [asOfWeek] view as of week N (weeks ≤ N); omit for the latest week
 * @returns {Promise<Object<number, object>>} keyed by roster_id
 */
export async function loadTeamRosters(asOfWeek) {
  const [rows, currentRows, teamRows, formRows, leakRows] = await Promise.all([
    query(SQL_ROSTER(asOfWeek)),
    query(SQL_CURRENT_TEAM(asOfWeek)),
    query(SQL_TEAM_NAMES),
    query(SQL_TEAM_FORM(asOfWeek)),
    query(SQL_TEAM_LEAKAGE(asOfWeek)),
  ]);

  // Form (trajectory) and leakage are pre-computed by the Python transforms; this
  // seam just reads them, keyed by roster_id, and assembles the view objects. Their
  // league-relative spectrum positions are pre-normalised in Python — no
  // attachSpectrumPos pass is needed for them here.
  const formByTeam = {};
  for (const r of formRows) formByTeam[Number(r.roster_id)] = formFromRow(r);
  const leakageByTeam = {};
  for (const r of leakRows) leakageByTeam[Number(r.roster_id)] = leakageFromRow(r);

  const nameOf = {};
  for (const t of teamRows) {
    nameOf[Number(t.roster_id)] = t.team_name || t.owner_name || `Team ${t.roster_id}`;
  }
  const curTeam = {};
  for (const c of currentRows) curTeam[c.name] = Number(c.cur_roster);

  // Build per-player records grouped by team.
  const byTeam = {};
  for (const r of rows) {
    const rid = Number(r.roster_id);
    const games = Number(r.games);
    const cur = curTeam[r.name];
    (byTeam[rid] ??= []).push({
      name: r.name,
      position: r.position,
      games,
      starterPts: Number(r.starter_pts),
      rate: games ? Number(r.total) / games : 0,
      startShare: games ? Number(r.starts) / games : 0,
      lowSample: games < MIN_GAMES,
      current: cur === rid,
      departedTo: cur === rid ? null : nameOf[cur] ?? null,
    });
  }

  // League per-position benchmark: the average rate of reliable, regular starters
  // across every team — the bar a position has to clear to not be a "hole".
  const lgSum = {};
  const lgN = {};
  for (const players of Object.values(byTeam)) {
    for (const p of players) {
      if (p.current && !p.lowSample && p.startShare >= 0.5) {
        lgSum[p.position] = (lgSum[p.position] ?? 0) + p.rate;
        lgN[p.position] = (lgN[p.position] ?? 0) + 1;
      }
    }
  }
  const leagueRate = {};
  for (const p of POS) leagueRate[p] = lgN[p] ? lgSum[p] / lgN[p] : 0;

  const rosters = {};
  for (const [ridStr, players] of Object.entries(byTeam)) {
    const rid = Number(ridStr);

    // Depth: per position, reliable players by rate desc, low-sample at the
    // bottom; bars scale to the position's top reliable rate.
    const byPosition = {};
    const posMax = {};
    for (const pos of POS) {
      const inPos = players.filter((p) => p.position === pos);
      const reliable = inPos.filter((p) => !p.lowSample).sort((a, b) => b.rate - a.rate);
      const noisy = inPos.filter((p) => p.lowSample).sort((a, b) => b.rate - a.rate);
      byPosition[pos] = [...reliable, ...noisy];
      posMax[pos] = reliable.length ? reliable[0].rate : Math.max(...inPos.map((p) => p.rate), 0);
    }

    // Star dependence: share of starting points carried by the single top player.
    const starters = players.filter((p) => p.starterPts > 0).sort((a, b) => b.starterPts - a.starterPts);
    const starterTotal = starters.reduce((s, p) => s + p.starterPts, 0);
    const top1 = starterTotal ? starters[0].starterPts / starterTotal : 0;

    // Signals — current roster, reliable samples only.
    const lineup = [];
    const holes = [];
    for (const pos of POS) {
      const cur = byPosition[pos].filter((p) => p.current && !p.lowSample); // rate desc
      if (!cur.length) continue;
      const regs = cur.filter((p) => p.startShare >= 0.5);
      const bench = cur.filter((p) => p.startShare < 0.5);

      // Lineup call: the best benched player out-rates the weakest regular
      // starter by a clear margin (>10%) — you may be starting the wrong guy.
      if (regs.length && bench.length) {
        const weakStarter = regs[regs.length - 1];
        const topBench = bench[0];
        if (topBench.rate > weakStarter.rate * 1.1) {
          lineup.push({
            position: pos,
            benchName: topBench.name,
            benchRate: round1(topBench.rate),
            starterName: weakStarter.name,
            starterRate: round1(weakStarter.rate),
            gap: topBench.rate - weakStarter.rate,
          });
        }
      }

      // Roster hole: even the best current option at this position trails the
      // league benchmark by a clear margin (>15%) — an outside upgrade target.
      const best = cur[0];
      if (leagueRate[pos] && best.rate < leagueRate[pos] * 0.85) {
        holes.push({
          position: pos,
          name: best.name,
          rate: round1(best.rate),
          leagueRate: round1(leagueRate[pos]),
          gap: leagueRate[pos] - best.rate,
        });
      }
    }
    lineup.sort((a, b) => b.gap - a.gap);
    holes.sort((a, b) => b.gap - a.gap);

    rosters[rid] = {
      byPosition,
      posMax,
      reliance: { top1, star: starters[0]?.name ?? null },
      signals: { lineup, holes },
      form: formByTeam[rid],
      leakage: leakageByTeam[rid],
    };
  }

  // Star-dependence is the one spectrum still computed here (reliance stays inline);
  // form's Fading↔Surging and leakage's Leaky↔Optimal markers are pre-normalised in
  // the Python transforms and arrive on the objects as `pos` already.
  attachSpectrumPos(rosters, (d) => d.reliance.top1, (d, t) => (d.reliance.pos = t));

  return rosters;
}

// Assemble the view-ready form object from a pre-computed team_form parquet row.
// The per-week series is stored as view-ready JSON, so this is parse + a trivial
// weekMax for the chart's bar-scaling (pure display, no analytics).
function formFromRow(r) {
  const weeks = JSON.parse(r.weeks_json);
  return {
    slope: Number(r.slope),
    direction: r.direction,
    recent: { w: Number(r.recent_w), l: Number(r.recent_l) },
    pos: Number(r.spectrum_pos),
    weeks,
    weekMax: weeks.length ? Math.max(...weeks.map((w) => w.pts)) : 0,
  };
}

// Assemble the view-ready leakage object from a pre-computed team_leakage parquet
// row. The per-week leak series and named fixes are stored as view-ready JSON.
function leakageFromRow(r) {
  return {
    pct: Number(r.pct),
    pointsLeft: Number(r.points_left),
    coachablePts: Number(r.coachable_pts),
    variancePts: Number(r.variance_pts),
    leakMax: Number(r.leak_max),
    pos: Number(r.spectrum_pos),
    byWeek: JSON.parse(r.by_week_json),
    fixes: JSON.parse(r.fixes_json),
  };
}

// ---------------------------------------------------------------------------
// Team tab — Players sub-view (the spike signal-quality read, per player).
// ---------------------------------------------------------------------------

// Pre-computed by compute_player_signal.py — one row per rostered skill player,
// the opportunity-vs-efficiency decomposition already done. This seam only reads
// and assembles; there is no signal math in JS (it lives in the Python transform,
// validated by backtest_player_signal.py). Default order puts the highest recent
// scorers first — the players a manager is most likely weighing a move on.
// Tall, grain (as_of_week, roster_id, player) — Season-replay. The week selector picks
// the as-of slice via asOfSlice(n); n == null defaults to the latest as_of_week.
const SQL_PLAYER_SIGNAL = (n) => `
  SELECT player_display_name, position, games, low_sample,
         recent_ppg, td_share, opp_pct, eff_ratio, regression_risk, read, weeks_json
  FROM 'player_signal.parquet'
  WHERE roster_id = $rid
    AND ${asOfSlice('player_signal.parquet', n)}
  ORDER BY recent_ppg DESC
`;

/**
 * The spike signal-quality read for one team's rostered skill players. Answers,
 * per player, "is the recent production real, or noise?" — a characterization of
 * past production (not a forward projection). `read` is the sample-gated verdict
 * (sticky / mixed / spike / too_early); `regressionRisk` is the share of recent
 * scoring the sustainable-usage picture doesn't support (the direction behind the
 * verdict); `oppPct` (volume rank in position) and `tdShare` are the evidence.
 * @param {number} rosterId
 * @param {number} [asOfWeek] view as of week N; omit for the latest week
 * @returns {Promise<object[]>} view-ready player rows, highest recent PPG first
 */
export async function loadTeamPlayers(rosterId, asOfWeek) {
  const rows = await query(SQL_PLAYER_SIGNAL(asOfWeek).replace('$rid', Number(rosterId)));
  return rows.map(playerSignalFromRow);
}

// Assemble the view-ready player object from a pre-computed player_signal row. The
// per-week (pts, opp) series is stored as view-ready JSON, so this is parse + Number
// coercion — no analytics.
function playerSignalFromRow(r) {
  return {
    name: r.player_display_name,
    position: r.position,
    games: Number(r.games),
    lowSample: Boolean(r.low_sample),
    recentPpg: Number(r.recent_ppg),
    tdShare: Number(r.td_share),
    oppPct: Number(r.opp_pct),
    effRatio: Number(r.eff_ratio),
    regressionRisk: Number(r.regression_risk),
    read: r.read,
    weeks: JSON.parse(r.weeks_json),
  };
}

// ---------------------------------------------------------------------------
// Team tab — the roster picker (who's in the league + which one is "you").
// ---------------------------------------------------------------------------

/**
 * The league's teams for the Team-tab switcher, plus which roster is the
 * logged-in user's (resolved by matching MY_USERNAME against owner_name).
 * Names follow the same custom-name → handle → stub fallback as the cards.
 * @returns {Promise<{teams: {rosterId: number, name: string, owner: string, isMe: boolean}[], myRosterId: number|null}>}
 */
export async function loadTeams() {
  const rows = await query(
    `SELECT roster_id, team_name, owner_name FROM 'teams.parquet' ORDER BY roster_id`,
  );
  let myRosterId = null;
  const teams = rows.map((r) => {
    const isMe = r.owner_name === MY_USERNAME;
    if (isMe) myRosterId = Number(r.roster_id);
    return {
      rosterId: Number(r.roster_id),
      name: r.team_name || r.owner_name || `Team ${r.roster_id}`,
      owner: r.owner_name,
      isMe,
    };
  });
  return { teams, myRosterId };
}

const round1 = (n) => Math.round(n * 10) / 10;

// Season-replay week-selector seam. Two SQL fragments express "view the dashboard as
// of week N"; passing n == null means "latest", so existing default behaviour is
// unchanged. asOfSlice picks one as-of slice from a tall derived parquet; weekCutoff
// bounds an inline season.parquet read to weeks ≤ N (the point-in-time cutoff — which
// is also the roster-as-of-N fix where it gates arg_max(roster_id, week)).
const asOfSlice = (table, n) =>
  n == null
    ? `as_of_week = (SELECT max(as_of_week) FROM '${table}')`
    : `as_of_week = ${Number(n)}`;
const weekCutoff = (n) => (n == null ? 'TRUE' : `week <= ${Number(n)}`);

/**
 * The weeks selectable in the week selector, plus the default (latest). Reads the
 * source of truth for "weeks played" — distinct weeks in the season join. The selector
 * only travels back: a live app opens on `latest` (today, week 4) and offers weeks 1..N.
 * @returns {Promise<{weeks: number[], latest: number|null}>}
 */
export async function loadWeeks() {
  const rows = await query(`SELECT DISTINCT week FROM 'season.parquet' ORDER BY week`);
  const weeks = rows.map((r) => Number(r.week));
  return { weeks, latest: weeks.length ? weeks[weeks.length - 1] : null };
}

/**
 * League chrome for the top-bar switcher — all derived from real config, none hardcoded:
 *   - label: "10-tm · PPR · 1QB" from teams count + league_settings scoring + lineup_slots
 *   - record: the logged-in user's W-L as of week N
 *   - name/myOwner: the league name (not persisted by Sleeper's config fetch yet — falls
 *     back) + the user's handle for the avatar
 * @param {number} [asOfWeek] view as of week N; omit for the latest week
 * @returns {Promise<{name: string|null, label: string, record: string|null, myOwner: string|null}>}
 */
export async function loadLeagueMeta(asOfWeek) {
  const [teamRows, recRows, slotRows, meRows] = await Promise.all([
    query(`SELECT count(*)::INT AS n FROM 'teams.parquet'`),
    query(`SELECT value FROM 'league_settings.parquet' WHERE section = 'scoring' AND key = 'rec'`),
    query(`SELECT slot, count, eligible FROM 'slots.parquet'`),
    query(`SELECT roster_id, owner_name FROM 'teams.parquet' WHERE owner_name = '${MY_USERNAME}'`),
  ]);

  const teamCount = Number(teamRows[0]?.n ?? 0);

  // Scoring label from the reception value (1 → PPR, 0.5 → Half, else Standard).
  const rec = recRows.length ? Number(recRows[0].value) : null;
  const scoring = rec === 1 ? 'PPR' : rec === 0.5 ? 'Half-PPR' : rec === 0 ? 'Std' : rec != null ? `${rec}-PPR` : '—';

  // QB structure from the lineup slots: a QB-eligible flex (SUPERFLEX) reads as SF,
  // else the count of dedicated QB slots (1QB / 2QB).
  let qbSlots = 0;
  let superflex = false;
  for (const s of slotRows) {
    const elig = String(s.eligible ?? '').toUpperCase();
    const isQbOnly = elig === 'QB';
    if (isQbOnly) qbSlots += Number(s.count);
    else if (elig.split(',').includes('QB')) superflex = true;
  }
  const qb = superflex ? 'SF' : `${qbSlots || 1}QB`;

  // The user's record as of week N (one W/L per team-week).
  const myRosterId = meRows.length ? Number(meRows[0].roster_id) : null;
  let record = null;
  if (myRosterId != null) {
    const rows = await query(`
      WITH tw AS (
        SELECT roster_id, week, any_value(matchup_result) AS result
        FROM 'season.parquet'
        WHERE ${weekCutoff(asOfWeek)}
        GROUP BY roster_id, week
      )
      SELECT sum(result = 'W')::INT AS w, sum(result = 'L')::INT AS l
      FROM tw WHERE roster_id = ${myRosterId}
    `);
    if (rows.length && rows[0].w != null) record = `${Number(rows[0].w)}-${Number(rows[0].l)}`;
  }

  return {
    name: null,
    label: `${teamCount}-tm · ${scoring} · ${qb}`,
    record,
    myOwner: meRows.length ? meRows[0].owner_name : null,
  };
}

// Coefficient of variation (sample stddev / mean) of a numeric list.
function cv(xs) {
  if (xs.length < 2) return 0;
  const mean = xs.reduce((s, x) => s + x, 0) / xs.length;
  if (!mean) return 0;
  const variance = xs.reduce((s, x) => s + (x - mean) ** 2, 0) / (xs.length - 1);
  return Math.sqrt(variance) / mean;
}

// Normalise a metric across all teams to a 0–1 position (min → 0, max → 1).
function attachSpectrumPos(details, get, set) {
  const vals = Object.values(details).map(get);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const span = hi - lo;
  for (const d of Object.values(details)) set(d, span ? (get(d) - lo) / span : 0.5);
}
