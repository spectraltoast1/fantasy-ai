import React, { useEffect, useState } from 'react';
import { loadMatchupDetail } from './queries.js';
import { RangeGauge } from './charts.jsx';
import { POS_COLORS } from './posColors.js';

// Matchup detail (§4.3): head-to-head win prob, each team's Score Range (Σ starters' 25–75 band on a
// shared scale — overlap = upset room), per-starter range gauges (median tick in 25–75, wider = more
// volatile), and the starters+bench split. Pure renderer off loadMatchupDetail. Rendered both in the
// web two-pane (Matchups, right side) and as a stack detail (from Team detail's this-week bar), so it
// fills whatever container holds it. Teams arrive "you" first.
export default function MatchupDetail({ matchupId, asOfWeek }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let live = true;
    setData(null);
    setErr(null);
    loadMatchupDetail(matchupId, asOfWeek)
      .then((d) => live && setData(d))
      .catch((e) => live && setErr(e));
    return () => {
      live = false;
    };
  }, [matchupId, asOfWeek]);

  if (err) return <div className="gr-state error">Could not load matchup.<pre>{String(err.message ?? err)}</pre></div>;
  if (!data) return <div className="gr-state">Loading matchup…</div>;

  const [a, b] = data.teams;
  // Shared scale for the two team Score Range bars (so overlap reads true).
  const teamLo = Math.min(a.range.p25, b.range.p25);
  const teamHi = Math.max(a.range.p75, b.range.p75);
  // Shared scale for every per-player gauge (all shown players, both teams) so magnitudes compare.
  const shown = [...a.starters, ...a.bench, ...b.starters, ...b.bench].filter((p) => p.p25 != null);
  const pLo = shown.length ? Math.min(...shown.map((p) => p.p25)) : 0;
  const pHi = shown.length ? Math.max(...shown.map((p) => p.p75)) : 1;

  return (
    <div className="md">
      <div className="md-head">
        <TeamHead t={a} />
        <div className="md-vs gr-label">Wk {data.targetWeek}</div>
        <TeamHead t={b} align="right" />
      </div>

      {/* Score Range — both teams on one scale; overlap = upset room. */}
      <section className="md-section">
        <div className="md-h3 gr-label">Score Range · 25–75</div>
        <RangeRow t={a} lo={teamLo} hi={teamHi} />
        <RangeRow t={b} lo={teamLo} hi={teamHi} />
      </section>

      {/* Lineups — per-starter median + 25–75 gauge, then bench. */}
      <div className="md-rosters">
        <TeamRoster t={a} lo={pLo} hi={pHi} />
        <TeamRoster t={b} lo={pLo} hi={pHi} />
      </div>
    </div>
  );
}

function TeamHead({ t, align }) {
  return (
    <div className={`md-team-head ${align === 'right' ? 'r' : ''} ${t.isMe ? 'me' : ''}`}>
      <div className="md-team-wp mono">{t.winProb}%</div>
      <div className="md-team-name">
        {t.name}
        {t.isMe ? <span className="pl-you">YOU</span> : null}
      </div>
      <div className="md-team-rec mono">{t.record} · proj {t.proj.toFixed(1)}</div>
    </div>
  );
}

function RangeRow({ t, lo, hi }) {
  return (
    <div className="md-range-row">
      <span className="md-range-name">{t.name}</span>
      <div className="md-range-bar">
        <RangeGauge
          lo={t.range.p25}
          md={t.range.p50}
          hi={t.range.p75}
          min={lo}
          max={hi}
          color={t.isMe ? 'var(--violet)' : 'var(--steel-l)'}
          height={14}
        />
      </div>
      <span className="md-range-val mono">{Math.round(t.range.p50)}</span>
    </div>
  );
}

function TeamRoster({ t, lo, hi }) {
  return (
    <div className="md-col">
      <div className="md-col-head">
        <span className="md-col-name">{t.name}</span>
        <span className="md-col-proj mono">{t.proj.toFixed(1)}</span>
      </div>
      <PlayerGroup title="Starters" players={t.starters} lo={lo} hi={hi} isMe={t.isMe} />
      <PlayerGroup title="Bench" players={t.bench} lo={lo} hi={hi} isMe={t.isMe} bench />
    </div>
  );
}

function PlayerGroup({ title, players, lo, hi, isMe, bench }) {
  if (!players.length) return null;
  return (
    <div className="md-group">
      <div className="md-group-title gr-label">{title}</div>
      {players.map((p) => (
        <div className="md-prow" key={p.sleeperId}>
          <span className="md-prow-pos" style={{ color: POS_COLORS[p.pos] }}>{p.pos}</span>
          <span className="md-prow-name">{p.name}</span>
          <span className="md-prow-proj mono">{p.proj != null ? p.proj.toFixed(1) : '—'}</span>
          <div className="md-prow-gauge">
            {p.p25 != null ? (
              <RangeGauge
                lo={p.p25}
                md={p.p50}
                hi={p.p75}
                min={lo}
                max={hi}
                color={bench ? 'var(--faint-2)' : isMe ? 'var(--violet)' : 'var(--steel-l)'}
                height={10}
              />
            ) : null}
          </div>
        </div>
      ))}
    </div>
  );
}
