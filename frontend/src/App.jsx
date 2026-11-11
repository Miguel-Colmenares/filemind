import { useEffect, useState } from 'react';
import NetworkBackground from './components/NetworkBackground.jsx';
import { Link, NavLink, Route, Routes, useLocation } from 'react-router-dom';
import Icon from './components/Icon.jsx';
import Logo, { UccLogo } from './components/Logo.jsx';
import { PROYECTO, Splash } from './components/Academic.jsx';
import { api } from './api/client.js';
import { useApi } from './hooks/useApi.js';
import { useToast } from './components/ui.jsx';
import Dashboard from './pages/Dashboard.jsx';
import Files from './pages/Files.jsx';
import Quarantine from './pages/Quarantine.jsx';
import Analyze from './pages/Analyze.jsx';
import Groups from './pages/Groups.jsx';
import Models from './pages/Models.jsx';
import Audit from './pages/Audit.jsx';
import Notifications from './pages/Notifications.jsx';
import Requirements from './pages/Requirements.jsx';
import Settings from './pages/Settings.jsx';
import Users from './pages/Users.jsx';
import Workspaces from './pages/Workspaces.jsx';
import { LoginScreen, useAuth } from './components/Auth.jsx';
import UserMenu, { SpacePicker } from './components/UserMenu.jsx';

// `top` marca los enlaces que aparecen en la barra superior; el menú hamburguesa muestra todos.
// `accent` es la parte del título que se resalta en serif naranja.
const NAV = [
  { section: 'Operación' },
  { to: '/', icon: 'dashboard', label: 'Panel', title: 'Panel', accent: 'general', sub: 'Resumen de la actividad y del estado del sistema', top: true },
  { to: '/archivos', icon: 'files', label: 'Archivos', title: 'Archivos', accent: 'recibidos', sub: 'Todo lo recibido desde los grupos monitoreados', top: true },
  { to: '/cuarentena', icon: 'lock', label: 'Cuarentena', title: 'Archivos en', accent: 'cuarentena', sub: 'Archivos retenidos por riesgo alto (puntaje mayor a 70)', badge: 'q', top: true },
  { to: '/grupos', admin: true, icon: 'whatsapp', label: 'Chats de WhatsApp', short: 'Chats', title: 'Chats de', accent: 'WhatsApp', sub: 'Conecta WhatsApp y escoge de qué chats se analizan y clasifican los archivos', top: true },
  { to: '/analizar', icon: 'upload', label: 'Analizar archivo', short: 'Analizar', title: 'Analizar', accent: 'archivo', sub: 'Pasa un archivo por el protocolo completo', top: true },
  { to: '/notificaciones', icon: 'bell', label: 'Notificaciones', title: '', accent: 'Notificaciones', sub: 'Avisos enviados a los usuarios en lenguaje claro' },
  { section: 'Inteligencia artificial' },
  { to: '/modelos', icon: 'brain', label: 'Modelos de IA', short: 'Modelos IA', title: 'Modelos de', accent: 'IA', sub: 'Clasificación temática y modelo de riesgo', top: true },
  { section: 'Equipo' },
  { to: '/espacios', icon: 'layers', label: 'Espacios de trabajo', short: 'Espacios', title: 'Espacios de', accent: 'trabajo', sub: 'Equipos que comparten chats y ven los mismos archivos clasificados', top: true },
  { to: '/usuarios', icon: 'users', label: 'Usuarios', title: '', accent: 'Usuarios', sub: 'Cuentas, roles y acceso al sistema', admin: true },
  { section: 'Administración', admin: true },
  { to: '/auditoria', admin: true, icon: 'list', label: 'Auditoría', title: '', accent: 'Auditoría', sub: 'Registro de eventos con marca de tiempo (RNF8)' },
  { to: '/requisitos', icon: 'checklist', label: 'Requisitos', title: 'Cumplimiento de', accent: 'requisitos', sub: 'RF y RNF del documento de seguridad y objetivos de IA' },
  { to: '/configuracion', admin: true, icon: 'server', label: 'Configuración', title: '', accent: 'Configuración', sub: 'Parámetros del sistema y acceso' },
];

function useTheme() {
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem('filemind.theme.v2') || 'dark'; } catch { return 'dark'; }
  });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('filemind.theme.v2', theme); } catch { /* ignorar */ }
  }, [theme]);
  return [theme, () => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))];
}

// En pantallas pequeñas las tablas marcadas con «stack-sm» se ven como tarjetas:
// cada celda necesita el nombre de su columna (data-label), que se toma del encabezado.
function useTableLabels(dep) {
  useEffect(() => {
    const label = () => {
      document.querySelectorAll('table.stack-sm').forEach((t) => {
        const heads = [...t.querySelectorAll('thead th')].map((th) => th.textContent.trim());
        t.querySelectorAll('tbody tr').forEach((tr) => {
          [...tr.children].forEach((td, i) => {
            if (heads[i] && td.dataset.label !== heads[i]) td.dataset.label = heads[i];
          });
        });
      });
    };
    label();
    const mo = new MutationObserver(label);
    mo.observe(document.getElementById('root'), { childList: true, subtree: true });
    return () => mo.disconnect();
  }, [dep]);
}

const BOTTOM = [
  { to: '/', icon: 'dashboard', label: 'Panel' },
  { to: '/archivos', icon: 'files', label: 'Archivos' },
  { to: '/analizar', icon: 'upload', label: 'Analizar', main: true },
  { to: '/cuarentena', icon: 'lock', label: 'Cuarentena', badge: 'q' },
  { to: '/grupos', icon: 'whatsapp', label: 'Chats', admin: true },
];

function sectionOf(item) {
  const i = NAV.indexOf(item);
  for (let j = i; j >= 0; j -= 1) if (NAV[j].section) return NAV[j].section;
  return '';
}

export default function App() {
  const auth = useAuth();
  const [theme, toggleTheme] = useTheme();
  const { pathname } = useLocation();
  // Un solo fondo animado para toda la app: cambia de variante, no se vuelve a crear
  const variant = !auth.user ? 'login' : pathname === '/' ? 'home' : 'page';
  const bg = (
    <div className={`bg-fx v-${variant}`} aria-hidden="true">
      <NetworkBackground variant={variant} />
      <span className="orb o1" /><span className="orb o2" /><span className="orb o3" />
      <span className="bg-scan" />
    </div>
  );
  if (auth.loading) return <>{bg}<div className="boot"><div className="spinner" /></div></>;
  if (!auth.user) return <>{bg}<LoginScreen /><Splash /></>;
  return <>{bg}<Shell theme={theme} toggleTheme={toggleTheme} /></>;
}

function Shell({ theme, toggleTheme }) {
  const { isAdmin, space } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const { pathname } = useLocation();
  const stats = useApi(api.stats, [pathname], { interval: 15000 });
  const health = useApi(api.health, [], { interval: 15000 });
  const wa = useApi(api.whatsappConnection, [], { interval: 10000 });
  const waState = wa.data?.estado;
  const waOk = waState === 'conectado';
  const waBusy = waState === 'iniciando' || waState === 'reconectando';
  const waText = waOk ? 'WhatsApp conectado' : waState === 'esperando_qr' ? 'WhatsApp: falta escanear el QR'
    : waBusy ? 'WhatsApp conectando…' : 'WhatsApp desconectado';
  const nav = NAV.filter((n) => isAdmin || !n.admin);
  const current = nav.find((n) => n.to && (n.to === '/' ? pathname === '/' : pathname.startsWith(n.to))) || NAV[1];
  const qCount = stats.data?.por_estado?.cuarentena || 0;

  // Aviso cuando llegan archivos nuevos por WhatsApp (se revisa cada 15 s con las estadísticas)
  const toast = useToast();
  const porEstado = stats.data?.por_estado;
  const total = porEstado ? Object.values(porEstado).reduce((a, b) => a + (Number(b) || 0), 0) : null;
  const [lastTotal, setLastTotal] = useState(null);
  const [lastQ, setLastQ] = useState(null);
  useEffect(() => {
    if (total == null) return;
    if (lastTotal != null && total > lastTotal) {
      const nuevos = total - lastTotal;
      const enQ = Math.max(0, qCount - (lastQ ?? qCount));
      toast(`Llegó ${nuevos === 1 ? 'un archivo nuevo' : `${nuevos} archivos nuevos`} por WhatsApp`
        + (enQ ? ` · ${enQ} quedó en cuarentena` : ' y ya está clasificado'), enQ ? 'bad' : 'ok');
    }
    setLastTotal(total);
    setLastQ(qCount);
  }, [total]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { setMenuOpen(false); window.scrollTo(0, 0); }, [pathname]);
  useTableLabels(pathname);
  useEffect(() => {
    if (!menuOpen) return undefined;
    const onKey = (e) => { if (e.key === 'Escape') setMenuOpen(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [menuOpen]);

  const count = (n) => n.badge === 'q' && qCount > 0 && <span className="count">{qCount}</span>;
  const brand = (
    <Link to="/" className="brand" aria-label="FileMind, ir al panel">
      <Logo />
    </Link>
  );

  return (
    <div className={`layout ${pathname === '/' ? 'is-home' : ''}`}>
      <header className="navbar">
        <div className="navbar-in">
          <button className="icon-btn hamburger" onClick={() => setMenuOpen(true)} aria-label="Abrir menú" aria-expanded={menuOpen} aria-controls="menu-principal">
            <Icon name="menu" />
          </button>
          {brand}
          <nav className="topnav" aria-label="Secciones principales">
            {nav.filter((n) => n.top).map((n) => (
              <NavLink key={n.to} to={n.to} end={n.to === '/'}>{n.short || n.label}{count(n)}</NavLink>
            ))}
          </nav>
          <div className="nav-actions" role="toolbar" aria-label="Opciones del sistema">
            <SpacePicker />
            <span className={`status-pill ${health.error ? 'off' : ''}`} title={health.error ? 'Sin conexión' : 'En línea'}>
              <i /><span>{health.error ? 'Sin conexión' : 'En línea'}</span>
            </span>
            {wa.data && (
              <Link to={isAdmin ? '/grupos' : pathname} className={`status-pill wa ${waOk ? '' : waBusy ? 'warn' : 'off'}`} title={waText} aria-label={waText}>
                <i /><Icon name="whatsapp" size={14} /><span>{waOk ? 'WhatsApp' : waBusy ? 'Conectando…' : 'Sin WhatsApp'}</span>
              </Link>
            )}
            <NavLink to="/notificaciones" className="icon-btn" title="Notificaciones" aria-label="Notificaciones"><Icon name="bell" /></NavLink>
            <NavLink to="/cuarentena" className="icon-btn hide-sm" title="Cuarentena" aria-label={`Cuarentena, ${qCount} archivos`}>
              <Icon name="lock" />{qCount > 0 && <span className="dot">{qCount}</span>}
            </NavLink>
            <button className="icon-btn hide-sm" onClick={toggleTheme} title="Cambiar tema" aria-label="Cambiar tema">
              <Icon name={theme === 'dark' ? 'sun' : 'moon'} />
            </button>
            <UserMenu theme={theme} toggleTheme={toggleTheme} />
          </div>
        </div>
      </header>

      <div className={`menu-overlay ${menuOpen ? 'open' : ''}`} onClick={() => setMenuOpen(false)} />
      <aside id="menu-principal" className={`menu-panel ${menuOpen ? 'open' : ''}`} aria-label="Menú principal" aria-hidden={!menuOpen}>
        <div className="menu-head">
          {brand}
          <div className="spacer" />
          <button className="icon-btn" onClick={() => setMenuOpen(false)} aria-label="Cerrar menú" tabIndex={menuOpen ? 0 : -1}><Icon name="x" /></button>
        </div>
        <nav className="menu-nav">
          {nav.map((n, i) => (n.section
            ? <div key={i} className="nav-section">{n.section}</div>
            : (
              <NavLink key={n.to} to={n.to} end={n.to === '/'} tabIndex={menuOpen ? 0 : -1}>
                <Icon name={n.icon} />{n.label}{count(n)}
              </NavLink>
            )))}
        </nav>
        <div className="menu-foot">
          <UccLogo height={30} />
          <span>{PROYECTO.tipo} · {PROYECTO.anio}</span>
        </div>
      </aside>

      <main className="main">
        {wa.data && !waOk && !(isAdmin && pathname === '/grupos') && (
          <div className={`wa-banner ${waBusy ? 'warn' : ''}`} role="status">
            <Icon name="whatsapp" size={20} />
            <div>
              <b>{waText}</b>
              <div className="small">
                {waBusy ? 'El puente está intentando conectarse. Los archivos nuevos llegarán apenas termine.'
                  : 'FileMind necesita estar conectado a WhatsApp para recibir y analizar los archivos de los chats.'}
              </div>
            </div>
            <div className="spacer" />
            {isAdmin
              ? !waBusy && <Link className="btn btn-primary btn-sm" to="/grupos">Conectar WhatsApp</Link>
              : <span className="small muted">Pide al administrador que lo conecte.</span>}
          </div>
        )}
        <div className="page-head" key={pathname}>
          <span className="eyebrow"><i />{sectionOf(current)}</span>
          <h1>{current.title}{current.title && ' '}<span className="serif">{current.accent}</span></h1>
          <div className="sub">{current.sub}</div>
        </div>
        <div className="content page-enter" key={`c-${pathname}-${space || 'todos'}`}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/archivos" element={<Files />} />
            <Route path="/cuarentena" element={<Quarantine />} />
            <Route path="/analizar" element={<Analyze />} />
            <Route path="/notificaciones" element={<Notifications />} />
            <Route path="/modelos" element={<Models />} />
            <Route path="/espacios" element={<Workspaces />} />
            <Route path="/requisitos" element={<Requirements />} />
            {isAdmin && <Route path="/grupos" element={<Groups />} />}
            {isAdmin && <Route path="/auditoria" element={<Audit />} />}
            {isAdmin && <Route path="/configuracion" element={<Settings />} />}
            {isAdmin && <Route path="/usuarios" element={<Users />} />}
            <Route path="*" element={<Dashboard />} />
          </Routes>
        </div>
      </main>
      <footer className="app-foot">
        <div>
          <div className="foot-brand">
            <Logo size={26} />
            <span>Organiza y protege los archivos que llegan por WhatsApp</span>
          </div>
          <span className="spacer" />
          <div className="foot-academic">
            <div>
              <span className="academic-pill"><i />{PROYECTO.tipo}</span>
              <small>{PROYECTO.universidad} · {PROYECTO.sede} · {PROYECTO.anio}</small>
            </div>
            <UccLogo height={38} />
          </div>
        </div>
      </footer>

      <nav className="bottom-nav" aria-label="Accesos rápidos" style={{ gridTemplateColumns: `repeat(${BOTTOM.filter((n) => isAdmin || !n.admin).length + 1}, 1fr)` }}>
        {BOTTOM.filter((n) => isAdmin || !n.admin).map((n) => (
          <NavLink key={n.to} to={n.to} end={n.to === '/'} className={n.main ? 'main-action' : ''}>
            <span className="bn-ic"><Icon name={n.icon} size={n.main ? 22 : 20} />
              {n.badge === 'q' && qCount > 0 && <span className="dot">{qCount}</span>}</span>
            <span>{n.label}</span>
          </NavLink>
        ))}
        <button type="button" onClick={() => setMenuOpen(true)} aria-label="Abrir menú completo">
          <span className="bn-ic"><Icon name="menu" size={20} /></span><span>Más</span>
        </button>
      </nav>
      <Splash />
    </div>
  );
}
