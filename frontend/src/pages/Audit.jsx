import { useMemo, useState } from 'react';
import { api } from '../api/client.js';
import { useApi } from '../hooks/useApi.js';
import Icon from '../components/Icon.jsx';
import { Card, Empty, Kpi, Loading } from '../components/ui.jsx';
import { eventLabel, EVENT_LABEL } from '../utils/format.js';

const fmtFull = (iso) => (iso ? new Date(iso).toLocaleString('es-CO', { dateStyle: 'medium', timeStyle: 'medium' }) : '—');

export default function Audit() {
  const [kind, setKind] = useState('');
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(null);
  const events = useApi(() => api.events(null, 1000), [], { interval: 15000 });
  const ret = useApi(api.retention, [], { interval: 30000 });

  const rows = useMemo(() => (events.data || []).filter((e) => (!kind || e.event === kind)
    && (!q || JSON.stringify(e).toLowerCase().includes(q.toLowerCase()))), [events.data, kind, q]);
  const kinds = useMemo(() => [...new Set((events.data || []).map((e) => e.event))], [events.data]);
  const r = ret.data || {};

  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="grid g3">
        <Kpi icon="list" label="Eventos registrados" value={r.n ?? '—'} hint="SQLite + archivo de solo anexado" />
        <Kpi icon="clock" label="Retención mínima" value={`${r.retention_days ?? '—'} días`} hint="Meta: 6 meses (RNF8)" tone="ok" />
        <Kpi icon="activity" label="Evento más antiguo" value={r.oldest ? new Date(r.oldest).toLocaleDateString('es-CO') : '—'} hint={`más reciente ${fmtFull(r.newest)}`} />
      </div>
      <div className="toolbar">
        <div className="search"><Icon name="search" size={16} />
          <input className="input" placeholder="Buscar en eventos (huella, grupo, detalle)" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Buscar" /></div>
        <select className="select" value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Tipo de evento">
          <option value="">Todos los eventos</option>
          {kinds.map((k) => <option key={k} value={k}>{EVENT_LABEL[k] || k}</option>)}
        </select>
        <div className="spacer" /><span className="small muted">{rows.length} eventos</span>
      </div>
      <Card pad={false}>
        {events.loading ? <Loading /> : rows.length ? (
          <div className="table-wrap">
            <table className="table stack-sm">
              <thead><tr><th>Fecha y hora (UTC, ms)</th><th>Evento</th><th>Grupo</th><th>Huella SHA-256</th><th>Detalle</th></tr></thead>
              <tbody>
                {rows.map((e) => (
                  <tr key={e.id} className="clickable" onClick={() => setOpen(open === e.id ? null : e.id)}>
                    <td className="small mono" style={{ whiteSpace: 'nowrap' }}>{e.ts}</td>
                    <td className="small">{eventLabel(e.event)}</td>
                    <td className="small">{e.group_name || '—'}</td>
                    <td className="small mono">{e.sha256 ? `${e.sha256.slice(0, 12)}…` : '—'}</td>
                    <td className="small" style={{ maxWidth: 420 }}>
                      {open === e.id ? <pre className="pre">{JSON.stringify(e.detail, null, 2)}</pre>
                        : <span className="muted">{JSON.stringify(e.detail || {}).slice(0, 90)}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty icon="list" title="Sin eventos para este filtro" />}
      </Card>
    </div>
  );
}
