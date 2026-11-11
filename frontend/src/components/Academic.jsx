import { useEffect, useState } from 'react';
import { LogoMark, UccLogo } from './Logo.jsx';

export const PROYECTO = {
  tipo: 'Proyecto académico',
  curso: 'Proyecto integrador de Inteligencia Artificial y Seguridad de la Información',
  universidad: 'Universidad Cooperativa de Colombia',
  sede: 'Campus Villavicencio',
  anio: '2026',
  autores: ['Miguel S. Colmenares R.', 'Juan D. Vargas V.', 'Nelson D. Quiroga M.'],
};

const SPLASH_KEY = 'filemind.splash.v1';

function reducedMotion() {
  try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch { return false; }
}

/** Pantalla de bienvenida corta, una vez por sesión del navegador. */
export function Splash() {
  const [state, setState] = useState(() => {
    try { if (sessionStorage.getItem(SPLASH_KEY)) return 'off'; } catch { /* sin almacenamiento */ }
    return reducedMotion() ? 'off' : 'on';
  });
  useEffect(() => {
    if (state !== 'on') return undefined;
    try { sessionStorage.setItem(SPLASH_KEY, '1'); } catch { /* sin almacenamiento */ }
    const t1 = setTimeout(() => setState('leaving'), 1700);
    const t2 = setTimeout(() => setState('off'), 2200);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, [state]);
  if (state === 'off') return null;
  return (
    <div className={`splash ${state}`} onClick={() => setState('off')} role="presentation">
      <div className="splash-in">
        <LogoMark size={76} className="big" />
        <div className="splash-name">File<span>Mind</span></div>
        <div className="splash-tag">Verificación de seguridad y clasificación con IA</div>
        <div className="splash-ucc">
          <span className="academic-pill"><i />{PROYECTO.tipo}</span>
          <UccLogo height={34} />
        </div>
      </div>
    </div>
  );
}

/** Franja del panel con los datos del proyecto académico. */
export function AcademicHero() {
  return (
    <section className="card academic-hero">
      <div className="academic-hero-l">
        <span className="academic-pill"><i />{PROYECTO.tipo} · {PROYECTO.anio}</span>
        <h2>{PROYECTO.curso}</h2>
        <p className="muted small">
          {PROYECTO.autores.join(' · ')}
        </p>
      </div>
      <div className="academic-hero-r">
        <UccLogo height={46} />
        <span className="small muted">{PROYECTO.sede}</span>
      </div>
    </section>
  );
}
