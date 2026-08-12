import React, { useEffect, useRef, useState } from 'react';
import { loadWeeks, loadLeagueMeta, loadLeagues, setActiveSlice, setAuthToken,
         setOnAuthRejected } from './queries.js';
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

// The catalog is FLAT as of P5/S2e — one entry per visible league, its season on the row. It used
// to nest seasons under a lineage to feed a season selector; that selector is gone (prior seasons
// are corpus, not product), so there is no longer a latest-season to pick. `season` still travels
// in the slice because every read carries it, inert but carried.
const sliceFrom = (lg) => ({
  leagueId: lg.league_id,
  season: lg.season,
  viewerRosterId: lg.viewer_roster_id,
  name: lg.name,
  panels: lg.panels,
});

export default function App() {
  const [tab, setTab] = useState('league');
  // Drill-downs form a stack so multi-level paths (team → player, team → dossier) get a
  // correct "‹ Back" that pops one level. Switching tabs — or leagues — clears it. The
  // top is the active detail; empty stack = the tab's own surface.
  const [stack, setStack] = useState([]);
  const detail = stack.length ? stack[stack.length - 1] : null;
  const [weekList, setWeekList] = useState(null);
  const [playedWeeks, setPlayedWeeks] = useState(null);   // weeks with RESULTS — the honest-depth clock
  const [asOfWeek, setAsOfWeek] = useState(null);
  const [league, setLeague] = useState(null);
  const [leagues, setLeagues] = useState(null);   // the /api/leagues catalog (a flat league list)
  const [slice, setSlice] = useState(null);       // active { leagueId, season, viewerRosterId, name, panels }
  const [switching, setSwitching] = useState(false);
  const [session, setSession] = useState(null);   // the Supabase session (P5/S1), null = signed out
  const [signInOpen, setSignInOpen] = useState(false);
  const [authReady, setAuthReady] = useState(false);   // has the stored session been resolved yet?
  const [identityEpoch, setIdentityEpoch] = useState(0);  // bumps on a real identity CHANGE → refetch
  const [sessionLost, setSessionLost] = useState(false);  // our token was rejected → say so (S2c)
  const [catalogError, setCatalogError] = useState(null); // /api/leagues failed → say so, don't spin
  // The last user id we have SEEN, not the last one we rendered. A ref, because the subscription
  // below has `[]` deps and its closure would capture `session` as null forever. `undefined` means
  // "no auth event yet" and is distinct from `null` (signed out) on purpose — see the handler.
  const lastUserId = useRef(undefined);

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
  // So the catalog now waits for `authReady`, and refetches whenever the IDENTITY changes.
  //
  // P5/S2c: "identity changed" means the USER ID changed — not "an event named SIGNED_IN arrived".
  // supabase-js reports a tab REFOCUS as SIGNED_IN, so keying off the event name meant switching
  // away and back cleared the slice and refetched the catalog: league, season, week and the whole
  // drill-down stack, gone, for a person who did nothing. Comparing ids also subsumes what the old
  // event filter was for — TOKEN_REFRESHED is the same person, and now that is a fact about the id
  // rather than a list of event names to keep in sync with the library.
  //
  // `supabase` is null when the build has no Supabase config: sign-in is then unavailable and says
  // so, and `authReady` flips immediately so the public demo still loads. Auth breaking must not
  // break the app around it — a permanently-false authReady would hang every visitor on "Loading…".
  useEffect(() => {
    if (!supabase) { setAuthReady(true); return; }
    // P5/S2b: when the server refuses our token, queries.js has already dropped it and retried
    // anonymously — but the active slice still names a league an anonymous caller cannot see, so
    // that retry 404s. Signing out properly is what actually rescues the app: the id goes to null
    // below, which clears the slice and refetches the catalog, landing on the public demo.
    //
    // P5/S2c adds the half that was missing: SAYING so. The rescue worked and was completely
    // silent — a signed-in user was dropped to the public demo with no explanation. This flag is
    // set only here, i.e. only when a token was actually PRESENT and the server rejected it (see
    // `apiGet`); a visitor who was never signed in is in a normal state, not an error state.
    setOnAuthRejected(() => { setSessionLost(true); supabase.auth.signOut(); });
    supabase.auth.getSession().then(({ data }) => {
      setAuthToken(data.session?.access_token);
      setSession(data.session ?? null);
      // Seed the identity we booted with, so the subscription below compares against it instead
      // of treating the first event as a change. Belt AND braces with the `undefined` sentinel
      // there: whichever of these two async paths lands first records the boot identity, and
      // neither refetches the catalog — the `authReady` effect already does that once.
      lastUserId.current = data.session?.user?.id ?? null;
      setAuthReady(true);
    // A rejection here would otherwise leave authReady false forever, which is the same permanent
    // "Loading…" the `!supabase` guard above exists to prevent — carry on as a visitor instead.
    }).catch(() => { lastUserId.current = null; setAuthReady(true); });
    const { data: sub } = supabase.auth.onAuthStateChange((event, next) => {
      // Unconditional, and it must stay that way: TOKEN_REFRESHED carries a fresh token roughly
      // hourly, and a token that stops being republished silently starts failing.
      setAuthToken(next?.access_token);
      setSession(next ?? null);
      if (next) setSignInOpen(false);
      if (event === 'SIGNED_IN') track('signed_in');

      const nextId = next?.user?.id ?? null;
      const first = lastUserId.current === undefined;
      const changed = !first && nextId !== lastUserId.current;
      lastUserId.current = nextId;
      // The FIRST event only records who we are. The `authReady` effect below already loads the
      // catalog once on boot, so bumping here too would just fetch it twice.
      if (!changed) return;
      if (nextId) setSessionLost(false);   // a real sign-in resolves the "we lost your session" state
      // Clear the SELECTION, not just the list. A stale `league_id`/`viewer_roster_id` left in
      // queries.js would keep riding on every request after sign-out — the previous person's
      // league still on screen, which is the bug this session exists to prevent the API version of.
      // Sign-out reaches here as a change to `null`, which is what keeps the rejected-token rescue
      // above working: it depends on this branch clearing the poisoned slice.
      setActiveSlice({});
      setSlice(null);
      setIdentityEpoch((n) => n + 1);
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
  //
  // P5/S2c: a failure here used to only console.error, which left `slice` null forever and the
  // whole app on a permanent "Loading…" — a spinner that will never resolve, describing an error
  // as progress. S2a's audit (F1) called this out as the reason the route must never 401; the
  // route holding that property is not a reason for the client to have no answer when it does not.
  useEffect(() => {
    if (!authReady) return;
    setCatalogError(null);
    loadLeagues()
      .then((data) => {
        const lgs = data.leagues || [];
        setLeagues(lgs);
        if (lgs.length) applySlice(sliceFrom(lgs[0]));
        else setCatalogError(new Error('The catalog came back empty.'));
      })
      .catch((e) => { console.error('Could not load leagues', e); setCatalogError(e); });
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

  // A league IS a catalog entry now (P5/S2e), so switching is a straight lookup by league_id —
  // no lineage indirection, and no season to default to.
  const switchLeague = (leagueId) => {
    const lg = leagues.find((l) => l.league_id === leagueId);
    if (lg) applySlice(sliceFrom(lg));
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
        onLeague={switchLeague}
        session={session}
        onSignIn={() => { track('sign_in_opened'); setSignInOpen(true); }}
        onSignOut={signOut}
      />
      {signInOpen && <SignIn onClose={() => setSignInOpen(false)} />}
      {sessionLost && (
        <SessionLost
          onSignIn={() => { track('sign_in_opened'); setSignInOpen(true); }}
          onDismiss={() => setSessionLost(false)}
        />
      )}
      <main className="gr-main">
        {catalogError ? (
          <div className="gr-view">
            <div className="gr-state error">
              Couldn’t load your leagues.
              <pre>{String(catalogError.message || catalogError)}</pre>
            </div>
          </div>
        ) : !slice || switching ? (
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
// slice too, so switching leagues remounts the surface → it reloads against the new slice.
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

function TopBar({ tab, onTab, weeks, asOfWeek, onWeek, league, leagues, slice, onLeague,
                  session, onSignIn, onSignOut }) {
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

      {/* The season switcher was removed in P5/S2e — prior seasons are corpus, not product, and
          the catalog now offers one entry per league rather than a lineage of seasons. The week
          switcher (season replay) stays. */}
      <div className="gr-controls">
        <WeekSwitcher weeks={weeks} value={asOfWeek} onChange={onWeek} />
      </div>

      <Account session={session} league={league} onSignIn={onSignIn} onSignOut={onSignOut} />
    </header>
  );
}

// The one thing S2b's rescue was missing: telling the person it happened (P5/S2c, S2a audit F1).
//
// Shown ONLY when a token was present and the server rejected it — `apiGet` distinguishes that
// from "no token was ever sent", and a visitor who was never signed in is in a normal state, not
// an error state. Deliberately a banner rather than a modal: the app underneath is working, on the
// public demo, which is the accurate thing to convey. Dismissible for the same reason.
function SessionLost({ onSignIn, onDismiss }) {
  return (
    <div className="gr-notice" role="status">
      <span className="gr-notice-text">
        We couldn’t restore your session — showing the public demo.
      </span>
      <button className="gr-notice-action" onClick={onSignIn}>Sign in again</button>
      <button className="gr-notice-close" onClick={onDismiss} aria-label="Dismiss">×</button>
    </div>
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

// The league selector — a real dropdown over whatever the caller can see (their own leagues
// first, the demo last, from /api/leagues), leading the derived format label (team count ·
// scoring · QB structure) + the user's record, all real. Keyed on `league_id` since P5/S2e: the
// catalog is flat, so a league is an entry rather than a lineage with seasons under it.
function LeagueSwitcher({ league, leagues, slice, onLeague }) {
  return (
    <div className="gr-league">
      {leagues && slice ? (
        <select
          className="gr-league-select"
          value={slice.leagueId}
          onChange={(e) => onLeague(e.target.value)}
        >
          {leagues.map((l) => (
            <option key={l.league_id} value={l.league_id}>
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
