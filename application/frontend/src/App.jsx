import React, { useEffect, useState } from 'react';
import { query } from './db.js';

const POS = ['QB', 'RB', 'WR', 'TE'];
const POS_COLORS = { QB: '#e0709a', RB: '#5fb3a3', WR: '#6699e6', TE: '#d9a85f' };

// --- SQL (all run live against the parquet via DuckDB-WASM) ---
// Team-week score collapses the per-player rows to one row per (team, week),
// since roster_total_points / matchup_result repeat across a team's players.
const SQL_TEAMS = `
  WITH team_week AS (
    SELECT roster_id, week,
           any_value(roster_total_points) AS team_pts,
           any_value(matchup_result)      AS result
    FROM 'season.parquet'
    GROUP BY roster_id, week
  )
  SELECT roster_id,
         round(avg(team_pts), 2)                      AS avg_pts,
         round(coalesce(stddev_samp(team_pts), 0), 2) AS pts_std,
         sum(result = 'W')::INT                        AS wins,
         sum(result = 'L')::INT                        AS losses,
         count(*)::INT                                 AS games
  FROM team_week
  GROUP BY roster_id
  ORDER BY avg_pts DESC
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

export default function App() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    (async () => {
      try {
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

        setData({
          teams: ranked,
          maxStarterTotal,
          season: seasonRows[0]?.season,
          weeks: weekRows.map((w) => Number(w.week)),
        });
      } catch (e) {
        console.error(e);
        setError(e.message ?? String(e));
      }
    })();
  }, []);

  if (error) {
    return (
      <div className="state error">
        <h2>Couldn’t load data</h2>
        <pre>{error}</pre>
      </div>
    );
  }
  if (!data) {
    return <div className="state">Loading season data via DuckDB…</div>;
  }

  const weekLabel =
    data.weeks.length > 1
      ? `Weeks ${data.weeks[0]}–${data.weeks[data.weeks.length - 1]}`
      : `Week ${data.weeks[0]}`;

  return (
    <div className="page">
      <header className="page-head">
        <h1>Power Rankings</h1>
        <div className="sub">
          {data.season} · {weekLabel} · {data.teams.length} teams
        </div>
      </header>

      <div className="rankings">
        {data.teams.map((t) => (
          <TeamCard key={t.rosterId} team={t} maxStarterTotal={data.maxStarterTotal} />
        ))}
      </div>

      <footer className="legend">
        {POS.map((p) => (
          <span key={p} className="legend-item">
            <span className="swatch" style={{ background: POS_COLORS[p] }} />
            {p}
          </span>
        ))}
        <span className="legend-note">segments = avg starter pts/wk by position</span>
      </footer>
    </div>
  );
}

function TeamCard({ team, maxStarterTotal }) {
  const consistency =
    team.cv < 0.15 ? 'Steady' : team.cv < 0.28 ? 'Average' : 'Volatile';
  const stackWidthPct = (team.starterTotal / maxStarterTotal) * 100;

  return (
    <div className="card">
      <div className="rank">{team.rank}</div>

      <div className="card-body">
        <div className="card-top">
          <div className="team-name">Team {team.rosterId}</div>
          <div className="record">
            {team.wins}–{team.losses}
          </div>
        </div>

        <div className="metrics">
          <div className="ppg">
            <span className="big">{team.avgPts.toFixed(1)}</span>
            <span className="unit">PPG</span>
          </div>
          <span className={`badge c-${consistency.toLowerCase()}`}>
            {consistency}
            <span className="badge-sub">±{team.std.toFixed(1)}</span>
          </span>
        </div>

        {/* Positional composition: one stacked bar, width relative to the league's strongest starters. */}
        <div className="stack-wrap" style={{ width: `${stackWidthPct}%` }}>
          <div className="stack">
            {POS.map((p) => {
              const v = team.breakdown[p] ?? 0;
              const pct = team.starterTotal ? (v / team.starterTotal) * 100 : 0;
              return (
                <div
                  key={p}
                  className="seg"
                  style={{ width: `${pct}%`, background: POS_COLORS[p] }}
                  title={`${p}: ${v.toFixed(1)} pts/wk`}
                />
              );
            })}
          </div>
        </div>
        <div className="pos-values">
          {POS.map((p) => (
            <span key={p} className="pv">
              <span className="pv-dot" style={{ background: POS_COLORS[p] }} />
              {p} {(team.breakdown[p] ?? 0).toFixed(1)}
            </span>
          ))}
        </div>
      </div>

      <div className="power">
        <div className="power-score">{team.powerScore}</div>
        <div className="power-label">POWER</div>
      </div>
    </div>
  );
}
