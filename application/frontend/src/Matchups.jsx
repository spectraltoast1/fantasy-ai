import React, { useEffect, useState } from 'react';
import { loadMatchups } from './queries.js';
import { WinProbBar } from './charts.jsx';

// Matchups surface — the upcoming week's projected head-to-head slate (§4.3). As-of week N this
// shows week N+1 (the app is a season replay): each game's two teams, records, projected totals
// (optimal-lineup μ) and analytic win prob. Your game is pinned first + violet-washed. Pure
// renderer — everything comes assembled from loadMatchups; win prob mirrors the backend bracket
// sim (see queries.js). Card drill-in to the matchup detail is wired in the next slice.
export default function Matchups({ asOfWeek }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let live = true;
    setData(null);
    setErr(null);
    loadMatchups(asOfWeek)
      .then((d) => live && setData(d))
      .catch((e) => live && setErr(e));
    return () => {
      live = false;
    };
  }, [asOfWeek]);

  if (err) {
    return (
      <div className="gr-state error">
        Could not load matchups.
        <pre>{String(err.message ?? err)}</pre>
      </div>
    );
  }

  return (
    <div className="gr-page mu-page">
      <div className="gr-page-head">
        <h1>Matchups</h1>
        <div className="sub">
          {data?.targetWeek ? (
            <>
              The <strong>Week {data.targetWeek}</strong> slate, projected.{' '}
            </>
          ) : null}
          Totals are each team's <strong>optimal-lineup</strong> projection; win probability is the
          analytic head-to-head from the same score distribution the playoff sim uses. Your game is
          pinned first.
        </div>
      </div>

      {data == null ? (
        <div className="gr-state">Loading matchups…</div>
      ) : data.empty || !data.games.length ? (
        <div className="mu-empty">No upcoming games — the regular season is complete.</div>
      ) : (
        <div className="mu-slate">
          {data.games.map((g) => (
            <div key={g.matchupId} className={`mu-card ${g.isMine ? 'mine' : ''}`}>
              <div className="mu-card-head">
                <span className="mu-card-tag gr-label">{g.isMine ? 'Your matchup' : 'Matchup'}</span>
              </div>
              <div className="mu-teams">
                {g.teams.map((t) => (
                  <div key={t.rosterId} className={`mu-team ${t.isMe ? 'me' : ''}`}>
                    <div className="mu-team-id">
                      <span className="mu-team-name">{t.name}</span>
                      {t.isMe ? <span className="pl-you">YOU</span> : null}
                      <span className="mu-team-rec mono">{t.record}</span>
                    </div>
                    <span className="mu-team-proj mono">{t.proj != null ? t.proj.toFixed(1) : '—'}</span>
                    <span className="mu-team-wp mono">{t.winProb != null ? `${t.winProb}%` : '—'}</span>
                  </div>
                ))}
              </div>
              <div className="mu-winprob">
                <WinProbBar teams={g.teams} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
