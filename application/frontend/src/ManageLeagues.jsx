import React, { useEffect, useState } from 'react';
import { discoverLeagues, connectLeague } from './queries.js';

// "Manage Leagues" — the connect flow's front door (P5/S4c).
//
// A modal sibling of <main>, like SignIn.jsx, for the same reason: the SPA has no router (that is
// why analytics.js sends virtual pageviews), so a new surface is a piece of state, not a place.
//
// THE TITLE IS "MANAGE", NOT "IMPORT", and that is a decision about what this becomes. It is a
// management surface that currently contains one thing — linking. The list of leagues you already
// have belongs above "Link a League", and that is where removing one eventually lands (the UI
// equivalent of `users.py --revoke`). S4c does not build the list; it just does not design it out.
//
// THE VERB IS "LINK", NOT "IMPORT". S4d refreshes these weekly, so what the user sets up is an
// ongoing connection, not a one-time copy, and the copy should not tell them otherwise.
//
// The platform row is data, not markup, so a second live platform is an ADDITION rather than a
// refactor — the concrete form of "build the dimension, not the second implementation". Only
// Sleeper has an implementation behind it; the API refuses anything else, so a mistake here
// surfaces as a refusal rather than as a silent nothing.
const PLATFORMS = [
  { id: 'sleeper', label: 'sleeper', live: true },
  { id: 'espn', label: 'ESPN' },
  { id: 'yahoo', label: 'yahoo!' },
  { id: 'mfl', label: 'MFL' },
  { id: 'ffpc', label: 'FFPC' },
];

export default function ManageLeagues({ onClose, onLinked }) {
  const [platform, setPlatform] = useState('sleeper');
  const [input, setInput] = useState('');
  const [state, setState] = useState('idle');     // idle | looking | listed | linking | error
  const [found, setFound] = useState(null);       // the discovery response
  const [picked, setPicked] = useState(() => new Set());
  const [error, setError] = useState(null);

  // Switching platform throws away a list that describes a different one. Cheap, and the
  // alternative — showing Sleeper leagues under the Yahoo tab — is the kind of thing nobody
  // notices until it has been wrong for a week.
  useEffect(() => { setFound(null); setPicked(new Set()); setState('idle'); setError(null); },
    [platform]);

  const live = PLATFORMS.find((p) => p.id === platform)?.live;

  const look = async (e) => {
    e.preventDefault();
    const handle = input.trim();
    if (!handle || state === 'looking') return;
    setState('looking'); setError(null); setFound(null); setPicked(new Set());
    try {
      const data = await discoverLeagues(platform, handle);
      setFound(data);
      setState('listed');
    } catch (err) {
      setError(err.message);
      setState('error');
    }
  };

  const toggle = (id) => setPicked((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const supported = (found?.leagues || []).filter((l) => l.supported);
  const selectAll = () => setPicked(new Set(supported.map((l) => l.league_id)));

  const link = async () => {
    const ids = [...picked];
    if (!ids.length || state === 'linking') return;
    setState('linking'); setError(null);
    try {
      // One at a time, and the FIRST job is the one the progress screen follows. The queue
      // enforces one active job per (league, season) rather than one per person, so several can
      // legitimately be in flight — but a progress banner can only describe one thing, and
      // `GET /api/connect` returns the newest. Linking a pile at once is not what this is for.
      let first = null;
      for (const id of ids) {
        const job = await connectLeague(platform, found?.handle || null, id);
        first = first || job;
      }
      onLinked(first);
    } catch (err) {
      setError(err.message);
      setState('error');
    }
  };

  return (
    <div className="gr-overlay" role="dialog" aria-modal="true" aria-labelledby="manage-title">
      <div className="gr-manage">
        <button className="gr-signin-x" onClick={onClose} aria-label="Close">×</button>
        <h2 className="gr-signin-title" id="manage-title">Manage Leagues</h2>

        <h3 className="gr-manage-section">Link a League</h3>

        <div className="gr-manage-tabs" role="tablist" aria-label="Platform">
          {PLATFORMS.map((p) => (
            <button
              key={p.id}
              role="tab"
              aria-selected={platform === p.id}
              className={`gr-manage-tab ${platform === p.id ? 'active' : ''} ${p.live ? '' : 'soon'}`}
              onClick={() => setPlatform(p.id)}
              title={p.live ? undefined : 'Not supported yet'}
            >
              {p.label}
            </button>
          ))}
        </div>

        {!live ? (
          // An honest unavailable state rather than a form that submits into a refusal. The tab
          // is still selectable on purpose: it says what is coming, which is the whole reason the
          // row has five entries while one platform works.
          <p className="gr-manage-note">
            {PLATFORMS.find((p) => p.id === platform)?.label} isn&rsquo;t supported yet —
            Sleeper is the one we can read today.
          </p>
        ) : (
          <>
            <form className="gr-manage-form" onSubmit={look}>
              <input
                className="gr-signin-input gr-manage-input"
                type="text"
                autoComplete="off"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck="false"
                placeholder="Username or League ID…"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                autoFocus
              />
              <button className="gr-signin-go gr-manage-go" type="submit"
                      disabled={state === 'looking'}>
                {state === 'looking' ? 'Looking…' : 'Submit'}
              </button>
            </form>
            <p className="gr-manage-note">
              Enter your Sleeper username to see your leagues, or a league ID to link one directly.
            </p>
          </>
        )}

        {error && <p className="gr-signin-err">{error}</p>}

        {state === 'listed' && found && <Results found={found} picked={picked} toggle={toggle} />}

        {state === 'listed' && supported.length > 1 && (
          <button className="gr-manage-all" onClick={selectAll}>
            Select all {supported.length} supported
          </button>
        )}

        {(state === 'listed' || state === 'linking') && picked.size > 0 && (
          <button className="gr-signin-go gr-manage-link" onClick={link}
                  disabled={state === 'linking'}>
            {state === 'linking'
              ? 'Linking…'
              : `Link ${picked.size} league${picked.size === 1 ? '' : 's'}`}
          </button>
        )}
      </div>
    </div>
  );
}

// The list, with unsupported leagues GREYED AND LABELLED rather than hidden or silently dropped.
//
// Two things this is deliberately not. It is not a bulk import: V1 is redraft / PPR / half, and a
// handle here returned ten leagues of which one qualified — a blind "import everything" would have
// enqueued nine jobs whose only possible outcome is a refusal, which teaches somebody that the
// product usually says no. And it is NOT a security control (standing rule 11): the real gates are
// on the worker, they raise, and a disabled button in a React app is a suggestion.
function Results({ found, picked, toggle }) {
  if (!found.platform_user_id && !found.leagues.length) {
    return (
      <p className="gr-manage-note gr-manage-empty">
        Sleeper doesn&rsquo;t know that username. Check the spelling — or paste a league ID
        instead.
      </p>
    );
  }
  if (!found.leagues.length) {
    return (
      <p className="gr-manage-note gr-manage-empty">
        No leagues found for that account.
      </p>
    );
  }
  return (
    <ul className="gr-manage-list">
      {found.leagues.map((l) => (
        <li key={`${l.season}:${l.league_id}`}
            className={`gr-manage-row ${l.supported ? '' : 'unsupported'}`}>
          <label>
            <input
              type="checkbox"
              checked={picked.has(l.league_id)}
              disabled={!l.supported}
              onChange={() => toggle(l.league_id)}
            />
            <span className="gr-manage-name">{l.name}</span>
            <span className="gr-manage-meta">
              {l.season}{l.total_rosters ? ` · ${l.total_rosters} teams` : ''}
            </span>
          </label>
          {l.reason && <span className="gr-manage-reason">{l.reason}</span>}
        </li>
      ))}
    </ul>
  );
}
