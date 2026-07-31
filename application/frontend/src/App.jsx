import React, { useEffect, useState } from 'react';
import { loadWeeks, loadLeagueMeta, loadLeagues, setActiveSlice } from './queries.js';
import { TAB_ICONS, IconChevronLeft } from './icons.jsx';
import Placeholder from './Placeholder.jsx';
import Players from './Players.jsx';
import PlayerCard from './PlayerCard.jsx';
import Teams from './Teams.jsx';
import TeamDetail from './TeamDetail.jsx';
import Dossier from './Dossier.jsx';
import League from './League.jsx';
import Matchups from './Matchups.jsx';
import MatchupDetail from './MatchupDetail.jsx';
import { weeksOfData } from './readiness.jsx';

// Gridiron app shell. Owns the global state the whole app reads:
//   tab      — the active surface (league / matchups / teams / players)
//   detail   — the active drill-down ({ type, id } | null); "‹ Back" clears it
//   asOfWeek — the season-replay week (default latest; travels back only)
//   slice    — the active league/season/viewer (Stage-B B5): what league you're looking at
// Surfaces stay pure renderers and load their own data through queries.js; the active `slice`
// is set on queries.js (setActiveSlice) so it rides on every request without threading it
// through each surface. All four surfaces render real data.
const TABS = [
  { id: 'league', label: 'League' },
  { id: 'matchups', label: 'Matchups' },
  { id: 'teams', label: 'Teams' },
  { id: 'players', label: 'Players' },
];

// The demo catalog groups seasons under a lineage; the latest season is first (seasons desc).
const latestSeason = (lineage) => lineage.seasons[0];
const sliceFrom = (lineage, s) => ({
  lineageId: lineage.lineage_id,
  leagueId: s.league_id,
  season: s.season,
  viewerRosterId: s.viewer_roster_id,
  name: lineage.name,
  panels: s.panels,
});

export default function App() {
  const [tab, setTab] = useState('league');
  // Drill-downs form a stack so multi-level paths (team → player, team → dossier) get a
  // correct "‹ Back" that pops one level. Switching tabs — or leagues/seasons — clears it. The
  // top is the active detail; empty stack = the tab's own surface.
  const [stack, setStack] = useState([]);
  const detail = stack.length ? stack[stack.length - 1] : null;
  const [weekList, setWeekList] = useState(null);
  const [playedWeeks, setPlayedWeeks] = useState(null);   // weeks with RESULTS — the honest-depth clock
  const [asOfWeek, setAsOfWeek] = useState(null);
  const [league, setLeague] = useState(null);
  const [leagues, setLeagues] = useState(null);   // the /api/leagues catalog (lineages → seasons)
  const [slice, setSlice] = useState(null);       // active { lineageId, leagueId, season, viewerRosterId, name, panels }
  const [switching, setSwitching] = useState(false);

  // Apply a slice: publish it to queries.js SYNCHRONOUSLY (so the reloads below scope to it),
  // clear the drill-down, then reload the new slice's weeks and snap the week to its latest.
  // `switching` gates the surfaces off until the week is settled, so no surface renders against a
  // half-applied slice (and two leagues sharing a latest week still get a clean remount).
  const applySlice = (next) => {
    setSwitching(true);
    setActiveSlice({ league_id: next.leagueId, season: next.season, viewer_roster_id: next.viewerRosterId });
    setSlice(next);
    setStack([]);
    return loadWeeks()
      .then(({ weeks, played, latest }) => {
        setWeekList(weeks);
        setPlayedWeeks(played ?? []);
        setAsOfWeek(latest);
      })
      .catch((e) => console.error('Could not load weeks', e))
      .finally(() => setSwitching(false));
  };

  // Startup: load the catalog, then default to the is_mine lineage's latest season (the catalog
  // lists is_mine first). Setting this default slice explicitly is parity-safe — its league_id +
  // viewer resolve to exactly the server's is_mine default.
  useEffect(() => {
    loadLeagues()
      .then((data) => {
        const lgs = data.leagues || [];
        setLeagues(lgs);
        if (lgs.length) applySlice(sliceFrom(lgs[0], latestSeason(lgs[0])));
      })
      .catch((e) => console.error('Could not load leagues', e));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // League chrome (format label / record / myOwner) is real data and follows the active week AND
  // slice (the leagueId dep re-fires it on a switch even when the latest week is unchanged).
  useEffect(() => {
    if (!slice) return;
    loadLeagueMeta(asOfWeek)
      .then(setLeague)
      .catch((e) => console.error('Could not load league meta', e));
  }, [asOfWeek, slice?.leagueId]);

  const goTab = (id) => {
    setTab(id);
    setStack([]);
  };
  const push = (d) => setStack((s) => [...s, d]);
  const openPlayer = (id) => push({ type: 'player', id });
  const openTeam = (id) => push({ type: 'team', id });
  const openDossier = (id) => push({ type: 'dossier', id });
  const openMatchup = (id) => push({ type: 'matchup', id });
  const back = () => setStack((s) => s.slice(0, -1));

  // Switch handlers: a league change defaults to that lineage's latest season; a season change
  // stays within the current lineage.
  const currentLineage = leagues && slice ? leagues.find((l) => l.lineage_id === slice.lineageId) : null;
  const switchLeague = (lineageId) => {
    const lineage = leagues.find((l) => l.lineage_id === lineageId);
    if (lineage) applySlice(sliceFrom(lineage, latestSeason(lineage)));
  };
  const switchSeason = (season) => {
    if (!currentLineage) return;
    const s = currentLineage.seasons.find((x) => x.season === season);
    if (s) applySlice(sliceFrom(currentLineage, s));
  };

  return (
    <div className="gr-frame">
      <TopBar
        tab={tab}
        onTab={goTab}
        weeks={weekList}
        asOfWeek={asOfWeek}
        onWeek={setAsOfWeek}
        league={league}
        leagues={leagues}
        slice={slice}
        lineage={currentLineage}
        onLeague={switchLeague}
        onSeason={switchSeason}
      />
      <main className="gr-main">
        {!slice || switching ? (
          <div className="gr-view"><div className="gr-state">Loading…</div></div>
        ) : (
          <Surface
            tab={tab}
            detail={detail}
            depth={stack.length}
            asOfWeek={asOfWeek}
            weeks={weeksOfData(playedWeeks, asOfWeek)}
            slice={slice}
            onOpenPlayer={openPlayer}
            onOpenTeam={openTeam}
            onOpenDossier={openDossier}
            onOpenMatchup={openMatchup}
            onBack={back}
          />
        )}
      </main>
    </div>
  );
}

// Routes tab/detail to a surface; all four surfaces render real data. The view is keyed on the
// slice too, so switching leagues/seasons remounts the surface → it reloads against the new slice.
// Detail views render centered behind a "‹ Back" affordance. `panels` = the slice's catalog panel
// map (market/manager/ros_synthesis), threaded to the surfaces for gating. `weeks` = weeks of real
// RESULTS as of the viewed week (readiness.weeksOfData) — the one depth clock every surface reads.
function Surface({ tab, detail, depth, asOfWeek, weeks, slice, onOpenPlayer, onOpenTeam, onOpenDossier, onOpenMatchup, onBack }) {
  const panels = slice?.panels;
  const viewKey = slice.leagueId + ':' + tab + ':' + depth + (detail ? ':' + detail.type + ':' + detail.id : '');

  let content;
  if (detail?.type === 'player') {
    content = (
      <DetailShell onBack={onBack}>
        <PlayerCard sleeperId={detail.id} asOfWeek={asOfWeek} weeks={weeks} panels={panels} />
      </DetailShell>
    );
  } else if (detail?.type === 'team') {
    content = (
      <DetailShell onBack={onBack}>
        <TeamDetail rosterId={detail.id} asOfWeek={asOfWeek} weeks={weeks} panels={panels} onOpenPlayer={onOpenPlayer} onOpenDossier={onOpenDossier} onOpenMatchup={onOpenMatchup} />
      </DetailShell>
    );
  } else if (detail?.type === 'dossier') {
    content = (
      <DetailShell onBack={onBack}>
        <Dossier rosterId={detail.id} />
      </DetailShell>
    );
  } else if (detail?.type === 'matchup') {
    content = (
      <DetailShell onBack={onBack}>
        <MatchupDetail matchupId={detail.id} asOfWeek={asOfWeek} weeks={weeks} />
      </DetailShell>
    );
  } else if (tab === 'players') {
    content = <Players asOfWeek={asOfWeek} weeks={weeks} panels={panels} onOpenPlayer={onOpenPlayer} />;
  } else if (tab === 'teams') {
    content = <Teams asOfWeek={asOfWeek} weeks={weeks} onOpenTeam={onOpenTeam} />;
  } else if (tab === 'league') {
    content = <League asOfWeek={asOfWeek} weeks={weeks} panels={panels} onOpenTeam={onOpenTeam} />;
  } else if (tab === 'matchups') {
    content = <Matchups asOfWeek={asOfWeek} weeks={weeks} onOpenMatchup={onOpenMatchup} />;
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

function TopBar({ tab, onTab, weeks, asOfWeek, onWeek, league, leagues, slice, lineage, onLeague, onSeason }) {
  return (
    <header className="gr-topbar">
      <div className="gr-brand">
        <span className="gr-brand-mark">G</span>
        Gridiron
      </div>

      <LeagueSwitcher league={league} leagues={leagues} slice={slice} onLeague={onLeague} />

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

      <div className="gr-controls">
        <SeasonSwitcher lineage={lineage} value={slice?.season} onChange={onSeason} />
        <WeekSwitcher weeks={weeks} value={asOfWeek} onChange={onWeek} />
      </div>

      <div className="gr-avatar" title={league?.myOwner ?? 'You'}>
        {(league?.myOwner ?? 'Y').slice(0, 1).toUpperCase()}
      </div>
    </header>
  );
}

// The league selector — a real dropdown over the 12 lineages (is_mine first, from /api/leagues),
// leading the derived format label (team count · scoring · QB structure) + the user's record, all
// real. The selected lineage's display name comes from the catalog.
function LeagueSwitcher({ league, leagues, slice, onLeague }) {
  return (
    <div className="gr-league">
      {leagues && slice ? (
        <select
          className="gr-league-select"
          value={slice.lineageId}
          onChange={(e) => onLeague(e.target.value)}
        >
          {leagues.map((l) => (
            <option key={l.lineage_id} value={l.lineage_id}>
              {l.name}
            </option>
          ))}
        </select>
      ) : (
        <span className="gr-league-name">{slice?.name ?? 'My League'}</span>
      )}
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

// The season selector — mirrors WeekSwitcher, over the selected lineage's seasons (desc).
function SeasonSwitcher({ lineage, value, onChange }) {
  if (!lineage || value == null) return null;
  return (
    <label className="gr-season">
      <span className="gr-week-label">Season</span>
      <select value={value} onChange={(e) => onChange(Number(e.target.value))}>
        {lineage.seasons.map((s) => (
          <option key={s.season} value={s.season}>
            {s.season}
          </option>
        ))}
      </select>
    </label>
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
