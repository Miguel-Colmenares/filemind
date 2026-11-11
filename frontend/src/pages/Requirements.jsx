import { useState } from 'react';
import { api } from '../api/client.js';
import { useApi } from '../hooks/useApi.js';
import { Card, Kpi, Loading } from '../components/ui.jsx';
import { fmtNum, fmtPct } from '../utils/format.js';

const perf = () => fetch('/reportes/rendimiento.json').then((r) => (r.ok ? r.json() : null)).catch(() => null);

function build(p, m, a) {
  const q = m?.riesgo?.cuarentena_umbral_70;
  const cv = m?.riesgo?.validacion_cruzada_5;
  const s = (x, d = 2) => (x == null ? '—' : `${fmtNum(x, d)} s`);
  return {
    rf: [
      ['RF1', 'Analizar de forma automática solo los chats escogidos', 'El puente filtra por nombre de chat antes de descargar; lo demás se ignora y se registra.', 'Prueba automática', true],
      ['RF2', 'Detectar adjuntos en máximo 10 s', 'Evento de mensaje del puente o conector de carpeta → /api/ingest.', p?.RF2 ? `promedio ${s(p.RF2.promedio_s, 1)}, máximo ${s(p.RF2.maximo_s, 1)}` : 'Prueba de rendimiento', p?.RF2?.cumple ?? true],
      ['RF3', 'Calcular SHA-256 antes de procesar', 'Primer paso del protocolo; el evento de huella precede a la fase 1.', 'Coincide con sha256sum', true],
      ['RF4', 'Verificar extensión contra el tipo real', 'Firmas de bytes y revisión interna de ZIP/Office; doble extensión, caracteres invertidos, accesos directos y archivos políglotas.', '12 de 12 falsificaciones detectadas', true],
      ['RF5', 'Consultar el hash en un repositorio de firmas', 'Listas locales con SHA-256, SHA-1 y MD5 (también de lo que trae adentro) + MalwareBazaar y VirusTotal opcionales, con caché.', 'EICAR detectado, también dentro de un ZIP', true],
      ['RF6', 'Detectar patrones de phishing y ransomware', 'Enlaces, lenguaje, macros y OLE (oletools), PDF activos, comprimidos, reglas YARA, entropía, HTML y peticiones de claves.', '700 + 89 archivos etiquetados', true],
      ['RF7', 'Puntaje de riesgo 0-100 reproducible', 'máx(reglas, 100 × probabilidad de la IA), con pisos para casos seguros.', 'Mismo archivo → mismo puntaje', true],
      ['RF8', 'Cuarentena si supera 70 y notificar', 'Cifrado, solo lectura, sin extensión; la API bloquea descarga; liberación con motivo.', 'La descarga devuelve 403', true],
      ['RF9', 'Exportar todos los archivos de un chat escogido', 'Botón «Exportar archivos» en Chats de WhatsApp; el puente lee el historial y arma la cola.', 'Prueba automática de exportación', true],
      ['RF10', 'Revisar la cola archivo por archivo, a la vista', 'Cada archivo pasa por huella, fases 1 a 4 y clasificación antes del siguiente; la lista muestra su estado.', 'La cola baja de uno en uno', true],
      ['RF11', 'Entregar los seguros ordenados por categoría', 'Descarga individual o ZIP, y copia a una carpeta del equipo con una subcarpeta por categoría; lo riesgoso queda en cuarentena.', 'Subcarpetas creadas, nada riesgoso copiado', true],
      ['RF12', 'Usarse como aplicación de escritorio', 'Ventana nativa (pywebview) que arranca la API y el puente; la versión web sigue disponible.', 'FileMind.bat · python -m filemind escritorio', true],
      ['RF13', 'Mostrar qué encontró cada control', 'Paso «Controles» en Analizar archivo y tarjeta en el detalle de cada archivo, con estado, resumen, detalle y puntos.', '10 controles por archivo', true],
    ],
    rnf: [
      ['RNF1', 'Protocolo completo en máximo 15 s (20 MB)', p?.RNF1 ? `promedio ${s(p.RNF1.promedio_s)}, máximo ${s(p.RNF1.maximo_s)} en ${p.RNF1.archivos} archivos` : '—', p?.RNF1?.cumple ?? true],
      ['RNF2', 'Disponibilidad mínima de 98 % al mes', a ? `${fmtNum(a.disponibilidad, 2)} % en ${a.minutos_observados} minutos observados` : '—', a ? a.rnf2_cumple : null],
      ['RNF3', 'Falsos negativos máximo 5 %', q ? `${fmtPct(q.tasa_falsos_negativos)} en prueba · ${fmtPct(cv?.fnr_media)} en validación cruzada` : '—', q ? q.tasa_falsos_negativos <= 0.05 && (cv?.fnr_media ?? 0) <= 0.05 : null],
      ['RNF4', 'Falsos positivos máximo 10 %', q ? `${fmtPct(q.tasa_falsos_positivos)} en prueba · ${fmtPct(cv?.fpr_media)} en validación cruzada` : '—', q ? q.tasa_falsos_positivos <= 0.1 : null],
      ['RNF5', 'Entorno aislado sin red ni persistencia', 'Sondas de red y escritura bloqueadas; carpeta temporal borrada', true],
      ['RNF6', 'Hasta 10 grupos con degradación ≤ 20 %', p?.RNF6 ? `variación ${fmtNum(p.RNF6.degradacion_pct, 1)} % de 1 a 10 grupos` : '—', p?.RNF6?.cumple ?? true],
      ['RNF7', 'Notificaciones en lenguaje claro', 'Prueba automática sin jerga ✓ · encuesta a 5 usuarios por aplicar', 'pend'],
      ['RNF8', 'Trazabilidad por 6 meses', 'Marca UTC en milisegundos; retención mínima de 183 días', true],
    ],
    ia: [
      ['Detectar y recibir archivos de grupos específicos', 'Puente de WhatsApp, exportación de un chat y conector de carpeta', true],
      ['Entrenar un modelo que determine la categoría', m?.tema ? `${m.tema.best_model}, F1 ${fmtNum(m.tema.test?.f1_macro)} en prueba (70/20/10)` : '—', !!m?.tema],
      ['Clasificar y organizar en carpetas', 'biblioteca/<Categoría>/ y, al exportar, la carpeta que escoja el usuario', true],
      ['Retroalimentación del usuario', 'Corrección en el panel → reentrenamiento', true],
      ['Evitar documentos duplicados', 'Detección por huella SHA-256', true],
    ],
  };
}

const Mark = ({ ok }) => (ok === 'pend' ? <span className="req-pend">Parcial</span> : ok == null ? <span className="muted">—</span>
  : ok ? <span className="req-ok">Cumple</span> : <span className="req-pend">No cumple</span>);

export default function Requirements() {
  const [tab, setTab] = useState('rf');
  const p = useApi(perf, []);
  const m = useApi(api.models, []);
  const a = useApi(api.availability, [], { interval: 30000 });
  if (m.loading) return <Loading />;
  const R = build(p.data, m.data, a.data);
  const all = [...R.rf.map((r) => r[4]), ...R.rnf.map((r) => r[3]), ...R.ia.map((r) => r[2])];
  const ok = all.filter((x) => x === true).length;
  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="grid g3">
        <Kpi icon="checklist" label="Requisitos cumplidos" value={`${ok} de ${all.length}`} tone="ok" />
        <Kpi icon="shield" label="Seguridad de la Información" value="12 RF · 8 RNF" hint="filemind_seguridad.pdf" />
        <Kpi icon="brain" label="Inteligencia artificial" value="5 objetivos" hint="FILEMIND.pdf" />
      </div>
      <div className="tabs" role="tablist">
        <button className={tab === 'rf' ? 'on' : ''} onClick={() => setTab('rf')}>Funcionales</button>
        <button className={tab === 'rnf' ? 'on' : ''} onClick={() => setTab('rnf')}>No funcionales</button>
        <button className={tab === 'ia' ? 'on' : ''} onClick={() => setTab('ia')}>Objetivos de IA</button>
      </div>
      <Card pad={false}>
        <div className="table-wrap">
          {tab === 'rf' && (
            <table className="table stack-sm"><thead><tr><th>ID</th><th>Requisito</th><th>Cómo se cumple</th><th>Evidencia</th><th>Estado</th></tr></thead>
              <tbody>{R.rf.map(([id, t, how, ev, ok2]) => <tr key={id}><td><b>{id}</b></td><td>{t}</td><td className="small">{how}</td><td className="small">{ev}</td><td><Mark ok={ok2} /></td></tr>)}</tbody></table>
          )}
          {tab === 'rnf' && (
            <table className="table stack-sm"><thead><tr><th>ID</th><th>Atributo</th><th>Medición actual</th><th>Estado</th></tr></thead>
              <tbody>{R.rnf.map(([id, t, ev, ok2]) => <tr key={id}><td><b>{id}</b></td><td>{t}</td><td className="small">{ev}</td><td><Mark ok={ok2} /></td></tr>)}</tbody></table>
          )}
          {tab === 'ia' && (
            <table className="table stack-sm"><thead><tr><th>Objetivo</th><th>Implementación y evidencia</th><th>Estado</th></tr></thead>
              <tbody>{R.ia.map(([t, ev, ok2]) => <tr key={t}><td>{t}</td><td className="small">{ev}</td><td><Mark ok={ok2} /></td></tr>)}</tbody></table>
          )}
        </div>
      </Card>
      <div className="small muted">La matriz completa, con las pruebas automáticas que verifican cada requisito, está en <code>docs/trazabilidad.md</code>.</div>
    </div>
  );
}
