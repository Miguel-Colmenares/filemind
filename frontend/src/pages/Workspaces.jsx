import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client.js';
import { useApi } from '../hooks/useApi.js';
import { useAuth } from '../components/Auth.jsx';
import Icon from '../components/Icon.jsx';
import { Card, CategoryChip, Empty, Loading, Modal, useToast } from '../components/ui.jsx';

// sin tildes ni mayúsculas, para que «analisis» encuentre «Análisis de Sistema»
const norm = (s = '') => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

/** Resalta la parte del nombre que coincide con la búsqueda. */
function Highlight({ text, q }) {
  const nq = norm(q.trim());
  const i = nq ? norm(text).indexOf(nq) : -1;
  if (i < 0) return <span>{text}</span>;
  return <span>{text.slice(0, i)}<mark>{text.slice(i, i + nq.length)}</mark>{text.slice(i + nq.length)}</span>;
}

const initials = (name = '') => name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('');

function Editor({ ws, onClose, onSaved }) {
  const users = useApi(api.users, []);
  const chats = useApi(api.spaceChats, []);
  const cats = useApi(api.categories, []);
  const [f, setF] = useState({
    nombre: ws?.nombre || '', descripcion: ws?.descripcion || '',
    miembros: new Set(ws?.miembros.map((m) => m.id) || []), chats: new Set(ws?.chats || []),
    categorias: new Set(ws?.categorias || []),
  });
  const [extra, setExtra] = useState('');
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const toggle = (k, v) => { const s = new Set(f[k]); s.has(v) ? s.delete(v) : s.add(v); setF({ ...f, [k]: s }); };
  const chatList = [...new Set([...(chats.data || []).map((c) => c.nombre), ...f.chats])];
  const [q, setQ] = useState('');
  const nq = norm(q.trim());
  const shown = chatList.filter((c) => !nq || norm(c).includes(nq));
  const save = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.saveSpace(ws?.id, { nombre: f.nombre, descripcion: f.descripcion, miembros: [...f.miembros], chats: [...f.chats], categorias: [...f.categorias] });
      toast(ws ? 'Espacio actualizado' : 'Espacio creado', 'ok');
      onSaved();
    } catch (err) { toast(err.message, 'bad'); } finally { setBusy(false); }
  };
  return (
    <Modal title={ws ? `Editar «${ws.nombre}»` : 'Nuevo espacio de trabajo'} onClose={onClose} footer={<>
      <button className="btn" onClick={onClose}>Cancelar</button>
      <button className="btn btn-primary" form="ws" disabled={busy}>Guardar</button></>}>
      <form id="ws" className="stack" onSubmit={save}>
        <div className="field"><label htmlFor="ws-n">Nombre</label>
          <input id="ws-n" className="input" required minLength={2} value={f.nombre} onChange={(e) => setF({ ...f, nombre: e.target.value })} placeholder="Ej.: Litigios constitucionales" /></div>
        <div className="field"><label htmlFor="ws-d">Descripción (opcional)</label>
          <input id="ws-d" className="input" value={f.descripcion} onChange={(e) => setF({ ...f, descripcion: e.target.value })} /></div>
        <fieldset className="pick">
          <legend>Personas</legend>
          {users.loading ? <Loading /> : (users.data || []).map((u) => (
            <label key={u.id} className="pick-row">
              <input type="checkbox" checked={f.miembros.has(u.id)} onChange={() => toggle('miembros', u.id)} />
              <span className="avatar sm">{initials(u.name)}</span>{u.name}<span className="muted small">@{u.username}{u.role === 'admin' ? ' · admin' : ''}</span>
            </label>
          ))}
        </fieldset>
        <fieldset className="pick pick-chats">
          <legend>Chats de WhatsApp</legend>
          <div className="small muted">Todos los miembros verán los archivos que lleguen por estos chats, ya revisados y clasificados.</div>
          {f.chats.size > 0 && (
            <div className="pick-chips" aria-label="Chats escogidos">
              {[...f.chats].map((c) => (
                <button type="button" key={c} className="chip" title="Quitar" onClick={() => toggle('chats', c)}>
                  <Icon name="whatsapp" size={13} />{c}<Icon name="x" size={12} />
                </button>
              ))}
            </div>
          )}
          <div className="search pick-search">
            <Icon name="search" size={16} />
            <input className="input" type="search" placeholder={`Buscar entre ${chatList.length} chats…`} value={q} autoComplete="off"
              aria-label="Buscar chats" onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') { e.preventDefault(); if (shown[0]) { toggle('chats', shown[0]); setQ(''); } }
              }} />
          </div>
          <div className="pick-scroll">
            {chats.loading ? <Loading /> : shown.length ? shown.slice(0, 200).map((c) => (
              <label key={c} className="pick-row">
                <input type="checkbox" checked={f.chats.has(c)} onChange={() => toggle('chats', c)} />
                <Icon name="whatsapp" size={15} /><Highlight text={c} q={q} />
              </label>
            )) : <div className="small muted" style={{ padding: 8 }}>Ningún chat coincide con «{q}».</div>}
            {shown.length > 200 && <div className="small muted" style={{ padding: 8 }}>Hay {shown.length - 200} más: escribe para afinar la búsqueda.</div>}
          </div>
          <div className="row">
            <input className="input" style={{ flex: 1 }} placeholder="Otro chat (nombre exacto)" value={extra} onChange={(e) => setExtra(e.target.value)} />
            <button type="button" className="btn btn-sm" disabled={!extra.trim()} onClick={() => { toggle('chats', extra.trim()); setExtra(''); }}>
              <Icon name="plus" size={14} />Agregar</button>
          </div>
        </fieldset>
        <fieldset className="pick">
          <legend>Etiquetas que verá este espacio</legend>
          <div className="small muted">Marca las etiquetas de documentos que le interesan a este equipo (por ejemplo solo «Tutela»). Si no marcas ninguna, verán todas.</div>
          <div className="cat-picker">
            {cats.loading ? <Loading /> : (cats.data || []).map((c) => (
              <CategoryChip key={c.nombre} category={c.nombre} title={c.descripcion} active={f.categorias.has(c.nombre)} onClick={() => toggle('categorias', c.nombre)} />
            ))}
          </div>
          <div className="small">{f.categorias.size ? `Verán solo ${f.categorias.size} etiqueta(s).` : 'Verán todas las etiquetas.'}</div>
        </fieldset>
      </form>
    </Modal>
  );
}

export default function Workspaces() {
  const { isAdmin, chooseSpace, refresh, space } = useAuth();
  const spaces = useApi(api.spaces, []);
  const [edit, setEdit] = useState(null);
  const toast = useToast();
  const nav = useNavigate();
  const list = spaces.data || [];
  const saved = () => { setEdit(null); spaces.reload(); refresh(); };
  const remove = async (w) => {
    if (!window.confirm(`¿Eliminar el espacio «${w.nombre}»? Los archivos no se borran; solo deja de compartirse.`)) return;
    try { await api.deleteSpace(w.id); toast('Espacio eliminado', 'ok'); if (space === w.id) chooseSpace(null); saved(); }
    catch (err) { toast(err.message, 'bad'); }
  };
  return (
    <div className="stack" style={{ gap: 20 }}>
      <div className="toolbar">
        <div className="small muted" style={{ maxWidth: 640 }}>
          Un espacio de trabajo reúne a un equipo, los chats de WhatsApp que comparten y, si quieres, solo ciertas etiquetas
          (por ejemplo un equipo de tutelas). Todos ven los mismos archivos ya revisados y clasificados, y las correcciones
          de etiqueta de uno sirven para todos y para reentrenar la IA.
        </div>
        <div className="spacer" />
        {isAdmin && <button className="btn btn-primary" onClick={() => setEdit({})}><Icon name="plus" size={16} />Nuevo espacio</button>}
      </div>
      {spaces.loading ? <Loading /> : list.length ? (
        <div className="grid g3">
          {list.map((w) => (
            <Card key={w.id} className={`ws-card ${space === w.id ? 'on' : ''}`} title={w.nombre} actions={isAdmin && (
              <div className="row" style={{ gap: 2 }}>
                <button className="icon-btn" title="Editar" aria-label={`Editar ${w.nombre}`} onClick={() => setEdit(w)}><Icon name="edit" size={16} /></button>
                <button className="icon-btn" title="Eliminar" aria-label={`Eliminar ${w.nombre}`} onClick={() => remove(w)}><Icon name="trash" size={16} /></button>
              </div>)}>
              <div className="stack">
                {w.descripcion && <div className="small muted">{w.descripcion}</div>}
                <div className="ws-stats"><b>{w.archivos}</b> archivos · <b>{w.miembros.length}</b> personas · <b>{w.chats.length}</b> chats</div>
                <div className="avatars">
                  {w.miembros.slice(0, 6).map((m) => <span key={m.id} className="avatar sm" title={m.nombre}>{initials(m.nombre)}</span>)}
                  {w.miembros.length > 6 && <span className="avatar sm more">+{w.miembros.length - 6}</span>}
                  {!w.miembros.length && <span className="small muted">Sin personas todavía</span>}
                </div>
                <div className="row" style={{ flexWrap: 'wrap', gap: 6 }}>
                  {(w.categorias || []).length
                    ? w.categorias.map((c) => <CategoryChip key={c} category={c} />)
                    : <span className="small muted"><Icon name="tag" size={13} /> Todas las etiquetas</span>}
                </div>
                <div className="row" style={{ flexWrap: 'wrap', gap: 6 }}>
                  {w.chats.map((c) => <span key={c} className="chip"><Icon name="whatsapp" size={13} />{c}</span>)}
                  {!w.chats.length && <span className="small muted">Sin chats asignados</span>}
                </div>
                <button className="btn btn-sm" style={{ alignSelf: 'flex-start' }} onClick={() => { chooseSpace(w.id); nav('/archivos'); }}>
                  <Icon name="files" size={14} />Ver sus archivos</button>
              </div>
            </Card>
          ))}
        </div>
      ) : (
        <Card><Empty icon="layers" title="Todavía no hay espacios de trabajo">
          {isAdmin ? 'Crea uno, agrega a las personas y escoge qué chats comparten.' : 'Pide al administrador que te agregue a un espacio para ver archivos.'}
        </Empty></Card>
      )}
      {edit && <Editor ws={edit.id ? edit : null} onClose={() => setEdit(null)} onSaved={saved} />}
    </div>
  );
}
