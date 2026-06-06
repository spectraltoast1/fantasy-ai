import React, { useEffect, useState } from 'react';
import { loadPowerRankings, POS } from './queries.js';

// View-only concern: how positions are colored. All data access lives in queries.js.
const POS_COLORS = { QB: '#e0709a', RB: '#5fb3a3', WR: '#6699e6', TE: '#d9a85f' };

export default function App() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    loadPowerRankings()
      .then(setData)
      .catch((e) => {
        console.error(e);
        setError(e.message ?? String(e));
      });
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
          <div className="team-name">{team.name}</div>
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
