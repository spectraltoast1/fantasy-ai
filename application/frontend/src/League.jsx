import React, { useEffect, useState } from 'react';
import { loadLeague, loadPositionalTalent, POS } from './queries.js';
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
            <PostureMap data={data} onOpenTeam={onOpenTeam} />
            <PositionalTalent onOpenTeam={onOpenTeam} />
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

// Posture Map — the luck-vs-performance quadrant (contract §4.2 + §5). X = standing
// (playoff odds), Y = true record (all-play %, inverted so strong sits at top). The
// diagonal is the "on pace" line: above it a roster performs above its standing (buy),
// below it a roster is standing above its performance (sell). One dot per team, colored by
// the same posture read as the standings; a dot drills to Team detail.
function PostureMap({ data, onOpenTeam }) {
  const dots = data.standings.filter((t) => t.playoffPct != null && t.posture);
  return (
    <div className="lg-panel">
      <div className="lg-panel-head">
        <span className="lg-panel-title">Posture Map</span>
        <span className="lg-panel-note">playoff odds × true record</span>
      </div>
      <div className="lg-map-well">
        <svg className="lg-map-svg" viewBox="0 0 100 100" preserveAspectRatio="none">
          <polygon points="9,9 91,9 9,91" fill="color-mix(in srgb, var(--unlucky) 6%, transparent)" />
          <polygon points="91,9 91,91 9,91" fill="color-mix(in srgb, var(--ridingluck) 5%, transparent)" />
          <line x1="9" y1="91" x2="91" y2="9" stroke="var(--faint)" strokeWidth="1" strokeDasharray="3 3" vectorEffect="non-scaling-stroke" />
        </svg>
        <div className="lg-map-onpace mono">ON PACE</div>
        <div className="lg-map-corner tl mono" style={{ color: 'var(--unlucky)' }}>◤ UNLUCKY · buy</div>
        <div className="lg-map-corner tr mono" style={{ color: 'var(--contender)' }}>CONTENDER ◥</div>
        <div className="lg-map-corner bl mono" style={{ color: 'var(--rebuild)' }}>◣ REBUILD</div>
        <div className="lg-map-corner br mono" style={{ color: 'var(--ridingluck)' }}>RIDING LUCK · sell ◢</div>
        <div className="lg-map-axis mono">STANDING · PLAYOFF ODDS →</div>
        {dots.map((t) => (
          <div
            key={t.rosterId}
            className="lg-map-dot"
            style={{ left: `${9 + (t.playoffPct / 100) * 82}%`, top: `${9 + ((100 - t.allPlayPct) / 100) * 82}%` }}
            onClick={() => onOpenTeam?.(t.rosterId)}
            title={`${t.name} · ${Math.round(t.playoffPct)}% odds · ${Math.round(t.allPlayPct)}% all-play`}
          >
            <span
              className={`lg-map-pt ${t.isMe ? 'me' : ''}`}
              style={{ background: t.posture.tone, boxShadow: `0 0 0 3px ${ring(t.posture.tone)}` }}
            />
            <span className="lg-map-short mono">{shortName(t.name)}</span>
          </div>
        ))}
      </div>
      <p className="lg-map-cap">
        Off-diagonal is the read: <span style={{ color: 'var(--unlucky-l)' }}>top-left</span> wins less
        than it should (buy), <span style={{ color: 'var(--ridingluck)' }}>bottom-right</span> wins more
        than it should (sell).
      </p>
    </div>
  );
}

// Positional Talent — per position, teams ranked by the Market VOR they hold there (a
// surplus is trade capital, a gap is a target). Self-contained (its own read): Market VOR
// is the current market and does not replay with the week. Cross-time POC today, flagged.
// The Waiver Wire strip is deferred — it needs a free-agent pool entity (none in V1).
function PositionalTalent({ onOpenTeam }) {
  const [tal, setTal] = useState(null);
  const [pos, setPos] = useState('RB');

  useEffect(() => {
    let live = true;
    loadPositionalTalent()
      .then((t) => live && setTal(t))
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);

  const list = tal?.byPos[pos] ?? [];
  const max = list.length ? Math.max(0.1, list[0].vor) : 1;

  return (
    <div className="lg-panel">
      <div className="lg-panel-head">
        <span className="lg-panel-title">Positional Talent</span>
        <span className="lg-panel-note">market VOR by team</span>
      </div>
      <div className="lg-pt-toggle">
        {POS.map((p) => (
          <button key={p} className={pos === p ? 'active' : ''} onClick={() => setPos(p)}>
            {p}
          </button>
        ))}
      </div>
      {tal == null ? (
        <div className="gr-state">Loading…</div>
      ) : (
        <>
          {list.map((x) => (
            <div
              key={x.rosterId}
              className="lg-pt-row"
              style={{ background: x.isMe ? 'var(--violet-wash)' : 'transparent' }}
              onClick={() => onOpenTeam?.(x.rosterId)}
            >
              <span className="lg-pt-rank mono">{x.rank}</span>
              <span className="lg-pt-name">
                {x.name}
                {x.isMe ? <span className="pl-you">YOU</span> : null}
              </span>
              <div className="lg-pt-bar-wrap">
                <div className="lg-pt-bar">
                  <div className="lg-pt-fill" style={{ width: `${Math.max(2, (x.vor / max) * 100)}%` }} />
                </div>
                <span className="lg-pt-val mono">{x.vor.toFixed(1)}</span>
              </div>
            </div>
          ))}
          {tal.isCrossTime ? (
            <p className="lg-pt-poc">
              Market VOR is the current market × this frozen roster — a cross-time POC, not a live read.
            </p>
          ) : null}
          {/* Waiver Wire strip deferred: no free-agent pool entity in V1 (same block as the
              Players "Available" filter). */}
          <div className="lg-pt-waiver">
            <div className="lg-pt-waiver-label gr-label">Waiver Wire</div>
            <p>Best-available + THIN/STREAMABLE/DEEP needs the free-agent pool read (deferred in V1).</p>
          </div>
        </>
      )}
    </div>
  );
}

// Posture chips tint at ~13% of the tone (README color roles).
const chipBg = (tone) => `color-mix(in srgb, ${tone} 13%, transparent)`;
// Dot ring — the tone at low alpha.
const ring = (tone) => `color-mix(in srgb, ${tone} 18%, transparent)`;

// A compact scatter label from a team name (drop a leading "Team ", first word, ≤6 chars).
function shortName(name) {
  const n = String(name).replace(/^team\s+/i, '').trim();
  return (n.split(/\s+/)[0] || n).slice(0, 6).toUpperCase();
}

// Magic number → a manager-facing line from bracket_odds' magic_wins + remaining_games.
function magicLine(magicWins, remainingGames) {
  if (magicWins == null || remainingGames == null) return null;
  if (magicWins <= 0) return 'Clinched a spot';
  if (magicWins > remainingGames) return 'Needs help to clinch';
  if (magicWins === remainingGames) return 'Must win out';
  return `Clinch in ${magicWins} of next ${remainingGames}`;
}
