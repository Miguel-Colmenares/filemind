import { useCallback, useEffect, useState } from 'react';

/** Ejecuta una llamada a la API y expone { data, error, loading, reload }.
 *  Con ``interval`` se repite, pero no mientras la pestaña está oculta: al volver a verla se
 *  actualiza de inmediato (ahorra red y batería con la app abierta en segundo plano). */
export function useApi(fn, deps = [], { interval } = {}) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(() => fn()
    .then((data) => setState({ data, error: null, loading: false }))
    .catch((error) => setState((s) => ({ ...s, error, loading: false }))), deps);
  useEffect(() => {
    run();
    if (!interval) return undefined;
    const t = setInterval(() => { if (!document.hidden) run(); }, interval);
    const onVis = () => { if (!document.hidden) run(); };
    document.addEventListener('visibilitychange', onVis);
    return () => { clearInterval(t); document.removeEventListener('visibilitychange', onVis); };
  }, [run, interval]);
  return { ...state, reload: run };
}
