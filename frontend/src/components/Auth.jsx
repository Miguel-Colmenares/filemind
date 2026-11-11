import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { api, setSpace } from '../api/client.js';
import Icon from './Icon.jsx';
import { LogoMark, UccLogo } from './Logo.jsx';
import { PROYECTO } from './Academic.jsx';

const AuthCtx = createContext(null);
export const useAuth = () => useContext(AuthCtx);
const SPACE_KEY = 'filemind.espacio';

function readSpace() {
  try { return Number(localStorage.getItem(SPACE_KEY)) || null; } catch { return null; }
}

/** Estado de la sesión: usuario, sus espacios de trabajo y el espacio elegido. */
export function AuthProvider({ children }) {
  const [st, setSt] = useState({ loading: true, configured: true, user: null, spaces: [] });
  const [space, setSpaceState] = useState(readSpace);

  const apply = useCallback((r) => {
    const spaces = r.espacios || [];
    setSt({ loading: false, configured: r.configurado ?? true, user: r.usuario || null, spaces });
    // si el espacio guardado ya no es del usuario, se vuelve a «todos»
    setSpaceState((cur) => {
      const ok = cur && spaces.some((s) => s.id === cur) ? cur : null;
      setSpace(ok);
      return ok;
    });
  }, []);

  const refresh = useCallback(() => api.authState().then(apply)
    .catch(() => setSt((s) => ({ ...s, loading: false }))), [apply]);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    const onExpired = () => setSt((s) => (s.user ? { ...s, user: null, expired: true } : s));
    window.addEventListener('filemind:sin-sesion', onExpired);
    return () => window.removeEventListener('filemind:sin-sesion', onExpired);
  }, []);

  const chooseSpace = (id) => {
    setSpace(id);
    setSpaceState(id);
    try { if (id) localStorage.setItem(SPACE_KEY, String(id)); else localStorage.removeItem(SPACE_KEY); } catch { /* nada */ }
  };

  const value = {
    ...st,
    space,
    chooseSpace,
    isAdmin: st.user?.role === 'admin',
    login: async (u, p) => apply({ configurado: true, ...(await api.login(u, p)) }),
    setup: async (u, n, p) => apply({ configurado: true, ...(await api.setup(u, n, p)) }),
    logout: async () => { try { await api.logout(); } finally { chooseSpace(null); setSt((s) => ({ ...s, user: null, spaces: [] })); } },
    refresh,
  };
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

/** Pantalla de inicio de sesión (y de creación del primer administrador). */
export function LoginScreen() {
  const { configured, login, setup, expired } = useAuth();
  const [f, setF] = useState({ usuario: '', nombre: '', contrasena: '', repetir: '' });
  const [error, setError] = useState(expired ? 'Su sesión terminó. Vuelva a iniciar sesión.' : '');
  const [busy, setBusy] = useState(false);
  const [show, setShow] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    if (!configured && f.contrasena !== f.repetir) { setError('Las contraseñas no coinciden.'); return; }
    setBusy(true);
    try {
      if (configured) await login(f.usuario, f.contrasena);
      else await setup(f.usuario, f.nombre, f.contrasena);
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  };

  return (
    <div className="login">
      <div className="login-side">
        {/* Emblema animado: escudo con anillos que giran y un barrido de escaneo (solo transform/opacity) */}
        <div className="login-emblem" aria-hidden="true">
          <svg viewBox="0 0 200 200">
            <circle className="ring r1" cx="100" cy="100" r="92" />
            <circle className="ring r2" cx="100" cy="100" r="74" />
            <path className="shield" d="M100 40l44 16v32c0 28-19 47-44 54-25-7-44-26-44-54V56z" />
            <path className="check" d="M80 98l14 14 26-28" />
          </svg>
          <span className="sweep" />
        </div>
        <div className="login-brand">
          <LogoMark size={56} className="big" />
          <div className="splash-name">File<span>Mind</span></div>
          <p>Verifica la seguridad de los archivos que llegan por WhatsApp y los organiza con inteligencia artificial.</p>
          <ul className="login-points">
            <li><Icon name="shieldCheck" size={18} />Protocolo de 4 fases y 10 controles de ciberseguridad</li>
            <li><Icon name="brain" size={18} />Clasificación con IA entrenada con sentencias reales</li>
            <li><Icon name="layers" size={18} />Espacios de trabajo para compartir archivos con tu equipo</li>
          </ul>
        </div>
        <div className="login-academic">
          <span className="academic-pill"><i />{PROYECTO.tipo} · {PROYECTO.anio}</span>
          <UccLogo height={40} />
          <small>{PROYECTO.curso}</small>
        </div>
      </div>
      <form className="login-card card" onSubmit={submit}>
        <div className="login-mobile-brand"><LogoMark size={40} /><span className="brand-name">File<span>Mind</span></span></div>
        <h1>{configured ? <>Iniciar <span className="serif">sesión</span></> : <>Crear <span className="serif">administrador</span></>}</h1>
        <p className="muted small">{configured
          ? 'Entra con el usuario que te dio el administrador.'
          : 'Es el primer arranque de FileMind. Crea la cuenta del administrador, que podrá invitar al resto del equipo.'}</p>
        {error && <div className="alert alto" role="alert">{error}</div>}
        <div className="field"><label htmlFor="u">Usuario</label>
          <input id="u" className="input" autoComplete="username" autoCapitalize="none" required value={f.usuario} onChange={set('usuario')} autoFocus /></div>
        {!configured && (
          <div className="field"><label htmlFor="n">Nombre completo</label>
            <input id="n" className="input" autoComplete="name" required value={f.nombre} onChange={set('nombre')} /></div>
        )}
        <div className="field"><label htmlFor="p">Contraseña</label>
          <div className="pass">
            <input id="p" className="input" type={show ? 'text' : 'password'} required minLength={configured ? 1 : 8}
              autoComplete={configured ? 'current-password' : 'new-password'} value={f.contrasena} onChange={set('contrasena')} />
            <button type="button" className="icon-btn" onClick={() => setShow(!show)} aria-label={show ? 'Ocultar contraseña' : 'Mostrar contraseña'}>
              <Icon name={show ? 'lock' : 'unlock'} size={16} /></button>
          </div>
          {!configured && <small className="muted">Mínimo 8 caracteres, con letras y números.</small>}
        </div>
        {!configured && (
          <div className="field"><label htmlFor="r">Repetir contraseña</label>
            <input id="r" className="input" type={show ? 'text' : 'password'} required autoComplete="new-password" value={f.repetir} onChange={set('repetir')} /></div>
        )}
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy ? <span className="spinner sm" /> : <Icon name={configured ? 'arrowRight' : 'shieldCheck'} size={16} />}
          {configured ? 'Entrar' : 'Crear y entrar'}
        </button>
        <p className="small muted login-foot"><Icon name="lock" size={13} /> Conexión protegida: 5 intentos fallidos bloquean la cuenta 5 minutos.</p>
      </form>
    </div>
  );
}
