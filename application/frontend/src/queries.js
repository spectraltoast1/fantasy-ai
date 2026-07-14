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
import { derivePosture } from './posture.js';

export const POS = ['QB', 'RB', 'WR', 'TE'];

// Who "you" are in this league. Mirrors config.SLEEPER_USERNAME (Python-side, so
// not readable here); the value matches teams_2025.parquet's owner_name. Identity
// seam: the cleaner long-term move is to bake an `is_me` flag into the teams
// parquet at fetch time so this constant can go away.
export const MY_USERNAME = 'spectraltoast1';

// ---------------------------------------------------------------------------
// Players tab — the VOR-anchored player table (Gridiron surface #1).
// ---------------------------------------------------------------------------

// One row per rostered skill player, assembling the four reads that feed the table.
// The join key is sleeper_player_id everywhere (the one identity all entities share):
//   - production_vor: the as-of-week slice → PROD VOR (the anchor + default sort). 2025.
//   - market_vor: the latest market snapshot → MKT VOR + trade_gap. Cross-time (2026
//     market × 2025 roster) — carried with is_cross_time so the UI can flag it (POC).
//   - ros_synthesis: latest week per player → BULL/BEAR/SIT 1-10 grades. Sparse today
//     (only players with an AI run); LEFT JOIN so the rest still list, grades null.
//   - season identity: player name + NFL team, from the latest week <= N.
// production_vor is the anchor (LEFT JOINs hang off it) so the table is exactly the
// rostered skill players priced at week N.
const SQL_PLAYERS = (n) => `
  WITH ident AS (
    SELECT sleeper_player_id,
           arg_max(player_display_name, week) AS name,
           arg_max(team, week)                AS nfl_team,
           arg_max(position, week)            AS position
    FROM 'season.parquet'
    WHERE position IN ('QB','RB','WR','TE') AND ${weekCutoff(n)}
    GROUP BY sleeper_player_id
  ),
  pv AS (
    SELECT sleeper_player_id, roster_id, position, vor, ros_value
    FROM 'production_vor.parquet'
    WHERE ${asOfSlice('production_vor.parquet', n)}
  ),
  mv AS (
    SELECT sleeper_player_id, market_vor, trade_gap, is_cross_time
    FROM 'market_vor.parquet'
    WHERE snapshot_date = (SELECT max(snapshot_date) FROM 'market_vor.parquet')
  ),
  rs AS (
    SELECT sleeper_player_id, bull_grade, bear_grade, situation_grade
    FROM 'ros_synthesis.parquet'
    QUALIFY row_number() OVER (PARTITION BY sleeper_player_id ORDER BY week DESC) = 1
  )
  SELECT pv.sleeper_player_id            AS sleeper_id,
         coalesce(ident.name, pv.sleeper_player_id) AS name,
         coalesce(ident.position, pv.position)      AS position,
         ident.nfl_team,
         pv.roster_id,
         pv.vor                          AS prod_vor,
         mv.market_vor                   AS mkt_vor,
         mv.trade_gap,
         mv.is_cross_time,
         rs.bull_grade, rs.bear_grade, rs.situation_grade,
         t.team_name, t.owner_name
  FROM pv
  LEFT JOIN ident USING (sleeper_player_id)
  LEFT JOIN mv    ON mv.sleeper_player_id = pv.sleeper_player_id
  LEFT JOIN rs    ON rs.sleeper_player_id = pv.sleeper_player_id
  LEFT JOIN 'teams.parquet' t ON t.roster_id = pv.roster_id
  ORDER BY pv.vor DESC
`;

/**
 * The Players table: every rostered skill player priced by Production VOR (2025), with
 * Market VOR (cross-time), and ROS Synthesis bull/bear/situation grades where they exist.
 * Filtering/sorting stay in the view — this returns the full assembled set once.
 * @param {number} [asOfWeek] view as of week N; omit for the latest week
 * @returns {Promise<object[]>} view-ready player rows, highest PROD VOR first
 */
export async function loadPlayers(asOfWeek) {
  const rows = await query(SQL_PLAYERS(asOfWeek));
  return rows.map((r) => ({
    sleeperId: r.sleeper_id,
    name: r.name,
    pos: r.position,
    nflTeam: r.nfl_team ?? null,
    rosterId: Number(r.roster_id),
    teamName: r.team_name || r.owner_name || null,
    isMe: r.owner_name === MY_USERNAME,
    prodVor: r.prod_vor != null ? Number(r.prod_vor) : null,
    mktVor: r.mkt_vor != null ? Number(r.mkt_vor) : null,
    tradeGap: r.trade_gap != null ? Number(r.trade_gap) : null,
    mktCrossTime: Boolean(r.is_cross_time),
    bull: r.bull_grade != null ? Number(r.bull_grade) : null,
    bear: r.bear_grade != null ? Number(r.bear_grade) : null,
    sit: r.situation_grade != null ? Number(r.situation_grade) : null,
  }));
}

// Trade lean thresholds (VOR units) on the Production−Market gap. Market ≫ Production →
// SELL (market rich); Production ≫ Market → BUY (cheap on the market); else HOLD. Named
// constant (a future league/user-config candidate). Gated cross-time today (see below).
const TRADE_GAP_T = 0.25;

/**
 * The full player card for one player: Value·VOR (Production + Market weekly series with
 * value/delta + a trade lean), Opportunity (the player_signal axes), and the ROS Outcome
 * Shape (ros_synthesis grades/notes where they exist). All keyed by sleeper_player_id.
 * @param {string} sleeperId
 * @param {number} [asOfWeek] view as of week N; omit for the latest week
 * @returns {Promise<object>} the assembled card, or { missing: true } if not rostered
 */
export async function loadPlayerCard(sleeperId, asOfWeek) {
  const id = String(sleeperId).replace(/'/g, "''");
  const prodCutoff = asOfWeek == null ? 'TRUE' : `as_of_week <= ${Number(asOfWeek)}`;

  const [identRows, prodRows, mktRows, sigRows, rosRows, teamRows] = await Promise.all([
    query(`
      SELECT arg_max(player_display_name, week) AS name,
             arg_max(team, week)                AS nfl_team,
             arg_max(position, week)            AS position,
             arg_max(roster_id, week)           AS roster_id
      FROM 'season.parquet'
      WHERE sleeper_player_id = '${id}' AND ${weekCutoff(asOfWeek)}
    `),
    query(`
      SELECT as_of_week, vor, ros_value
      FROM 'production_vor.parquet'
      WHERE sleeper_player_id = '${id}' AND ${prodCutoff}
      ORDER BY as_of_week
    `),
    query(`
      SELECT snapshot_date, market_vor, trade_gap, is_cross_time
      FROM 'market_vor.parquet'
      WHERE sleeper_player_id = '${id}'
      ORDER BY snapshot_date
    `),
    query(`
      SELECT recent_ppg, expected_ppg, opp_g, opp_pct, td_share, eff_ratio, regression_risk,
             read, quality_rate, luck, direction, reliability, point_correlation, security,
             games, low_sample
      FROM 'player_signal.parquet'
      WHERE sleeper_player_id = '${id}' AND ${asOfSlice('player_signal.parquet', asOfWeek)}
    `),
    query(`
      SELECT bull_grade, bull_note, bear_grade, bear_note, situation_grade, situation_note,
             confidence, confidence_note, signal_tier, has_news, has_ros_anchor, anchor_is_prior_season
      FROM 'ros_synthesis.parquet'
      WHERE sleeper_player_id = '${id}'
      QUALIFY row_number() OVER (PARTITION BY sleeper_player_id ORDER BY week DESC) = 1
    `),
    query(`SELECT roster_id, team_name, owner_name FROM 'teams.parquet'`),
  ]);

  const ident = identRows[0];
  if (!ident && prodRows.length === 0) return { missing: true };

  // Identity + roster status. production_vor is rostered-only, so status is always
  // "on your roster" or "rostered by X" (no free-agent state in V1).
  const rosterId = ident?.roster_id != null ? Number(ident.roster_id) : null;
  const teamById = {};
  let myRosterId = null;
  for (const t of teamRows) {
    teamById[Number(t.roster_id)] = t;
    if (t.owner_name === MY_USERNAME) myRosterId = Number(t.roster_id);
  }
  const myTeam = teamById[rosterId];
  const onYours = rosterId != null && rosterId === myRosterId;
  const status = onYours
    ? 'On your roster'
    : myTeam
      ? `Rostered · ${myTeam.team_name || myTeam.owner_name}`
      : 'Rostered';

  // Value·VOR series (oldest → newest) + value/delta.
  const prodSeries = prodRows.map((r) => Number(r.vor));
  const mktSeries = mktRows.map((r) => Number(r.market_vor));
  const prod = seriesRead(prodSeries);
  const mkt = seriesRead(mktSeries);

  // Trade lean off the current Production−Market gap. CROSS-TIME today (2026 market ×
  // 2025 roster) — surfaced as POC, never a confident live call (contract §6).
  const last = mktRows.length ? mktRows[mktRows.length - 1] : null;
  const gap = last?.trade_gap != null ? Number(last.trade_gap) : null;
  const crossTime = Boolean(last?.is_cross_time);
  let lean = null;
  if (gap != null) {
    if (gap > TRADE_GAP_T) lean = { call: 'SELL', why: 'Market values him above his production.' };
    else if (gap < -TRADE_GAP_T) lean = { call: 'BUY', why: 'Production beats his current market price.' };
    else lean = { call: 'HOLD', why: 'Market and production roughly agree.' };
    lean.gap = gap;
    lean.crossTime = crossTime;
  }

  // Opportunity axes (player_signal).
  const s = sigRows[0];
  const opportunity = s
    ? {
        qualityRate: num(s.quality_rate),
        effRatio: num(s.eff_ratio),
        volumePct: num(s.opp_pct),
        oppG: num(s.opp_g),
        trustDir: s.direction ?? null,
        reliability: num(s.reliability),
        pointCorr: num(s.point_correlation),
        luck: num(s.luck),
        recentPpg: num(s.recent_ppg),
        expectedPpg: num(s.expected_ppg),
        read: s.read ?? null,
        security: s.security ?? null,
        lowSample: Boolean(s.low_sample),
      }
    : null;

  // ROS Outcome Shape (ros_synthesis) — sparse; null when no AI read exists.
  const r = rosRows[0];
  const ros = r
    ? {
        bull: num(r.bull_grade),
        bear: num(r.bear_grade),
        situation: num(r.situation_grade),
        bullNote: r.bull_note,
        bearNote: r.bear_note,
        situationNote: r.situation_note,
        confidence: r.confidence,
        confidenceNote: r.confidence_note,
        signalTier: r.signal_tier,
        priorSeason: Boolean(r.anchor_is_prior_season),
      }
    : null;

  return {
    sleeperId,
    name: ident?.name ?? sleeperId,
    pos: ident?.position ?? null,
    nflTeam: ident?.nfl_team ?? null,
    status,
    onYours,
    prod,
    mkt: { ...mkt, crossTime },
    lean,
    opportunity,
    ros,
  };
}

// ---------------------------------------------------------------------------
// Teams tab — the standings table (Gridiron surface #3).
// ---------------------------------------------------------------------------

// One row per (team, week): total points + W/L, bounded to weeks ≤ N. Feeds both the
// real record and the all-play ("true record") computation (score vs every other team
// every week — the luck-neutral read the contract §4.4 keeps distinct from true_rank).
const SQL_STANDINGS_WEEKS = (n) => `
  SELECT roster_id, week,
         any_value(roster_total_points) AS pts,
         any_value(matchup_result)      AS result
  FROM 'season.parquet'
  WHERE ${weekCutoff(n)}
  GROUP BY roster_id, week
`;

/**
 * The Teams standings: every team with its real record, all-play "true record",
 * playoff odds (+ the weekly odds series for the trendline) and derived posture.
 * Sorted by playoff odds desc. bracket_odds is tall over as_of_week; playoff_odds is a
 * 0–1 fraction (surfaced ×100). Posture is the shared §5 derivation (posture.js).
 * @param {number} [asOfWeek] view as of week N; omit for the latest week
 * @returns {Promise<object[]>} view-ready standings rows, best playoff odds first
 */
export async function loadStandings(asOfWeek) {
  // All odds rows up to week N → per team, the weekly series + the current (latest) row.
  const oddsCutoff = asOfWeek == null ? 'TRUE' : `as_of_week <= ${Number(asOfWeek)}`;
  const [teamWeeks, oddsRows, teamRows] = await Promise.all([
    query(SQL_STANDINGS_WEEKS(asOfWeek)),
    query(`
      SELECT as_of_week, roster_id, playoff_odds, avg_seed, magic_wins, remaining_games
      FROM 'bracket_odds.parquet'
      WHERE ${oddsCutoff}
      ORDER BY roster_id, as_of_week
    `),
    query(`SELECT roster_id, team_name, owner_name FROM 'teams.parquet'`),
  ]);

  // Records + all-play, from the team-week scores.
  const byWeek = {};
  const record = {};
  for (const r of teamWeeks) {
    const row = { rosterId: Number(r.roster_id), pts: Number(r.pts), result: r.result };
    (byWeek[Number(r.week)] ??= []).push(row);
    const rec = (record[row.rosterId] ??= { w: 0, l: 0 });
    if (row.result === 'W') rec.w++;
    else if (row.result === 'L') rec.l++;
  }
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

  // Odds: weekly playoff-odds series (×100) + the latest slice's current values.
  const oddsByTeam = {};
  for (const r of oddsRows) {
    const rid = Number(r.roster_id);
    (oddsByTeam[rid] ??= { series: [], last: null });
    oddsByTeam[rid].series.push(Number(r.playoff_odds) * 100);
    oddsByTeam[rid].last = r; // rows are ordered by as_of_week, so this ends as the latest
  }

  const nameOf = {};
  for (const t of teamRows) nameOf[Number(t.roster_id)] = t;

  const rows = Object.keys(allPlay).map(Number).map((rid) => {
    const t = nameOf[rid];
    const o = oddsByTeam[rid];
    const ap = allPlay[rid];
    const rec = record[rid] ?? { w: 0, l: 0 };
    const playoffPct = o?.last ? Number(o.last.playoff_odds) * 100 : null;
    const allPlayPct = ap.w + ap.l ? (ap.w / (ap.w + ap.l)) * 100 : 0;
    return {
      rosterId: rid,
      name: t?.team_name || t?.owner_name || `Team ${rid}`,
      owner: t?.owner_name ?? null,
      isMe: t?.owner_name === MY_USERNAME,
      wins: rec.w,
      losses: rec.l,
      allPlayW: ap.w,
      allPlayL: ap.l,
      playoffPct,
      allPlayPct,
      seed: o?.last?.avg_seed != null ? Math.round(Number(o.last.avg_seed)) : null,
      magicWins: o?.last?.magic_wins != null ? Number(o.last.magic_wins) : null,
      remainingGames: o?.last?.remaining_games != null ? Number(o.last.remaining_games) : null,
      oddsSeries: o?.series ?? [],
      posture: playoffPct != null ? derivePosture(playoffPct, allPlayPct) : null,
    };
  });

  // Rank by playoff odds desc (nulls last), then all-play % as a tiebreak.
  rows.sort((a, b) => (b.playoffPct ?? -1) - (a.playoffPct ?? -1) || b.allPlayPct - a.allPlayPct);
  rows.forEach((r, i) => (r.rank = i + 1));
  return rows;
}

// ---------------------------------------------------------------------------
// League tab — "whole league at a glance" (Gridiron surface #4).
// ---------------------------------------------------------------------------

/**
 * The League surface's core data: the full standings (reused from loadStandings — each row
 * already carries playoff %, all-play %, posture, seed, magic, odds series) plus the "me"
 * row and the REAL playoff cut / team count from league_settings. One source feeds Your
 * Race, the Playoff Picture, and the Posture Map.
 * @param {number} [asOfWeek] view as of week N; omit for the latest week
 * @returns {Promise<{standings: object[], me: object|null, playoffCut: number|null, nTeams: number}>}
 */
export async function loadLeague(asOfWeek) {
  const [standings, cfgRows] = await Promise.all([
    loadStandings(asOfWeek),
    query(`
      SELECT key, value FROM 'league_settings.parquet'
      WHERE section = 'league' AND key IN ('playoff_teams', 'num_teams')
    `),
  ]);
  const cfg = {};
  for (const r of cfgRows) cfg[r.key] = Number(r.value);
  return {
    standings,
    me: standings.find((s) => s.isMe) ?? null,
    playoffCut: cfg.playoff_teams != null ? Math.round(cfg.playoff_teams) : null,
    nTeams: cfg.num_teams != null ? Math.round(cfg.num_teams) : standings.length,
  };
}

/**
 * Positional Talent: per position (QB/RB/WR/TE), teams ranked by the Market VOR they hold
 * there — the sum of each rostered player's positive `market_vor` at the latest market
 * snapshot (a surplus is trade capital, a gap is a target). Cross-time by construction
 * (2026 market × 2025 roster), flagged so the view marks it POC. Not week-parameterized:
 * the market is current and does not replay with the week selector.
 * @returns {Promise<{byPos: Object<string, object[]>, isCrossTime: boolean}>}
 */
export async function loadPositionalTalent() {
  const rows = await query(`
    WITH latest AS (
      SELECT roster_id, position,
             sum(greatest(market_vor, 0)) AS pos_vor,
             bool_or(is_cross_time)        AS is_cross_time
      FROM 'market_vor.parquet'
      WHERE snapshot_date = (SELECT max(snapshot_date) FROM 'market_vor.parquet')
        AND position IN ('QB','RB','WR','TE')
      GROUP BY roster_id, position
    )
    SELECT l.roster_id, l.position, l.pos_vor, l.is_cross_time, t.team_name, t.owner_name
    FROM latest l
    LEFT JOIN 'teams.parquet' t USING (roster_id)
  `);
  const byPos = { QB: [], RB: [], WR: [], TE: [] };
  let crossTime = false;
  for (const r of rows) {
    if (r.is_cross_time) crossTime = true;
    (byPos[r.position] ??= []).push({
      rosterId: Number(r.roster_id),
      name: r.team_name || r.owner_name || `Team ${r.roster_id}`,
      isMe: r.owner_name === MY_USERNAME,
      vor: Number(r.pos_vor),
    });
  }
  for (const pos of POS) {
    (byPos[pos] ??= []).sort((a, b) => b.vor - a.vor);
    byPos[pos].forEach((x, i) => (x.rank = i + 1));
  }
  return { byPos, isCrossTime: crossTime };
}

// ---------------------------------------------------------------------------
// Team detail (drill-down from the standings) — stat blocks, positional depth,
// roster with a PROD/MKT VOR toggle.
// ---------------------------------------------------------------------------

// positional_depth `shape` → the display chip (contract §4.5).
const SHAPE_LABEL = { surplus: 'SURPLUS', adequate: 'EVEN', gap: 'GAP' };

/**
 * Everything the Team-detail view needs for one roster: the 4 stat blocks (record,
 * all-play "true record", playoff % + seed, points/week), positional depth per
 * QB/RB/WR/TE (starter value, league-relative spectrum, rank, SURPLUS/EVEN/GAP shape),
 * and the roster split into starters/bench with each player's Production + Market VOR
 * weekly series (for the card's PROD/MKT toggle + trend sparkline). Keyed on
 * sleeper_player_id; the roster is resolved as-of week N (latest week ≤ N).
 * @param {number} rosterId
 * @param {number} [asOfWeek] view as of week N; omit for the latest week
 * @returns {Promise<object|null>} the assembled team, or null if the roster is unknown
 */
export async function loadTeamDetail(rosterId, asOfWeek) {
  const rid = Number(rosterId);
  const prodCutoff = asOfWeek == null ? 'TRUE' : `as_of_week <= ${Number(asOfWeek)}`;

  const [teamWeeks, oddsRows, depthRows, rosterRows, prodRows, mktRows, teamRows] = await Promise.all([
    query(SQL_STANDINGS_WEEKS(asOfWeek)),
    query(`SELECT playoff_odds, avg_seed FROM 'bracket_odds.parquet'
           WHERE roster_id = ${rid} AND ${asOfSlice('bracket_odds.parquet', asOfWeek)}`),
    query(`SELECT roster_id, position, starter_value, surplus_value, marginal_vor, spectrum_pos, shape
           FROM 'positional_depth.parquet' WHERE ${asOfSlice('positional_depth.parquet', asOfWeek)}`),
    query(`
      WITH latest AS (
        SELECT sleeper_player_id,
               arg_max(roster_id, week)           AS roster_id,
               arg_max(is_starter, week)          AS is_starter,
               arg_max(player_display_name, week) AS name,
               arg_max(position, week)            AS position,
               arg_max(team, week)                AS nfl_team
        FROM 'season.parquet'
        WHERE position IN ('QB','RB','WR','TE') AND ${weekCutoff(asOfWeek)}
        GROUP BY sleeper_player_id
      )
      SELECT * FROM latest WHERE roster_id = ${rid}
    `),
    query(`SELECT sleeper_player_id, as_of_week, vor FROM 'production_vor.parquet'
           WHERE roster_id = ${rid} AND ${prodCutoff} ORDER BY sleeper_player_id, as_of_week`),
    query(`SELECT sleeper_player_id, snapshot_date, market_vor FROM 'market_vor.parquet'
           WHERE roster_id = ${rid} ORDER BY sleeper_player_id, snapshot_date`),
    query(`SELECT roster_id, team_name, owner_name FROM 'teams.parquet'`),
  ]);

  // Identity / "you".
  const teamById = {};
  let myRosterId = null;
  for (const t of teamRows) {
    teamById[Number(t.roster_id)] = t;
    if (t.owner_name === MY_USERNAME) myRosterId = Number(t.roster_id);
  }
  const me = teamById[rid];
  if (!me && rosterRows.length === 0) return null;

  // Record + all-play "true record" + points-for, from the team-week scores.
  const byWeek = {};
  for (const r of teamWeeks) {
    (byWeek[Number(r.week)] ??= []).push({ rosterId: Number(r.roster_id), pts: Number(r.pts), result: r.result });
  }
  let w = 0, l = 0, ptsFor = 0, games = 0;
  const ap = { w: 0, l: 0 };
  for (const rows of Object.values(byWeek)) {
    const mine = rows.find((x) => x.rosterId === rid);
    if (!mine) continue;
    games++; ptsFor += mine.pts;
    if (mine.result === 'W') w++; else if (mine.result === 'L') l++;
    for (const b of rows) {
      if (b.rosterId === rid) continue;
      if (mine.pts > b.pts) ap.w++; else if (mine.pts < b.pts) ap.l++;
    }
  }

  const odds = oddsRows[0];
  const stats = {
    record: `${w}-${l}`,
    trueRec: `${ap.w}-${ap.l}`,
    playoffPct: odds?.playoff_odds != null ? Number(odds.playoff_odds) * 100 : null,
    seed: odds?.avg_seed != null ? Math.round(Number(odds.avg_seed)) : null,
    ptsWk: games ? round1(ptsFor / games) : null,
  };

  // Positional depth per position, with league rank (by starter_value) and the shape chip.
  const byPos = {};
  for (const d of depthRows) (byPos[d.position] ??= []).push(d);
  const depth = POS.map((pos) => {
    const all = (byPos[pos] ?? []).slice().sort((a, b) => Number(b.starter_value) - Number(a.starter_value));
    const idx = all.findIndex((d) => Number(d.roster_id) === rid);
    if (idx < 0) return null;
    const d = all[idx];
    return {
      position: pos,
      starterValue: Number(d.starter_value),
      surplusValue: Number(d.surplus_value),
      marginalVor: Number(d.marginal_vor),
      spectrumPos: Number(d.spectrum_pos),
      shape: SHAPE_LABEL[d.shape] ?? d.shape,
      rank: idx + 1,
      nTeams: all.length,
    };
  }).filter(Boolean);

  // Per-player VOR series, keyed by sleeper_player_id.
  const prodById = {};
  for (const r of prodRows) (prodById[r.sleeper_player_id] ??= []).push(Number(r.vor));
  const mktById = {};
  for (const r of mktRows) (mktById[r.sleeper_player_id] ??= []).push(Number(r.market_vor));

  const players = rosterRows.map((p) => ({
    sleeperId: p.sleeper_player_id,
    name: p.name,
    pos: p.position,
    nflTeam: p.nfl_team ?? null,
    isStarter: Boolean(p.is_starter),
    prod: seriesRead(prodById[p.sleeper_player_id] ?? []),
    mkt: seriesRead(mktById[p.sleeper_player_id] ?? []),
  }));
  const byValue = (a, b) => (b.prod.value ?? -Infinity) - (a.prod.value ?? -Infinity);
  const starters = players.filter((p) => p.isStarter).sort(byValue);
  const bench = players.filter((p) => !p.isStarter).sort(byValue);

  // This-week matchup bar (§4.5): the team's upcoming projected game (now that the Matchups slice
  // supplies the read — no longer deferred).
  const thisWeek = await teamMatchupSummary(rid, asOfWeek);

  return {
    rosterId: rid,
    name: me?.team_name || me?.owner_name || `Team ${rid}`,
    owner: me?.owner_name ?? null,
    onYours: rid === myRosterId,
    stats,
    thisWeek,
    depth,
    roster: { starters, bench },
  };
}

// ---------------------------------------------------------------------------
// Manager Dossier (drill-down from team detail) — the cleanest 1:1 map (§4.8).
// ---------------------------------------------------------------------------

/**
 * The Manager Dossier for one roster: the AI headline + five tendency fields, the signal
 * depth footer (tier + league/season/move counts + confidence note), and provenance.
 * Byte-identical to the manager_dossiers entity — the row already carries the feature
 * counts, so no second read is needed. is_zero_signal drives the "no intel" state.
 * @param {number} rosterId
 * @returns {Promise<object>} the dossier, or { missing: true } if none exists
 */
export async function loadManagerDossier(rosterId) {
  const rows = await query(`
    SELECT owner_name, team_name, headline, waiver_faab, trade_tendency, positional_lean,
           roster_construction, edge_or_blindspot, confidence_note, depth_tier,
           n_leagues, n_seasons, n_transactions, is_zero_signal, model, generated_at
    FROM 'manager_dossiers.parquet'
    WHERE roster_id = ${Number(rosterId)}
  `);
  const d = rows[0];
  if (!d) return { missing: true };
  return {
    owner: d.owner_name,
    teamName: d.team_name || d.owner_name,
    isZeroSignal: Boolean(d.is_zero_signal),
    headline: d.headline,
    tendencies: {
      waiverFaab: d.waiver_faab,
      tradeTendency: d.trade_tendency,
      positionalLean: d.positional_lean,
      rosterConstruction: d.roster_construction,
      edgeOrBlindspot: d.edge_or_blindspot,
    },
    depthTier: d.depth_tier,
    nLeagues: Number(d.n_leagues),
    nSeasons: Number(d.n_seasons),
    nTransactions: Number(d.n_transactions),
    confidenceNote: d.confidence_note,
    model: d.model,
    generatedAt: d.generated_at,
  };
}

// Summarize a value series → current value, delta (last − first), direction.
function seriesRead(series) {
  if (!series.length) return { series: [], value: null, delta: null, up: true };
  const value = series[series.length - 1];
  const delta = value - series[0];
  return { series, value, delta, up: delta >= 0 };
}

const num = (v) => (v == null ? null : Number(v));

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

// ---------------------------------------------------------------------------
// Matchups tab — the week's head-to-head slate + matchup detail (Gridiron surface #2, §4.3).
// The app is a season replay: "this week" is the upcoming week N+1 (as-of N), shown fully
// PROJECTED. A team's weekly score distribution mirrors compute_bracket_sim.py — μ = Σ optimal-
// starter center_ppr, σ = √(Σ band_ppr²) — so the analytic win prob Φ((μA−μB)/√(σA²+σB²)) matches
// the backend sim (its Monte Carlo only exists to roll μ/σ up into playoff odds, which we already
// read from bracket_odds). Projections + pairings come from projection_consensus + the pairing-only
// schedule (points dropped upstream, so the replay never sees a future result).
// ---------------------------------------------------------------------------

// Resolve N (as-of) → the upcoming target week N+1. asOfWeek is normally a number (App resolves the
// latest via loadWeeks); null falls back to the latest played week here.
async function targetWeekFor(asOfWeek) {
  let n = asOfWeek == null ? null : Number(asOfWeek);
  if (n == null) {
    const r = await query(`SELECT max(week) AS w FROM 'season.parquet'`);
    n = r.length && r[0].w != null ? Number(r[0].w) : null;
  }
  return n == null ? null : n + 1;
}

// Real W-L per team from the team-week results (weeks ≤ N). Mirrors loadStandings' record pass.
function recordsByRoster(weekRows) {
  const rec = {};
  for (const r of weekRows) {
    const x = (rec[Number(r.roster_id)] ??= { w: 0, l: 0 });
    if (r.result === 'W') x.w++;
    else if (r.result === 'L') x.l++;
  }
  return rec;
}

// Per-team projected lineup for a target week: the frozen roster-as-of-N (same arg_max definition
// Team detail uses, so the two surfaces agree) set into its optimal lineup by that week's borrowed
// projection centre. Shared by the slate and the detail so both read ONE definition of "who starts
// and how much they score". Returns rosterId → { mu, sigma, starters, bench } — starters/bench
// players carry their p25/p50/p75 for the range gauges.
async function teamProjections(asOfWeek, targetWeek) {
  const [rosterRows, projRows, slotRows, teamRows] = await Promise.all([
    query(`
      WITH latest AS (
        SELECT sleeper_player_id,
               arg_max(roster_id, week)           AS roster_id,
               arg_max(player_display_name, week) AS name,
               arg_max(position, week)            AS position,
               arg_max(team, week)                AS nfl_team
        FROM 'season.parquet'
        WHERE position IN ('QB','RB','WR','TE') AND ${weekCutoff(asOfWeek)}
        GROUP BY sleeper_player_id
      )
      SELECT * FROM latest WHERE roster_id IS NOT NULL
    `),
    query(`
      SELECT sleeper_player_id, center_ppr, band_ppr, p25_ppr, p50_ppr, p75_ppr
      FROM 'projection_consensus.parquet' WHERE week = ${Number(targetWeek)}
    `),
    query(`SELECT slot, count, eligible FROM 'slots.parquet'`),
    query(`SELECT roster_id, team_name, owner_name FROM 'teams.parquet'`),
  ]);

  const projById = {};
  for (const p of projRows) projById[p.sleeper_player_id] = p;
  const slots = expandSlots(slotRows);

  const byRoster = {};
  for (const r of rosterRows) (byRoster[Number(r.roster_id)] ??= []).push(r);

  const teams = {};
  for (const t of teamRows) {
    const rid = Number(t.roster_id);
    const roster = byRoster[rid] ?? [];
    // Attach the target-week projection to each rostered skill player (center == p50 = μ term;
    // band = σ term). A rostered player with no projection that week contributes 0 / won't start.
    const players = roster.map((p, i) => {
      const pr = projById[p.sleeper_player_id];
      return {
        _i: i,
        sleeperId: p.sleeper_player_id,
        name: p.name,
        position: p.position,
        nflTeam: p.nfl_team ?? null,
        pts: pr ? Number(pr.center_ppr) : 0,
        band: pr ? Number(pr.band_ppr) : 0,
        p25: pr ? Number(pr.p25_ppr) : null,
        p50: pr ? Number(pr.p50_ppr) : null,
        p75: pr ? Number(pr.p75_ppr) : null,
        hasProj: Boolean(pr),
      };
    });
    const { picks } = optimalLineup(players, slots);
    const starterSet = new Set(picks.map((p) => p._i));
    const bench = players.filter((p) => !starterSet.has(p._i)).sort((a, b) => b.pts - a.pts);
    const mu = picks.reduce((s, p) => s + p.pts, 0);
    const sigma = Math.sqrt(picks.reduce((s, p) => s + p.band * p.band, 0));
    teams[rid] = {
      rosterId: rid,
      name: t.team_name || t.owner_name || `Team ${rid}`,
      owner: t.owner_name ?? null,
      isMe: t.owner_name === MY_USERNAME,
      mu: round1(mu),
      sigma,
      starters: picks,
      bench,
    };
  }
  return teams;
}

// One matchup's two sides → [winProbA, winProbB] as 0–1 fractions (0.5 if both σ are 0).
function matchupWinProbs(muA, sigA, muB, sigB) {
  const denom = Math.sqrt(sigA * sigA + sigB * sigB);
  const pa = denom > 0 ? normalCdf((muA - muB) / denom) : 0.5;
  return [pa, 1 - pa];
}

// One team's upcoming (week N+1) game — opponent + projected totals + win prob — for the Team-detail
// this-week bar (§4.5). Folded into loadTeamDetail so the surface stays one read. null when there's
// no next game (season complete) or the team isn't scheduled.
async function teamMatchupSummary(rid, asOfWeek) {
  const targetWeek = await targetWeekFor(asOfWeek);
  if (targetWeek == null) return null;
  const mine = await query(
    `SELECT matchup_id FROM 'schedule.parquet' WHERE week = ${targetWeek} AND roster_id = ${Number(rid)}`,
  );
  if (!mine.length) return null;
  const mid = Number(mine[0].matchup_id);
  const [teams, sides] = await Promise.all([
    teamProjections(asOfWeek, targetWeek),
    query(`SELECT roster_id FROM 'schedule.parquet' WHERE week = ${targetWeek} AND matchup_id = ${mid}`),
  ]);
  const oppId = sides.map((r) => Number(r.roster_id)).find((r) => r !== Number(rid));
  if (oppId == null || !teams[Number(rid)] || !teams[oppId]) return null;
  const me = teams[Number(rid)];
  const opp = teams[oppId];
  const [pMe, pOpp] = matchupWinProbs(me.mu, me.sigma, opp.mu, opp.sigma);
  return {
    matchupId: mid,
    targetWeek,
    me: { proj: me.mu, winProb: Math.round(pMe * 100) },
    opp: { rosterId: oppId, name: opp.name, proj: opp.mu, winProb: Math.round(pOpp * 100) },
  };
}

/**
 * The Matchups slate: the upcoming week's (as-of N → week N+1) head-to-head games, each with both
 * teams' records, projected totals (optimal-lineup μ) and analytic win prob. Your game is flagged
 * (`isMine`) and sorted first. Fully projected — the replay never reads the week's actual result.
 * @param {number} [asOfWeek] view as of week N; omit for the latest week
 * @returns {Promise<{targetWeek: number|null, games: object[], myGameId: number|null, empty: boolean}>}
 */
export async function loadMatchups(asOfWeek) {
  const targetWeek = await targetWeekFor(asOfWeek);
  const schedRows = targetWeek == null ? [] : await query(
    `SELECT roster_id, matchup_id FROM 'schedule.parquet' WHERE week = ${targetWeek} ORDER BY matchup_id, roster_id`,
  );
  if (!schedRows.length) return { targetWeek, games: [], myGameId: null, empty: true };

  const [teams, weekRows] = await Promise.all([
    teamProjections(asOfWeek, targetWeek),
    query(SQL_STANDINGS_WEEKS(asOfWeek)),
  ]);
  const rec = recordsByRoster(weekRows);

  const byMatchup = {};
  for (const s of schedRows) (byMatchup[Number(s.matchup_id)] ??= []).push(Number(s.roster_id));

  const games = Object.entries(byMatchup).map(([mid, rids]) => {
    const sides = rids.map((rid) => {
      const t = teams[rid] ?? { rosterId: rid, name: `Team ${rid}`, owner: null, isMe: false, mu: 0, sigma: 0 };
      const r = rec[rid] ?? { w: 0, l: 0 };
      return { ...t, record: `${r.w}-${r.l}` };
    });
    let probs = sides.map(() => null);
    if (sides.length === 2) probs = matchupWinProbs(sides[0].mu, sides[0].sigma, sides[1].mu, sides[1].sigma);
    const out = sides.map((s, i) => ({
      rosterId: s.rosterId,
      name: s.name,
      owner: s.owner,
      isMe: s.isMe,
      record: s.record,
      proj: s.mu,
      winProb: probs[i] == null ? null : Math.round(probs[i] * 100),
    }));
    // My team first, else higher win prob first.
    out.sort((x, y) => Number(y.isMe) - Number(x.isMe) || (y.winProb ?? 0) - (x.winProb ?? 0));
    return { matchupId: Number(mid), teams: out, isMine: out.some((t) => t.isMe) };
  });

  games.sort((a, b) => Number(b.isMine) - Number(a.isMine) || a.matchupId - b.matchupId);
  return { targetWeek, games, myGameId: games.find((g) => g.isMine)?.matchupId ?? null, empty: false };
}

// Flatten a starter/bench player to the view shape (median tick + 25–75 range for the gauge).
const matchupPlayerView = (p) => ({
  sleeperId: p.sleeperId,
  name: p.name,
  pos: p.position,
  nflTeam: p.nflTeam ?? null,
  slot: p.slot ?? null,
  proj: p.hasProj ? round1(p.pts) : null,
  p25: p.p25,
  p50: p.p50,
  p75: p.p75,
  hasProj: p.hasProj,
});

/**
 * One matchup's full breakdown: head-to-head win prob, each team's Score Range (Σ starters'
 * p25/p50/p75 — contract §4.3), per-starter range gauges (p25/p50/p75), and the starters+bench
 * split (starters = the optimal projected lineup). Teams ordered with "you" first.
 * @param {number} matchupId the game's matchup_id in the target week
 * @param {number} [asOfWeek] view as of week N; omit for the latest week
 * @returns {Promise<{matchupId: number, targetWeek: number, teams: object[]}|null>}
 */
export async function loadMatchupDetail(matchupId, asOfWeek) {
  const mid = Number(matchupId);
  const targetWeek = await targetWeekFor(asOfWeek);
  if (targetWeek == null) return null;

  const [teams, schedRows, weekRows] = await Promise.all([
    teamProjections(asOfWeek, targetWeek),
    query(`SELECT roster_id FROM 'schedule.parquet' WHERE week = ${targetWeek} AND matchup_id = ${mid} ORDER BY roster_id`),
    query(SQL_STANDINGS_WEEKS(asOfWeek)),
  ]);
  const rids = schedRows.map((r) => Number(r.roster_id));
  if (rids.length < 2 || !teams[rids[0]] || !teams[rids[1]]) return null;
  const rec = recordsByRoster(weekRows);

  const sides = rids.map((rid) => {
    const t = teams[rid];
    const r = rec[rid] ?? { w: 0, l: 0 };
    // Team Score Range = sum of starters' quantiles (a starter without a projection falls back to
    // its μ term so the band stays coherent).
    const range = t.starters.reduce(
      (acc, p) => ({
        p25: acc.p25 + (p.p25 ?? p.pts),
        p50: acc.p50 + (p.p50 ?? p.pts),
        p75: acc.p75 + (p.p75 ?? p.pts),
      }),
      { p25: 0, p50: 0, p75: 0 },
    );
    return {
      rosterId: rid,
      name: t.name,
      owner: t.owner,
      isMe: t.isMe,
      record: `${r.w}-${r.l}`,
      proj: t.mu,
      sigma: t.sigma,
      range: { p25: round1(range.p25), p50: round1(range.p50), p75: round1(range.p75) },
      starters: t.starters.map(matchupPlayerView),
      bench: t.bench.map(matchupPlayerView),
    };
  });

  const probs = matchupWinProbs(sides[0].proj, sides[0].sigma, sides[1].proj, sides[1].sigma);
  sides.forEach((s, i) => (s.winProb = Math.round(probs[i] * 100)));
  sides.sort((x, y) => Number(y.isMe) - Number(x.isMe) || y.winProb - x.winProb);

  return { matchupId: mid, targetWeek, teams: sides };
}

// Optimal-lineup engine, ported from transforms/_analytics.py (expand_slots + optimal_lineup) so the
// front-end projected lineup matches the backend sim. expandSlots: one entry per physical starting
// slot (a FLEX count of 2 → two slots), most-constrained first so dedicated slots claim their stars
// before flex slots draw from the pool.
function expandSlots(slotRows) {
  const slots = [];
  for (const s of slotRows) {
    const eligible = String(s.eligible).split(',');
    for (let k = 0; k < Number(s.count); k++) slots.push({ slot: s.slot, eligible });
  }
  slots.sort((a, b) => a.eligible.length - b.eligible.length);
  return slots;
}

// Greedy optimal lineup: fill the most-constrained slot first with the top-`pts` eligible player
// still available. Each player carries a stable `_i` so usage is tracked across slots. Returns the
// chosen picks (each tagged with its filled slot) and the total.
function optimalLineup(players, slots) {
  const used = new Set();
  const picks = [];
  let total = 0;
  for (const slot of slots) {
    let best = null;
    for (const p of players) {
      if (used.has(p._i) || !slot.eligible.includes(p.position)) continue;
      if (best == null || p.pts > best.pts) best = p;
    }
    if (!best) continue;
    total += best.pts;
    used.add(best._i);
    picks.push({ ...best, slot: slot.slot });
  }
  return { total, picks };
}

// Φ(z): the standard normal CDF via the Abramowitz–Stegun erf approximation (7.1.26; |ε| < 1.5e-7)
// — mirrors compute_bracket_sim.py's math.erf so the analytic win prob matches the backend sim.
function erf(x) {
  const sign = x < 0 ? -1 : 1;
  const ax = Math.abs(x);
  const t = 1 / (1 + 0.3275911 * ax);
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t) * Math.exp(-ax * ax);
  return sign * y;
}
function normalCdf(z) {
  return 0.5 * (1 + erf(z / Math.SQRT2));
}
