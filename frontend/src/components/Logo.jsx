import { useId } from 'react';

const SHIELD = 'M12 3l8 3v6c0 5-3.5 8.5-8 9.5C7.5 20.5 4 17 4 12V6z';
const CHECK = 'M8.5 12l2.5 2.5 4.5-5';

/**
 * Marca animada de FileMind: el escudo se dibuja, aparece el visto bueno y
 * cada cierto tiempo una línea de escaneo recorre el escudo (como el protocolo
 * revisando un archivo). Con «reducir movimiento» del sistema se muestra quieta.
 */
export function LogoMark({ size = 30, className = '' }) {
  const clip = `fm-clip-${useId().replace(/:/g, '')}`;
  return (
    <span className={`logo-mark ${className}`} style={{ width: size, height: size }} aria-hidden="true">
      <svg viewBox="0 0 24 24" width={size * 0.62} height={size * 0.62} fill="none" stroke="currentColor"
        strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <defs><clipPath id={clip}><path d={SHIELD} /></clipPath></defs>
        <g clipPath={`url(#${clip})`}>
          <rect className="logo-scan" x="2" y="2" width="20" height="3" fill="currentColor" stroke="none" />
        </g>
        <path className="logo-shield" d={SHIELD} pathLength="1" />
        <path className="logo-check" d={CHECK} pathLength="1" />
      </svg>
    </span>
  );
}

export default function Logo({ size = 30, showName = true }) {
  return (
    <span className="logo">
      <LogoMark size={size} />
      {showName && <span className="brand-name">File<span>Mind</span></span>}
    </span>
  );
}

/** Logo de la Universidad Cooperativa de Colombia, en su versión para fondo claro u oscuro. */
export function UccLogo({ height = 28, className = '' }) {
  return (
    <span className={`ucc-logo ${className}`} style={{ height }}>
      <img className="ucc-light" src="/ucc-logo.png" alt="Universidad Cooperativa de Colombia" height={height} />
      <img className="ucc-dark" src="/ucc-logo-dark.png" alt="" aria-hidden="true" height={height} />
    </span>
  );
}
