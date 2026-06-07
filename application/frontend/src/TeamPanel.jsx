import React, { useEffect, useState } from 'react';
import { loadTeams, loadPowerRankings, loadTeamRosters, POS } from './queries.js';
import { POS_COLORS } from './posColors.js';

// Team tab: a deep drill-down on ONE team. Opens on the logged-in user's team
// and can flip to any other via the switcher. Two inner views:
//   - overview: how the team is built and how it's doing — strengths, fragility
//   - players:  per-player real-world metrics, made interpretable
// The League tab answers "how do I stack up?" (comparative); the Team tab answers
// "how is THIS team built and managed?" — so it looks inside one roster (bench
// included) rather than ranking starters across the league.
const SUBTABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'players', label: 'Players' },
];

export default function TeamPanel() {
  const [teams, setTeams] = useState(null);
  const [summary, setSummary] = useState(null); // rosterId -> power-ranking vitals
  const [rosters, setRosters] = useState(null); // rosterId -> construction detail
  const [selected, setSelected] = useState(null); // rosterId in focus
  const [subtab, setSubtab] = useState('overview');
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([loadTeams(), loadPowerRankings(), loadTeamRosters()])
      .then(([{ teams, myRosterId }, rankings, rosterDetail]) => {
        setTeams(teams);
        // Index power-ranking vitals (rank, record, PPG, power) by roster.
        const byId = {};
        for (const t of rankings.teams) byId[t.rosterId] = { ...t, teamCount: rankings.teams.length };
        setSummary(byId);
        setRosters(rosterDetail);
        // Default to the user's own team; fall back to the first roster.
        setSelected(myRosterId ?? teams[0]?.rosterId ?? null);
      })
      .catch((e) => {
        console.error(e);
        setError(e.message ?? String(e));
      });
  }, []);

  if (error) {
    return (
      <div className="state error">
        <h2>Couldn’t load teams</h2>
        <pre>{error}</pre>
      </div>
    );
  }
  if (!teams || !summary || !rosters) {
    return <div className="state">Loading team data via DuckDB…</div>;
  }

  const team = teams.find((t) => t.rosterId === selected);
  const vitals = summary[selected];
  const roster = rosters[selected];

  return (
    <div className="page">
      <header className="page-head team-head">
        <div>
          <h1>{team?.name ?? 'Team'}</h1>
          <div className="sub">
            {team?.isMe ? 'Your team' : `@${team?.owner}`}
          </div>
        </div>
        <label className="team-switch">
          <span className="team-switch-label">Viewing</span>
          <select
            value={selected ?? ''}
            onChange={(e) => setSelected(Number(e.target.value))}
          >
            {teams.map((t) => (
              <option key={t.rosterId} value={t.rosterId}>
                {t.name}
                {t.isMe ? ' (you)' : ''}
              </option>
            ))}
          </select>
        </label>
      </header>

      <div className="subnav">
        {SUBTABS.map((s) => (
          <button
            key={s.id}
            className={`subnav-tab ${subtab === s.id ? 'active' : ''}`}
            onClick={() => setSubtab(s.id)}
          >
            {s.label}
          </button>
        ))}
      </div>

      {subtab === 'overview' && <Overview vitals={vitals} roster={roster} />}
      {subtab === 'players' && (
        <div className="subview-stub">
          Players — per-player real-world metrics with visualizations that make
          the stats interpretable. Coming next.
        </div>
      )}
    </div>
  );
}

function Overview({ vitals, roster }) {
  if (!vitals || !roster) {
    return <div className="subview-stub">No data for this team.</div>;
  }
  return (
    <>
      <Vitals vitals={vitals} />
      <section className="to-section">
        <h3 className="to-h3">How this team is built</h3>
        <Reliance reliance={roster.reliance} />
        <DepthChart byPosition={roster.byPosition} maxTotal={roster.maxTotal} />
        <div className="to-foot">
          Bars are total points scored for this team over the season window
          (bench included), on one scale per team — so the drop-off after a
          starter reads as real roster depth or a cliff. Filled markers = regular
          starters.
        </div>
      </section>
    </>
  );
}

// At-a-glance vitals: where the team sits before the construction detail.
function Vitals({ vitals }) {
  const tiles = [
    { label: 'Power rank', value: `#${vitals.rank}`, sub: `of ${vitals.teamCount}` },
    { label: 'Record', value: `${vitals.wins}–${vitals.losses}` },
    { label: 'Points / wk', value: vitals.avgPts.toFixed(1), sub: `±${vitals.std.toFixed(1)}` },
    { label: 'Power score', value: vitals.powerScore, accent: true },
  ];
  return (
    <div className="to-vitals">
      {tiles.map((t) => (
        <div className="to-tile" key={t.label}>
          <div className={`to-tile-value ${t.accent ? 'accent' : ''}`}>{t.value}</div>
          <div className="to-tile-label">{t.label}</div>
          {t.sub && <div className="to-tile-sub">{t.sub}</div>}
        </div>
      ))}
    </div>
  );
}

// Star reliance: how concentrated the team's starting output is. High top-3 share
// = leaning on a few players (fragile to injury/bye); low = distributed/deep.
function relianceRead(top3) {
  if (top3 >= 0.55) return { label: 'Top-heavy', tone: 'heavy', note: 'leans on a few players' };
  if (top3 >= 0.42) return { label: 'Balanced', tone: 'balanced', note: 'a solid core, some spread' };
  return { label: 'Deep', tone: 'deep', note: 'output spread across the roster' };
}

function Reliance({ reliance }) {
  const read = relianceRead(reliance.top3);
  // Contribution bar: show the top contributors by name, fold the rest together.
  const TOP = 5;
  const shown = reliance.contributors.slice(0, TOP);
  const restShare = reliance.contributors.slice(TOP).reduce((s, c) => s + c.share, 0);

  return (
    <div className="to-reliance">
      <div className="to-reliance-head">
        <div>
          <div className="to-reliance-stat">
            Top 3 starters
            <span className="to-reliance-pct">{Math.round(reliance.top3 * 100)}%</span>
            <span className="to-reliance-of">of starting points</span>
          </div>
          <div className="to-reliance-sub">
            Top scorer alone {Math.round(reliance.top1 * 100)}%
          </div>
        </div>
        <span className={`reliance-tag rel-${read.tone}`} title={read.note}>{read.label}</span>
      </div>

      <div className="to-contrib" role="img" aria-label="starting-point contribution by player">
        {shown.map((c) => (
          <div
            key={c.name}
            className="to-contrib-seg"
            style={{ width: `${c.share * 100}%`, background: POS_COLORS[c.position] }}
            title={`${c.name} — ${Math.round(c.share * 100)}%`}
          />
        ))}
        {restShare > 0 && (
          <div
            className="to-contrib-seg rest"
            style={{ width: `${restShare * 100}%` }}
            title={`Rest of roster — ${Math.round(restShare * 100)}%`}
          />
        )}
      </div>
      <div className="to-contrib-legend">
        {shown.map((c) => (
          <span key={c.name} className="to-contrib-key">
            <span className="to-contrib-dot" style={{ background: POS_COLORS[c.position] }} />
            {c.name} {Math.round(c.share * 100)}%
          </span>
        ))}
        {restShare > 0 && (
          <span className="to-contrib-key">
            <span className="to-contrib-dot rest" />
            Rest {Math.round(restShare * 100)}%
          </span>
        )}
      </div>
    </div>
  );
}

// Depth chart: per position, every rostered skill player as a bar (total points,
// one scale per team). Starters are solid, bench is dimmed — so the shape of the
// position (deep vs. one stud + a cliff) is visible at a glance.
function DepthChart({ byPosition, maxTotal }) {
  return (
    <div className="to-depth">
      {POS.map((pos) => {
        const players = byPosition[pos] ?? [];
        return (
          <div className="to-depth-group" key={pos}>
            <div className="to-depth-pos" style={{ color: POS_COLORS[pos] }}>{pos}</div>
            <div className="to-depth-rows">
              {players.length === 0 ? (
                <div className="to-depth-empty">no players</div>
              ) : (
                players.map((p) => {
                  const width = maxTotal ? (p.total / maxTotal) * 100 : 0;
                  const starter = p.starts > 0;
                  return (
                    <div className={`to-depth-row ${starter ? 'starter' : 'bench'}`} key={p.name}>
                      <span className="to-depth-name">
                        {starter && <span className="to-depth-marker" />}
                        {p.name}
                      </span>
                      <div className="to-depth-track">
                        <div
                          className="to-depth-fill"
                          style={{ width: `${width}%`, background: POS_COLORS[pos] }}
                        />
                      </div>
                      <span className="to-depth-val">{p.total.toFixed(0)}</span>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
