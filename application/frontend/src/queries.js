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
// roster_total_points / matchup_result repeat across a team's players.
const SQL_TEAMS = `
  WITH team_week AS (
    SELECT roster_id, week,
           any_value(roster_total_points) AS team_pts,
           any_value(matchup_result)      AS result
    FROM 'season.parquet'
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
const SQL_POSITIONS = `
  WITH pos_week AS (
    SELECT roster_id, week, position, sum(sleeper_points) AS pos_pts
    FROM 'season.parquet'
    WHERE is_starter AND position IN ('QB','RB','WR','TE')
    GROUP BY roster_id, week, position
  )
  SELECT roster_id, position, round(avg(pos_pts), 2) AS avg_pos_pts
  FROM pos_week
  GROUP BY roster_id, position
`;

/**
 * Power Rankings: teams ranked by avg PPG, with positional strength breakdown,
 * record, week-to-week consistency, and a 0-100 power score vs. the leader.
 * @returns {Promise<{teams: object[], maxStarterTotal: number, season: number, weeks: number[]}>}
 */
export async function loadPowerRankings() {
  const [teams, positions, weekRows, seasonRows] = await Promise.all([
    query(SQL_TEAMS),
    query(SQL_POSITIONS),
    query(`SELECT DISTINCT week FROM 'season.parquet' ORDER BY week`),
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
const SQL_TEAM_WEEK = `
  SELECT roster_id, week,
         any_value(roster_total_points) AS pts,
         any_value(matchup_result)      AS result
  FROM 'season.parquet'
  GROUP BY roster_id, week
  ORDER BY roster_id, week
`;

// Every skill player's weekly line (starters + bench) — the pool the optimal
// lineup is chosen from. Carries the name so lineup misses can be named.
const SQL_PLAYER_WEEK = `
  SELECT roster_id, week, position, player_display_name AS name,
         sleeper_points AS pts, is_starter
  FROM 'season.parquet'
  WHERE position IN ('QB','RB','WR','TE')
`;

const SQL_SLOTS = `SELECT slot, count, eligible FROM 'slots.parquet'`;

// Per team & position: total starter points and number of starter-slots used,
// so per-start output can be compared like-for-like against the league.
const SQL_POS_STARTS = `
  SELECT roster_id, position,
         sum(sleeper_points) AS tot,
         count(*)            AS starts
  FROM 'season.parquet'
  WHERE is_starter AND position IN ('QB','RB','WR','TE')
  GROUP BY roster_id, position
`;

/** Expand the league's slot config into one entry per physical slot (FLEX count 2
 *  → two), most-constrained first so dedicated slots claim their position's stars
 *  before flex slots. Shared by the League drawer (loadTeamDetails) and the Team
 *  Overview's "where you leave points" lens (loadTeamRosters). */
function expandSlots(slotRows) {
  const slots = [];
  for (const s of slotRows) {
    const eligible = String(s.eligible).split(',');
    for (let n = 0; n < Number(s.count); n++) slots.push({ slot: s.slot, eligible });
  }
  slots.sort((a, b) => a.eligible.length - b.eligible.length);
  return slots;
}

/** Best achievable lineup from a roster-week given the league's slot rules.
 *  Greedy by ascending eligibility size: fill the most-constrained slots
 *  (single-position) before flex slots, taking the top scorer available for
 *  each. Correct when flex eligibility is a superset of dedicated positions
 *  (the standard case), which is why dedicated slots claim their stars first.
 *  Returns the total and the chosen players (each carrying its filled slot), so
 *  callers can both score the lineup and diff it against who was actually started.
 *  Each player must carry a stable `_i` to track usage. */
function optimalLineup(players, slots) {
  const used = new Set();
  const picks = [];
  let total = 0;
  for (const slot of slots) {
    const pick = players
      .filter((p) => !used.has(p._i) && slot.eligible.includes(p.position))
      .sort((a, b) => b.pts - a.pts)[0];
    if (pick) {
      total += pick.pts;
      used.add(pick._i);
      picks.push({ ...pick, slot: slot.slot });
    }
  }
  return { total, picks };
}

/**
 * Per-team drill-down detail, computed once for every team:
 *   - allPlay: record as if each team played all others every week (luck-stripped)
 *   - efficiency: actual starter points vs. the optimal possible lineup (manager skill)
 *   - weeks: per-week points, result, and whether they beat the league median
 * @returns {Promise<Object<number, object>>} keyed by roster_id
 */
export async function loadTeamDetails() {
  const [teamWeeks, playerWeeks, slotRows, posStarts] = await Promise.all([
    query(SQL_TEAM_WEEK),
    query(SQL_PLAYER_WEEK),
    query(SQL_SLOTS),
    query(SQL_POS_STARTS),
  ]);

  const slots = expandSlots(slotRows);

  // Index team-week scores by week (for all-play + median) and by team.
  const byWeek = {};
  const byTeam = {};
  for (const r of teamWeeks) {
    const row = { rosterId: Number(r.roster_id), week: Number(r.week), pts: Number(r.pts), result: r.result };
    (byWeek[row.week] ??= []).push(row);
    (byTeam[row.rosterId] ??= []).push(row);
  }

  // Index player-week rows by team+week for the optimal-lineup calc.
  const playersByTeamWeek = {};
  const actualByTeamWeek = {};
  for (const p of playerWeeks) {
    const key = `${p.roster_id}|${p.week}`;
    (playersByTeamWeek[key] ??= []).push({ position: p.position, pts: Number(p.pts) });
    if (p.is_starter) actualByTeamWeek[key] = (actualByTeamWeek[key] ?? 0) + Number(p.pts);
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

    let actual = 0;
    let optimal = 0;
    for (const w of weeks) {
      const key = `${rosterId}|${w.week}`;
      const pool = (playersByTeamWeek[key] ?? []).map((p, i) => ({ ...p, _i: i }));
      actual += actualByTeamWeek[key] ?? 0;
      optimal += optimalLineup(pool, slots).total;
    }
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

    details[rosterId] = {
      allPlay: { wins: ap.w, losses: ap.l, pct: ap.w + ap.l ? ap.w / (ap.w + ap.l) : 0 },
      efficiency: {
        actual: round1(actual),
        optimal: round1(optimal),
        pct: optimal ? actual / optimal : 0,
        pointsLeft: round1(optimal - actual),
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
const SQL_ROSTER = `
  SELECT roster_id,
         player_display_name           AS name,
         any_value(position)           AS position,
         count(*)                      AS games,
         sum(is_starter::INT)          AS starts,
         round(sum(sleeper_points), 1) AS total,
         round(sum(CASE WHEN is_starter THEN sleeper_points ELSE 0 END), 1) AS starter_pts
  FROM 'season.parquet'
  WHERE position IN ('QB','RB','WR','TE')
  GROUP BY roster_id, name
`;

// Each player's CURRENT team = the roster they belong to in their latest week
// (arg_max over week). roster_id is per-week in the join, so a traded/dropped
// player lands here on whoever rosters them now — letting a former team's view
// mark him as departed while still crediting the weeks he played there.
const SQL_CURRENT_TEAM = `
  SELECT player_display_name AS name, arg_max(roster_id, week) AS cur_roster
  FROM 'season.parquet'
  WHERE position IN ('QB','RB','WR','TE')
  GROUP BY name
`;

const SQL_TEAM_NAMES = `SELECT roster_id, team_name, owner_name FROM 'teams.parquet'`;

// One row per (team, week): the team's total points and W/L — the per-week series
// the trajectory (form) read is built from. Mirrors SQL_TEAM_WEEK in the drawer
// seam, kept here so the Team-tab Overview stays self-contained.
const SQL_TEAM_TRAJECTORY = `
  SELECT roster_id, week,
         any_value(roster_total_points) AS pts,
         any_value(matchup_result)      AS result
  FROM 'season.parquet'
  GROUP BY roster_id, week
  ORDER BY roster_id, week
`;

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
 * @returns {Promise<Object<number, object>>} keyed by roster_id
 */
export async function loadTeamRosters() {
  const [rows, currentRows, teamRows, trajRows, playerWeeks, slotRows] = await Promise.all([
    query(SQL_ROSTER),
    query(SQL_CURRENT_TEAM),
    query(SQL_TEAM_NAMES),
    query(SQL_TEAM_TRAJECTORY),
    query(SQL_PLAYER_WEEK),
    query(SQL_SLOTS),
  ]);

  // Per (team, week) player pool for the optimal-lineup / leakage calc, tagging
  // each player with whether they were actually started.
  const slots = expandSlots(slotRows);
  const poolByTeamWeek = {};
  for (const p of playerWeeks) {
    const key = `${Number(p.roster_id)}|${Number(p.week)}`;
    (poolByTeamWeek[key] ??= []).push({
      name: p.name,
      position: p.position,
      pts: Number(p.pts),
      started: !!p.is_starter,
    });
  }

  // Per-week team scores, indexed by team (sorted series) and by week (for the
  // league median, so each week reads beat/below the field).
  const weeksByTeam = {};
  const ptsByWeek = {};
  for (const r of trajRows) {
    const rid = Number(r.roster_id);
    const wk = Number(r.week);
    const pts = Number(r.pts);
    (weeksByTeam[rid] ??= []).push({ week: wk, pts, result: r.result });
    (ptsByWeek[wk] ??= []).push(pts);
  }
  const medianByWeek = {};
  for (const [wk, list] of Object.entries(ptsByWeek)) medianByWeek[wk] = median(list);

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
      form: computeForm(weeksByTeam[rid] ?? [], medianByWeek),
      leakage: computeLeakage(
        (weeksByTeam[rid] ?? []).map((w) => w.week),
        poolByTeamWeek,
        rid,
        slots,
        // Season-level role + rate per player, so leakage can tell a repeatable
        // hierarchy error (coachable) from a one-week spike (variance).
        Object.fromEntries(
          players.map((p) => [
            p.name,
            { rate: p.rate, startShare: p.startShare, lowSample: p.lowSample, current: p.current },
          ]),
        ),
      ),
    };
  }

  // League-relative markers, so each team reads against the league's actual
  // spread rather than a fixed threshold: star dependence (balanced ↔ star-led),
  // form trajectory (fading ↔ surging), and lineup efficiency (leaky ↔ optimal).
  attachSpectrumPos(rosters, (d) => d.reliance.top1, (d, t) => (d.reliance.pos = t));
  attachSpectrumPos(rosters, (d) => d.form.slope, (d, t) => (d.form.pos = t));
  attachSpectrumPos(rosters, (d) => d.leakage.pct, (d, t) => (d.leakage.pos = t));

  return rosters;
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

const mean = (xs) => (xs.length ? xs.reduce((s, x) => s + x, 0) / xs.length : 0);

// Median of a numeric list (avg of the two middle values when even).
function median(xs) {
  const s = xs.slice().sort((a, b) => a - b);
  const m = s.length;
  if (!m) return 0;
  return m % 2 ? s[(m - 1) / 2] : (s[m / 2 - 1] + s[m / 2]) / 2;
}

// Recency-weighted trajectory from a team's weekly score series. Rather than
// splitting the season into two windows (which discards the middle week and jumps
// discontinuously each time a new week lands), this fits an exponentially-weighted
// linear trend: every week's weight halves every HALF_LIFE_WK weeks back from the
// most recent, so the read is smooth, uses every game, and works from two weeks on.
// `slope` is that recency-weighted points/week trend (positive = heating up); the
// direction label thresholds it against the team's own scoring so a small wobble
// stays "steady". Each week carries its `weight` so the chart can show the decay.
const HALF_LIFE_WK = 2;

function computeForm(series, medianByWeek) {
  const weeks = series
    .slice()
    .sort((a, b) => a.week - b.week)
    .map((w) => ({ ...w, beatMedian: w.pts > (medianByWeek[w.week] ?? 0), weight: 1 }));
  const n = weeks.length;
  const pts = weeks.map((w) => w.pts);
  const weekMax = pts.length ? Math.max(...pts) : 0;

  if (n < 2) {
    return { slope: 0, direction: 'steady', recent: { w: 0, l: 0 }, weeks, weekMax };
  }

  // Exponential weights: most recent week = 1, halving every HALF_LIFE_WK weeks.
  const decay = Math.pow(0.5, 1 / HALF_LIFE_WK);
  const wts = weeks.map((_, i) => Math.pow(decay, n - 1 - i));
  weeks.forEach((w, i) => (w.weight = wts[i]));

  // Weighted least-squares slope of points vs. week index (x = 0..n-1) — pts/week.
  const W = wts.reduce((s, x) => s + x, 0);
  const mx = wts.reduce((s, x, i) => s + x * i, 0) / W;
  const my = wts.reduce((s, x, i) => s + x * pts[i], 0) / W;
  let num = 0;
  let den = 0;
  for (let i = 0; i < n; i++) {
    num += wts[i] * (i - mx) * (pts[i] - my);
    den += wts[i] * (i - mx) ** 2;
  }
  const slope = den ? num / den : 0;

  // Direction: slope as a fraction of the team's own average scoring, so the
  // "steady" band scales to how much this team puts up. The ±4%/wk band is tuned
  // to the per-week slope scale (≈ a 12% swing across a 4-week window) — it catches
  // a genuine monotonic climb or slide while leaving erratic week-to-week noise
  // (a one-week spike or dip that doesn't establish a direction) reading steady.
  const avg = mean(pts);
  const rel = avg ? slope / avg : 0;
  const direction = rel > 0.04 ? 'rising' : rel < -0.04 ? 'fading' : 'steady';

  // Recent record: the last two weeks — a results counterpoint to the scoring trend.
  const recentCount = Math.min(2, n);
  const recentWeeks = weeks.slice(n - recentCount);
  const rec = {
    w: recentWeeks.filter((w) => w.result === 'W').length,
    l: recentWeeks.filter((w) => w.result === 'L').length,
  };

  return { slope: round1(slope), direction, recent: rec, weeks, weekMax };
}

// Lineup leakage, framed for improvement rather than regret. Leads with lineup
// efficiency (process soundness, placed league-relative elsewhere), then splits the
// points left into two buckets that mean very different things to a manager:
//   - coachable: an ONGOING misallocation — a player you habitually bench
//     (startShare<0.5) out-rates one you habitually start (startShare>=0.5) on the
//     season and is still rostered. That's a repeatable "start X over Y going
//     forward" fix (the same structure as the Lens-1 lineup signal), and the points
//     it cost are recoverable. Aggregated across weeks into named fixes.
//   - variance: everything else — a bench player who happened to spike a single
//     week, or a one-off wrong call on a player who's normally your starter. Not a
//     repeatable mistake; not the manager's fault. This is the reassurance bucket.
// The two buckets sum to the season points left (every weekly swap routes to one),
// so the raw total is preserved as supporting evidence rather than the headline.
// `seasonByName`: name -> { rate, startShare, lowSample, current } for the team.
function computeLeakage(weekNums, poolByTeamWeek, rid, slots, seasonByName) {
  const byWeek = [];
  let actualTot = 0;
  let optimalTot = 0;
  let leakMax = 0;
  let coachablePts = 0;
  let variancePts = 0;
  const fixAgg = {}; // "gem|dud" -> aggregated repeatable fix across weeks

  for (const wk of weekNums) {
    const pool = (poolByTeamWeek[`${rid}|${wk}`] ?? []).map((p, i) => ({ ...p, _i: i }));
    if (!pool.length) continue;

    const started = pool.filter((p) => p.started);
    const actualPts = started.reduce((s, p) => s + p.pts, 0);
    const opt = optimalLineup(pool, slots);
    const left = opt.total - actualPts;

    actualTot += actualPts;
    optimalTot += opt.total;
    leakMax = Math.max(leakMax, left);
    byWeek.push({ week: wk, left: round1(left) });

    if (left <= 0.05) continue;

    // gems = optimal picks not actually started; duds = starters the optimal lineup
    // drops. Pair them within swap-eligibility classes so each swap is a legal
    // start/sit (a QB can only displace a QB; RB/WR/TE interchange via FLEX). Counts
    // balance within each class, so zipping best gem ↔ worst dud is sum-exact.
    const optIdx = new Set(opt.picks.map((p) => p._i));
    const cls = (pos) => (pos === 'QB' ? 'QB' : 'FLEX');
    const gemsByCls = {};
    const dudsByCls = {};
    for (const p of opt.picks) if (!p.started) (gemsByCls[cls(p.position)] ??= []).push(p);
    for (const p of started) if (!optIdx.has(p._i)) (dudsByCls[cls(p.position)] ??= []).push(p);
    for (const c of Object.keys(gemsByCls)) {
      const gems = gemsByCls[c].sort((a, b) => b.pts - a.pts);
      const duds = (dudsByCls[c] ?? []).sort((a, b) => a.pts - b.pts);
      for (let j = 0; j < Math.min(gems.length, duds.length); j++) {
        const g = gems[j];
        const d = duds[j];
        const gain = g.pts - d.pts;
        const gs = seasonByName[g.name];
        const ds = seasonByName[d.name];

        // Coachable only if this is a repeatable hierarchy error AND the swap would
        // actually have helped that week: the benched gem is a habitual bench player
        // who clearly out-rates the started dud (a habitual starter) over the season
        // — the same >10% margin as the Lens-1 lineup signal — both reliable samples,
        // the gem still rostered, and the realized weekly gain positive. Everything
        // else is variance: a one-week bench spike, a marginal edge, or a week the
        // habitual starter happened to outscore the better player (gain ≤ 0). We
        // don't moralize about variance — routing gain>0 only also keeps the
        // coachable bucket non-negative while staying sum-exact with the total.
        const coachable =
          gs && ds && !gs.lowSample && !ds.lowSample && gs.current &&
          gs.startShare < 0.5 && ds.startShare >= 0.5 && gs.rate > ds.rate * 1.1 &&
          gain > 0;

        if (coachable) {
          coachablePts += gain;
          const key = `${g.name}|${d.name}`;
          const f = (fixAgg[key] ??= {
            position: g.position === d.position ? g.position : 'FLEX',
            benchName: g.name,
            benchRate: round1(gs.rate),
            starterName: d.name,
            starterRate: round1(ds.rate),
            edge: round1(gs.rate - ds.rate), // repeatable season rate gap (the signal)
            pts: 0, // realized points recovered, for ranking the fixes
          });
          f.pts += gain;
        } else {
          variancePts += gain;
        }
      }
    }
  }

  const fixes = Object.values(fixAgg)
    .sort((a, b) => b.pts - a.pts)
    .map((f) => ({ ...f, pts: round1(f.pts) }));

  return {
    pct: optimalTot ? actualTot / optimalTot : 1,
    pointsLeft: round1(optimalTot - actualTot),
    coachablePts: round1(coachablePts),
    variancePts: round1(variancePts),
    byWeek,
    leakMax: round1(leakMax),
    fixes: fixes.slice(0, 2),
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
