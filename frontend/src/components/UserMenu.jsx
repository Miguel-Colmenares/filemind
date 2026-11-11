import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client.js';
import { useAuth } from './Auth.jsx';
import Icon from './Icon.jsx';
import { Modal, useToast } from './ui.jsx';

const initials = (name = '') => name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('') || '?';
const ROLE = { admin: 'Administrador', miembro: 'Miembro' };

function PasswordModal({ onClose }) {
  const [f, setF] = useState({ actual: '', nueva: '', repetir: '' });
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const save = async (e) => {
    e.preventDefault();
    if (f.nueva !== f.repetir) { toast('Las contraseñas nuevas no coinciden', 'bad'); return; }
    setBusy(true);
    try { await api.changePassword(f.actual, f.nueva); toast('Contraseña cambiada. Se cerraron tus otras sesiones.', 'ok'); onClose(); }
    catch (err) { toast(err.message, 'bad'); } finally { setBusy(false); }
  };
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  return (
    <Modal title="Cambiar contraseña" onClose={onClose} footer={<>
      <button className="btn" type="button" onClick={onClose}>Cancelar</button>
      <button className="btn btn-primary" type="submit" form="pwd" disabled={busy}>Guardar</button></>}>
      <form id="pwd" className="stack" onSubmit={save}>
        <div className="field"><label htmlFor="pa">Contraseña actual</label>
          <input id="pa" type="password" className="input" autoComplete="current-password" required value={f.actual} onChange={set('actual')} /></div>
        <div className="field"><label htmlFor="pn">Contraseña nueva</label>
          <input id="pn" type="password" className="input" autoComplete="new-password" minLength={8} required value={f.nueva} onChange={set('nueva')} />
          <small className="muted">Mínimo 8 caracteres, con letras y números.</small></div>
        <div className="field"><label htmlFor="pr">Repetir contraseña nueva</label>
          <input id="pr" type="password" className="input" autoComplete="new-password" required value={f.repetir} onChange={set('repetir')} /></div>
      </form>
    </Modal>
  );
}

/** Botón con las iniciales del usuario: rol, cambiar contraseña, tema y cerrar sesión. */
export default function UserMenu({ theme, toggleTheme }) {
  const { user, logout, isAdmin } = useAuth();
  const [open, setOpen] = useState(false);
  const [pwd, setPwd] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    const esc = (e) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', esc);
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', esc); };
  }, [open]);
  return (
    <div className="user-menu" ref={ref}>
      <button className="avatar" onClick={() => setOpen(!open)} aria-haspopup="menu" aria-expanded={open} title={user.name}>
        {initials(user.name)}
      </button>
      {open && (
        <div className="dropdown" role="menu">
          <div className="dropdown-head">
            <span className="avatar lg">{initials(user.name)}</span>
            <div><b>{user.name}</b><div className="small muted">@{user.username} · {ROLE[user.role] || user.role}</div></div>
          </div>
          <Link to="/espacios" role="menuitem" onClick={() => setOpen(false)}><Icon name="layers" size={16} />Mis espacios de trabajo</Link>
          {isAdmin && <Link to="/usuarios" role="menuitem" onClick={() => setOpen(false)}><Icon name="users" size={16} />Usuarios</Link>}
          {isAdmin && <Link to="/configuracion" role="menuitem" onClick={() => setOpen(false)}><Icon name="gear" size={16} />Configuración</Link>}
          <button role="menuitem" onClick={() => { setOpen(false); setPwd(true); }}><Icon name="key" size={16} />Cambiar contraseña</button>
          <button role="menuitem" onClick={toggleTheme}><Icon name={theme === 'dark' ? 'sun' : 'moon'} size={16} />Tema {theme === 'dark' ? 'claro' : 'oscuro'}</button>
          <button role="menuitem" className="danger" onClick={logout}><Icon name="logout" size={16} />Cerrar sesión</button>
        </div>
      )}
      {pwd && <PasswordModal onClose={() => setPwd(false)} />}
    </div>
  );
}

/** Selector del espacio de trabajo activo (filtra archivos, panel y avisos). */
export function SpacePicker() {
  const { spaces, space, chooseSpace, isAdmin } = useAuth();
  if (!spaces.length) return null;
  return (
    <label className="space-picker" title="Espacio de trabajo">
      <Icon name="layers" size={15} />
      <select value={space || ''} onChange={(e) => chooseSpace(Number(e.target.value) || null)} aria-label="Espacio de trabajo">
        <option value="">{isAdmin ? 'Todos los archivos' : 'Todos mis espacios'}</option>
        {spaces.map((s) => <option key={s.id} value={s.id}>{s.nombre}</option>)}
      </select>
    </label>
  );
}
