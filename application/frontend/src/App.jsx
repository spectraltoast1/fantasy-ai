import React, { useState } from 'react';
import LeaguePanel from './LeaguePanel.jsx';
import TeamPanel from './TeamPanel.jsx';

// App shell: owns the top-level tab and renders the active panel. Each panel owns
// its own data loading (via queries.js), so this stays a thin navigation frame.
const TABS = [
  { id: 'league', label: 'League' },
  { id: 'team', label: 'Team' },
];

export default function App() {
  const [tab, setTab] = useState('league');

  return (
    <div className="app-shell">
      <nav className="topnav">
        <div className="topnav-inner">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={`topnav-tab ${tab === t.id ? 'active' : ''}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </nav>

      {tab === 'league' && <LeaguePanel />}
      {tab === 'team' && <TeamPanel />}
    </div>
  );
}
