import React, { useEffect, useState } from 'react';
import { loadTeams } from './queries.js';

// Team tab: a deep drill-down on ONE team. Opens on the logged-in user's team
// and can flip to any other via the switcher. Two inner views:
//   - overview: how the team is doing — strengths and weak spots
//   - players:  per-player real-world metrics, made interpretable
// Both views are scaffolded here; their real content lands in later sessions.
const SUBTABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'players', label: 'Players' },
];

export default function TeamPanel() {
  const [teams, setTeams] = useState(null);
  const [selected, setSelected] = useState(null); // rosterId in focus
  const [subtab, setSubtab] = useState('overview');
  const [error, setError] = useState(null);

  useEffect(() => {
    loadTeams()
      .then(({ teams, myRosterId }) => {
        setTeams(teams);
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
  if (!teams) {
    return <div className="state">Loading teams…</div>;
  }

  const team = teams.find((t) => t.rosterId === selected);

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

      {subtab === 'overview' && (
        <div className="subview-stub">
          Team overview — strengths and weak spots, deepened from the league
          sidebar metrics. Coming next.
        </div>
      )}
      {subtab === 'players' && (
        <div className="subview-stub">
          Players — per-player real-world metrics with visualizations that make
          the stats interpretable. Coming next.
        </div>
      )}
    </div>
  );
}
