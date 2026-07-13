import React, { useEffect, useState } from 'react';
import { loadLeague } from './queries.js';
import { Sparkline } from './charts.jsx';
import { Gate, REGIME } from './readiness.jsx';

// League surface — "whole league at a glance". A full-width Your Race band over a
// 3-column dashboard: Playoff Picture · Posture Map · Positional Talent. Pure renderer:
// everything comes assembled from loadLeague (which reuses loadStandings — one source for
// records/odds/posture across Teams and League). Rows/dots drill to Team detail.

export default function League({ asOfWeek, onOpenTeam }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let live = true;
    setData(null);
    setErr(null);
    loadLeague(asOfWeek)
      .then((d) => live && setData(d))
      .catch((e) => live && setErr(e));
    return () => {
      live = false;
    };
  }, [asOfWeek]);

  if (err) {
    return (
      <div className="gr-state error">
        Could not load the league.
        <pre>{String(err.message ?? err)}</pre>
      </div>
    );
  }

  return (
    <div className="gr-page lg-page">
      <div className="gr-page-head">
        <h1>League</h1>
        <div className="sub">
          The whole league at a glance — your playoff race, the bracket-sim picture, the
          luck-vs-performance posture map, and where each position's talent sits.
        </div>
      </div>

      {data == null ? (
        <div className="gr-state">Loading league…</div>
      ) : (
        <Gate regime={REGIME.POINT_IN_TIME} weeks={asOfWeek ?? 0} label="League">
          <YourRace data={data} onOpenTeam={onOpenTeam} />
          <div className="lg-dash">
            <PlayoffPicture data={data} onOpenTeam={onOpenTeam} />
          </div>
        </Gate>
      )}
    </div>
  );
}

// Your Race — the manager's POV band: playoff chance + posture, seed & cut, magic number.
// The this-week head-to-head + win% is deferred to the Matchups slice (its win prob is a
// bracket-sim per-matchup read that isn't surfaced yet) — an honest note, not a fake bar.
function YourRace({ data, onOpenTeam }) {
  const me = data.me;
  if (!me) return null;
  return (
    <div className="lg-race">
      <div className="lg-race-odds" onClick={() => onOpenTeam?.(me.rosterId)}>
        <div className="lg-race-label gr-label">Your Race</div>
        <div className="lg-race-big">
          <span className="lg-race-pct mono">{me.playoffPct != null ? `${Math.round(me.playoffPct)}%` : '—'}</span>
          {me.posture ? (
            <span className="lg-race-posture" style={{ color: me.posture.tone, background: chipBg(me.posture.tone) }}>
              {me.posture.label}
            </span>
          ) : null}
        </div>
        <div className="lg-race-sub gr-label">Playoff chance</div>
      </div>

      <div className="lg-race-div" />

      <div className="lg-race-seed">
        <div className="lg-race-seedn">Seed {me.seed ?? '—'} of {data.nTeams}</div>
        <div className="lg-race-cut mono">top {data.playoffCut ?? '—'} advance</div>
        <div className="lg-race-magic mono">{magicLine(me.magicWins, me.remainingGames) ?? '—'}</div>
      </div>

      <div className="lg-race-div" />

      {/* This-week head-to-head + win% — deferred to the Matchups slice (bracket-sim win prob). */}
      <div className="lg-race-week">
        <div className="lg-race-weeklabel gr-label">This week</div>
        <p className="lg-race-defer">
          Your head-to-head + win probability land with the Matchups slice (off the bracket
          sim). Not shown here yet.
        </p>
      </div>
    </div>
  );
}

// Playoff Picture — the 10 teams ranked by playoff odds (loadStandings already returns
// them in that order), with a magic-number subline, the weekly odds trendline, and a
// PLAYOFF LINE drawn after the real cut (seed = playoffCut).
function PlayoffPicture({ data, onOpenTeam }) {
  const { standings, playoffCut } = data;
  return (
    <div className="lg-panel">
      <div className="lg-panel-head">
        <span className="lg-panel-title">Playoff Picture</span>
        <span className="lg-panel-note">10k-run bracket sim</span>
      </div>
      {standings.map((t) => (
        <React.Fragment key={t.rosterId}>
          <div
            className="lg-pp-row"
            style={{ background: t.isMe ? 'var(--violet-wash)' : 'transparent' }}
            onClick={() => onOpenTeam?.(t.rosterId)}
          >
            <span className="lg-pp-rank mono">{t.rank}</span>
            <div className="lg-pp-id">
              <span className="lg-pp-name">
                {t.name}
                {t.isMe ? <span className="pl-you">YOU</span> : null}
              </span>
              <span className="lg-pp-magic mono">{magicLine(t.magicWins, t.remainingGames) ?? ''}</span>
            </div>
            <div className="lg-pp-odds">
              <Sparkline values={t.oddsSeries} color={t.posture ? t.posture.tone : 'var(--violet)'} width={54} height={16} />
              <span className="lg-pp-pct mono">{t.playoffPct != null ? `${Math.round(t.playoffPct)}%` : '—'}</span>
            </div>
          </div>
          {playoffCut != null && t.rank === playoffCut ? (
            <div className="lg-pp-line">
              <span />
              <span className="lg-pp-line-label mono">Playoff line</span>
              <span />
            </div>
          ) : null}
        </React.Fragment>
      ))}
    </div>
  );
}

// Posture chips tint at ~13% of the tone (README color roles).
const chipBg = (tone) => `color-mix(in srgb, ${tone} 13%, transparent)`;

// Magic number → a manager-facing line from bracket_odds' magic_wins + remaining_games.
function magicLine(magicWins, remainingGames) {
  if (magicWins == null || remainingGames == null) return null;
  if (magicWins <= 0) return 'Clinched a spot';
  if (magicWins > remainingGames) return 'Needs help to clinch';
  if (magicWins === remainingGames) return 'Must win out';
  return `Clinch in ${magicWins} of next ${remainingGames}`;
}
