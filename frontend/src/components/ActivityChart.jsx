import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client.js';
import { useApi } from '../hooks/useApi.js';
import { Card, Loading } from './ui.jsx';

const SERIES = [
  { key: 'clasificado', label: 'Clasificados', color: 'var(--series-1)' },
  { key: 'cuarentena', label: 'En cuarentena', color: 'var(--series-2)' },
];
const RANGES = [7, 30, 90];
const H = 200, PAD = { l: 34, r: 8, t: 10, b: 26 };

const dayLabel = (iso, long = false) => new Date(`${iso}T12:00:00`).toLocaleDateString('es-CO',
  long ? { weekday: 'long', day: 'numeric', month: 'long' } : { day: 'numeric', month: 'short' });

function niceMax(v) {
  if (v <= 4) return 4;
  const p = 10 ** Math.floor(Math.log10(v));
  return [1, 2, 2.5, 5, 10].map((m) => m * p).find((m) => m >= v);
}

// Barra con la punta de datos redondeada (4 px) y la base recta sobre el eje.
function barPath(x, y, w, h, round) {
  const r = Math.min(round ? 4 : 0, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

/** Archivos por día, apilados por resultado (clasificado / cuarentena), con tooltip y tabla. */
export default function ActivityChart() {
  const [dias, setDias] = useState(30);
  const serie = useApi(() => api.series(dias), [dias], { interval: 30000 });
  const ro = useRef(null);
  const [w, setW] = useState(640);
  const [hover, setHover] = useState(null);
  // el contenedor aparece después de la primera carga: se observa al montarse
  const wrap = useCallback((el) => {
    ro.current?.disconnect();
    if (!el) return;
    ro.current = new ResizeObserver(([e]) => setW(Math.max(280, e.contentRect.width)));
    ro.current.observe(el);
  }, []);
  useEffect(() => () => ro.current?.disconnect(), []);

  const days = serie.data?.dias || [];
  const totals = Object.fromEntries(SERIES.map((s) => [s.key, days.reduce((a, d) => a + (d.estado[s.key] || 0), 0)]));
  const max = niceMax(Math.max(1, ...days.map((d) => SERIES.reduce((a, s) => a + (d.estado[s.key] || 0), 0))));
  const iw = w - PAD.l - PAD.r, ih = H - PAD.t - PAD.b;
  const step = days.length ? iw / days.length : 0;
  const bw = Math.max(2, Math.min(28, step * 0.62));
  const y = (v) => PAD.t + ih - (v / max) * ih;
  const ticks = [0, max / 2, max];
  const every = Math.ceil(days.length / Math.max(2, Math.floor(iw / 64)));
  const busiest = days.reduce((b, d) => (d.total > (b?.total || 0) ? d : b), null);
  const h = hover != null ? days[hover] : null;

  return (
    <Card title="Actividad por día" actions={
      <div className="seg" role="group" aria-label="Rango de días">
        {RANGES.map((r) => <button key={r} className={r === dias ? 'on' : ''} aria-pressed={r === dias} onClick={() => setDias(r)}>{r} días</button>)}
      </div>}>
      {serie.loading && !days.length ? <Loading /> : (
        <div className="stack" style={{ gap: 10 }}>
          <div className="chart-legend">
            {SERIES.map((s) => <span key={s.key}><i style={{ background: s.color }} />{s.label} <b>{totals[s.key]}</b></span>)}
            {busiest?.total > 0 && <span className="muted small">Día con más archivos: {dayLabel(busiest.fecha)} ({busiest.total})</span>}
          </div>
          <div className="chart" ref={wrap} onMouseLeave={() => setHover(null)}>
            <svg width={w} height={H} role="img" aria-label={`Archivos por día en los últimos ${dias} días: ${totals.clasificado} clasificados y ${totals.cuarentena} en cuarentena`}>
              {ticks.map((t) => (
                <g key={t}>
                  <line x1={PAD.l} x2={w - PAD.r} y1={y(t)} y2={y(t)} className={t === 0 ? 'axis' : 'grid'} />
                  <text x={PAD.l - 6} y={y(t) + 4} textAnchor="end" className="tick">{Math.round(t)}</text>
                </g>
              ))}
              {days.map((d, i) => {
                const x = PAD.l + i * step + (step - bw) / 2;
                let acc = 0;
                const segs = SERIES.map((s) => ({ ...s, v: d.estado[s.key] || 0 })).filter((s) => s.v > 0);
                return (
                  <g key={d.fecha} className={hover === i ? 'col on' : 'col'}>
                    {segs.map((s, j) => {
                      const y0 = y(acc), y1 = y(acc + s.v);
                      acc += s.v;
                      const gap = j > 0 ? 2 : 0; // separación de 2 px entre segmentos
                      return <path key={s.key} d={barPath(x, y1, bw, Math.max(1, y0 - y1 - gap), j === segs.length - 1)} fill={s.color} />;
                    })}
                    {i % every === 0 && <text x={x + bw / 2} y={H - 8} textAnchor="middle" className="tick">{dayLabel(d.fecha)}</text>}
                    <rect x={PAD.l + i * step} y={PAD.t} width={step} height={ih} fill="transparent"
                      onMouseEnter={() => setHover(i)} onClick={() => setHover(i)} />
                  </g>
                );
              })}
            </svg>
            {h && (
              <div className="chart-tip" style={{ left: Math.min(Math.max(PAD.l + hover * step + step / 2, 90), w - 90) }}>
                <b>{dayLabel(h.fecha, true)}</b>
                {SERIES.map((s) => <div key={s.key}><i style={{ background: s.color }} />{s.label}<span>{h.estado[s.key] || 0}</span></div>)}
                {Object.keys(h.categoria).length > 0 && (
                  <div className="muted small" style={{ marginTop: 4 }}>
                    {Object.entries(h.categoria).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([c, n]) => `${c} ${n}`).join(' · ')}
                  </div>
                )}
              </div>
            )}
          </div>
          <details className="small">
            <summary className="muted" style={{ cursor: 'pointer' }}>Ver como tabla</summary>
            <div className="table-wrap" style={{ maxHeight: 240, overflowY: 'auto', marginTop: 8 }}>
              <table className="table">
                <thead><tr><th>Día</th>{SERIES.map((s) => <th key={s.key} className="num">{s.label}</th>)}<th className="num">Total</th></tr></thead>
                <tbody>{[...days].reverse().filter((d) => d.total).map((d) => (
                  <tr key={d.fecha}><td>{dayLabel(d.fecha)}</td>{SERIES.map((s) => <td key={s.key} className="num">{d.estado[s.key] || 0}</td>)}<td className="num">{d.total}</td></tr>
                ))}</tbody>
              </table>
            </div>
          </details>
        </div>
      )}
    </Card>
  );
}
