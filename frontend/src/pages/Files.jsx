import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../api/client.js';
import { useApi } from '../hooks/useApi.js';
import FileDrawer from '../components/FileDrawer.jsx';
import Icon from '../components/Icon.jsx';
import { BufeteCard } from '../components/Bufete.jsx';
import { AddChats } from '../components/GettingStarted.jsx';
import { Card, CategoryChip, Empty, FolderBadge, Loading, RiskBadge, StatusBadge } from '../components/ui.jsx';
import { fmtBytes, fmtDate, STATUS_LABEL } from '../utils/format.js';

const CARPETA = [['', 'Todos'], ['guardado', 'Guardados en el PC'], ['falta', 'Faltan por guardar'], ['cuarentena', 'En cuarentena']];

/** Resalta las palabras buscadas dentro del fragmento (el fragmento viene sin tildes y en minúsculas). */
function Highlight({ text, q }) {
  const norm = (s) => s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  const terms = norm(q).split(/\s+/).filter((t) => t.length >= 2);
  if (!terms.length) return text;
  const re = new RegExp(`(${terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'g');
  return text.split(re).map((part, i) => (i % 2 ? <mark key={i}>{part}</mark> : part));
}

export default function Files() {
  const [q, setQ] = useState('');
  const [qd, setQd] = useState('');      // texto de búsqueda con espera de 300 ms
  useEffect(() => { const t = setTimeout(() => setQd(q.trim()), 300); return () => clearTimeout(t); }, [q]);
  const [estado, setEstado] = useState('');
  const [params, setParams] = useSearchParams();
  const categoria = params.get('categoria') || '';
  const carpeta = params.get('carpeta') || '';
  const setParam = (k, v) => { const p = new URLSearchParams(params); if (v) p.set(k, v); else p.delete(k); setParams(p, { replace: true }); };
  const [open, setOpen] = useState(null);
  const cats = useApi(api.categories, []);
  const stats = useApi(api.stats, [], { interval: 15000 });
  const files = useApi(() => api.files({ q: qd, estado, categoria, carpeta, limite: 500 }), [qd, estado, categoria, carpeta], { interval: 15000 });
  const byCat = stats.data?.por_categoria || {};
  const reloadAll = () => { files.reload(); stats.reload(); };
  const enContenido = (files.data || []).filter((f) => f.coincidencia).length;

  return (
    <div className="stack" style={{ gap: 16 }}>
      <BufeteCard compact onChanged={reloadAll} />
      <div className="cat-filter" role="group" aria-label="Filtrar por etiqueta">
        <span className="small muted">Etiquetas:</span>
        <button type="button" className={`chip cat-chip all ${!categoria ? 'on' : ''}`} onClick={() => setParam('categoria', '')}>
          Todas<span className="cat-count">{Object.values(byCat).reduce((a, b) => a + b, 0)}</span></button>
        {[...(cats.data || []), ...Object.keys(byCat).filter((k) => !(cats.data || []).some((c) => c.nombre === k)).map((k) => ({ nombre: k }))]
          .filter((c) => byCat[c.nombre] || categoria === c.nombre).map((c) => (
          <CategoryChip key={c.nombre} category={c.nombre} count={byCat[c.nombre] || 0} active={categoria === c.nombre} title={c.descripcion}
            onClick={() => setParam('categoria', categoria === c.nombre ? '' : c.nombre)} />
        ))}
      </div>
      <div className="toolbar">
        <div className="search">
          <Icon name="search" size={16} />
          <input className="input" type="search" placeholder="Buscar por nombre, chat, remitente o dentro del documento" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Buscar" />
        </div>
        <select className="select" value={estado} onChange={(e) => setEstado(e.target.value)} aria-label="Estado">
          <option value="">Todos los estados</option>
          {Object.entries(STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <div className="seg" role="group" aria-label="Carpeta del bufete">
          {CARPETA.map(([k, label]) => (
            <button key={k} type="button" className={carpeta === k ? 'on' : ''} onClick={() => setParam('carpeta', k)}>{label}</button>
          ))}
        </div>
        <AddChats />
        <div className="spacer" />
        <span className="small muted">{files.data?.length ?? 0} archivos{qd && enContenido > 0 && ` · ${enContenido} por su contenido`}</span>
      </div>
      <Card pad={false}>
        {files.loading ? <Loading /> : files.data?.length ? (
          <div className="table-wrap">
            <table className="table stack-sm">
              <thead><tr><th>Archivo</th><th>Tipo · tamaño</th><th>Grupo · remitente</th><th>Estado</th><th>Riesgo</th><th>Etiqueta</th><th>Carpeta del PC</th><th>Recibido</th></tr></thead>
              <tbody>
                {files.data.map((f) => (
                  <tr key={f.sha256} className="clickable" onClick={() => setOpen(f.sha256)}>
                    <td className="file-name">{f.original_name}
                      {f.coincidencia && <small className="hit"><Icon name="search" size={12} /> <Highlight text={f.coincidencia} q={qd} /></small>}</td>
                    <td className="small"><span className="mono">{f.real_type}</span><div className="muted">{fmtBytes(f.size)}</div></td>
                    <td className="small">{f.group_name}<div className="muted">{f.sender || '—'}</div></td>
                    <td><StatusBadge status={f.status} /></td>
                    <td><RiskBadge level={f.risk_level} score={f.risk_score} /></td>
                    <td><CategoryChip category={f.category} /></td>
                    <td><FolderBadge carpeta={f.carpeta} /></td>
                    <td className="small muted">{fmtDate(f.detected_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty title="No hay archivos que coincidan">Cambia los filtros o analiza un archivo nuevo.</Empty>}
      </Card>
      {open && <FileDrawer sha={open} categories={cats.data || []} onClose={() => setOpen(null)} onChanged={reloadAll} />}
    </div>
  );
}
