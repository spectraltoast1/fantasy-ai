import * as duckdb from '@duckdb/duckdb-wasm';

// Single shared DuckDB-WASM instance. The parquet is fetched once and registered
// as an in-memory file; every query runs real SQL against it in the browser —
// mirroring the eventual "DuckDB over parquet" architecture.
let dbPromise = null;

async function initDB() {
  const bundles = duckdb.getJsDelivrBundles();
  const bundle = await duckdb.selectBundle(bundles);

  // Worker is created from the CDN bundle via a Blob shim to dodge cross-origin limits.
  const workerUrl = URL.createObjectURL(
    new Blob([`importScripts("${bundle.mainWorker}");`], { type: 'text/javascript' }),
  );
  const worker = new Worker(workerUrl);
  const logger = new duckdb.ConsoleLogger(duckdb.LogLevel.WARNING);
  const db = new duckdb.AsyncDuckDB(logger, worker);
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  URL.revokeObjectURL(workerUrl);

  // Live reads: public/data/*.parquet are symlinks to the real snapshots.
  // season = the weekly join; teams = roster_id → team/owner names;
  // slots = the league's declared starting skill-slot config (for optimal lineups);
  // form/leakage = pre-computed Team Overview analytics (transforms/compute_team_*.py),
  // promoted out of the JS seam so the heavy math lives in Python;
  // player_signal = the per-player spike signal-quality read (compute_player_signal.py).
  await registerParquet(db, '/data/season_2025.parquet', 'season.parquet');
  await registerParquet(db, '/data/teams_2025.parquet', 'teams.parquet');
  await registerParquet(db, '/data/lineup_slots_2025.parquet', 'slots.parquet');
  await registerParquet(db, '/data/league_settings_2025.parquet', 'league_settings.parquet');
  await registerParquet(db, '/data/team_form_2025.parquet', 'team_form.parquet');
  await registerParquet(db, '/data/team_leakage_2025.parquet', 'team_leakage.parquet');
  await registerParquet(db, '/data/player_signal_2025.parquet', 'player_signal.parquet');
  // Gridiron player reads: Production VOR (2025 frozen roster), Market VOR (cross-time
  // 2026 market), and ROS Synthesis (the AI 1-10 grades; sparse — keyed on the 2026
  // news world, hence _2026). All join to the others on sleeper_player_id.
  await registerParquet(db, '/data/production_vor_2025.parquet', 'production_vor.parquet');
  await registerParquet(db, '/data/market_vor_2025.parquet', 'market_vor.parquet');
  await registerParquet(db, '/data/ros_synthesis_2026.parquet', 'ros_synthesis.parquet');
  // Teams standings: bracket_odds (playoff odds, tall over as_of_week — the standings
  // playoff % + trendline; also all-play "true record" computed off season above).
  await registerParquet(db, '/data/bracket_odds_2025.parquet', 'bracket_odds.parquet');
  // Team detail: positional_depth (per team/position starter value + league spectrum +
  // surplus/adequate/gap shape, tall over as_of_week).
  await registerParquet(db, '/data/positional_depth_2025.parquet', 'positional_depth.parquet');
  // Manager Dossier: the AI headline + tendencies + signal-depth counts, one row per team.
  await registerParquet(db, '/data/manager_dossiers_2025.parquet', 'manager_dossiers.parquet');
  // Matchups: projection_consensus (per-player p25/p50/p75 + center/band, tall over weeks 1-18 —
  // the forward projections the slate + detail read) and the pairing-only schedule (week →
  // matchup_id pairs; points dropped upstream so future results never reach the client).
  await registerParquet(db, '/data/projection_consensus_2025.parquet', 'projection_consensus.parquet');
  await registerParquet(db, '/data/schedule_2025.parquet', 'schedule.parquet');
  return db;
}

async function registerParquet(db, url, name) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Could not load ${url} (HTTP ${res.status})`);
  const buf = new Uint8Array(await res.arrayBuffer());
  await db.registerFileBuffer(name, buf);
}

export function getDB() {
  if (!dbPromise) dbPromise = initDB();
  return dbPromise;
}

// Run SQL, return plain JS objects. BigInts (from 64-bit counts) are coerced to Number.
export async function query(sql) {
  const db = await getDB();
  const conn = await db.connect();
  try {
    const result = await conn.query(sql);
    return result.toArray().map((row) => {
      const obj = row.toJSON();
      for (const k of Object.keys(obj)) {
        if (typeof obj[k] === 'bigint') obj[k] = Number(obj[k]);
      }
      return obj;
    });
  } finally {
    await conn.close();
  }
}
