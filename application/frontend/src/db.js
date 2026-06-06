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
  // season = the weekly join; teams = roster_id → team/owner names.
  await registerParquet(db, '/data/season_2025.parquet', 'season.parquet');
  await registerParquet(db, '/data/teams_2025.parquet', 'teams.parquet');
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
