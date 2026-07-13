import React, { useEffect, useState } from 'react';
import { loadWeeks, loadLeagueMeta } from './queries.js';
import { TAB_ICONS, IconChevronLeft } from './icons.jsx';
import Placeholder from './Placeholder.jsx';
import Players from './Players.jsx';
import PlayerCard from './PlayerCard.jsx';
import Teams from './Teams.jsx';
import TeamDetail from './TeamDetail.jsx';
import Dossier from './Dossier.jsx';

// Gridiron app shell. Owns the three pieces of global state the whole app reads:
//   tab      — the active surface (league / matchups / teams / players)
//   detail   — the active drill-down ({ type, id } | null); "‹ Back" clears it
//   asOfWeek — the season-replay week (default latest; travels back only)
// Surfaces stay pure renderers and load their own data through queries.js. During the
// migration only Players is wired; League/Matchups/Teams show the coming-soon slot.
const TABS = [
  { id: 'league', label: 'League' },
  { id: 'matchups', label: 'Matchups' },
  { id: 'teams', label: 'Teams' },
  { id: 'players', label: 'Players' },
];

export default function App() {
  const [tab, setTab] = useState('players');
  // Drill-downs form a stack so multi-level paths (team → player, team → dossier) get a
  // correct "‹ Back" that pops one level. Switching tabs clears it. The top is the active
  // detail; empty stack = the tab's own surface.
  const [stack, setStack] = useState([]);
  const detail = stack.length ? stack[stack.length - 1] : null;
  const [weekList, setWeekList] = useState(null);
  const [asOfWeek, setAsOfWeek] = useState(null);
  const [league, setLeague] = useState(null);

  // The week list drives the selector; latest is the live default. null asOfWeek means
  // "latest" to queries.js, so reads work before this resolves.
  useEffect(() => {
    loadWeeks()
      .then(({ weeks, latest }) => {
        setWeekList(weeks);
        setAsOfWeek(latest);
      })
      .catch((e) => console.error('Could not load weeks', e));
  }, []);

  // League chrome (name/meta/record) is real data — derived from teams + league_settings,
  // and the record follows the active week.
  useEffect(() => {
    loadLeagueMeta(asOfWeek)
      .then(setLeague)
      .catch((e) => console.error('Could not load league meta', e));
  }, [asOfWeek]);

  const goTab = (id) => {
    setTab(id);
    setStack([]);
  };
  const push = (d) => setStack((s) => [...s, d]);
  const openPlayer = (id) => push({ type: 'player', id });
  const openTeam = (id) => push({ type: 'team', id });
  const openDossier = (id) => push({ type: 'dossier', id });
  const back = () => setStack((s) => s.slice(0, -1));

  return (
    <div className="gr-frame">
      <TopBar
        tab={tab}
        onTab={goTab}
        weeks={weekList}
        asOfWeek={asOfWeek}
        onWeek={setAsOfWeek}
        league={league}
      />
      <main className="gr-main">
        <Surface
          tab={tab}
          detail={detail}
          depth={stack.length}
          asOfWeek={asOfWeek}
          onOpenPlayer={openPlayer}
          onOpenTeam={openTeam}
          onOpenDossier={openDossier}
          onBack={back}
        />
      </main>
    </div>
  );
}

// Routes tab/detail to a surface. Players is wired; the other three surfaces show the
// coming-soon slot. Detail views render centered behind a "‹ Back" affordance.
function Surface({ tab, detail, depth, asOfWeek, onOpenPlayer, onOpenTeam, onOpenDossier, onBack }) {
  const viewKey = tab + ':' + depth + (detail ? ':' + detail.type + ':' + detail.id : '');

  let content;
  if (detail?.type === 'player') {
    content = (
      <DetailShell onBack={onBack}>
        <PlayerCard sleeperId={detail.id} asOfWeek={asOfWeek} />
      </DetailShell>
    );
  } else if (detail?.type === 'team') {
    content = (
      <DetailShell onBack={onBack}>
        <TeamDetail rosterId={detail.id} asOfWeek={asOfWeek} onOpenPlayer={onOpenPlayer} onOpenDossier={onOpenDossier} />
      </DetailShell>
    );
  } else if (detail?.type === 'dossier') {
    content = (
      <DetailShell onBack={onBack}>
        <Dossier rosterId={detail.id} />
      </DetailShell>
    );
  } else if (tab === 'players') {
    content = <Players asOfWeek={asOfWeek} onOpenPlayer={onOpenPlayer} />;
  } else if (tab === 'teams') {
    content = <Teams asOfWeek={asOfWeek} onOpenTeam={onOpenTeam} />;
  } else {
    content = <Placeholder tab={tab} />;
  }

  return (
    <div key={viewKey} className="gr-view">
      {content}
    </div>
  );
}

// Centered detail container with a back affordance. Shared by every drill-down.
function DetailShell({ onBack, children }) {
  return (
    <div className="gr-detail">
      <button className="gr-back" onClick={onBack}>
        <IconChevronLeft size={15} /> Back
      </button>
      {children}
    </div>
  );
}

function TopBar({ tab, onTab, weeks, asOfWeek, onWeek, league }) {
  return (
    <header className="gr-topbar">
      <div className="gr-topbar-left">
        <div className="gr-brand">
          <span className="gr-brand-mark">G</span>
          Gridiron
        </div>
        <LeagueSwitcher league={league} />
      </div>

      <nav className="gr-tabs">
        {TABS.map((t) => {
          const Icon = TAB_ICONS[t.id];
          return (
            <button
              key={t.id}
              className={`gr-tab ${tab === t.id ? 'active' : ''}`}
              onClick={() => onTab(t.id)}
            >
              <span className="gr-tab-icon">
                <Icon size={16} />
              </span>
              {t.label}
            </button>
          );
        })}
      </nav>

      <div className="gr-topbar-right">
        <WeekSwitcher weeks={weeks} value={asOfWeek} onChange={onWeek} />
        <div className="gr-avatar" title={league?.myOwner ?? 'You'}>
          {(league?.myOwner ?? 'Y').slice(0, 1).toUpperCase()}
        </div>
      </div>
    </header>
  );
}

// League name isn't persisted by Sleeper's config fetch yet, so the switcher leads with
// the derived format label (team count · scoring · QB structure) + the user's record —
// all real, none hardcoded. (Follow-up: persist the league name to fill the name line.)
function LeagueSwitcher({ league }) {
  return (
    <div className="gr-league">
      <span className="gr-league-name">{league?.name ?? 'My League'}</span>
      <span className="gr-league-meta">
        {league?.label ?? '—'}
        {league?.record ? (
          <>
            {' · '}
            <span className="rec">{league.record}</span>
          </>
        ) : null}
      </span>
    </div>
  );
}

// The global week selector (season replay). Travels back only; hidden until weeks load.
function WeekSwitcher({ weeks, value, onChange }) {
  if (!weeks || weeks.length === 0 || value == null) return null;
  return (
    <label className="gr-week">
      <span className="gr-week-label">As of</span>
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
