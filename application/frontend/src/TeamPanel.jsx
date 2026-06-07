import React, { useEffect, useState } from 'react';
import { loadTeams, loadPowerRankings, loadTeamRosters, POS } from './queries.js';
import { POS_COLORS } from './posColors.js';

// Team tab: a deep drill-down on ONE team. Opens on the logged-in user's team
// and can flip to any other via the switcher. Two inner views:
//   - overview: how the team is built and how it's doing — strengths, fragility
//   - players:  per-player real-world metrics, made interpretable
// The League tab answers "how do I stack up?" (comparative); the Team tab answers
// "how is THIS team built and managed?" — so it looks inside one roster (bench
// included) rather than ranking starters across the league.
const SUBTABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'players', label: 'Players' },
];

export default function TeamPanel() {
  const [teams, setTeams] = useState(null);
  const [summary, setSummary] = useState(null); // rosterId -> power-ranking vitals
  const [rosters, setRosters] = useState(null); // rosterId -> construction detail
  const [selected, setSelected] = useState(null); // rosterId in focus
  const [subtab, setSubtab] = useState('overview');
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([loadTeams(), loadPowerRankings(), loadTeamRosters()])
      .then(([{ teams, myRosterId }, rankings, rosterDetail]) => {
        setTeams(teams);
        // Index power-ranking vitals (rank, record, PPG, power) by roster.
        const byId = {};
        for (const t of rankings.teams) byId[t.rosterId] = { ...t, teamCount: rankings.teams.length };
        setSummary(byId);
        setRosters(rosterDetail);
        // Default to the user's own team; fall back to the first roster.
        setSelected(myRosterId ?? teams[0]?.rosterId ?? null);
      })
      .catch((e) => {
        console.error(e);
        setError(e.message ?? String(e));
      });
  }, []);

  if (error) {
    return (
      <div className="state error">
        <h2>Couldn’t load teams</h2>
        <pre>{error}</pre>
      </div>
    );
  }
  if (!teams || !summary || !rosters) {
    return <div className="state">Loading team data via DuckDB…</div>;
  }

  const team = teams.find((t) => t.rosterId === selected);
  const vitals = summary[selected];
  const roster = rosters[selected];

  return (
    <div className="page">
      <header className="page-head team-head">
        <div>
          <h1>{team?.name ?? 'Team'}</h1>
          <div className="sub">
            {team?.isMe ? 'Your team' : `@${team?.owner}`}
          </div>
        </div>
        <label className="team-switch">
          <span className="team-switch-label">Viewing</span>
          <select
            value={selected ?? ''}
            onChange={(e) => setSelected(Number(e.target.value))}
          >
            {teams.map((t) => (
              <option key={t.rosterId} value={t.rosterId}>
                {t.name}
                {t.isMe ? ' (you)' : ''}
              </option>
            ))}
          </select>
        </label>
      </header>

      <div className="subnav">
        {SUBTABS.map((s) => (
          <button
            key={s.id}
            className={`subnav-tab ${subtab === s.id ? 'active' : ''}`}
            onClick={() => setSubtab(s.id)}
          >
            {s.label}
          </button>
        ))}
      </div>

      {subtab === 'overview' && <Overview vitals={vitals} roster={roster} />}
      {subtab === 'players' && (
        <div className="subview-stub">
          Players — per-player real-world metrics with visualizations that make
          the stats interpretable. Coming next.
        </div>
      )}
    </div>
  );
}

function Overview({ vitals, roster }) {
  if (!vitals || !roster) {
    return <div className="subview-stub">No data for this team.</div>;
  }
  return (
    <>
      <Vitals vitals={vitals} />
      <section className="to-section">
        <h3 className="to-h3">How this team is built</h3>
        <Reliance reliance={roster.reliance} />
        <Signals signals={roster.signals} />
        <DepthChart byPosition={roster.byPosition} posMax={roster.posMax} />
        <div className="to-foot">
          Bars are points per game (bench included), scaled within each position —
          so a drop-off after a starter reads as a cliff. Filled dot = regular
          starter; dimmed = bench; struck-through = no longer on the roster. “1g”
          marks a one-game sample (too small to trust, left out of the signals).
        </div>
      </section>
      <section className="to-section">
        <h3 className="to-h3">Form</h3>
        <Form form={roster.form} />
      </section>
    </>
  );
}

// Form / trajectory: where the team is heading, not how much it bounces. Reads
// the swing between the season's first half and its last half (at 4 weeks,
// last-2 vs first-2) and places it on a league-relative Fading↔Surging spectrum,
// then shows the weekly scores so the shape is legible. Distinct from the League
// drawer's variance read — this is about direction.
const DIRECTION = {
  rising: { word: 'Heating up', cls: 'up' },
  fading: { word: 'Cooling off', cls: 'down' },
  steady: { word: 'Holding steady', cls: 'flat' },
};

function Form({ form }) {
  if (!form || form.weeks.length < 2) {
    return <div className="subview-stub">Not enough games yet to read a trend.</div>;
  }
  const dir = DIRECTION[form.direction];
  const span = form.recentCount === 1 ? 'week' : `${form.recentCount} weeks`;
  const sign = form.delta > 0 ? '+' : '';
  const detail =
    form.direction === 'steady'
      ? 'scoring is flat across the season so far'
      : `${sign}${form.delta.toFixed(1)} pts/wk over the last ${span} vs. the first ${span}`;
  const rec = `${form.recent.w}–${form.recent.l} recently`;

  return (
    <div className="to-form">
      <div className="to-form-head">
        <span className={`to-form-word ${dir.cls}`}>{dir.word}</span>
        <span className="to-form-detail">{detail} · {rec}</span>
      </div>

      <div className="spectrum">
        <div className="spec-track form-track">
          <div
            className="spec-marker"
            style={{ left: `${Math.max(0, Math.min(1, form.pos ?? 0.5)) * 100}%` }}
          />
        </div>
        <div className="spec-ends">
          <span>Fading</span>
          <span>Surging</span>
        </div>
      </div>

      <WeeklyTrend weeks={form.weeks} weekMax={form.weekMax} recentCount={form.recentCount} />

      <div className="to-foot">
        Columns are weekly points; green beat the league median that week, grey
        fell below it. The shaded weeks on the right are the recent window the
        trend compares against the earlier ones.
      </div>
    </div>
  );
}

// Weekly scores as a small column chart — the "show the work" behind the trend.
// Bars scale within the team; a tick marks the league median that week. The most
// recent half is shaded so the comparison the delta describes is visible.
function WeeklyTrend({ weeks, weekMax, recentCount }) {
  const n = weeks.length;
  const recentFrom = n - recentCount;
  return (
    <div className="to-trend">
      {weeks.map((w, i) => {
        const h = weekMax ? Math.max(4, (w.pts / weekMax) * 100) : 0;
        return (
          <div className={`to-trend-col ${i >= recentFrom ? 'recent' : ''}`} key={w.week}>
            <span className="to-trend-pts">{Math.round(w.pts)}</span>
            <div className="to-trend-bar-wrap">
              <div
                className={`to-trend-bar ${w.beatMedian ? 'beat' : 'below'}`}
                style={{ height: `${h}%` }}
              />
            </div>
            <span className={`to-trend-wk ${w.result === 'W' ? 'win' : 'loss'}`}>
              W{w.week} · {w.result}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// At-a-glance vitals: where the team sits before the construction detail. This is
// a deliberate recap of the League-card numbers — the bridge that carries context
// one level deeper, not new analysis.
function Vitals({ vitals }) {
  const tiles = [
    { label: 'Power rank', value: `#${vitals.rank}`, sub: `of ${vitals.teamCount}` },
    { label: 'Record', value: `${vitals.wins}–${vitals.losses}` },
    { label: 'Points / wk', value: vitals.avgPts.toFixed(1), sub: `±${vitals.std.toFixed(1)}` },
    { label: 'Power score', value: vitals.powerScore, accent: true },
  ];
  return (
    <div className="to-vitals">
      {tiles.map((t) => (
        <div className="to-tile" key={t.label}>
          <div className={`to-tile-value ${t.accent ? 'accent' : ''}`}>{t.value}</div>
          <div className="to-tile-label">{t.label}</div>
          {t.sub && <div className="to-tile-sub">{t.sub}</div>}
        </div>
      ))}
    </div>
  );
}

// Star dependence: how exposed the team is to its single best player, placed
// league-relative (balanced attack ↔ star-led) rather than on a fixed threshold.
function Reliance({ reliance }) {
  const pct = Math.round(reliance.top1 * 100);
  return (
    <div className="to-reliance">
      <div className="to-reliance-stat">
        Star dependence
        {reliance.star && (
          <span className="to-reliance-note">
            <strong>{reliance.star}</strong> carries {pct}% of starting points
          </span>
        )}
      </div>
      <div className="spectrum">
        <div className="spec-track">
          <div
            className="spec-marker"
            style={{ left: `${Math.max(0, Math.min(1, reliance.pos ?? 0.5)) * 100}%` }}
          />
        </div>
        <div className="spec-ends">
          <span>Balanced attack</span>
          <span>Star-led</span>
        </div>
      </div>
    </div>
  );
}

// Auto-surfaced signals: lead with what to do. Lineup calls are fixable in house
// (start the bench guy); holes need an outside upgrade. No noise = a clean bill.
function Signals({ signals }) {
  const lineup = signals.lineup.slice(0, 3);
  const holes = signals.holes.slice(0, 2);
  const none = lineup.length === 0 && holes.length === 0;

  return (
    <div className="to-signals">
      {none && (
        <div className="to-signal clean">
          <span className="to-signal-tag tag-clean">All set</span>
          <span className="to-signal-text">
            No lineup or roster red flags — your best options are in the lineup.
          </span>
        </div>
      )}
      {lineup.map((s) => (
        <div className="to-signal" key={`l-${s.position}-${s.benchName}`}>
          <span className="to-signal-tag tag-lineup">Lineup</span>
          <span className="to-signal-text">
            <strong>{s.benchName}</strong> ({s.benchRate}/g) is out-producing starter{' '}
            <strong>{s.starterName}</strong> ({s.starterRate}/g) at{' '}
            <span style={{ color: POS_COLORS[s.position] }}>{s.position}</span>.
          </span>
        </div>
      ))}
      {holes.map((s) => (
        <div className="to-signal" key={`h-${s.position}`}>
          <span className="to-signal-tag tag-hole">Hole</span>
          <span className="to-signal-text">
            <span style={{ color: POS_COLORS[s.position] }}>{s.position}</span> is thin —{' '}
            <strong>{s.name}</strong> ({s.rate}/g) trails the league’s ~{s.leagueRate}/g, with
            no better option on the roster.
          </span>
        </div>
      ))}
    </div>
  );
}

// Depth chart: per position, every rostered skill player as a bar (points per
// game, scaled within position). Solid = regular starter, dimmed = bench,
// struck-through = departed — so misused players and thin spots pop out.
function DepthChart({ byPosition, posMax }) {
  return (
    <div className="to-depth">
      {POS.map((pos) => {
        const players = byPosition[pos] ?? [];
        const max = posMax[pos] || 1;
        return (
          <div className="to-depth-group" key={pos}>
            <div className="to-depth-pos" style={{ color: POS_COLORS[pos] }}>{pos}</div>
            <div className="to-depth-rows">
              {players.length === 0 ? (
                <div className="to-depth-empty">no players</div>
              ) : (
                players.map((p) => {
                  const width = Math.min(100, (p.rate / max) * 100);
                  const role = p.departedTo ? 'departed' : p.startShare >= 0.5 ? 'starter' : 'bench';
                  return (
                    <div className={`to-depth-row ${role}`} key={p.name}>
                      <span className="to-depth-name" title={p.departedTo ? `now on ${p.departedTo}` : undefined}>
                        {role === 'starter' && <span className="to-depth-marker" />}
                        <span className="to-depth-pname">{p.name}</span>
                        {p.lowSample && <span className="to-depth-flag">1g</span>}
                        {p.departedTo && <span className="to-depth-left">→ {p.departedTo}</span>}
                      </span>
                      <div className="to-depth-track">
                        <div
                          className={`to-depth-fill ${p.lowSample ? 'noisy' : ''}`}
                          style={{ width: `${width}%`, background: POS_COLORS[pos] }}
                        />
                      </div>
                      <span className="to-depth-val">{p.rate.toFixed(1)}</span>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
