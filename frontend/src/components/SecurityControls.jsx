import Icon from './Icon.jsx';

// Resultado de cada control de ciberseguridad (backend/filemind/security/controls.py).
const TONE = { alerta: 'bad', aviso: 'warn', error: 'warn', ok: 'ok', no_aplica: 'neutral', no_disponible: 'neutral' };
const LABEL = { alerta: 'Riesgo', aviso: 'Revisar', error: 'Falló', ok: 'Sin hallazgos', no_aplica: 'No aplica', no_disponible: 'No disponible' };

/** Tono global de los controles: el peor de los que se aplicaron. */
export function controlsTone(controls = []) {
  const tones = controls.map((c) => TONE[c.estado]);
  return tones.includes('bad') ? 'bad' : tones.includes('warn') ? 'warn' : 'ok';
}

export default function SecurityControls({ controls }) {
  if (!controls?.length) {
    return <div className="small muted">Este archivo se analizó antes de que existieran los controles detallados. Analízalo de nuevo para verlos.</div>;
  }
  const applied = controls.filter((c) => c.estado !== 'no_aplica');
  const skipped = controls.filter((c) => c.estado === 'no_aplica');
  return (
    <div className="controls">
      {applied.map((c) => {
        const tone = TONE[c.estado] || 'neutral';
        return (
          <details className={`control ${tone}`} key={c.id} open={c.estado === 'alerta'}>
            <summary>
              <span className="check-ic"><Icon name={tone === 'ok' ? 'check' : tone === 'neutral' ? 'clock' : 'warning'} size={14} stroke={2.2} /></span>
              <span className="control-main">
                <span className="control-name">{c.nombre} <small className="muted">· Fase {c.fase}</small></span>
                <span className="control-res">{c.resumen}</span>
              </span>
              <span className="control-side">
                {c.puntos > 0 && <span className="control-pts" title="Puntos de riesgo que aportó">+{c.puntos}</span>}
                <span className={`badge ${tone}`}>{LABEL[c.estado] || c.estado}</span>
              </span>
            </summary>
            {(c.detalles?.length > 0 || c.indicadores?.length > 0) && (
              <div className="control-body">
                {c.detalles?.length > 0 && <ul>{c.detalles.map((d, i) => <li key={i}>{d}</li>)}</ul>}
                {c.indicadores?.length > 0 && (
                  <div className="small muted">Indicadores que sumaron puntos: {c.indicadores.map(([k, v]) => `${k} +${v}`).join(' · ')}</div>
                )}
              </div>
            )}
          </details>
        );
      })}
      {skipped.length > 0 && (
        <div className="small muted control-skip">No aplican a este tipo de archivo: {skipped.map((c) => c.nombre).join(' · ')}</div>
      )}
    </div>
  );
}
