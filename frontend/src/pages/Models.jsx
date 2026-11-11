import { useState } from 'react';
import { api } from '../api/client.js';
import { useApi } from '../hooks/useApi.js';
import Icon from '../components/Icon.jsx';
import { Card, Kpi, Loading, useToast } from '../components/ui.jsx';
import { catLabel, fmtNum, fmtPct } from '../utils/format.js';

const ATTACK_LABEL = {
  completo: 'Todas las familias (prueba)', dde: 'Campos DDE', doble_extension: 'Doble extensión', docm_autoopen: 'Macro AutoOpen',
  exe_disfrazado: 'Ejecutable disfrazado', exe_embebido: 'Ejecutable embebido', html_login: 'Formulario de inicio de sesión',
  nota_rescate: 'Nota de rescate', ole_macro: 'Macro en Office antiguo', pdf_hex: 'PDF ofuscado', pdf_js: 'PDF con JavaScript',
  pdf_launch: 'PDF que lanza programas', pdf_objstm: 'PDF con objetos ocultos', plantilla_remota: 'Plantilla remota',
  powershell_b64: 'PowerShell codificado', solo_enlace: 'Solo un enlace', suplantacion_marca: 'Suplantación de marca', sutil: 'Phishing sutil (sin indicadores)',
};

function Comparison({ meta }) {
  const best = meta.best_model;
  return (
    <table className="table">
      <thead><tr><th>Algoritmo</th><th className="num">Exactitud (val.)</th><th className="num">F1 macro (val.)</th><th className="num">Entrenamiento</th></tr></thead>
      <tbody>
        {Object.entries(meta.comparison || {}).map(([k, v]) => (
          <tr key={k}><td>{k} {k === best && <span className="badge ok">elegido</span>}</td>
            <td className="num">{fmtNum(v.accuracy)}</td><td className="num"><b>{fmtNum(v.f1_macro)}</b></td><td className="num">{fmtNum(v.train_s, 2)} s</td></tr>
        ))}
      </tbody>
    </table>
  );
}

function PerClass({ test, label = (x) => x }) {
  return (
    <table className="table">
      <thead><tr><th>Clase</th><th className="num">Precisión</th><th className="num">Sensibilidad</th><th className="num">F1</th><th className="num">Muestras</th></tr></thead>
      <tbody>
        {Object.entries(test.per_class || {}).map(([k, v]) => (
          <tr key={k}><td>{label(k)}</td><td className="num">{fmtNum(v.precision)}</td><td className="num">{fmtNum(v.recall)}</td>
            <td className="num"><b>{fmtNum(v['f1-score'])}</b></td><td className="num">{v.support}</td></tr>
        ))}
      </tbody>
    </table>
  );
}

const Img = ({ src, alt }) => <img className="report-img" src={`/reportes/${src}`} alt={alt} />;

function Origin({ o }) {
  if (!o) return null;
  return (
    <Card title="Origen de los documentos de entrenamiento">
      <div className="small" style={{ lineHeight: 1.6 }}>
        <b>{o.descripcion}.</b> Textos completos tomados de {o.texto}. Etiqueta oficial de cada sentencia tomada de {o.etiquetas}.
        De {fmtInt(o.sentencias_publicadas)} sentencias publicadas, {fmtInt(o.descartadas_sin_referencia + o.descartadas_sin_etiqueta)} se descartaron por no tener
        referencia legible o etiqueta oficial. Se usaron <b>{fmtInt(o.total_usadas)}</b> (hasta {o.por_clase_max} por categoría, de {o.desde.slice(0, 4)} a {o.hasta.slice(0, 4)}),
        cada una como un fragmento real de {fmtInt(o.fragmento_caracteres)} caracteres del cuerpo de la sentencia.
      </div>
      <table className="table" style={{ marginTop: 10 }}>
        <thead><tr><th>Categoría</th><th className="num">Sentencias disponibles</th><th className="num">Usadas</th></tr></thead>
        <tbody>{Object.keys(o.usadas).map((c) => (
          <tr key={c}><td>{catLabel(c)}</td><td className="num">{fmtInt(o.disponibles[c])}</td><td className="num">{fmtInt(o.usadas[c])}</td></tr>))}</tbody>
      </table>
    </Card>
  );
}

const fmtInt = (n) => (n == null ? '—' : Number(n).toLocaleString('es-CO'));
const fmtVal = (v) => (Array.isArray(v) ? `(${v.join(', ')})` : v === null ? 'ninguno' : String(v));

function Params({ p }) {
  if (!p) return null;
  const groups = [['Clasificador', p.clasificador], ['TF-IDF de palabras', p.vectorizador_palabras],
    ['TF-IDF de caracteres', p.vectorizador_caracteres], ['Aprendido al entrenar', p.aprendidos]];
  return (
    <div className="grid g2">
      {groups.filter(([, g]) => g).map(([t, g]) => (
        <table className="table" key={t}>
          <thead><tr><th colSpan={2}>{t}</th></tr></thead>
          <tbody>{Object.entries(g).map(([k, v]) => (
            <tr key={k}><td className="mono small">{k}</td><td className="num small">{k === 'clases' ? v.length : fmtVal(v)}</td></tr>))}</tbody>
        </table>
      ))}
    </div>
  );
}

function ClassTable({ rows }) {
  return (
    <table className="table">
      <thead><tr><th>Categoría</th><th className="num">Precisión</th><th className="num">Sensibilidad</th><th className="num">F1</th><th className="num">Soporte</th></tr></thead>
      <tbody>{Object.entries(rows || {}).map(([c, v]) => (
        <tr key={c}><td>{catLabel(c)}</td><td className="num">{fmtNum(v.precision)}</td><td className="num">{fmtNum(v.recall)}</td>
          <td className="num"><b>{fmtNum(v.f1)}</b></td><td className="num">{v.soporte}</td></tr>))}</tbody>
    </table>
  );
}

const HEALTH_TONE = { estable: 'ok', vigilar: 'warn', reentrenar: 'bad', sin_datos: 'neutral' };

function ModelHealth({ h }) {
  if (!h) return null;
  return (
    <Card title="Salud del modelo en uso" actions={<span className={`badge ${HEALTH_TONE[h.estado] || 'neutral'}`}>{h.estado.replace('_', ' ')}</span>}>
      <div className="small">{h.mensaje}</div>
      {h.archivos > 0 && (
        <div className="small muted" style={{ marginTop: 6 }}>
          Últimos {h.archivos} archivos · confianza media {fmtNum(h.confianza_media)} (en la prueba fue {fmtNum(h.referencia_prueba)}) ·
          {' '}{h.revision_pct}% enviados a revisión. Si la confianza cae más de 0,15 o la revisión pasa del 25 %, conviene reentrenar.
        </div>
      )}
    </Card>
  );
}

function Benchmark({ b, v }) {
  if (!b) return null;
  const rows = Object.entries(b.sistemas);
  return (
    <Card title={`Benchmark: FileMind frente a sistemas más simples (${fmtInt(b.documentos)} documentos reales)`}>
      <div className="small muted" style={{ marginBottom: 10 }}>{b.procedimiento} Fecha {b.fecha}.</div>
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>Sistema</th><th>Tipo</th><th className="num">F1 macro</th><th className="num">IC 95 %</th><th className="num">Exactitud</th>
            <th className="num">ms por documento (p50 / p95)</th><th className="num">Entrenamiento</th><th className="num">Tamaño</th><th className="num">McNemar p</th></tr></thead>
          <tbody>{rows.map(([n, r]) => (
            <tr key={n}><td>{n}</td><td className="small">{r.tipo}</td><td className="num"><b>{fmtNum(r.f1_macro)}</b></td>
              <td className="num small">{fmtNum(r.f1_macro_ic95[0])} a {fmtNum(r.f1_macro_ic95[1])}</td><td className="num">{fmtPct(r.accuracy)}</td>
              <td className="num">{fmtNum(r.latencia_ms.p50, 2)} / {fmtNum(r.latencia_ms.p95, 2)}</td><td className="num">{fmtNum(r.entrenamiento_s, 2)} s</td>
              <td className="num">{r.tamano_kb > 10240 ? `${fmtNum(r.tamano_kb / 1024, 0)} MB` : `${fmtNum(r.tamano_kb, 0)} KB`}</td>
              <td className="num small">{r.mcnemar_vs_filemind ? (r.mcnemar_vs_filemind.p_valor < 0.001 ? '< 0,001' : fmtNum(r.mcnemar_vs_filemind.p_valor, 3)) : '—'}</td></tr>))}</tbody>
        </table>
      </div>
      <div className="grid g2" style={{ marginTop: 12 }}>
        <Img src={`benchmark_f1_latencia.png${v}`} alt="F1 frente a tiempo por documento" />
        <Img src={`benchmark_robustez.png${v}`} alt="Robustez frente a textos cortos y ruido de OCR" />
        <Img src={`benchmark_f1_por_clase.png${v}`} alt="F1 por categoría de cada sistema" />
        <Img src={`benchmark_matrices.png${v}`} alt="Matrices de confusión de cada sistema" />
      </div>
    </Card>
  );
}

function ModelDetail({ m }) {
  const names = Object.keys(m.modelos || {});
  const [sel, setSel] = useState(m.best_model);
  const d = m.modelos?.[sel];
  if (!d) return null;
  const v = `?v=${encodeURIComponent(m.trained_at || '')}`;
  const total = d.total_documentos || d.total_prueba;
  const fp = Object.values(d.por_categoria || {}).reduce((a, x) => a + x.falsos_positivos, 0);
  const charts = [
    ['dispersion', 'Diagrama de dispersión: un punto por documento analizado'],
    ['roc', 'Curva ROC de cada categoría con sus verdaderos y falsos positivos'],
    ['aciertos', 'Aciertos, no reconocidos y falsos positivos por categoría'],
    ['matriz', 'Matriz de confusión con todos los documentos'],
    ['palabras', 'Palabras con mayor peso'],
  ];
  return (
    <Card title={`Detalle de cada modelo probado (${fmtInt(total)} documentos, validación cruzada de 5 particiones)`}>
      <div className="tabs" role="tablist" style={{ marginBottom: 12 }}>
        {names.map((n) => (
          <button key={n} role="tab" className={n === sel ? 'on' : ''} onClick={() => setSel(n)}>
            {n}{n === m.best_model ? ' (elegido)' : ''}</button>
        ))}
      </div>
      <div className="small muted" style={{ marginBottom: 12 }}>{d.hiperparametros}. Cada documento lo clasificó un modelo que no lo había visto.</div>
      <div className="grid g4">
        <Kpi icon="check" label="Aciertos" value={`${fmtInt(d.aciertos)} / ${fmtInt(total)}`} hint={`exactitud ${fmtPct(d.todos?.accuracy ?? d.test.accuracy)}`} tone="ok" />
        <Kpi icon="warning" label="Falsos positivos" value={fmtInt(fp)} hint="documentos puestos en una categoría que no era la suya" tone="bad" />
        <Kpi icon="brain" label="Verdaderos positivos (TPR)" value={fmtNum(d.tpr_macro)} hint={`F1 macro ${fmtNum(d.todos?.f1_macro ?? d.test.f1_macro)}`} />
        <Kpi icon="shield" label="Tasa de falsos positivos (FPR)" value={fmtNum(d.fpr_macro, 4)} hint={`en la prueba final: ${d.test_aciertos ?? '—'} / ${d.total_prueba} aciertos`} />
      </div>
      {d.latencia_ms && (
        <div className="grid g4" style={{ marginTop: 12 }}>
          <Kpi icon="refresh" label="Tiempo por documento (p50)" value={`${fmtNum(d.latencia_ms.p50, 2)} ms`} hint={`p95 ${fmtNum(d.latencia_ms.p95, 2)} ms · máx ${fmtNum(d.latencia_ms.max, 1)} ms`} />
          <Kpi icon="files" label="Documentos por segundo" value={fmtInt(Math.round(d.latencia_ms.documentos_por_s))} hint={`medido uno a uno con ${d.latencia_ms.n} documentos`} />
          <Kpi icon="brain" label="Tamaño del modelo" value={`${fmtNum(d.tamano_kb / 1024, 1)} MB`} hint={`${fmtInt(d.parametros?.aprendidos?.rasgos)} rasgos`} />
          <Kpi icon="check" label="F1 macro (prueba)" value={fmtNum(d.test.f1_macro)} hint={`entrenó en ${fmtNum(d.train_s, 2)} s`} tone="ok" />
        </div>
      )}
      {d.parametros && <Card title="Parámetros e hiperparámetros (leídos del modelo entrenado)"><Params p={d.parametros} /></Card>}
      {d.por_clase_prueba && <Card title="F1 por categoría (prueba)" pad={false}><div className="table-wrap"><ClassTable rows={d.por_clase_prueba} /></div></Card>}
      <div className="stack" style={{ gap: 16, marginTop: 16 }}>
        {charts.filter(([k]) => d.graficas[k]).map(([k, t]) => (
          <Card key={k} title={t}><Img src={d.graficas[k] + v} alt={`${t} de ${sel}`} /></Card>
        ))}
      </div>
    </Card>
  );
}

function Topic({ m, pending, retrain, state, health, bench }) {
  const v = `?v=${encodeURIComponent(m.trained_at || '')}`;
  return (
    <div className="stack" style={{ gap: 16 }}>
      <ModelHealth h={health} />
      <div className="grid g4">
        <Kpi icon="brain" text label="Modelo elegido" value={m.best_model} hint={`entrenado ${m.trained_at}`} />
        <Kpi icon="check" label="F1 macro (prueba)" value={fmtNum(m.test?.f1_macro)} hint={`exactitud ${fmtPct(m.test?.accuracy)}`} tone="ok" />
        <Kpi icon="files" label="Documentos" value={m.split.train + m.split.val + m.split.test} hint={`70/20/10: ${m.split.train} / ${m.split.val} / ${m.split.test}`} />
        <Kpi icon="refresh" label="Correcciones de usuarios" value={pending} hint={`${m.feedback_samples || 0} ya usadas`} tone="warn" />
      </div>
      <Card title="Retroalimentación" actions={
        <button className="btn btn-primary btn-sm" disabled={state.en_curso} onClick={retrain}>
          <Icon name="refresh" size={14} />{state.en_curso ? 'Reentrenando…' : 'Reentrenar con correcciones'}</button>}>
        <div className="small">Cada vez que alguien corrige la categoría de un archivo, el caso se guarda. Al reentrenar, esas correcciones se suman al conjunto de entrenamiento, se vuelven a comparar los cuatro algoritmos y el panel empieza a usar el nuevo modelo sin reiniciar.
          {state.ultimo_error && <div className="alert alto" style={{ marginTop: 10 }}>Último error: {state.ultimo_error}</div>}</div>
      </Card>
      <div className="grid g2">
        <Card title="Comparación de algoritmos (validación)" pad={false}><div className="table-wrap"><Comparison meta={m} /></div></Card>
        <Card title="Comparación visual"><Img src="tema_comparacion_modelos.png" alt="F1 macro por algoritmo" /></Card>
      </div>
      <Origin o={m.origen_datos} />
      {m.modelos && <ModelDetail m={m} />}
      <div className="grid g2">
        <Card title="Matriz de confusión (prueba)"><Img src="tema_matriz_confusion.png" alt="Matriz de confusión temática" /></Card>
        <Card title="Métricas por categoría (prueba)" pad={false}><div className="table-wrap"><PerClass test={m.test} label={catLabel} /></div></Card>
      </div>
      <div className="grid g2">
        <Card title="Curva precisión-sensibilidad"><Img src="tema_curva_pr.png" alt="Curvas precisión-sensibilidad por categoría" /></Card>
        <Card title="F1 según umbral de confianza">
          <Img src="tema_curva_f1_confianza.png" alt="F1 frente a confianza mínima" />
          {m.f1_conf_best && <div className="small muted" style={{ marginTop: 8 }}>Mejor umbral {fmtNum(m.f1_conf_best.threshold, 2)} (F1 {fmtNum(m.f1_conf_best.f1)}). Por debajo de la confianza mínima el archivo va a «Otros».</div>}
        </Card>
      </div>
      {m.curva_aprendizaje && (
        <div className="grid g2">
          <Card title="Curva de aprendizaje"><Img src={`tema_curva_aprendizaje.png${v}`} alt="F1 según cantidad de documentos" />
            <div className="small muted" style={{ marginTop: 8 }}>Si la línea de validación sigue subiendo al final, más documentos todavía mejorarían el modelo.</div></Card>
          <Card title="Calibración de la confianza"><Img src={`tema_calibracion.png${v}`} alt="Confianza frente a exactitud real" />
            <div className="small muted" style={{ marginTop: 8 }}>Error de calibración esperado (ECE) {fmtNum(m.calibracion?.ece, 3)}. Cuanto más cerca de la diagonal, más creíble es el porcentaje de confianza.</div></Card>
        </div>
      )}
      {m.modelos && <Card title="Exactitud frente a tiempo de respuesta de los cuatro algoritmos"><Img src={`tema_latencia_f1.png${v}`} alt="F1 frente a milisegundos por documento" /></Card>}
      <Benchmark b={bench} v={v} />
    </div>
  );
}

function Risk({ m }) {
  const q = m.cuarentena_umbral_70 || {};
  const cv = m.validacion_cruzada_5 || {};
  const maxImp = Math.max(...(m.feature_importances_top15 || [[0, 1]]).map(([, v]) => v));
  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="grid g4">
        <Kpi icon="shield" text label="Modelo elegido" value={m.best_model} hint={`entrenado ${m.trained_at}`} />
        <Kpi icon="warning" label="Falsos negativos" value={fmtPct(q.tasa_falsos_negativos)} hint={`validación cruzada ${fmtPct(cv.fnr_media)} · meta ≤ 5 %`} tone="bad" />
        <Kpi icon="check" label="Falsos positivos" value={fmtPct(q.tasa_falsos_positivos)} hint={`validación cruzada ${fmtPct(cv.fpr_media)} · meta ≤ 10 %`} tone="ok" />
        <Kpi icon="files" label="Muestras" value={m.split.train + m.split.val + m.split.test} hint="legítimo, phishing, ransomware" />
      </div>
      <div className="grid g2">
        <Card title="Comparación de algoritmos (validación)" pad={false}><div className="table-wrap"><Comparison meta={m} /></div></Card>
        <Card title="Decisión de cuarentena (umbral 70, prueba)">
          <Img src="riesgo_matriz_confusion_binaria.png" alt="Matriz binaria cuarentena sí/no" />
        </Card>
      </div>
      <div className="grid g2">
        <Card title="Métricas por clase (prueba)" pad={false}><div className="table-wrap"><PerClass test={m.test_multiclase} /></div></Card>
        <Card title="Validación cruzada en 5 particiones" pad={false}>
          <table className="table"><thead><tr><th>Partición</th><th className="num">Falsos negativos</th><th className="num">Falsos positivos</th></tr></thead>
            <tbody>{(cv.folds || []).map((f) => <tr key={f.fold}><td>{f.fold}</td><td className="num">{fmtPct(f.fnr)}</td><td className="num">{fmtPct(f.fpr)}</td></tr>)}
              <tr><td><b>Media</b></td><td className="num"><b>{fmtPct(cv.fnr_media)}</b></td><td className="num"><b>{fmtPct(cv.fpr_media)}</b></td></tr></tbody></table>
        </Card>
      </div>
      <Card title="Ataques nunca vistos en el entrenamiento" pad={false}>
        <div className="card-b small muted">Para cada familia se entrena sin ella y se prueba solo con ella. Muestra qué tan bien generaliza la combinación de reglas e IA frente al modelo solo.</div>
        <table className="table">
          <thead><tr><th>Familia de ataque</th><th className="num">Muestras</th><th style={{ width: '28%' }}>Detectados (reglas + IA)</th><th style={{ width: '28%' }}>Detectados (solo IA)</th></tr></thead>
          <tbody>
            {Object.entries(m.ataques_no_vistos || {}).map(([k, v]) => (
              <tr key={k}><td>{ATTACK_LABEL[k] || k}</td><td className="num">{v.n}</td>
                <td><div className="row"><div className={`meter ${v.detectados_puntaje_final < 0.8 ? 'bad' : ''}`} style={{ flex: 1 }}><div style={{ width: `${v.detectados_puntaje_final * 100}%` }} /></div><span className="num small">{fmtPct(v.detectados_puntaje_final, 0)}</span></div></td>
                <td><div className="row"><div className={`meter ${v.detectados_solo_modelo < 0.8 ? 'warn' : ''}`} style={{ flex: 1 }}><div style={{ width: `${v.detectados_solo_modelo * 100}%` }} /></div><span className="num small">{fmtPct(v.detectados_solo_modelo, 0)}</span></div></td></tr>
            ))}
          </tbody>
        </table>
        <div className="card-b small muted">El phishing sutil, sin enlaces ni adjuntos activos, es el límite conocido: se documenta como trabajo futuro.</div>
      </Card>
      <div className="grid g2">
        <Card title="Indicadores más influyentes">
          <div className="bars">
            {(m.feature_importances_top15 || []).map(([k, v]) => (
              <div className="bar-row" key={k}><span className="mono small">{k}</span>
                <div className="bar-track"><div className="bar-fill" style={{ width: `${(v / maxImp) * 100}%` }} /></div>
                <span className="num small">{fmtNum(v, 3)}</span></div>
            ))}
          </div>
        </Card>
        <Card title="Curva precisión-sensibilidad"><Img src="riesgo_curva_pr.png" alt="Curvas precisión-sensibilidad del modelo de riesgo" /></Card>
      </div>
    </div>
  );
}

export default function Models() {
  const [tab, setTab] = useState('tema');
  const models = useApi(api.models, [], { interval: 5000 });
  const toast = useToast();
  const retrain = async () => {
    try { const r = await api.retrain(); toast(`Reentrenamiento iniciado con ${r.correcciones} correcciones`, 'ok'); models.reload(); } catch (e) { toast(e.message, 'bad'); }
  };
  if (models.loading) return <Loading />;
  const d = models.data || {};
  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="tabs" role="tablist">
        <button role="tab" className={tab === 'tema' ? 'on' : ''} onClick={() => setTab('tema')}>Clasificación temática</button>
        <button role="tab" className={tab === 'riesgo' ? 'on' : ''} onClick={() => setTab('riesgo')}>Riesgo (seguridad)</button>
      </div>
      {tab === 'tema' && (d.tema ? <Topic m={d.tema} pending={d.correcciones_pendientes} retrain={retrain} state={d.reentrenamiento || {}} health={d.salud} bench={d.benchmark} />
        : <div className="alert medio">No hay modelo temático entrenado. Ejecuta <code>python scripts/entrenar.py</code> en la carpeta backend.</div>)}
      {tab === 'riesgo' && (d.riesgo ? <Risk m={d.riesgo} /> : <div className="alert medio">No hay modelo de riesgo entrenado.</div>)}
    </div>
  );
}
