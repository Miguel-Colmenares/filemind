import { useState } from 'react';
import { api } from '../api/client.js';
import { useApi } from '../hooks/useApi.js';
import { useAuth } from '../components/Auth.jsx';
import Icon from '../components/Icon.jsx';
import { Card, Empty, Kpi, Loading, Modal, useToast } from '../components/ui.jsx';
import { fmtDate } from '../utils/format.js';

const EMPTY = { usuario: '', nombre: '', contrasena: '', rol: 'miembro' };

function NewUser({ onDone }) {
  const [f, setF] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try { const u = await api.createUser(f); toast(`Usuario «${u.username}» creado`, 'ok'); setF(EMPTY); onDone(); }
    catch (err) { toast(err.message, 'bad'); } finally { setBusy(false); }
  };
  return (
    <Card title="Nuevo usuario">
      <form className="stack" onSubmit={submit}>
        <div className="field"><label htmlFor="nu-n">Nombre completo</label>
          <input id="nu-n" className="input" required value={f.nombre} onChange={set('nombre')} placeholder="Ej.: Laura Méndez" /></div>
        <div className="field"><label htmlFor="nu-u">Usuario</label>
          <input id="nu-u" className="input" required autoCapitalize="none" pattern="[a-zA-Z0-9._\-]{3,32}" value={f.usuario} onChange={set('usuario')} placeholder="laura.mendez" />
          <small className="muted">De 3 a 32 letras, números, punto o guion.</small></div>
        <div className="field"><label htmlFor="nu-p">Contraseña inicial</label>
          <input id="nu-p" className="input" type="text" required minLength={8} autoComplete="off" value={f.contrasena} onChange={set('contrasena')} />
          <small className="muted">Compártela por un canal privado. La persona puede cambiarla desde su menú.</small></div>
        <div className="field"><label htmlFor="nu-r">Rol</label>
          <select id="nu-r" className="select" value={f.rol} onChange={set('rol')}>
            <option value="miembro">Miembro: ve y corrige los archivos de sus espacios</option>
            <option value="admin">Administrador: todo, incluida la cuarentena y la configuración</option>
          </select></div>
        <button className="btn btn-primary" disabled={busy}><Icon name="plus" size={16} />Crear usuario</button>
      </form>
    </Card>
  );
}

function ResetPassword({ user, onClose }) {
  const [pwd, setPwd] = useState('');
  const toast = useToast();
  const save = async (e) => {
    e.preventDefault();
    try { await api.updateUser(user.id, { contrasena: pwd }); toast('Contraseña restablecida y sesiones cerradas', 'ok'); onClose(); }
    catch (err) { toast(err.message, 'bad'); }
  };
  return (
    <Modal title={`Restablecer contraseña de ${user.name}`} onClose={onClose} footer={<>
      <button className="btn" onClick={onClose}>Cancelar</button>
      <button className="btn btn-primary" form="rp">Guardar</button></>}>
      <form id="rp" onSubmit={save} className="field">
        <label htmlFor="rp-p">Contraseña nueva</label>
        <input id="rp-p" className="input" type="text" minLength={8} required autoComplete="off" value={pwd} onChange={(e) => setPwd(e.target.value)} />
        <small className="muted">Se cerrarán todas las sesiones abiertas de esta persona.</small>
      </form>
    </Modal>
  );
}

export default function Users() {
  const users = useApi(api.users, []);
  const { user: me } = useAuth();
  const [reset, setReset] = useState(null);
  const toast = useToast();
  const list = users.data || [];
  const patch = async (u, body, msg) => {
    try { await api.updateUser(u.id, body); toast(msg, 'ok'); users.reload(); } catch (err) { toast(err.message, 'bad'); }
  };
  const remove = async (u) => {
    if (!window.confirm(`¿Eliminar la cuenta de ${u.name}? Esta acción no se puede deshacer.`)) return;
    try { await api.deleteUser(u.id); toast('Usuario eliminado', 'ok'); users.reload(); } catch (err) { toast(err.message, 'bad'); }
  };
  return (
    <div className="stack" style={{ gap: 20 }}>
      <div className="grid g3">
        <Kpi icon="users" label="Usuarios" value={list.length} hint={`${list.filter((u) => u.active).length} activos`} />
        <Kpi icon="shieldCheck" label="Administradores" value={list.filter((u) => u.role === 'admin').length} hint="acceso completo" tone="warn" />
        <Kpi icon="layers" label="Sin espacio asignado" value={list.filter((u) => u.role !== 'admin' && !u.espacios.length).length} hint="no ven ningún archivo todavía" tone="bad" />
      </div>
      <div className="grid g-main">
        <Card title="Cuentas" pad={false}>
          {users.loading ? <Loading /> : list.length ? (
            <div className="table-wrap">
              <table className="table stack-sm">
                <thead><tr><th>Persona</th><th>Rol</th><th>Espacios</th><th>Último ingreso</th><th>Estado</th><th>Acciones</th></tr></thead>
                <tbody>
                  {list.map((u) => (
                    <tr key={u.id}>
                      <td className="file-name">{u.name}<small>@{u.username}{u.id === me.id ? ' · tú' : ''}</small></td>
                      <td>
                        <select className="select sm" value={u.role} disabled={u.id === me.id} aria-label={`Rol de ${u.name}`}
                          onChange={(e) => patch(u, { rol: e.target.value }, 'Rol actualizado')}>
                          <option value="miembro">Miembro</option><option value="admin">Administrador</option>
                        </select>
                      </td>
                      <td className="small">{u.espacios.map((w) => w.nombre).join(', ') || <span className="muted">—</span>}</td>
                      <td className="small muted">{u.last_login ? fmtDate(u.last_login) : 'Nunca'}</td>
                      <td>{u.active ? <span className="badge ok">Activo</span> : <span className="badge neutral">Desactivado</span>}
                        {u.locked_until && new Date(u.locked_until) > new Date() && <span className="badge bad" style={{ marginLeft: 6 }}>Bloqueado</span>}</td>
                      <td>
                        <div className="row" style={{ gap: 4 }}>
                          <button className="icon-btn" title="Restablecer contraseña" aria-label={`Restablecer contraseña de ${u.name}`} onClick={() => setReset(u)}><Icon name="key" size={16} /></button>
                          {u.id !== me.id && (
                            <>
                              <button className="icon-btn" title={u.active ? 'Desactivar' : 'Activar'} aria-label={u.active ? `Desactivar a ${u.name}` : `Activar a ${u.name}`}
                                onClick={() => patch(u, { activo: !u.active }, u.active ? 'Cuenta desactivada' : 'Cuenta activada')}>
                                <Icon name={u.active ? 'lock' : 'unlock'} size={16} /></button>
                              <button className="icon-btn" title="Eliminar" aria-label={`Eliminar a ${u.name}`} onClick={() => remove(u)}><Icon name="trash" size={16} /></button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <Empty icon="users" title="Aún no hay usuarios" />}
        </Card>
        <NewUser onDone={users.reload} />
      </div>
      {reset && <ResetPassword user={reset} onClose={() => setReset(null)} />}
    </div>
  );
}
