import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import Icon from './Icon.jsx';
import { catLabel, catStyle, STATUS_LABEL } from '../utils/format.js';

export function Card({ title, actions, children, pad = true, className = '' }) {
  return (
    <section className={`card ${className}`}>
      {title && (
        <div className="card-h"><h3>{title}</h3><div className="spacer" />{actions}</div>
      )}
      <div className={pad ? 'card-b' : ''}>{children}</div>
    </section>
  );
}

/** Cuenta desde 0 hasta el valor la primera vez que aparece (solo números enteros). */
function CountUp({ value }) {
  const [shown, setShown] = useState(typeof value === 'number' ? 0 : value);
  const done = useRef(false);
  useEffect(() => {
    if (typeof value !== 'number') { setShown(value); return undefined; }
    let reduce = false;
    try { reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch { /* nada */ }
    if (done.current || reduce || value <= 0) { setShown(value); done.current = true; return undefined; }
    done.current = true;
    const t0 = performance.now(), dur = 900;
    let raf;
    const step = (t) => {
      const k = Math.min(1, (t - t0) / dur);
      setShown(Math.round(value * (1 - (1 - k) ** 3)));
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value]);
  return shown;
}

export function Kpi({ icon, label, value, hint, tone, text = false }) {
  return (
    <div className="card kpi">
      <div className={`kpi-icon ${tone || ''}`}><Icon name={icon} size={22} /></div>
      <div>
        <div className="kpi-label">{label}</div>
        <div className={`kpi-value ${text ? 'text' : ''}`}><CountUp value={value} /></div>
        {hint && <div className="kpi-hint">{hint}</div>}
      </div>
    </div>
  );
}

export function RiskBadge({ level, score }) {
  if (!level) return <span className="badge neutral">—</span>;
  const label = { bajo: 'Bajo', medio: 'Medio', alto: 'Alto' }[level] || level;
  return <span className={`badge ${level}`}>{label}{score != null ? ` · ${score}` : ''}</span>;
}

export function StatusBadge({ status }) {
  const tone = { clasificado: 'ok', cuarentena: 'bad', duplicado: 'neutral', eliminado: 'neutral' }[status] || 'neutral';
  return <span className={`badge ${tone}`}>{STATUS_LABEL[status] || status}</span>;
}

export function CategoryChip({ category, count, active, onClick, title }) {
  if (!category) return <span className="muted">—</span>;
  const { color, icon } = catStyle(category);
  const Tag = onClick ? 'button' : 'span';
  return (
    <Tag type={onClick ? 'button' : undefined} className={`chip cat-chip ${active ? 'on' : ''} ${onClick ? 'clickable' : ''}`}
      style={{ '--cat': color }} onClick={onClick} title={title} aria-pressed={onClick ? !!active : undefined}>
      <Icon name={icon} size={14} />{catLabel(category)}{count != null && <span className="cat-count">{count}</span>}
    </Tag>
  );
}

/** Dónde quedó el archivo en la carpeta del bufete (o si falta guardarlo). */
export function FolderBadge({ carpeta, compact = false }) {
  if (!carpeta) return null;
  const { estado, subcarpeta } = carpeta;
  if (estado === 'guardado') {
    return <span className="badge ok" title={carpeta.ruta || ''}><Icon name="folderCheck" size={13} />{compact ? 'En la carpeta' : `En «${subcarpeta}»`}</span>;
  }
  if (estado === 'cuarentena') return <span className="badge neutral" title="Los archivos peligrosos nunca se copian al PC"><Icon name="lock" size={13} />No se guarda</span>;
  if (estado === 'falta' || estado === 'sin_carpeta') {
    return <span className="badge warn" title={subcarpeta ? `Irá a «${subcarpeta}»` : ''}><Icon name="clock" size={13} />Falta guardar</span>;
  }
  return <span className="muted">—</span>;
}

export function Empty({ icon = 'files', title, children }) {
  return (
    <div className="empty">
      <Icon name={icon} size={36} stroke={1.4} />
      <b>{title}</b>
      {children && <div className="small">{children}</div>}
    </div>
  );
}

export function Loading() {
  return <div className="empty"><div className="spinner" /></div>;
}

export function Modal({ title, onClose, children, footer }) {
  // Se monta en <body> para que ninguna transformación de la página desplace el diálogo fuera de la pantalla.
  return createPortal(
    <>
      <div className="overlay" onClick={onClose} />
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-h"><h3>{title}</h3></div>
        <div className="modal-b">{children}</div>
        {footer && <div className="modal-f">{footer}</div>}
      </div>
    </>,
    document.body,
  );
}

/** Medidor semicircular del puntaje de riesgo (0-100). */
export function RiskGauge({ score = 0, level }) {
  const r = 62, cx = 75, cy = 75;
  const angle = Math.PI * (1 - Math.min(Math.max(score, 0), 100) / 100);
  const x = cx + r * Math.cos(angle), y = cy - r * Math.sin(angle);
  const color = { bajo: 'var(--ok)', medio: 'var(--warn)', alto: 'var(--bad)' }[level] || 'var(--accent)';
  return (
    <div className="gauge">
      <svg width="150" height="80" viewBox="0 0 150 80">
        <path d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`} stroke="var(--border)" strokeWidth="12" fill="none" strokeLinecap="round" />
        {score > 0 && <path d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${x} ${y}`} stroke={color} strokeWidth="12" fill="none" strokeLinecap="round" />}
      </svg>
      <div className="gauge-value">{score}<small>de 100</small></div>
    </div>
  );
}

const ToastCtx = createContext(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }) {
  const [items, setItems] = useState([]);
  const push = useCallback((text, kind = 'info') => {
    const id = Math.random();
    setItems((xs) => [...xs, { id, text, kind }]);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), 4500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status">
        {items.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.text}</div>)}
      </div>
    </ToastCtx.Provider>
  );
}
