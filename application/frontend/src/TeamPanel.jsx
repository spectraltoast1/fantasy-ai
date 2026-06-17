import React, { useEffect, useState } from 'react';
import { loadTeams, loadPowerRankings, loadTeamRosters, loadTeamPlayers, POS } from './queries.js';
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
  const [players, setPlayers] = useState(null); // signal read for the selected team
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

  // Players signal read is per-team — (re)load it whenever the selected team changes.
  useEffect(() => {
    if (selected == null) return;
    setPlayers(null);
    loadTeamPlayers(selected)
      .then(setPlayers)
      .catch((e) => {
        console.error(e);
        setError(e.message ?? String(e));
      });
  }, [selected]);

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
      {subtab === 'players' && <Players players={players} />}
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
      <section className="to-section">
        <h3 className="to-h3">Where you leave points</h3>
        <Leakage leakage={roster.leakage} />
      </section>
    </>
  );
}

// Form / trajectory: where the team is heading, not how much it bounces. Reads a
// recency-weighted trend slope (half-life ~2wk) over the weekly scores — smooth,
// gap-free, every game counted — and places it on a league-relative Fading↔Surging
// spectrum, then shows the weekly scores (recent weeks bolder) so the shape is
// legible. Distinct from the League drawer's variance read — this is about direction.
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
  const sign = form.slope > 0 ? '+' : '';
  const detail =
    form.direction === 'steady'
      ? 'scoring has held roughly level across the season'
      : `trending ${sign}${form.slope.toFixed(1)} pts/wk, recent weeks weighted most`;
  const rec = `${form.recent.w}–${form.recent.l} last two`;

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

      <WeeklyTrend weeks={form.weeks} weekMax={form.weekMax} />

      <div className="to-foot">
        Columns are weekly points; green beat the league median that week, grey
        fell below it. More recent weeks are drawn bolder — they carry more weight
        in the trend, which fades older games rather than cutting them off.
      </div>
    </div>
  );
}

// Where you leave points, framed for improvement not regret. Leads with the
// league-relative process verdict (lineup efficiency) — most teams are sound — then
// splits the points left into variance (one-week bench spikes, not your fault) and
// coachable (a repeatable bench-over-starter fix still on your roster). The raw
// points-left total and per-week chart are demoted to supporting evidence. No
// retrospective "you blew week N" calls — only the one tendency worth changing.
function Leakage({ leakage }) {
  if (!leakage) return <div className="subview-stub">No lineup data for this team.</div>;
  const pct = Math.round(leakage.pct * 100);
  const clean = leakage.pointsLeft < 1;
  const pos = Math.max(0, Math.min(1, leakage.pos ?? 0.5));
  // League-relative process read — where this team's efficiency sits in the field.
  const verdict =
    pos >= 0.6
      ? { word: 'Sharp lineups', cls: 'up' }
      : pos >= 0.35
      ? { word: 'Sound process', cls: 'flat' }
      : { word: 'Room to tighten', cls: 'down' };

  return (
    <div className="to-leak">
      <div className="to-form-head">
        <span className={`to-form-word ${verdict.cls}`}>{verdict.word}</span>
        <span className="to-form-detail">{pct}% lineup efficiency this season, league-relative below</span>
      </div>

      <div className="spectrum">
        <div className="spec-track leak-track">
          <div className="spec-marker" style={{ left: `${pos * 100}%` }} />
        </div>
        <div className="spec-ends">
          <span>Leaky</span>
          <span>Optimal</span>
        </div>
      </div>

      {clean ? (
        <div className="to-signal clean">
          <span className="to-signal-tag tag-clean">Optimal</span>
          <span className="to-signal-text">
            You’ve started essentially your best lineup all season — almost nothing
            left on the bench.
          </span>
        </div>
      ) : (
        <LeakBreakdown leakage={leakage} />
      )}

      <WeeklyLeak byWeek={leakage.byWeek} leakMax={leakage.leakMax} />

      <div className="to-foot">
        Supporting detail: points left on the bench each week — the gap between your
        lineup and the best one your roster could have fielded. A near-empty column
        is a week you fielded your best lineup; everything reconciles to the season total.
      </div>
    </div>
  );
}

// The coachable-vs-variance split: a two-segment bar (most of it is variance, which
// is the point), then the one repeatable fix worth acting on — or, if there's no
// recurring hierarchy error, a clean reassurance that the leak was all variance.
function LeakBreakdown({ leakage }) {
  const { pointsLeft, coachablePts, variancePts, fixes } = leakage;
  const cPct = pointsLeft > 0 ? Math.round((coachablePts / pointsLeft) * 100) : 0;
  const vPct = 100 - cPct;
  const hasFix = fixes.length > 0;

  return (
    <div className="to-leak-breakdown">
      <div className="to-leak-split">
        <div className="to-leak-seg variance" style={{ width: `${vPct}%` }} />
        <div className="to-leak-seg coachable" style={{ width: `${cPct}%` }} />
      </div>
      <div className="to-leak-split-key">
        <span><span className="key-dot variance" />{round1(variancePts)} pts variance</span>
        <span><span className="key-dot coachable" />{round1(coachablePts)} pts coachable</span>
      </div>

      {hasFix ? (
        <>
          <p className="to-leak-lede">
            Most of the <strong>{round1(pointsLeft)}</strong> pts you left were
            one-week bench spikes — variance you couldn’t have called.{' '}
            {fixes.length === 1 ? 'One pattern is' : 'A few patterns are'} repeatable
            and worth fixing:
          </p>
          {fixes.map((f) => (
            <div className="to-signal" key={`${f.benchName}-${f.starterName}`}>
              <span className="to-signal-tag tag-lineup">Fix</span>
              <span className="to-signal-text">
                start <strong>{f.benchName}</strong> ({f.benchRate}/g) over{' '}
                <strong>{f.starterName}</strong> ({f.starterRate}/g) at{' '}
                <span style={{ color: POS_COLORS[f.position] ?? 'var(--muted)' }}>{f.position}</span>{' '}
                going forward — <span className="to-leak-gain">+{f.edge}/g</span> on the season.
              </span>
            </div>
          ))}
        </>
      ) : (
        <p className="to-leak-lede">
          Your lineup calls have been sound — essentially all{' '}
          <strong>{round1(pointsLeft)}</strong> pts left were bench players who
          happened to spike a single week, not a recurring start/sit you’d change
          going forward.
        </p>
      )}
    </div>
  );
}

// Per-week points-left columns — the "which weeks" view. A near-empty column is a
// week you nailed the lineup; a tall one is points left on the bench.
function WeeklyLeak({ byWeek, leakMax }) {
  return (
    <div className="to-trend leak">
      {byWeek.map((w) => {
        const h = leakMax ? Math.max(2, (w.left / leakMax) * 100) : 2;
        return (
          <div className="to-trend-col" key={w.week}>
            <span className="to-trend-pts">{w.left > 0.05 ? `−${w.left.toFixed(1)}` : '0'}</span>
            <div className="to-trend-bar-wrap">
              <div
                className={`to-trend-bar ${w.left > 0.05 ? 'leaked' : 'nailed'}`}
                style={{ height: `${h}%` }}
              />
            </div>
            <span className="to-trend-wk">W{w.week}</span>
          </div>
        );
      })}
    </div>
  );
}

const round1 = (n) => Math.round(n * 10) / 10;

// Weekly scores as a small column chart — the "show the work" behind the trend.
// Bars scale within the team; green = beat the league median that week. Each bar's
// opacity tracks its recency weight (most recent solid, older faded), making the
// trend's recency-weighting legible rather than implying a hard cutoff.
function WeeklyTrend({ weeks, weekMax }) {
  return (
    <div className="to-trend">
      {weeks.map((w) => {
        const h = weekMax ? Math.max(4, (w.pts / weekMax) * 100) : 0;
        return (
          <div className="to-trend-col" key={w.week}>
            <span className="to-trend-pts">{Math.round(w.pts)}</span>
            <div className="to-trend-bar-wrap">
              <div
                className={`to-trend-bar ${w.beatMedian ? 'beat' : 'below'}`}
                style={{ height: `${h}%`, opacity: 0.4 + 0.6 * (w.weight ?? 1) }}
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

// Players sub-view: the spike signal-quality read per player, as a sortable table.
// Reads "is this production real or noise?" — recent scoring next to whether the
// underlying usage backs it up. Framed as a question (the manager adjudicates), and
// the signal is shown as a direction/verdict, never a points projection. The read is
// pre-computed in Python (compute_player_signal.py); this is pure rendering.
const READS = {
  sticky: { label: 'Looks real', arrow: '▲', cls: 'up', q: 'the volume backs this pace up — the kind that tends to continue' },
  mixed: { label: 'Toss-up', arrow: '◆', cls: 'flat', q: 'part volume, part luck — a genuine coin-flip, weigh it yourself' },
  spike: { label: 'Cooling likely', arrow: '▼', cls: 'down', q: 'leaning on touchdowns / efficiency — the bouncy kind that fades' },
  too_early: { label: 'Too early', arrow: '·', cls: 'mute', q: 'too few games to read the production yet' },
};

const PLAYER_COLS = [
  { key: 'name', label: 'Player', align: 'left' },
  { key: 'recentPpg', label: 'Recent /g', align: 'right' },
  { key: 'regressionRisk', label: 'Signal', align: 'left' },
  { key: 'oppPct', label: 'Volume', align: 'left' },
  { key: 'tdShare', label: 'TD-driven', align: 'right' },
];

function Players({ players }) {
  const [sort, setSort] = useState({ key: 'recentPpg', dir: 'desc' });
  if (!players) return <div className="subview-stub">Loading players…</div>;
  if (players.length === 0) {
    return <div className="subview-stub">No rostered skill players for this team.</div>;
  }

  const sorted = [...players].sort((a, b) => {
    const av = a[sort.key];
    const bv = b[sort.key];
    const cmp = typeof av === 'string' ? av.localeCompare(bv) : av - bv;
    return sort.dir === 'asc' ? cmp : -cmp;
  });
  // Click toggles direction on the active column; a new column starts desc (asc for name).
  const toggle = (key) =>
    setSort((s) =>
      s.key === key
        ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' }
        : { key, dir: key === 'name' ? 'asc' : 'desc' },
    );

  return (
    <section className="to-section">
      <h3 className="to-h3">Players — real or noise?</h3>
      <p className="players-lede">
        Each player’s recent scoring, and whether the underlying usage backs it up.
        The signal is a question to weigh, not a call — <strong>you</strong> decide
        whether to trust the run. Tap any column to sort.
      </p>
      <table className="players-table">
        <thead>
          <tr>
            {PLAYER_COLS.map((c) => (
              <th
                key={c.key}
                className={`pt-${c.align} ${sort.key === c.key ? 'sorted' : ''}`}
                onClick={() => toggle(c.key)}
              >
                {c.label}
                {sort.key === c.key && <span className="pt-caret">{sort.dir === 'asc' ? ' ▲' : ' ▼'}</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((p) => (
            <PlayerRow key={p.name} p={p} />
          ))}
        </tbody>
      </table>
      <div className="to-foot">
        “Recent /g” is fantasy points per game so far — what’s already happened.
        “Signal” asks whether that pace is backed by repeatable usage or by
        regression-prone efficiency; it’s a read on the past, shown as a direction,
        not a points projection. “Volume” is opportunity rank within the player’s
        position (targets / carries — the sticky part); “TD-driven” is the share of
        points from touchdowns (the bounciest part). Thin samples read “Too early.”
      </div>
    </section>
  );
}

function PlayerRow({ p }) {
  const r = READS[p.read] ?? READS.too_early;
  const volPct = Math.round(p.oppPct * 100);
  const tdPct = Math.round(p.tdShare * 100);
  return (
    <tr className={p.lowSample ? 'low-sample' : ''}>
      <td className="pt-left">
        <span className="pt-pos" style={{ color: POS_COLORS[p.position] }}>{p.position}</span>
        <span className="pt-name">{p.name}</span>
        {p.lowSample && <span className="to-depth-flag">{p.games}g</span>}
      </td>
      <td className="pt-right pt-num">{p.recentPpg.toFixed(1)}</td>
      <td className="pt-left">
        <span className={`pt-read ${r.cls}`} title={r.q}>
          <span className="pt-arrow">{r.arrow}</span>
          {r.label}
        </span>
      </td>
      <td className="pt-left">
        <div className="pt-vol">
          <div className="pt-vol-track">
            <div className="pt-vol-fill" style={{ width: `${volPct}%`, background: POS_COLORS[p.position] }} />
          </div>
          <span className="pt-vol-pct">{volPct}</span>
        </div>
      </td>
      <td className={`pt-right pt-num ${p.tdShare >= 0.33 ? 'pt-td-hot' : ''}`}>{tdPct}%</td>
    </tr>
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
