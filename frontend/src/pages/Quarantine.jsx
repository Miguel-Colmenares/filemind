import { useState } from 'react';
import { api } from '../api/client.js';
import { useAuth } from '../components/Auth.jsx';
import { useApi } from '../hooks/useApi.js';
import FileDrawer from '../components/FileDrawer.jsx';
import Icon from '../components/Icon.jsx';
import { Card, Empty, Loading, Modal, RiskBadge, useToast } from '../components/ui.jsx';
import { catLabel, fmtDate } from '../utils/format.js';

function ReleaseModal({ file, categories, onClose, onDone }) {
  const [categoria, setCategoria] = useState(categories[0]?.nombre || 'Otros');
  const [motivo, setMotivo] = useState('');
  const [ok, setOk] = useState(false);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const submit = async () => {
    setBusy(true);
    try {
      await api.release(file.sha256, categoria, motivo);
      toast(`«${file.original_name}» se liberó y se guardó en ${catLabel(categoria)}`, 'ok');
      onDone();
    } catch (e) { toast(e.message, 'bad'); } finally { setBusy(false); }
  };
  return (
    <Modal title="Liberar archivo de la cuarentena" onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>Cancelar</button>
        <button className="btn btn-danger" disabled={busy || !ok || motivo.trim().length < 10} onClick={submit}>Liberar archivo</button>
      </>}>
      <div className="stack">
        <div className="alert alto">«{file.original_name}» obtuvo {file.risk_score} de 100. Libéralo solo si confirmaste con quien lo envió, por otro medio, que el archivo es legítimo.</div>
        <div className="field"><label htmlFor="rel-cat">Carpeta de destino</label>
          <select id="rel-cat" className="select" value={categoria} onChange={(e) => setCategoria(e.target.value)}>
            {categories.map((c) => <option key={c.nombre} value={c.nombre}>{catLabel(c.nombre)}</option>)}
          </select></div>
        <div className="field"><label htmlFor="rel-mot">Motivo (queda en la auditoría)</label>
          <textarea id="rel-mot" className="textarea" rows={3} value={motivo} onChange={(e) => setMotivo(e.target.value)}
            placeholder="Ej.: confirmado por teléfono con el remitente; es la factura de septiembre" />
          <span className="small muted">Mínimo 10 caracteres.</span></div>
        <label className="row small"><input type="checkbox" checked={ok} onChange={(e) => setOk(e.target.checked)} /> Entiendo el riesgo y asumo la liberación.</label>
      </div>
    </Modal>
  );
}

export default function Quarantine() {
  const { isAdmin } = useAuth();
  const files = useApi(() => api.files({ estado: 'cuarentena', limite: 500 }), [], { interval: 15000 });
  const cats = useApi(api.categories, []);
  const [release, setRelease] = useState(null);
  const [open, setOpen] = useState(null);
  const toast = useToast();

  const remove = async (f) => {
    if (!window.confirm(`¿Eliminar definitivamente «${f.original_name}»? No se puede deshacer.`)) return;
    try { await api.remove(f.sha256); toast('Archivo eliminado de la cuarentena', 'ok'); files.reload(); } catch (e) { toast(e.message, 'bad'); }
  };

  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="alert medio small">Los archivos en cuarentena están cifrados, sin su extensión original y con permisos de solo lectura. No se pueden abrir ni descargar desde el panel (RF8).</div>
      <Card pad={false}>
        {files.loading ? <Loading /> : files.data?.length ? (
          <div className="table-wrap">
            <table className="table stack-sm">
              <thead><tr><th>Archivo</th><th>Grupo · remitente</th><th>Riesgo</th><th>Motivos</th><th>Recibido</th><th /></tr></thead>
              <tbody>
                {files.data.map((f) => (
                  <tr key={f.sha256}>
                    <td className="file-name clickable" onClick={() => setOpen(f.sha256)}>{f.original_name}</td>
                    <td className="small">{f.group_name}<div className="muted">{f.sender || '—'}</div></td>
                    <td><RiskBadge level={f.risk_level} score={f.risk_score} /></td>
                    <td className="small" style={{ maxWidth: 380 }}>{(f.reasons || []).slice(0, 2).join(' ')}</td>
                    <td className="small muted">{fmtDate(f.detected_at)}</td>
                    <td><div className="row" style={{ justifyContent: 'flex-end' }}>
                      <a className="btn btn-sm btn-ghost" href={api.reportUrl(f.sha256)} download title="Reporte PDF" aria-label={`Reporte PDF de ${f.original_name}`}><Icon name="pdf" size={14} /></a>
                      {isAdmin && <button className="btn btn-sm" onClick={() => setRelease(f)}><Icon name="unlock" size={14} />Liberar</button>}
                      {isAdmin && <button className="btn btn-sm btn-ghost" onClick={() => remove(f)} aria-label="Eliminar"><Icon name="trash" size={14} /></button>}
                    </div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty icon="shield" title="La cuarentena está vacía">Ningún archivo ha superado el umbral de riesgo.</Empty>}
      </Card>
      {release && <ReleaseModal file={release} categories={cats.data || []} onClose={() => setRelease(null)} onDone={() => { setRelease(null); files.reload(); }} />}
      {open && <FileDrawer sha={open} categories={cats.data || []} onClose={() => setOpen(null)} onChanged={files.reload} />}
    </div>
  );
}
