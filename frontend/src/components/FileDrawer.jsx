import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import Icon from './Icon.jsx';
import SecurityControls from './SecurityControls.jsx';
import { api } from '../api/client.js';
import { CategoryChip, FolderBadge, Loading, RiskBadge, RiskGauge, StatusBadge, useToast } from './ui.jsx';
import { catLabel, eventLabel, fmtBytes, fmtDate, fmtPct } from '../utils/format.js';

const PHASES = [
  ['hash_calculado', 'Huella SHA-256'],
  ['fase1_estatico', 'Fase 1 · Estático'],
  ['fase2_heuristico', 'Fase 2 · Heurístico'],
  ['controles_seguridad', 'Controles de ciberseguridad'],
  ['fase3_sandbox', 'Fase 3 · Aislado'],
  ['fase4_puntaje', 'Fase 4 · Puntaje'],
];

function phaseSummary(ev) {
  const d = ev.detail || {};
  switch (ev.event) {
    case 'hash_calculado': return <code>{d.value?.slice(0, 32)}…</code>;
    case 'fase1_estatico':
      return `Tipo real: ${d.real_type} · extensión .${d.declared_ext || '—'}${d.extension_mismatch ? ' (no coincide)' : ''}`
        + `${d.double_extension ? ' · doble extensión' : ''} · firmas: ${d.signature_query?.malicious ? `malware conocido (${d.signature_query.family})` : 'sin coincidencias'}`;
    case 'fase2_heuristico': return d.findings?.length ? d.findings.join(' · ') : 'Sin patrones de phishing ni ransomware';
    case 'controles_seguridad': {
      const cs = d.controles || [];
      const bad = cs.filter((c) => c.estado === 'alerta').length;
      const warn = cs.filter((c) => c.estado === 'aviso').length;
      const used = cs.filter((c) => c.estado !== 'no_aplica').length;
      return `${used} controles aplicados · ${bad} con riesgo · ${warn} para revisar`;
    }
    case 'fase3_sandbox': {
      const iso = d.isolation || {};
      return `Estado: ${d.status} · aislamiento ${iso.backend || '—'} · red bloqueada: ${iso.network_blocked ? 'sí' : 'no'} · escritura bloqueada: ${iso.fs_write_blocked ? 'sí' : 'no'}`;
    }
    case 'fase4_puntaje':
      return `Puntaje ${d.score} (${d.level}) · reglas ${d.rule_score}${d.ml ? ` · IA: P(malicioso) ${fmtPct(1 - d.ml.legitimo)}` : ''}`;
    default: return '';
  }
}

export default function FileDrawer({ sha, categories, onClose, onChanged }) {
  const [rec, setRec] = useState(null);
  const [cat, setCat] = useState('');
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const load = () => api.file(sha).then((r) => { setRec(r); setCat(r.category || ''); });
  useEffect(() => { load(); }, [sha]); // eslint-disable-line react-hooks/exhaustive-deps

  const saveCategory = async () => {
    setBusy(true);
    try {
      await api.correct(sha, cat);
      toast(`Etiqueta cambiada a «${catLabel(cat)}». Si estaba en la carpeta del PC, se movió a su nueva subcarpeta.`, 'ok');
      await load();
      onChanged?.();
    } catch (e) { toast(e.message, 'error'); } finally { setBusy(false); }
  };

  const saveToPc = async () => {
    setBusy(true);
    try {
      const r = await api.saveFileToBufete(sha);
      toast(`Guardado en la subcarpeta «${r.subcarpeta}»`, 'ok');
      await load();
      onChanged?.();
    } catch (e) { toast(e.message, 'bad'); } finally { setBusy(false); }
  };

  const events = rec?.eventos || [];
  const byEvent = Object.fromEntries(events.map((e) => [e.event, e]));
  const risk = rec?.report?.risk;
  const topic = rec?.report?.topic;

  // Portal al <body>: así el panel queda por encima de la barra superior en cualquier página
  return createPortal(
    <>
      <div className="overlay" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="Detalle del archivo">
        <div className="drawer-h">
          <Icon name="files" />
          <div style={{ minWidth: 0 }}>
            <h3 style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{rec?.original_name || 'Cargando…'}</h3>
            {rec && <div className="small muted">{rec.group_name} · {rec.sender || 'remitente desconocido'} · {fmtDate(rec.detected_at)}</div>}
          </div>
          <div className="spacer" />
          {rec && <a className="btn btn-sm" href={api.reportUrl(sha)} download title="Reporte PDF del análisis"><Icon name="pdf" size={16} /><span className="hide-xs">Reporte PDF</span></a>}
          <button className="icon-btn" onClick={onClose} aria-label="Cerrar"><Icon name="x" /></button>
        </div>
        {!rec ? <Loading /> : (
          <div className="drawer-b">
            <div className="card card-b row" style={{ gap: 24, flexWrap: 'wrap' }}>
              <RiskGauge score={rec.risk_score} level={rec.risk_level} />
              <div className="stack" style={{ gap: 8, flex: 1 }}>
                <div className="row"><StatusBadge status={rec.status} /><RiskBadge level={rec.risk_level} /></div>
                <div className="small"><b>Categoría:</b> <CategoryChip category={rec.category} /> {rec.category_confidence != null && <span className="muted">confianza {fmtPct(rec.category_confidence, 0)}</span>}</div>
                <div className="small muted">Tipo real: {rec.real_type} · {fmtBytes(rec.size)} · protocolo en {rec.protocol_seconds?.toFixed(2)} s</div>
                <div className="small muted mono">SHA-256 {rec.sha256}</div>
              </div>
            </div>

            <div className={`alert ${rec.risk_level}`}>{rec.notification}</div>

            {rec.carpeta && (
              <section className="card card-b row" style={{ gap: 12, flexWrap: 'wrap' }}>
                <Icon name="monitor" />
                <div style={{ flex: 1, minWidth: 200 }}>
                  <div className="row" style={{ gap: 8 }}><b>Carpeta del bufete</b><FolderBadge carpeta={rec.carpeta} /></div>
                  <div className="small muted" style={{ marginTop: 4, wordBreak: 'break-all' }}>
                    {rec.carpeta.estado === 'guardado' && <>Guardado en <code className="path">{rec.carpeta.ruta}</code></>}
                    {rec.carpeta.estado === 'falta' && <>Todavía no está en el PC. Irá a la subcarpeta «{rec.carpeta.subcarpeta}».</>}
                    {rec.carpeta.estado === 'sin_carpeta' && <>Aún no hay carpeta del bufete. El administrador la escoge en Configuración.</>}
                    {rec.carpeta.estado === 'cuarentena' && <>Los archivos peligrosos nunca se copian al PC.</>}
                  </div>
                </div>
                {rec.carpeta.estado === 'falta' && (
                  <button className="btn btn-primary btn-sm" disabled={busy} onClick={saveToPc}><Icon name="download" size={14} />Guardar en el PC</button>
                )}
              </section>
            )}

            <section className="card">
              <div className="card-h"><h3>Protocolo de seguridad</h3></div>
              <div className="card-b timeline">
                {PHASES.map(([key, label], i) => {
                  const ev = byEvent[key];
                  const bad = (key === 'fase4_puntaje' && rec.risk_level === 'alto')
                    || (key === 'controles_seguridad' && ev?.detail?.controles?.some((c) => c.estado === 'alerta'));
                  return (
                    <div className="tl-item" key={key}>
                      <div className={`tl-dot ${ev ? (bad ? 'bad' : 'ok') : ''}`}>{ev ? <Icon name={bad ? 'warning' : 'check'} size={14} /> : i}</div>
                      <div><div className="tl-title">{label}</div><div className="tl-body">{ev ? phaseSummary(ev) : 'Omitida'}</div></div>
                    </div>
                  );
                })}
              </div>
            </section>

            <section className="card">
              <div className="card-h"><h3>Controles de ciberseguridad</h3><div className="spacer" /><span className="small muted">qué encontró cada revisión</span></div>
              <div className="card-b"><SecurityControls controls={rec.report?.controls} /></div>
            </section>

            {risk && (
              <section className="card">
                <div className="card-h"><h3>Cómo se calculó el puntaje</h3><div className="spacer" /><span className="small muted">{risk.formula}</span></div>
                <div className="card-b stack">
                  <div className="row small"><b>Reglas:</b> {risk.rule_score} · <b>IA:</b> {risk.p_malicious != null ? fmtPct(risk.p_malicious) : '—'} malicioso{risk.threat_type ? ` (${risk.threat_type})` : ''}</div>
                  {risk.rule_contributions?.length ? (
                    <table className="table"><thead><tr><th>Indicador</th><th className="num">Puntos</th></tr></thead>
                      <tbody>{risk.rule_contributions.map(([k, v]) => <tr key={k}><td className="mono">{k}</td><td className="num">+{v}</td></tr>)}</tbody></table>
                  ) : <div className="small muted">Ningún indicador de riesgo.</div>}
                  {risk.floors?.length > 0 && <div className="small">Piso aplicado: {risk.floors.join(', ')}</div>}
                </div>
              </section>
            )}

            {rec.status === 'clasificado' && (
              <section className="card">
                <div className="card-h"><h3>Etiqueta del documento</h3><div className="spacer" /><CategoryChip category={rec.category} /></div>
                <div className="card-b stack">
                  {topic?.top && (
                    <div className="bars">
                      {topic.top.map(([c, p]) => (
                        <div className="bar-row" key={c}><span>{catLabel(c)}</span>
                          <div className="bar-track"><div className="bar-fill" style={{ width: `${p * 100}%` }} /></div>
                          <span className="num small">{Math.round(p * 100)}%</span></div>
                      ))}
                    </div>
                  )}
                  {topic?.explicacion?.length > 0 && (
                    <div className="small">
                      <b>Por qué {catLabel(topic.predicted || rec.category)}:</b> estas palabras del documento son las que más pesaron.
                      <div className="row" style={{ flexWrap: 'wrap', gap: 6, marginTop: 6 }}>
                        {topic.explicacion.map((e) => (
                          <span className="chip" key={e.termino} title={`aporte ${e.peso}`}>{e.termino} <span className="muted">{e.porcentaje}%</span></span>
                        ))}
                      </div>
                    </div>
                  )}
                  <div className="small"><b>¿La etiqueta no es la correcta?</b> Escoge la correcta: el documento se mueve a esa carpeta y la IA aprende de la corrección.</div>
                  <div className="cat-picker" role="radiogroup" aria-label="Etiqueta correcta">
                    {categories.map((c) => (
                      <CategoryChip key={c.nombre} category={c.nombre} active={cat === c.nombre} title={c.descripcion} onClick={() => setCat(c.nombre)} />
                    ))}
                  </div>
                  <div className="toolbar">
                    <button className="btn btn-primary" disabled={busy || cat === rec.category} onClick={saveCategory}>
                      <Icon name="check" size={16} />{cat === rec.category ? 'Etiqueta actual' : `Cambiar a «${catLabel(cat)}»`}</button>
                    <a className="btn" href={api.downloadUrl(sha)}><Icon name="download" size={16} />Descargar</a>
                  </div>
                </div>
              </section>
            )}

            <details className="card card-b">
              <summary style={{ cursor: 'pointer', fontWeight: 600 }}>Historial completo ({events.length} eventos)</summary>
              <table className="table" style={{ marginTop: 12 }}>
                <tbody>{[...events].reverse().map((e) => (
                  <tr key={e.id}><td className="small muted" style={{ whiteSpace: 'nowrap' }}>{fmtDate(e.ts)}</td><td className="small">{eventLabel(e.event)}</td></tr>
                ))}</tbody>
              </table>
            </details>
          </div>
        )}
      </aside>
    </>,
    document.body,
  );
}
