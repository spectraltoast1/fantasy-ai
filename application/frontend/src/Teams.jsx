import React, { useEffect, useState } from 'react';
import { loadStandings } from './queries.js';
import { Sparkline } from './charts.jsx';
import { Gate, REGIME } from './readiness.jsx';

// Teams surface — the standings table. Ranked by playoff odds, each row carries the real
// record, the all-play "true record", a posture chip (the shared §5 derivation), and the
// playoff-odds trendline. Pure renderer: everything comes assembled from loadStandings;
// row click drills into Team detail. Mirrors Players.jsx structure/classes.

export default function Teams({ asOfWeek, onOpenTeam }) {
  const [rows, setRows] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let live = true;
    setRows(null);
    setErr(null);
    loadStandings(asOfWeek)
      .then((r) => live && setRows(r))
      .catch((e) => live && setErr(e));
    return () => {
      live = false;
    };
  }, [asOfWeek]);

  if (err) {
    return (
      <div className="gr-state error">
        Could not load standings.
        <pre>{String(err.message ?? err)}</pre>
      </div>
    );
  }

  return (
    <div className="gr-page">
      <div className="gr-page-head">
        <h1>Teams</h1>
        <div className="sub">
          Ranked by <strong>playoff odds</strong>. <strong>True record</strong> is all-play
          (your score vs every team, every week — luck-stripped). The{' '}
          <strong>posture</strong> chip reads standing against true record; the trendline is
          playoff odds week over week.
        </div>
      </div>

      {rows == null ? (
        <div className="gr-state">Loading standings…</div>
      ) : (
        <Gate regime={REGIME.POINT_IN_TIME} weeks={asOfWeek ?? 0} label="Standings">
          <table className="tm-table">
            <thead>
              <tr>
                <th className="tm-l">#</th>
                <th className="tm-l">Team</th>
                <th className="tm-r">Record</th>
                <th className="tm-r">True Rec</th>
                <th className="tm-l">Posture</th>
                <th className="tm-r">Playoff %</th>
                <th className="tm-l">Trend</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.rosterId} onClick={() => onOpenTeam?.(t.rosterId)}>
                  <td className="tm-l mono tm-rank">{t.rank}</td>
                  <td className="tm-l">
                    <span className="tm-name">{t.name}</span>
                    <span className="tm-sub">
                      <span className="tm-owner">{t.owner ?? '—'}</span>
                      {t.isMe ? <span className="pl-you">YOU</span> : null}
                    </span>
                  </td>
                  <td className="tm-r mono">{t.wins}-{t.losses}</td>
                  <td className="tm-r mono tm-true">{t.allPlayW}-{t.allPlayL}</td>
                  <td className="tm-l">
                    {t.posture ? (
                      <span
                        className="tm-posture"
                        style={{ color: t.posture.tone, background: chipBg(t.posture.tone) }}
                      >
                        {t.posture.label}
                      </span>
                    ) : (
                      <span className="pl-empty">—</span>
                    )}
                  </td>
                  <td className="tm-r mono tm-odds">{fmtPct(t.playoffPct)}</td>
                  <td className="tm-l">
                    <Sparkline
                      values={t.oddsSeries}
                      color={t.posture ? t.posture.tone : 'var(--violet)'}
                      width={72}
                      height={22}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Gate>
      )}
    </div>
  );
}

// Posture chips tint at the color's ~13% alpha (README color roles). The tone is a
// `var(--x)` token; color-mix keeps one source of truth for the hue.
const chipBg = (tone) => `color-mix(in srgb, ${tone} 13%, transparent)`;

const fmtPct = (v) => (v == null ? <span className="pl-empty">—</span> : `${Math.round(v)}%`);
