import { useEffect, useState } from 'react';
import { api } from '../api/client.js';
import Icon from './Icon.jsx';
import { Card, CategoryChip, RiskBadge, useToast } from './ui.jsx';
import { FolderPicker } from './Bufete.jsx';
import { fmtBytes } from '../utils/format.js';

const DEST_KEY = 'filemind.export.destino';
const ACTIVE = ['esperando_puente', 'leyendo_chat', 'en_proceso'];

const JOB = {
  esperando_puente: { tone: 'warn', label: 'Esperando al puente' },
  leyendo_chat: { tone: 'warn', label: 'Leyendo el chat…' },
  en_proceso: { tone: 'warn', label: 'Analizando' },
  terminado: { tone: 'ok', label: 'Terminado' },
  cancelado: { tone: 'neutral', label: 'Cancelado' },
  error: { tone: 'bad', label: 'Error' },
};

const ITEM = {
  en_cola: { tone: 'neutral', label: 'En cola' },
  descargando: { tone: 'warn', label: 'Descargando' },
  analizando: { tone: 'warn', label: 'Analizando' },
  seguro: { tone: 'ok', label: 'Seguro' },
  cuarentena: { tone: 'bad', label: 'Cuarentena' },
  error: { tone: 'bad', label: 'No disponible' },
  omitido: { tone: 'neutral', label: 'Omitido' },
};

function readDest() {
  try { return localStorage.getItem(DEST_KEY) || ''; } catch { return ''; }
}

/** Cola de exportación de un chat: cada archivo se analiza, se clasifica y se revisa su seguridad en orden. */
export default function ExportQueue({ jobId, onClose }) {
  const [job, setJob] = useState(null);
  const [dest, setDest] = useState(readDest);
  const [busy, setBusy] = useState(false);
  const [picking, setPicking] = useState(false);
  const toast = useToast();

  const active = !job || ACTIVE.includes(job.estado);
  useEffect(() => {
    let stop = false;
    const load = () => api.exportJob(jobId).then((j) => !stop && setJob(j)).catch((e) => !stop && toast(e.message, 'bad'));
    load();
    if (!active) return () => { stop = true; };
    const t = setInterval(load, 1200);
    return () => { stop = true; clearInterval(t); };
  }, [jobId, active, toast]);

  if (!job) return <Card title="Exportando archivos"><div className="empty"><div className="spinner" /></div></Card>;

  const st = JOB[job.estado] || JOB.en_proceso;
  const c = job.conteo || {};
  const pct = job.total ? Math.round((job.procesados / job.total) * 100) : 0;
  const finished = !active;

  // Ventana de Windows; si no está disponible, explorador de carpetas dentro de la página
  const pick = async () => {
    try {
      const ruta = await api.nativeFolder('Carpeta donde guardar los archivos seguros');
      if (ruta === null) setPicking(true);
      else if (ruta) picked(ruta);
    } catch (e) { toast(e.message, 'bad'); }
  };
  const picked = (ruta) => {
    setPicking(false);
    if (ruta) { setDest(ruta); try { localStorage.setItem(DEST_KEY, ruta); } catch { /* sin almacenamiento */ } }
  };
  const save = async () => {
    setBusy(true);
    try {
      try { localStorage.setItem(DEST_KEY, dest); } catch { /* sin almacenamiento */ }
      const r = await api.saveExport(job.id, dest.trim());
      toast(`${r.archivos} archivo(s) guardados en ${Object.keys(r.por_carpeta).length} carpeta(s)`, 'ok');
      setJob(await api.exportJob(job.id));
    } catch (e) { toast(e.message, 'bad'); } finally { setBusy(false); }
  };
  const cancel = async () => {
    try { setJob(await api.cancelExport(job.id)); } catch (e) { toast(e.message, 'bad'); }
  };

  return (
    <Card
      title={<>Exportar archivos <span className="serif">· {job.chat_nombre}</span></>}
      actions={(
        <div className="row" style={{ gap: 8 }}>
          <span className={`badge ${st.tone}`}>{st.label}</span>
          {active
            ? <button className="btn btn-ghost btn-sm" onClick={cancel}>Cancelar</button>
            : <button className="icon-btn" onClick={onClose} aria-label="Cerrar exportación"><Icon name="x" size={16} /></button>}
        </div>
      )}
    >
      <div className="stack">
        {job.estado === 'esperando_puente' && (
          <p className="small muted">Esperando a que el puente de WhatsApp tome el pedido. Si no avanza, revisa que la cuenta esté vinculada.</p>
        )}
        {job.estado === 'error' && <p className="small" style={{ color: 'var(--bad)' }}>{job.motivo}</p>}

        <div className="export-progress">
          <div className="bar-track"><div className="bar-fill" style={{ width: `${pct}%` }} /></div>
          <span className="small">{job.procesados} de {job.total}</span>
        </div>
        <div className="row small" style={{ flexWrap: 'wrap', gap: 8 }}>
          <span className="badge ok">{c.seguro || 0} seguros</span>
          <span className="badge bad">{c.cuarentena || 0} en cuarentena</span>
          {(c.error || 0) > 0 && <span className="badge neutral">{c.error} no disponibles</span>}
          {(c.en_cola || 0) > 0 && <span className="badge neutral">{c.en_cola} en cola</span>}
          {job.incremental && job.total > 0 && (job.incremental.ya_importado + job.incremental.misma_huella) > 0 && (
            <span className="badge neutral" title="No se volvieron a descargar">
              {job.incremental.nuevos} nuevo(s) · {job.incremental.ya_importado} ya importado(s) · {job.incremental.misma_huella} repetido(s)
            </span>
          )}
        </div>

        {job.total > 0 && (
          <ol className="export-list">
            {job.items.map((it) => {
              const s = ITEM[it.estado] || ITEM.en_cola;
              const working = it.estado === 'descargando' || it.estado === 'analizando';
              return (
                <li key={it.idx} className={`export-item ${working ? 'working' : ''} ${it.estado}`}>
                  <span className="export-idx">{working ? <span className="spinner sm" /> : it.idx + 1}</span>
                  <div className="export-name">
                    <b title={it.nombre}>{it.nombre}</b>
                    <span className="small muted">
                      {fmtBytes(it.tamano)}{it.remitente ? ` · ${it.remitente}` : ''}{it.duplicado ? ' · ya estaba en FileMind' : ''}
                    </span>
                    {it.estado === 'cuarentena' && it.motivo && <span className="small" style={{ color: 'var(--bad)' }}>{it.motivo}</span>}
                    {(it.estado === 'error' || it.estado === 'omitido') && it.motivo && <span className="small muted">{it.motivo}</span>}
                  </div>
                  <div className="export-meta">
                    {it.categoria && <CategoryChip category={it.categoria} />}
                    {it.nivel && <RiskBadge level={it.nivel} score={it.riesgo} />}
                    <span className={`badge ${s.tone}`}>{s.label}</span>
                    {it.estado === 'seguro' && it.sha256 && (
                      <a className="icon-btn" href={api.downloadUrl(it.sha256)} download title="Descargar" aria-label={`Descargar ${it.nombre}`}>
                        <Icon name="download" size={16} />
                      </a>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
        )}
        {finished && job.total === 0 && job.estado === 'terminado' && (
          <p className="small muted">Este chat no tiene archivos en el historial que WhatsApp Web tiene cargado.</p>
        )}

        {finished && (c.seguro || 0) > 0 && (
          <div className="export-save">
            <div className="row" style={{ gap: 10 }}>
              <Icon name="folder" />
              <div style={{ flex: 1 }}>
                <b>Guardar los seguros en mi equipo</b>
                <div className="small muted">FileMind crea una subcarpeta por categoría dentro de la carpeta que escojas. Los archivos en cuarentena no se copian.</div>
              </div>
            </div>
            <div className="toolbar">
              <input className="input" style={{ flex: 1, minWidth: 220 }} placeholder="Carpeta destino, por ejemplo C:\Users\…\Documentos\Expedientes"
                value={dest} onChange={(e) => setDest(e.target.value)} aria-label="Carpeta destino" />
              <button className="btn" onClick={pick}><Icon name="folder" size={16} />Escoger carpeta</button>
              <button className="btn btn-primary" onClick={save} disabled={busy || !dest.trim()}>
                <Icon name="check" size={16} />{busy ? 'Guardando…' : 'Guardar aquí'}
              </button>
            </div>
            {job.guardado && (
              <div className="small" style={{ color: 'var(--ok)' }}>
                Guardados {job.guardado.archivos} archivo(s) en <code>{job.destino}</code>:{' '}
                {Object.entries(job.guardado.por_carpeta).map(([k, v]) => `${k} (${v})`).join(', ')}
              </div>
            )}
            {picking && (
              <FolderPicker initial={dest} title="¿Dónde guardo los archivos seguros?" onClose={() => setPicking(false)} onPick={picked}
                hint="FileMind crea dentro una subcarpeta por categoría y copia ahí cada archivo seguro." />
            )}
            <a className="btn btn-sm btn-ghost" style={{ alignSelf: 'flex-start' }} href={api.exportZipUrl(job.id)} download>
              <Icon name="download" size={16} />O descargar todo en un ZIP organizado
            </a>
          </div>
        )}
      </div>
    </Card>
  );
}
