import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client.js';
import { useApi } from '../hooks/useApi.js';
import Icon from '../components/Icon.jsx';
import { Card, Loading, useToast } from '../components/ui.jsx';
import ExportQueue from '../components/ExportQueue.jsx';

const JOB_KEY = 'filemind.export.job';

const ESTADO = {
  sin_puente: { tone: 'neutral', label: 'Puente apagado' },
  iniciando: { tone: 'warn', label: 'Conectando…' },
  esperando_qr: { tone: 'warn', label: 'Esperando vinculación' },
  conectado: { tone: 'ok', label: 'Conectado' },
  reconectando: { tone: 'warn', label: 'Reconectando…' },
  desconectado: { tone: 'bad', label: 'Desconectado' },
};

function Health({ s }) {
  if (!s) return null;
  return (
    <div className="small muted" style={{ borderTop: '1px solid var(--border)', paddingTop: 8 }}>
      Reconexiones automáticas: <b>{s.reconexiones}</b>
      {s.cola_pendiente > 0 && <> · <b>{s.cola_pendiente}</b> archivo(s) esperando a FileMind</>}
      {s.conectado_desde && <> · conectado desde {new Date(s.conectado_desde).toLocaleString('es-CO')}</>}
      {s.ultimo_error && <div title={s.ultimo_error}>Último problema: {s.ultimo_error.slice(0, 90)}</div>}
    </div>
  );
}

function Connection({ wa, onChange }) {
  const st = ESTADO[wa?.estado] || ESTADO.sin_puente;
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const startBridge = async () => {
    setBusy(true);
    try {
      const r = await api.startBridge();
      toast(r.ya_encendido ? 'El puente ya estaba encendido; espera unos segundos' : 'Encendiendo WhatsApp… tarda alrededor de un minuto en cargar los chats', 'ok');
      onChange?.();
    } catch (err) { toast(err.message, 'bad'); } finally { setBusy(false); }
  };
  const unlink = async () => {
    if (!window.confirm('¿Desvincular este número? WhatsApp cerrará la sesión en el puente y aparecerá un código QR nuevo para vincular otro número. Los archivos ya analizados no se borran.')) return;
    setBusy(true);
    try { await api.unlinkWhatsapp(); toast('Desvinculando… en unos segundos aparecerá el código QR', 'ok'); onChange?.(); }
    catch (err) { toast(err.message, 'bad'); } finally { setBusy(false); }
  };
  return (
    <Card title={<><span className="step-n">1</span>Conectar WhatsApp</>} actions={<span className={`badge ${st.tone}`}>{st.label}</span>}>
      {!wa ? <Loading /> : (
        <div className="stack small">
          {wa.estado === 'esperando_qr' && wa.qr && (
            <>
              <img src={wa.qr} alt="Código QR para vincular WhatsApp" width="240" height="240"
                style={{ alignSelf: 'center', background: '#fff', padding: 8, borderRadius: 8 }} />
              <p>En el celular del bufete abre WhatsApp → <b>Dispositivos vinculados</b> → <b>Vincular un dispositivo</b> y escanea el código.</p>
            </>
          )}
          {wa.estado === 'conectado' && <p>Cuenta vinculada: <b>{wa.cuenta || 'WhatsApp'}</b>. Escoge en el paso 2 los chats cuyos archivos quieres analizar.</p>}
          {wa.estado === 'sin_puente' && (
            <>
              <p style={{ margin: 0 }}><b>WhatsApp está apagado.</b> El «puente» es el programa que lee tus chats de WhatsApp y le pasa los archivos
                a FileMind. Enciéndelo y en unos segundos aparecerá el código QR (o se conectará solo si ya estaba vinculado).</p>
              <button className="btn btn-primary" style={{ alignSelf: 'flex-start' }} disabled={busy} onClick={startBridge}>
                <Icon name="whatsapp" size={16} />{busy ? 'Encendiendo…' : 'Encender WhatsApp'}</button>
              <small className="muted">Si el botón no funciona: en la carpeta <code>whatsapp-gateway</code> ejecuta <code>npm start</code>.</small>
            </>
          )}
          {(wa.estado === 'iniciando' || wa.estado === 'desconectado') && <p>Esperando al puente de WhatsApp…</p>}
          {wa.estado === 'reconectando' && (
            <p>La conexión con WhatsApp Web se cayó y el puente la está recuperando solo
              {wa.reintento_en_s ? <> (siguiente intento en {wa.reintento_en_s} s)</> : null}. Los archivos que lleguen mientras tanto no se pierden.</p>
          )}
          {['conectado', 'reconectando', 'desconectado'].includes(wa.estado) && (
            <button className="btn btn-sm" style={{ alignSelf: 'flex-start' }} disabled={busy} onClick={unlink}>
              <Icon name="logout" size={14} />Desvincular y usar otro número</button>
          )}
          {wa.estado !== 'sin_puente' && <Health s={wa.salud} />}
        </div>
      )}
    </Card>
  );
}

export default function Groups() {
  const groups = useApi(api.groups, []);
  const wa = useApi(api.whatsapp, [], { interval: 4000 });
  const counts = useApi(api.groupCounts, [], { interval: 30000 });
  const [list, setList] = useState([]);
  const [name, setName] = useState('');
  const [filter, setFilter] = useState('');
  const [busy, setBusy] = useState(false);
  const [jobId, setJobId] = useState(() => { try { return localStorage.getItem(JOB_KEY) || ''; } catch { return ''; } });
  const toast = useToast();
  useEffect(() => { if (groups.data) setList(groups.data); }, [groups.data]);
  useEffect(() => {
    try { if (jobId) localStorage.setItem(JOB_KEY, jobId); else localStorage.removeItem(JOB_KEY); } catch { /* ignorar */ }
  }, [jobId]);
  // Si el servidor se reinició, la exportación guardada ya no existe
  useEffect(() => { if (jobId) api.exportJob(jobId).catch(() => setJobId('')); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const connected = wa.data?.estado === 'conectado';
  const startExport = async (chat) => {
    try {
      const h = await api.exportHistory(chat.id).catch(() => null);
      const job = await api.startExport(chat, false);
      setJobId(job.id);
      toast(h?.importados ? `Trayendo solo lo nuevo de «${chat.nombre}»` : `Trayendo los archivos anteriores de «${chat.nombre}»`, 'ok');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (e) { toast(e.message, 'bad'); }
  };

  const saved = groups.data || [];
  const dirty = JSON.stringify([...list].sort()) !== JSON.stringify([...saved].sort());
  const added = list.filter((g) => !saved.includes(g)).length;
  const removed = saved.filter((g) => !list.includes(g)).length;
  const toggle = (n) => setList(list.includes(n) ? list.filter((x) => x !== n) : [...list, n]);
  const add = () => {
    const n = name.trim();
    if (n && !list.includes(n)) { setList([...list, n]); toast(`«${n}» agregado. Pulsa «Guardar» para empezar a analizarlo.`, 'ok'); }
    setName('');
  };
  const save = async () => {
    setBusy(true);
    try { await api.saveGroups(list); toast('Listo: FileMind analizará y clasificará los archivos nuevos de esos chats', 'ok'); groups.reload(); }
    catch (e) { toast(e.message, 'bad'); } finally { setBusy(false); }
  };

  const f = filter.trim().toLowerCase();
  const match = (n) => !f || n.toLowerCase().includes(f);
  // WhatsApp a veces deja espacios al final del nombre («Análisis de Sistema »): se comparan sin ellos
  const bridgeChats = useMemo(() => (wa.data?.chats || []).map((c) => ({ ...c, nombre: c.nombre.trim() })), [wa.data]);
  const byName = useMemo(() => Object.fromEntries(bridgeChats.map((c) => [c.nombre, c])), [bridgeChats]);
  const analyzing = list.filter(match).map((n) => byName[n] || { id: null, nombre: n, grupo: true, manual: true });
  const available = bridgeChats.filter((c) => !list.includes(c.nombre) && match(c.nombre));
  const cnt = counts.data || {};

  const row = (c, on) => (
    <label key={`${on ? 'a' : 'd'}-${c.id || c.nombre}`} className={`chat-row pick-chat ${on ? 'on' : ''}`}>
      <input type="checkbox" className="big-check" checked={on} onChange={() => toggle(c.nombre)}
        aria-label={`${on ? 'Dejar de analizar' : 'Analizar'} ${c.nombre}`} />
      <Icon name={c.grupo ? 'whatsapp' : 'user'} size={16} />
      <span className="chat-name">
        <b>{c.nombre}</b>
        <small className="muted">{c.manual ? 'Escrito a mano' : c.grupo ? 'Grupo' : 'Chat privado'}
          {cnt[c.nombre] ? ` · ${cnt[c.nombre]} archivo(s) analizados` : ''}</small>
      </span>
      {c.id && connected && (
        <button type="button" className="btn btn-sm btn-ghost" title="Descarga y clasifica los archivos que ya estaban en el chat"
          onClick={(e) => { e.preventDefault(); startExport(c); }}>
          <Icon name="download" size={14} /><span className="hide-xs">Traer anteriores</span></button>
      )}
    </label>
  );

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div className="steps-intro small">
        <span><span className="step-n">1</span>Conecta WhatsApp</span><Icon name="chevronRight" size={14} className="muted" />
        <span><span className="step-n">2</span>Marca los chats</span><Icon name="chevronRight" size={14} className="muted" />
        <span><span className="step-n">3</span>Guarda</span><Icon name="chevronRight" size={14} className="muted" />
        <span>Los archivos nuevos se analizan y clasifican solos</span>
      </div>
      {jobId && <ExportQueue key={jobId} jobId={jobId} onClose={() => setJobId('')} />}
      <div className="grid g-main">
        <Card title={<><span className="step-n">2</span>Escoge de qué chats analizar archivos</>}>
          {groups.loading ? <Loading /> : (
            <div className="stack">
              <div className="search" style={{ flex: 'none', maxWidth: 'none' }}>
                <Icon name="search" size={16} />
                <input className="input" type="search" placeholder="Buscar un chat o grupo" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Buscar chat" />
              </div>

              <div className="chat-section">
                <div className="chat-section-h"><Icon name="check" size={14} />Analizando <span className="cat-count">{list.length}</span></div>
                {analyzing.length ? analyzing.map((c) => row(c, true))
                  : <div className="small muted chat-empty">{f ? 'Ningún chat analizado coincide.' : 'Todavía no hay chats. Márcalos abajo o escribe su nombre.'}</div>}
              </div>

              <div className="chat-section">
                <div className="chat-section-h"><Icon name="whatsapp" size={14} />Disponibles en tu WhatsApp
                  <span className="cat-count">{bridgeChats.filter((c) => !list.includes(c.nombre)).length}</span></div>
                {!bridgeChats.length ? (
                  <div className="small muted chat-empty">
                    {connected ? 'Cargando la lista de chats…' : 'Conecta WhatsApp (paso 1) y aquí aparecerán todos tus chats para marcarlos.'}
                  </div>
                ) : available.length ? (
                  <div className="chat-scroll">{available.map((c) => row(c, false))}</div>
                ) : <div className="small muted chat-empty">Ningún chat disponible coincide con la búsqueda.</div>}
              </div>

              <div className="field">
                <label htmlFor="chat-manual">¿No aparece el chat? Escribe su nombre exacto</label>
                <div className="toolbar">
                  <input id="chat-manual" className="input" style={{ flex: 1, minWidth: 0 }} placeholder="Ej.: Expedientes Juzgado 3" value={name}
                    onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && add()} />
                  <button className="btn" onClick={add} disabled={!name.trim()}><Icon name="plus" size={16} />Agregar</button>
                </div>
              </div>
            </div>
          )}
        </Card>

        <div className="stack">
          <Connection wa={wa.data} onChange={wa.reload} />
          <Card title={<><span className="step-n">3</span>Traer archivos anteriores <span className="muted small">(opcional)</span></>}>
            <div className="stack small">
              <p style={{ margin: 0 }}>Marcar un chat analiza solo lo que llegue <b>desde ahora</b>. Para revisar también lo que ya estaba en el chat, pulsa
                <b> «Traer anteriores»</b> junto a su nombre: los archivos se revisan uno por uno y se clasifican. Si lo repites, solo trae lo nuevo.</p>
              {!connected && <p className="muted" style={{ margin: 0 }}>Disponible cuando WhatsApp esté conectado.</p>}
            </div>
          </Card>
          <Card title={<><span className="step-n">4</span>Compartir con el equipo</>}>
            <div className="stack small">
              <p style={{ margin: 0 }}>Para que un abogado vea los archivos de un chat, agrega ese chat a su espacio de trabajo (y, si quieres, solo ciertas etiquetas).</p>
              <Link className="btn btn-sm" style={{ alignSelf: 'flex-start' }} to="/espacios"><Icon name="layers" size={14} />Asignar a un espacio de trabajo</Link>
            </div>
          </Card>
        </div>
      </div>

      {dirty && (
        <div className="save-bar" role="status">
          <span><b>Cambios sin guardar:</b> {added ? `${added} chat(s) nuevo(s)` : ''}{added && removed ? ' · ' : ''}{removed ? `${removed} quitado(s)` : ''}</span>
          <div className="spacer" />
          <button className="btn btn-ghost btn-sm" onClick={() => setList(saved)} disabled={busy}>Descartar</button>
          <button className="btn btn-primary" onClick={save} disabled={busy}><Icon name="check" size={16} />{busy ? 'Guardando…' : 'Guardar'}</button>
        </div>
      )}
    </div>
  );
}
