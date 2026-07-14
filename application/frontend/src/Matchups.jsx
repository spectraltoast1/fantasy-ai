import React, { useEffect, useState } from 'react';
import { loadMatchups } from './queries.js';
import { WinProbBar } from './charts.jsx';
import MatchupDetail from './MatchupDetail.jsx';
import useIsMobile from './useIsMobile.js';

// Matchups surface — the upcoming week's projected slate (§4.3). As-of week N this shows week N+1
// (the app is a season replay). Web is a persistent two-pane: the slate list (left, your game pinned
// + highlighted) and the selected game's breakdown (right), your game selected by default. Mobile is
// a tap-through: the slate only, each card drilling into the full-screen matchup detail (the App
// stack `matchup` type). Pure renderer off loadMatchups; win prob mirrors the backend bracket sim.
export default function Matchups({ asOfWeek, onOpenMatchup }) {
  const isMobile = useIsMobile();
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [sel, setSel] = useState(null); // selected matchup_id (web two-pane only)

  useEffect(() => {
    let live = true;
    setData(null);
    setErr(null);
    loadMatchups(asOfWeek)
      .then((d) => {
        if (!live) return;
        setData(d);
        setSel(d.myGameId ?? d.games[0]?.matchupId ?? null); // your game by default
      })
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

  // One slate of cards, reused by both layouts. On mobile a card drills into the full-screen detail;
  // on web it selects the two-pane's right side (and shows the selected highlight).
  const slate =
    data && !data.empty && data.games.length ? (
      <div className="mu-slate">
        {data.games.map((g) => (
          <button
            key={g.matchupId}
            className={`mu-card ${g.isMine ? 'mine' : ''} ${!isMobile && g.matchupId === sel ? 'sel' : ''}`}
            onClick={() => (isMobile ? onOpenMatchup?.(g.matchupId) : setSel(g.matchupId))}
          >
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
          </button>
        ))}
      </div>
    ) : null;

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
          analytic head-to-head from the same score distribution the playoff sim uses.{' '}
          {isMobile ? 'Tap' : 'Select'} a game for its full breakdown.
        </div>
      </div>

      {data == null ? (
        <div className="gr-state">Loading matchups…</div>
      ) : data.empty || !data.games.length ? (
        <div className="mu-empty">No upcoming games — the regular season is complete.</div>
      ) : isMobile ? (
        slate
      ) : (
        <div className="mu-layout">
          {slate}
          <div className="mu-detail-pane">
            {sel != null ? <MatchupDetail matchupId={sel} asOfWeek={asOfWeek} /> : null}
          </div>
        </div>
      )}
    </div>
  );
}
