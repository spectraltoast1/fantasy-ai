import React, { useEffect, useState } from 'react';
import { loadWeeks, loadLeagueMeta, loadLeagues, setActiveSlice, setAuthToken } from './queries.js';
import { supabase } from './supabase.js';
import SignIn from './SignIn.jsx';
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
import { pageView, track } from './analytics.js';

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

// What GA is told a "page" is (appendices/analytics.md). The SPA has no router, so the app
// reports the surface itself; without this GA sees one pageview per visit and eight minutes in
// Matchups is indistinguishable from a bounce.
const SURFACES = {
  league:   { path: '/league',   title: 'League' },
  matchups: { path: '/matchups', title: 'Matchups' },
  teams:    { path: '/teams',    title: 'Teams' },
  players:  { path: '/players',  title: 'Players' },
};
// Drill-downs are FLAT, not nested under the tab they were opened from: a player card opens from
// Players and from TeamDetail. Nesting would split one thing's usage across several rows and make
// the ranking — the whole point — harder to read.
const DETAILS = {
  player:  { path: '/player-card',    title: 'Player card' },
  team:    { path: '/team-detail',    title: 'Team detail' },
  dossier: { path: '/dossier',        title: 'Manager dossier' },
  matchup: { path: '/matchup-detail', title: 'Matchup detail' },
};

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
  const [session, setSession] = useState(null);   // the Supabase session (P5/S1), null = signed out
  const [signInOpen, setSignInOpen] = useState(false);
  const [authReady, setAuthReady] = useState(false);   // has the stored session been resolved yet?
  const [identityEpoch, setIdentityEpoch] = useState(0);  // bumps on sign-in/out → refetch catalog

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

  // Auth (P5/S1). Publish the token to queries.js on EVERY auth event, not just sign-in:
  // onAuthStateChange also fires for TOKEN_REFRESHED, and a token that stops being republished
  // there silently starts failing about an hour after sign-in. Publishing is synchronous and
  // happens before any dependent reload, mirroring applySlice's ordering rule above.
  //
  // P5/S2a made the ORDER load-bearing. This effect used to run alongside the catalog load below
  // rather than before it, which was correct while /api/leagues was unscoped and became a bug the
  // moment it wasn't: `getSession()` is async, so the first catalog request went out with no token
  // and a signed-in user landed on the DEMO instead of their own league until they reloaded.
  // So the catalog now waits for `authReady`, and refetches whenever the IDENTITY changes —
  // SIGNED_IN and SIGNED_OUT only. TOKEN_REFRESHED is the same person with a fresher token; treating
  // it as a change would refetch the catalog every hour for no reason.
  //
  // `supabase` is null when the build has no Supabase config: sign-in is then unavailable and says
  // so, and `authReady` flips immediately so the public demo still loads. Auth breaking must not
  // break the app around it — a permanently-false authReady would hang every visitor on "Loading…".
  useEffect(() => {
    if (!supabase) { setAuthReady(true); return; }
    supabase.auth.getSession().then(({ data }) => {
      setAuthToken(data.session?.access_token);
      setSession(data.session ?? null);
      setAuthReady(true);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((event, next) => {
      setAuthToken(next?.access_token);
      setSession(next ?? null);
      if (next) setSignInOpen(false);
      if (event === 'SIGNED_IN') track('signed_in');
      if (event === 'SIGNED_IN' || event === 'SIGNED_OUT') {
        // Clear the SELECTION, not just the list. A stale `league_id`/`viewer_roster_id` left in
        // queries.js would keep riding on every request after sign-out — the previous person's
        // league still on screen, which is the bug this session exists to prevent the API version of.
        setActiveSlice({});
        setSlice(null);
        setIdentityEpoch((n) => n + 1);
      }
    });
    return () => sub.subscription.unsubscribe();
  }, []);

  const signOut = () => supabase?.auth.signOut();

  // Load the catalog once the session is known, and again on every identity change. Default to the
  // FIRST entry's latest season: the server orders a caller's own leagues first and the demo last,
  // so "first entry" is what makes a signed-in user land on their own league, a signed-out visitor
  // on the demo, and a signed-in user with no league on the demo as their empty state.
  // Until this resolves `slice` is null, so the surfaces render "Loading…" rather than flashing the
  // demo — a wrong state that would also hide this bug's return.
  useEffect(() => {
    if (!authReady) return;
    loadLeagues()
      .then((data) => {
        const lgs = data.leagues || [];
        setLeagues(lgs);
        if (lgs.length) applySlice(sliceFrom(lgs[0], latestSeason(lgs[0])));
      })
      .catch((e) => console.error('Could not load leagues', e));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authReady, identityEpoch]);

  // League chrome (format label / record / myOwner) is real data and follows the active week AND
  // slice (the leagueId dep re-fires it on a switch even when the latest week is unchanged).
  useEffect(() => {
    if (!slice) return;
    loadLeagueMeta(asOfWeek)
      .then(setLeague)
      .catch((e) => console.error('Could not load league meta', e));
  }, [asOfWeek, slice?.leagueId]);

  // Virtual pageviews — the only thing that makes GA able to tell one surface from another here.
  // `ready` is `!!slice` and deliberately NOT `!!slice && !switching`: applySlice sets `switching`
  // before `slice`, so `switching` is a pure proxy for "the slice is changing" — gating on it would
  // fire a pageview on every league AND season switch for a surface the user never left, which is
  // the same reason `slice.leagueId` is absent from the deps.
  // `detail?.type`, never `detail.id`: the id is a sleeper_id or a roster_id, and in a 12-team
  // league a roster id names a person. It must never leave the browser.
  const ready = !!slice;
  useEffect(() => {
    if (!ready) return;   // don't count the pre-catalog "Loading…" state as a page
    const view = detail?.type ? DETAILS[detail.type] : SURFACES[tab];
    if (view) pageView(view.path, view.title);
  }, [tab, detail?.type, ready]);

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
        session={session}
        onSignIn={() => { track('sign_in_opened'); setSignInOpen(true); }}
        onSignOut={signOut}
      />
      {signInOpen && <SignIn onClose={() => setSignInOpen(false)} />}
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

function TopBar({ tab, onTab, weeks, asOfWeek, onWeek, league, leagues, slice, lineage, onLeague,
                  onSeason, session, onSignIn, onSignOut }) {
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

      <Account session={session} league={league} onSignIn={onSignIn} onSignOut={onSignOut} />
    </header>
  );
}

// The top-right identity slot (P5/S1). Signed OUT it is exactly what it has always been — the
// avatar derived from the demo league's owner — plus a way in; the logged-out view is
// unchanged by design. Signed IN the avatar becomes the REAL account rather than the demo
// league's owner, because two identity widgets side by side, one of them fictional, is worse
// than either alone.
function Account({ session, league, onSignIn, onSignOut }) {
  const email = session?.user?.email;
  if (!email) {
    return (
      <div className="gr-account">
        <button className="gr-signin-btn" onClick={onSignIn}>Sign in</button>
        <div className="gr-avatar" title={league?.myOwner ?? 'You'}>
          {(league?.myOwner ?? 'Y').slice(0, 1).toUpperCase()}
        </div>
      </div>
    );
  }
  return (
    <div className="gr-account">
      <button className="gr-signout-btn" onClick={onSignOut}>Sign out</button>
      <div className="gr-avatar gr-avatar-auth" title={email}>
        {email.slice(0, 1).toUpperCase()}
      </div>
    </div>
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
