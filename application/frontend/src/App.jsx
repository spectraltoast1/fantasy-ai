import React, { useEffect, useState } from 'react';
import LeaguePanel from './LeaguePanel.jsx';
import TeamPanel from './TeamPanel.jsx';
import { loadWeeks } from './queries.js';

// App shell: owns the top-level tab and the active as-of week, and renders the active
// panel. Each panel owns its own data loading (via queries.js), so this stays a thin
// navigation frame — but the week selector lives here, in the shell, so one active week
// applies across League + Team and stays editable from every tab (Season-replay).
const TABS = [
  { id: 'league', label: 'League' },
  { id: 'team', label: 'Team' },
];

export default function App() {
  const [tab, setTab] = useState('league');
  // The Season-replay week dimension: which week N the whole dashboard reads "as of".
  // weekList = the selectable weeks (1..latest); asOfWeek = the active one, defaulting
  // to the latest (the current week — a live app opens here, today week 4). null until
  // the week list loads, which means "latest" to queries.js, so reads work meanwhile.
  const [weekList, setWeekList] = useState(null);
  const [asOfWeek, setAsOfWeek] = useState(null);

  useEffect(() => {
    loadWeeks()
      .then(({ weeks, latest }) => {
        setWeekList(weeks);
        setAsOfWeek(latest);
      })
      .catch((e) => console.error('Could not load weeks', e));
  }, []);

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
          <WeekSelector weeks={weekList} value={asOfWeek} onChange={setAsOfWeek} />
        </div>
      </nav>

      {tab === 'league' && <LeaguePanel asOfWeek={asOfWeek} />}
      {tab === 'team' && <TeamPanel asOfWeek={asOfWeek} />}
    </div>
  );
}

// The global week selector. A dropdown over weeks 1..latest that sets the dashboard's
// active as-of week; it only travels back (the data only goes up to the latest week).
// Hidden until the week list loads.
function WeekSelector({ weeks, value, onChange }) {
  if (!weeks || weeks.length === 0 || value == null) return null;
  return (
    <label className="week-switch">
      <span className="week-switch-label">As of</span>
      <select value={value} onChange={(e) => onChange(Number(e.target.value))}>
        {weeks.map((w) => (
          <option key={w} value={w}>
            Week {w}
          </option>
        ))}
      </select>
    </label>
  );
}
