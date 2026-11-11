// Carpeta del bufete: dónde quedan en el PC los archivos seguros, una subcarpeta por etiqueta.
import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client.js';
import { useApi } from '../hooks/useApi.js';
import { useAuth } from './Auth.jsx';
import Icon from './Icon.jsx';
import { Card, CategoryChip, Loading, Modal, useToast } from './ui.jsx';

/** Selector de carpeta: diálogo de Windows o, si no se puede abrir, un explorador dentro de la página. */
export function FolderPicker({ initial = '', onClose, onPick, title = 'Elegir la carpeta del bufete',
  hint = 'Dentro de esta carpeta FileMind crea una subcarpeta por cada etiqueta (Tutela, Tratados internacionales…) y guarda ahí cada documento seguro.' }) {
  const [path, setPath] = useState(initial);
  const [dir, setDir] = useState(null);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const browse = useCallback(async (ruta) => {
    try { const d = await api.browseFolders(ruta); setDir(d); return d; } catch (e) {
      // la ruta guardada no existe en este servidor: mostrar el inicio
      if (ruta) { try { setDir(await api.browseFolders('')); return null; } catch { /* sigue abajo */ } }
      toast(e.message, 'bad');
      setDir({ ruta: '', padre: null, carpetas: [] });
      return null;
    }
  }, [toast]);
  useEffect(() => { browse(initial); }, [browse, initial]);
  const [hasNative, setHasNative] = useState(false);
  useEffect(() => { api.hasNativeFolder().then(setHasNative); }, []);

  const native = async () => {
    setBusy(true);
    try {
      const ruta = await api.pickBufeteFolder();
      if (ruta) onPick(ruta);
    } catch (e) {
      toast('No se pudo abrir el selector de Windows. Escoja la carpeta en la lista de abajo.', 'bad');
    } finally { setBusy(false); }
  };
  const create = async () => {
    if (!dir?.ruta || !name.trim()) return;
    try { const d = await api.newFolder(dir.ruta, name.trim()); setDir(d); setPath(d.ruta_pc || d.ruta); setName(''); } catch (e) { toast(e.message, 'bad'); }
  };
  // se muestra la ruta como en Windows (C:\...) aunque FileMind corra en Docker; el servidor la traduce
  const go = async (ruta, shown) => {
    setPath(shown || ruta);
    const d = await browse(ruta);
    if (d?.ruta) setPath(d.ruta_pc || d.ruta);
  };

  return (
    <Modal title={title} onClose={onClose} footer={<>
      <button className="btn" onClick={onClose}>Cancelar</button>
      <button className="btn btn-primary" disabled={!path.trim()} onClick={() => onPick(path.trim())}><Icon name="check" size={16} />Usar esta carpeta</button></>}>
      <div className="stack">
        <p className="small muted" style={{ margin: 0 }}>
          {hint} Entra a la carpeta que quieras con un clic y pulsa «Usar esta carpeta».
        </p>
        {(dir?.nativo !== false || hasNative) && (
        <button className="btn" style={{ alignSelf: 'flex-start' }} onClick={native} disabled={busy}>
          <Icon name="monitor" size={16} />{busy ? 'Esperando la ventana de Windows…' : 'Abrir el selector de Windows'}</button>)}
        <div className="field"><label htmlFor="fp-ruta">Carpeta escogida</label>
          <input id="fp-ruta" className="input mono" value={path} onChange={(e) => setPath(e.target.value)} placeholder="C:\Users\…\Documents\Bufete" /></div>
        <div className="folder-browser">
          <div className="folder-path">
            {dir?.padre != null && dir.ruta && (
              <button className="icon-btn" title="Subir un nivel" aria-label="Subir un nivel" onClick={() => go(dir.padre, '')}><Icon name="arrowUp" size={16} /></button>
            )}
            <span className="mono small" title={dir?.ruta}>{dir?.ruta_pc || dir?.ruta || 'Este equipo'}</span>
          </div>
          <div className="folder-list">
            {!dir ? <Loading /> : dir.carpetas.length ? dir.carpetas.map((c) => (
              <button key={c.ruta} className={`folder-row ${path === (c.ruta_pc || c.ruta) ? 'on' : ''}`} onClick={() => go(c.ruta, c.ruta_pc)}>
                <Icon name="folder" size={16} />{c.nombre}<Icon name="chevronRight" size={14} className="muted" style={{ marginLeft: 'auto' }} />
              </button>
            )) : <div className="small muted" style={{ padding: 12 }}>Esta carpeta no tiene subcarpetas.</div>}
          </div>
          {dir?.ruta && (
            <div className="row" style={{ padding: 8, gap: 8 }}>
              <input className="input" style={{ flex: 1, minWidth: 0 }} placeholder="Nueva carpeta aquí, p. ej. Bufete" value={name} onChange={(e) => setName(e.target.value)} />
              <button className="btn btn-sm" onClick={create} disabled={!name.trim()}><Icon name="folderPlus" size={14} />Crear</button>
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}

/** Copia los pendientes de a 20 para mostrar el avance. */
export function useSavePending(onDone) {
  const [progress, setProgress] = useState(null);
  const toast = useToast();
  const run = useCallback(async (total) => {
    let done = 0;
    const folders = {};
    setProgress({ done: 0, total: total || 0 });
    try {
      for (let i = 0; i < 1000; i += 1) {
        const r = await api.savePending(20);
        done += r.guardados;
        Object.entries(r.por_carpeta).forEach(([k, v]) => { folders[k] = (folders[k] || 0) + v; });
        setProgress({ done, total: Math.max(total || 0, done + r.restantes) });
        if (r.errores.length) toast(`${r.errores.length} archivo(s) no se pudieron guardar: ${r.errores[0].motivo}`, 'bad');
        if (!r.restantes || !r.guardados) break;
      }
      const n = Object.keys(folders).length;
      toast(done ? `Listo: ${done} archivo(s) guardados en ${n} subcarpeta(s)` : 'No había archivos pendientes', 'ok');
    } catch (e) { toast(e.message, 'bad'); }
    setProgress(null);
    onDone?.();
  }, [onDone, toast]);
  return { run, progress };
}

/** Configura la carpeta (crea subcarpetas, activa el guardado automático) y descarga lo que falta. */
export function useDownloadToPc(summary, reload) {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const [picking, setPicking] = useState(false);
  const { run, progress } = useSavePending(reload);
  const setFolder = async (ruta, { crear = false } = {}) => {
    try {
      await api.saveBufete({ ruta, crear, preparar: true, auto: true });
    } catch (e) {
      if (/no existe/i.test(e.message) && window.confirm(`La carpeta «${ruta}» no existe. ¿Crearla?`)) return setFolder(ruta, { crear: true });
      toast(e.message, 'bad');
      return false;
    }
    setPicking(false);
    toast('Carpeta lista: se crearon las subcarpetas por etiqueta y el guardado automático quedó activado', 'ok');
    await run(summary?.faltan);
    return true;
  };
  // Primero la ventana de Windows; si no está disponible, el explorador dentro de la página
  const choose = async () => {
    try {
      const ruta = await api.nativeFolder('Escoge la carpeta del bufete');
      if (ruta === null) setPicking(true);
      else if (ruta) await setFolder(ruta, { crear: true });
    } catch (e) { toast(e.message, 'bad'); }
  };
  const start = () => {
    if (summary?.configurada) return run(summary.faltan);
    if (!isAdmin) { toast('El administrador debe escoger primero la carpeta del bufete en Configuración.', 'bad'); return null; }
    choose();
    return null;
  };
  const picker = picking ? <FolderPicker initial={summary?.ruta_pc || summary?.ruta || ''} onClose={() => setPicking(false)} onPick={(r) => setFolder(r)} /> : null;
  return { start, progress, picker, openPicker: choose };
}

export function SaveProgress({ progress }) {
  if (!progress) return null;
  const pct = progress.total ? Math.round((progress.done / progress.total) * 100) : 0;
  return (
    <div className="export-progress" role="status">
      <div className="bar-track"><div className="bar-fill" style={{ width: `${pct}%` }} /></div>
      <span className="small">Guardando {progress.done} de {progress.total}…</span>
    </div>
  );
}

/** Tarjeta «Carpeta del bufete»: guardados, faltan, dónde se guardan y botón «Descargar a mi PC». */
export function BufeteCard({ compact = false, onChanged }) {
  const { isAdmin } = useAuth();
  const sum = useApi(api.bufeteSummary, [], { interval: 15000 });
  const toast = useToast();
  const reload = useCallback(() => { sum.reload(); onChanged?.(); }, [sum, onChanged]); // eslint-disable-line react-hooks/exhaustive-deps
  const dl = useDownloadToPc(sum.data, reload);
  const s = sum.data;
  const clasificados = s ? s.guardados + s.faltan : 0;
  const pct = clasificados ? Math.round((s.guardados / clasificados) * 100) : 0;
  const toggleAuto = async (auto) => {
    try { await api.saveBufete({ auto }); toast(auto ? 'Los archivos nuevos se guardarán solos en su carpeta' : 'Guardado automático apagado', 'ok'); sum.reload(); }
    catch (e) { toast(e.message, 'bad'); }
  };
  return (
    <Card className="bufete-card" title={<><Icon name="monitor" size={18} /> Carpeta del bufete en este PC</>}
      actions={isAdmin && s?.configurada ? <Link className="btn btn-sm btn-ghost" to="/configuracion#carpeta">Ajustar carpetas</Link> : null}>
      {!s ? <Loading /> : (
        <div className="stack">
          <div className="bufete-stats">
            <div><b className="ok-text">{s.guardados}</b><span>guardados en el PC</span></div>
            <div><b className="warn-text">{s.faltan}</b><span>faltan por guardar</span></div>
            {!compact && <div><b className="muted">{s.cuarentena}</b><span>en cuarentena (no se guardan)</span></div>}
          </div>
          <div className="bar-track" title={`${pct} % guardado`}><div className="bar-fill ok" style={{ width: `${pct}%` }} /></div>
          {s.configurada ? (
            <div className="small">
              Se guardan en <code className="path">{s.ruta_pc || s.ruta}</code>, cada uno en la subcarpeta de su etiqueta.
            </div>
          ) : (
            <div className="small muted">
              Todavía no hay carpeta. Al pulsar «Descargar a mi PC» escoge una carpeta y FileMind crea dentro una subcarpeta por etiqueta.
            </div>
          )}
          {isAdmin && s.configurada && (
            <label className="switch-row">
              <input type="checkbox" className="switch" checked={s.auto} onChange={(e) => toggleAuto(e.target.checked)} />
              <span><b>Guardar automáticamente los archivos nuevos</b><br /><span className="small muted">
                {s.auto ? 'Activado: cada archivo seguro se copia a su subcarpeta apenas se clasifica.' : 'Apagado: los archivos nuevos quedan como «Falta guardar».'}</span></span>
            </label>
          )}
          <SaveProgress progress={dl.progress} />
          <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
            <button className="btn btn-primary" onClick={dl.start} disabled={!!dl.progress || (s.configurada && !s.faltan)}>
              <Icon name="download" size={16} />{s.configurada && !s.faltan ? 'Todo está guardado' : `Descargar a mi PC${s.faltan ? ` (${s.faltan})` : ''}`}</button>
            {isAdmin && <button className="btn" onClick={dl.openPicker}><Icon name="folder" size={16} />{s.configurada ? 'Cambiar carpeta…' : 'Elegir carpeta…'}</button>}
            {compact && <Link className="btn btn-ghost" to="/archivos?carpeta=falta">Ver los que faltan</Link>}
          </div>
        </div>
      )}
      {dl.picker}
    </Card>
  );
}

/** Configuración (solo admin): carpeta, guardado automático y nombre de la subcarpeta de cada etiqueta. */
export function BufeteSettings() {
  const cfg = useApi(api.bufete, []);
  const [names, setNames] = useState({});
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const dl = useDownloadToPc(cfg.data ? { configurada: !!cfg.data.ruta, ruta: cfg.data.ruta, faltan: 0 } : null, cfg.reload);
  useEffect(() => { if (cfg.data) setNames(Object.fromEntries(cfg.data.categorias.map((c) => [c.nombre, c.subcarpeta]))); }, [cfg.data]);
  const d = cfg.data;
  const missing = d ? d.categorias.filter((c) => !c.existe).length : 0;
  const changed = d && d.categorias.some((c) => (names[c.nombre] || '') !== c.subcarpeta);

  const act = async (fn, ok) => {
    setBusy(true);
    try { const r = await fn(); toast(ok(r), 'ok'); cfg.reload(); } catch (e) { toast(e.message, 'bad'); } finally { setBusy(false); }
  };
  return (
    <Card title={<span id="carpeta"><Icon name="folder" size={18} /> Carpeta del bufete</span>}>
      {!d ? <Loading /> : (
        <div className="stack">
          <p className="small muted" style={{ margin: 0 }}>
            Cada documento seguro se copia a una carpeta de este PC, dentro de la subcarpeta de su etiqueta. Los archivos en cuarentena nunca se copian.
            Si cambias la etiqueta de un documento, su copia se mueve sola a la subcarpeta nueva.
          </p>
          <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
            <code className="path" style={{ flex: 1, minWidth: 200 }}>{d.ruta || 'Sin carpeta escogida'}</code>
            <button className="btn" onClick={dl.openPicker}><Icon name="folder" size={16} />{d.ruta ? 'Cambiar carpeta…' : 'Elegir carpeta…'}</button>
          </div>
          {d.ruta && !d.carpeta_existe && <div className="alert medio small">La carpeta ya no existe en el PC. Escoge otra o crea las carpetas de nuevo.</div>}
          {d.ruta && (
            <label className="switch-row">
              <input type="checkbox" className="switch" checked={d.auto} onChange={(e) => act(() => api.saveBufete({ auto: e.target.checked }), () => (e.target.checked ? 'Guardado automático activado' : 'Guardado automático apagado'))} />
              <span><b>Guardar automáticamente los archivos nuevos</b><br /><span className="small muted">Cada archivo clasificado se copia a su subcarpeta en cuanto termina el análisis.</span></span>
            </label>
          )}
          <div className="table-wrap">
            <table className="table stack-sm">
              <thead><tr><th>Etiqueta</th><th>Subcarpeta en el PC</th><th>Estado</th></tr></thead>
              <tbody>
                {d.categorias.map((c) => (
                  <tr key={c.nombre}>
                    <td><CategoryChip category={c.nombre} title={c.descripcion} /><div className="small muted" style={{ marginTop: 4 }}>{c.descripcion}</div></td>
                    <td><input className="input" value={names[c.nombre] || ''} aria-label={`Subcarpeta de ${c.etiqueta}`}
                      onChange={(e) => setNames({ ...names, [c.nombre]: e.target.value })} /></td>
                    <td>{!d.ruta ? <span className="muted small">—</span> : c.existe
                      ? <span className="badge ok"><Icon name="folderCheck" size={13} />Ya existe</span>
                      : <span className="badge warn">Falta crearla</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
            <button className="btn btn-primary" disabled={busy || !changed} onClick={() => act(() => api.saveBufete({ subcarpetas: names, preparar: !!d.ruta }), () => 'Nombres de subcarpetas guardados')}>
              <Icon name="check" size={16} />Guardar nombres</button>
            <button className="btn" disabled={busy || !d.ruta || !missing} onClick={() => act(api.createBufeteFolders, (r) => `Se crearon ${r.creadas.length} carpeta(s)`)}>
              <Icon name="folderPlus" size={16} />Crear las carpetas que faltan{missing ? ` (${missing})` : ''}</button>
          </div>
          <div className="small muted">¿El bufete ya tiene sus carpetas? Escribe aquí el nombre exacto de cada una y FileMind usará esas mismas.</div>
        </div>
      )}
      <SaveProgress progress={dl.progress} />
      {dl.picker}
    </Card>
  );
}
