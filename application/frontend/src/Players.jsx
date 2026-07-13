import React, { useEffect, useMemo, useState } from 'react';
import { loadPlayers, POS } from './queries.js';
import { Gate, REGIME } from './readiness.jsx';
import { POS_COLORS } from './posColors.js';

// Players surface — the VOR-anchored table. Anchored on Production VOR (default sort),
// with Market VOR and the ROS Synthesis bull/bear/situation grades as sortable columns.
// Pure renderer: all data comes assembled from queries.loadPlayers; filtering + sorting
// are client-side view state (per the contract — no data access in the component).

const SORT_KEYS = { prod: 'prodVor', mkt: 'mktVor', bull: 'bull', bear: 'bear', sit: 'sit' };
const SORT_COLS = [
  ['prod', 'PROD'],
  ['mkt', 'MKT'],
  ['bull', 'BULL'],
  ['bear', 'BEAR'],
  ['sit', 'SIT'],
];
const POS_FILTERS = ['ALL', ...POS];

export default function Players({ asOfWeek, onOpenPlayer }) {
  const [rows, setRows] = useState(null);
  const [err, setErr] = useState(null);
  const [pos, setPos] = useState('ALL');
  const [sort, setSort] = useState('prod');

  useEffect(() => {
    let live = true;
    setRows(null);
    setErr(null);
    loadPlayers(asOfWeek)
      .then((r) => live && setRows(r))
      .catch((e) => live && setErr(e));
    return () => {
      live = false;
    };
  }, [asOfWeek]);

  const view = useMemo(() => {
    if (!rows) return [];
    const key = SORT_KEYS[sort];
    const filtered = pos === 'ALL' ? rows : rows.filter((p) => p.pos === pos);
    const prod = (p) => (p.prodVor == null ? -Infinity : p.prodVor);
    return filtered.slice().sort((a, b) => {
      const av = a[key];
      const bv = b[key];
      // Missing values (no market row / no ROS grade) sort to the bottom.
      if (av == null && bv == null) return prod(b) - prod(a);
      if (av == null) return 1;
      if (bv == null) return -1;
      return bv - av || prod(b) - prod(a);
    });
  }, [rows, pos, sort]);

  if (err) {
    return (
      <div className="gr-state error">
        Could not load players.
        <pre>{String(err.message ?? err)}</pre>
      </div>
    );
  }

  return (
    <div className="gr-page">
      <div className="gr-page-head">
        <h1>Players</h1>
        <div className="sub">
          Every rostered skill player, anchored on <strong>Production VOR</strong> over the
          waiver line. <strong>MKT</strong> is the current market's VOR (2026 market × 2025
          roster — a cross-time POC, not a live trade call). <strong>BULL / BEAR / SIT</strong>{' '}
          are ROS Synthesis grades, shown where an AI read exists.
        </div>
      </div>

      <div className="pl-controls">
        <div className="pl-chips">
          {POS_FILTERS.map((p) => (
            <button
              key={p}
              className={`pl-chip ${pos === p ? 'active' : ''}`}
              onClick={() => setPos(p)}
            >
              {p}
            </button>
          ))}
        </div>
        {/* Available (waivers) filter is deferred: the free-agent pool has no VOR entity
            yet, so it can't be populated honestly. Disabled with a note. */}
        <button className="pl-chip ghost" disabled title="Free-agent pool not available in V1 yet">
          Available · soon
        </button>
      </div>

      {rows == null ? (
        <div className="gr-state">Loading players…</div>
      ) : (
        <Gate regime={REGIME.POINT_IN_TIME} weeks={asOfWeek ?? 0} label="Player VOR">
          <table className="pl-table">
            <thead>
              <tr>
                <th className="pl-l">POS</th>
                <th className="pl-l">Player</th>
                {SORT_COLS.map(([k, label]) => (
                  <th
                    key={k}
                    className={`pl-r sortable ${sort === k ? 'sorted' : ''}`}
                    onClick={() => setSort(k)}
                  >
                    {label}
                    {sort === k ? <span className="pl-caret"> ▾</span> : null}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {view.map((p) => (
                <tr key={p.sleeperId} onClick={() => onOpenPlayer?.(p.sleeperId)}>
                  <td className="pl-l">
                    <span className="pl-pos" style={{ color: POS_COLORS[p.pos] }}>
                      {p.pos}
                    </span>
                  </td>
                  <td className="pl-l">
                    <span className="pl-name">{p.name}</span>
                    <span className="pl-sub">
                      {p.nflTeam ?? '—'}
                      {p.isMe ? <span className="pl-you">YOU</span> : null}
                    </span>
                  </td>
                  <td className={`pl-r mono ${sort === 'prod' ? 'hot' : ''}`}>{fmtVor(p.prodVor)}</td>
                  <td className={`pl-r mono ${sort === 'mkt' ? 'hot' : ''}`}>{fmtVor(p.mktVor)}</td>
                  <td className={`pl-r mono grade ${sort === 'bull' ? 'hot' : ''}`}>{fmtGrade(p.bull)}</td>
                  <td className={`pl-r mono grade ${sort === 'bear' ? 'hot' : ''}`}>{fmtGrade(p.bear)}</td>
                  <td className={`pl-r mono grade ${sort === 'sit' ? 'hot' : ''}`}>{fmtGrade(p.sit)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Gate>
      )}
    </div>
  );
}

const fmtVor = (v) => (v == null ? <span className="pl-empty">—</span> : v.toFixed(1));
const fmtGrade = (g) => (g == null ? <span className="pl-empty">—</span> : g);
