import React, { useEffect, useState } from 'react';
import { loadPowerRankings, loadTeamDetails, POS } from './queries.js';
import { POS_COLORS } from './posColors.js';

// League tab: league-wide views. Today that's Power Rankings (cards + drill-down
// drawer); manager dossiers and other league overviews will join it here.
export default function LeaguePanel() {
  const [data, setData] = useState(null);
  const [details, setDetails] = useState(null);
  const [selected, setSelected] = useState(null); // rosterId of the open drawer
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([loadPowerRankings(), loadTeamDetails()])
      .then(([rankings, detail]) => {
        setData(rankings);
        setDetails(detail);
      })
      .catch((e) => {
        console.error(e);
        setError(e.message ?? String(e));
      });
  }, []);

  if (error) {
    return (
      <div className="state error">
        <h2>Couldn’t load data</h2>
        <pre>{error}</pre>
      </div>
    );
  }
  if (!data) {
    return <div className="state">Loading season data via DuckDB…</div>;
  }

  const weekLabel =
    data.weeks.length > 1
      ? `Weeks ${data.weeks[0]}–${data.weeks[data.weeks.length - 1]}`
      : `Week ${data.weeks[0]}`;

  return (
    <div className="page">
      <header className="page-head">
        <h1>Power Rankings</h1>
        <div className="sub">
          {data.season} · {weekLabel} · {data.teams.length} teams
        </div>
      </header>

      <div className="rankings">
        {data.teams.map((t) => (
          <TeamCard
            key={t.rosterId}
            team={t}
            maxStarterTotal={data.maxStarterTotal}
            onOpen={() => setSelected(t.rosterId)}
          />
        ))}
      </div>

      {selected != null && (
        <TeamDrawer
          team={data.teams.find((t) => t.rosterId === selected)}
          detail={details?.[selected]}
          onClose={() => setSelected(null)}
        />
      )}

      <footer className="legend">
        {POS.map((p) => (
          <span key={p} className="legend-item">
            <span className="swatch" style={{ background: POS_COLORS[p] }} />
            {p}
          </span>
        ))}
        <span className="legend-note">segments = avg starter pts/wk by position</span>
      </footer>
    </div>
  );
}

function TeamCard({ team, maxStarterTotal, onOpen }) {
  const consistency =
    team.cv < 0.15 ? 'Steady' : team.cv < 0.28 ? 'Average' : 'Volatile';
  const stackWidthPct = (team.starterTotal / maxStarterTotal) * 100;

  return (
    <div
      className="card"
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onOpen())}
    >
      <div className="rank">{team.rank}</div>

      <div className="card-body">
        <div className="card-top">
          <div className="team-name">{team.name}</div>
          <div className="record">
            {team.wins}–{team.losses}
          </div>
        </div>

        <div className="metrics">
          <div className="ppg">
            <span className="big">{team.avgPts.toFixed(1)}</span>
            <span className="unit">PPG</span>
          </div>
          <span className={`badge c-${consistency.toLowerCase()}`}>
            {consistency}
            <span className="badge-sub">±{team.std.toFixed(1)}</span>
          </span>
        </div>

        {/* Positional composition: one stacked bar, width relative to the league's strongest starters. */}
        <div className="stack-wrap" style={{ width: `${stackWidthPct}%` }}>
          <div className="stack">
            {POS.map((p) => {
              const v = team.breakdown[p] ?? 0;
              const pct = team.starterTotal ? (v / team.starterTotal) * 100 : 0;
              return (
                <div
                  key={p}
                  className="seg"
                  style={{ width: `${pct}%`, background: POS_COLORS[p] }}
                  title={`${p}: ${v.toFixed(1)} pts/wk`}
                />
              );
            })}
          </div>
        </div>
        <div className="pos-values">
          {POS.map((p) => (
            <span key={p} className="pv">
              <span className="pv-dot" style={{ background: POS_COLORS[p] }} />
              {p} {(team.breakdown[p] ?? 0).toFixed(1)}
            </span>
          ))}
        </div>
      </div>

      <div className="power">
        <div className="power-score">{team.powerScore}</div>
        <div className="power-label">POWER</div>
      </div>
    </div>
  );
}

// Compare luck-stripped all-play strength to the actual record.
function luckRead(team, allPlay) {
  const actualPct = team.wins + team.losses ? team.wins / (team.wins + team.losses) : 0;
  const gap = allPlay.pct - actualPct;
  if (gap > 0.12) return { label: 'Unlucky', tone: 'unlucky', note: 'scoring outruns the record' };
  if (gap < -0.12) return { label: 'Lucky', tone: 'lucky', note: 'record outruns the scoring' };
  return { label: 'Earned', tone: 'earned', note: 'record matches the scoring' };
}

function TeamDrawer({ team, detail, onClose }) {
  // Close on Escape while the drawer is open.
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  if (!team) return null;

  return (
    <>
      <div className="drawer-scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label={`${team.name} detail`}>
        <header className="drawer-head">
          <div>
            <div className="drawer-name">{team.name}</div>
            <div className="drawer-sub">
              actual {team.wins}–{team.losses} · #{team.rank} · {team.avgPts.toFixed(1)} PPG
            </div>
          </div>
          <button className="drawer-close" onClick={onClose} aria-label="Close">×</button>
        </header>

        {!detail ? (
          <div className="drawer-empty">No detail available.</div>
        ) : (
          <>
            <section className="drawer-section">
              <h3 className="drawer-h3">Is the record real?</h3>

              {(() => {
                const luck = luckRead(team, detail.allPlay);
                const ap = detail.allPlay;
                return (
                  <div className="stat-row">
                    <div className="stat-main">
                      <div className="stat-label">True record <span className="stat-hint">all-play</span></div>
                      <div className="stat-value">
                        {ap.wins}–{ap.losses}
                        <span className="stat-pct">{Math.round(ap.pct * 100)}%</span>
                      </div>
                    </div>
                    <span className={`luck-tag luck-${luck.tone}`} title={luck.note}>{luck.label}</span>
                  </div>
                );
              })()}

              {(() => {
                const e = detail.efficiency;
                return (
                  <div className="stat-row">
                    <div className="stat-main">
                      <div className="stat-label">Lineup efficiency <span className="stat-hint">vs perfect lineup</span></div>
                      <div className="stat-value">
                        {Math.round(e.pct * 100)}%
                        <span className="stat-sub">{e.pointsLeft.toFixed(1)} pts left on bench</span>
                      </div>
                    </div>
                    <div className="eff-bar" aria-hidden>
                      <div className="eff-fill" style={{ width: `${Math.round(e.pct * 100)}%` }} />
                    </div>
                  </div>
                );
              })()}
            </section>

            <section className="drawer-section">
              <h3 className="drawer-h3">Weekly scoring</h3>
              <WeeklyScoring weeks={detail.weeks} />
              <div className="wk-legend">
                <span><span className="wk-swatch beat" /> beat league median</span>
                <span><span className="wk-swatch miss" /> below median</span>
                <span className="wk-mean-key">— mean</span>
              </div>
            </section>

            <section className="drawer-section">
              <h3 className="drawer-h3">What kind of team</h3>
              <div className="spec-block">
                <div className="spec-name">Consistency</div>
                <Spectrum leftLabel="Consistent" rightLabel="Volatile" pos={detail.consistency.pos} />
              </div>
              <div className="spec-block">
                <div className="spec-name">Positional shape</div>
                <Spectrum leftLabel="Balanced" rightLabel="Hero-led" pos={detail.shape.pos} />
                <PosBars ratios={detail.shape.ratios} />
              </div>
              <div className="spec-foot">markers show where this team sits in the league · bars are per-position output vs. league average</div>
            </section>
          </>
        )}
      </aside>
    </>
  );
}

// A labelled track with a single marker placed at `pos` (0 = left end, 1 = right).
function Spectrum({ leftLabel, rightLabel, pos }) {
  const clamped = Math.max(0, Math.min(1, pos ?? 0.5));
  return (
    <div className="spectrum">
      <div className="spec-track">
        <div className="spec-marker" style={{ left: `${clamped * 100}%` }} />
      </div>
      <div className="spec-ends">
        <span>{leftLabel}</span>
        <span>{rightLabel}</span>
      </div>
    </div>
  );
}

// Per-position output vs. league average — a diverging bar from a center baseline.
// Ratio 1.0 = league average; bars cap at ±60% so outliers stay in frame.
function PosBars({ ratios }) {
  const CAP = 0.6;
  return (
    <div className="posbars">
      {POS.map((p) => {
        const r = ratios?.[p];
        const delta = r != null ? r - 1 : 0;
        const pct = Math.round(delta * 100);
        const half = (Math.min(Math.abs(delta), CAP) / CAP) * 50; // % of full track
        const up = delta >= 0;
        return (
          <div className="posbar-row" key={p}>
            <span className="posbar-label" style={{ color: POS_COLORS[p] }}>{p}</span>
            <div className="posbar-track">
              <div className="posbar-center" />
              {r != null && (
                <div
                  className="posbar-fill"
                  style={{
                    [up ? 'left' : 'right']: '50%',
                    width: `${half}%`,
                    background: POS_COLORS[p],
                  }}
                />
              )}
            </div>
            <span className={`posbar-delta ${up ? 'up' : 'down'}`}>
              {r == null ? '—' : `${up ? '+' : ''}${pct}%`}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function WeeklyScoring({ weeks }) {
  if (!weeks?.length) return null;
  const max = Math.max(...weeks.map((w) => w.pts));
  const mean = weeks.reduce((s, w) => s + w.pts, 0) / weeks.length;
  return (
    <div className="wk-chart">
      <div className="wk-mean" style={{ bottom: `${(mean / max) * 100}%` }} title={`mean ${mean.toFixed(1)}`} />
      {weeks.map((w) => (
        <div className="wk-col" key={w.week}>
          <div
            className={`wk-bar ${w.beatMedian ? 'beat' : 'miss'}`}
            style={{ height: `${(w.pts / max) * 100}%` }}
            title={`Week ${w.week}: ${w.pts.toFixed(1)} (${w.result})`}
          >
            <span className="wk-pts">{w.pts.toFixed(0)}</span>
            <span className="wk-label">W{w.week}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
