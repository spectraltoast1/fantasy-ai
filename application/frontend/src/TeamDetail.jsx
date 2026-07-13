import React, { useEffect, useState } from 'react';
import { loadTeamDetail } from './queries.js';
import { TrendLine, DepthBar, WinProbBar } from './charts.jsx';
import { POS_COLORS } from './posColors.js';
import { IconShieldCheck } from './icons.jsx';

// Team detail (drill-down from the standings). Consumes the assembled object from
// queries.loadTeamDetail: 4 stat blocks, the this-week matchup bar, positional depth per
// QB/RB/WR/TE, and the roster (starters/bench) with a PROD/MKT VOR toggle + trend sparkline per
// player. Pure renderer. The this-week bar drills into the full matchup detail (Matchups slice).

export default function TeamDetail({ rosterId, asOfWeek, onOpenPlayer, onOpenDossier, onOpenMatchup }) {
  const [team, setTeam] = useState(null);
  const [err, setErr] = useState(null);
  const [metric, setMetric] = useState('prod'); // 'prod' | 'mkt'

  useEffect(() => {
    let live = true;
    setTeam(null);
    setErr(null);
    loadTeamDetail(rosterId, asOfWeek)
      .then((t) => live && setTeam(t))
      .catch((e) => live && setErr(e));
    return () => {
      live = false;
    };
  }, [rosterId, asOfWeek]);

  if (err) return <div className="gr-state error">Could not load team.<pre>{String(err.message ?? err)}</pre></div>;
  if (!team) return <div className="gr-state">Loading…</div>;

  const s = team.stats;
  return (
    <div className="td">
      <header className="td-head">
        <div>
          <h1 className="td-name">{team.name}</h1>
          <div className="td-meta">
            <span className="mono">{team.owner ?? '—'}</span>
            {team.onYours ? <span className="pl-you">YOU</span> : null}
          </div>
        </div>
        <button className="td-dossier" onClick={() => onOpenDossier?.(team.rosterId)}>
          <IconShieldCheck size={15} /> Manager Dossier
        </button>
      </header>

      {/* 4 stat blocks. */}
      <div className="td-stats">
        <Stat label="Record" value={s.record} />
        <Stat label="True Rec" value={s.trueRec} sub="all-play" />
        <Stat label="Playoff %" value={s.playoffPct != null ? `${Math.round(s.playoffPct)}%` : '—'} sub={s.seed != null ? `seed ${s.seed}` : null} />
        <Stat label="Pts / Wk" value={s.ptsWk != null ? s.ptsWk.toFixed(1) : '—'} />
      </div>

      {/* This-week matchup bar — the team's upcoming projected game; drills into the full detail. */}
      <section className="td-section">
        <div className="td-h3">
          This week{team.thisWeek ? ` · Wk ${team.thisWeek.targetWeek}` : ''}
        </div>
        {team.thisWeek ? (
          <button className="td-matchup" onClick={() => onOpenMatchup?.(team.thisWeek.matchupId)}>
            <div className="td-matchup-side">
              <span className="td-matchup-name">{team.name}</span>
              <span className="td-matchup-nums mono">
                <span className="td-matchup-wp">{team.thisWeek.me.winProb}%</span>
                <span className="td-matchup-proj">proj {team.thisWeek.me.proj.toFixed(1)}</span>
              </span>
            </div>
            <WinProbBar
              teams={[
                { winProb: team.thisWeek.me.winProb, isMe: team.onYours },
                { winProb: team.thisWeek.opp.winProb, isMe: false },
              ]}
              height={10}
            />
            <div className="td-matchup-side r">
              <span className="td-matchup-name">{team.thisWeek.opp.name}</span>
              <span className="td-matchup-nums mono">
                <span className="td-matchup-wp">{team.thisWeek.opp.winProb}%</span>
                <span className="td-matchup-proj">proj {team.thisWeek.opp.proj.toFixed(1)}</span>
              </span>
            </div>
          </button>
        ) : (
          <p className="td-defer">No upcoming game — the regular season is complete.</p>
        )}
      </section>

      {/* Positional Depth. */}
      <section className="td-section">
        <div className="td-h3">Positional Depth</div>
        {team.depth.length ? (
          <div className="td-depth">
            {team.depth.map((d) => (
              <div className="td-depth-row" key={d.position}>
                <span className="td-depth-pos" style={{ color: POS_COLORS[d.position] }}>{d.position}</span>
                <div className="td-depth-bar">
                  <DepthBar pos={d.spectrumPos} />
                </div>
                <span className={`td-depth-shape shape-${d.shape.toLowerCase()}`}>{d.shape}</span>
                <span className="td-depth-rank mono">{d.rank} of {d.nTeams}</span>
                <span className="td-depth-val mono">{d.starterValue.toFixed(1)}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="pc-empty">No positional depth for this team yet.</div>
        )}
      </section>

      {/* Roster with PROD/MKT toggle. */}
      <section className="td-section">
        <div className="td-roster-head">
          <div className="td-h3" style={{ margin: 0 }}>Roster</div>
          <div className="td-toggle">
            <button className={metric === 'prod' ? 'active' : ''} onClick={() => setMetric('prod')}>PROD VOR</button>
            <button className={metric === 'mkt' ? 'active' : ''} onClick={() => setMetric('mkt')}>MKT VOR</button>
          </div>
        </div>
        {metric === 'mkt' ? (
          <p className="td-poc">MKT VOR is the current market × this frozen roster — a cross-time POC, not a live call.</p>
        ) : null}

        <RosterGroup title="Starters" players={team.roster.starters} metric={metric} onOpenPlayer={onOpenPlayer} />
        <RosterGroup title="Bench" players={team.roster.bench} metric={metric} onOpenPlayer={onOpenPlayer} />
      </section>
    </div>
  );
}

function Stat({ label, value, sub }) {
  return (
    <div className="td-stat">
      <span className="td-stat-label gr-label">{label}</span>
      <span className="td-stat-value">{value}</span>
      {sub ? <span className="td-stat-sub">{sub}</span> : null}
    </div>
  );
}

function RosterGroup({ title, players, metric, onOpenPlayer }) {
  if (!players.length) return null;
  return (
    <div className="td-rgroup">
      <div className="td-rgroup-title gr-label">{title}</div>
      {players.map((p) => {
        const m = metric === 'prod' ? p.prod : p.mkt;
        return (
          <div className="td-prow" key={p.sleeperId} onClick={() => onOpenPlayer?.(p.sleeperId)}>
            <span className="td-prow-pos" style={{ color: POS_COLORS[p.pos] }}>{p.pos}</span>
            <div className="td-prow-id">
              <span className="td-prow-name">{p.name}</span>
              <span className="td-prow-team mono">{p.nflTeam ?? '—'}</span>
            </div>
            <div className="td-prow-trend">
              <TrendLine
                values={m.series}
                valueStr={m.value != null ? m.value.toFixed(1) : '—'}
                deltaStr={m.delta != null ? (m.delta >= 0 ? '+' : '') + m.delta.toFixed(1) : null}
                up={m.up}
                muted={metric === 'mkt'}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
