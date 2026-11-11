import { useEffect, useRef, useState } from 'react';
import { api } from '../api/client.js';
import { useApi } from '../hooks/useApi.js';
import FileDrawer from '../components/FileDrawer.jsx';
import SecurityControls, { controlsTone } from '../components/SecurityControls.jsx';
import Icon from '../components/Icon.jsx';
import { Card, CategoryChip, RiskBadge, RiskGauge, StatusBadge, useToast } from '../components/ui.jsx';
import { catLabel, fmtBytes, fmtPct } from '../utils/format.js';

// Cada fase del protocolo se muestra por separado y espera a que la persona pase a la siguiente.
const STEPS = [
  { key: 'hash_calculado', title: 'Huella digital', short: 'Huella', req: 'RF3',
    what: 'Antes de abrir o tocar el archivo se calcula su huella SHA-256: una cadena única que cambia si se altera un solo byte. Sirve para reconocer duplicados, consultar firmas de malware y dejar evidencia para auditoría.' },
  { key: 'fase1_estatico', title: 'Fase 1 · Análisis estático', short: 'Estático', req: 'RF4, RF5',
    what: 'Se lee la cabecera del archivo (los "bytes mágicos") para saber qué es realmente, sin ejecutarlo. Se compara con la extensión del nombre, se buscan trucos como la doble extensión (.pdf.exe) y se consulta la huella en el repositorio de firmas de malware conocido.' },
  { key: 'fase2_heuristico', title: 'Fase 2 · Análisis heurístico', short: 'Heurístico', req: 'RF6',
    what: 'Se extrae el texto y los enlaces del archivo y se buscan patrones típicos de phishing (urgencia, pedir claves, dominios recién creados o que imitan marcas) y de ransomware (macros, scripts ocultos, instrucciones de rescate).' },
  { key: 'controles_seguridad', title: 'Controles de ciberseguridad', short: 'Controles', req: 'RF4, RF5, RF6',
    what: 'Diez revisiones locales y más profundas, cada una con su resultado: tipo real frente a la extensión, huellas MD5/SHA-1/SHA-256 contra listas de malware, macros y objetos OLE (oletools), JavaScript y adjuntos en PDF, comprimidos anidados o con contraseña, reglas YARA, entropía, enlaces ocultos, formularios HTML y peticiones de claves. Ábrelas para ver el detalle.' },
  { key: 'fase3_sandbox', title: 'Fase 3 · Apertura aislada', short: 'Aislado', req: 'RNF5',
    what: 'El archivo se abre dentro de un entorno aislado sin acceso a la red ni permiso para escribir en disco. Así, si intenta conectarse a internet o modificar archivos, no puede hacer daño y ese comportamiento queda registrado.' },
  { key: 'fase4_puntaje', title: 'Fase 4 · Puntaje de riesgo', short: 'Puntaje', req: 'RF7, RF8',
    what: 'Se combinan las reglas de las fases anteriores con el modelo de inteligencia artificial para obtener un puntaje de 0 a 100. Si supera 70, el archivo va a cuarentena y no se entrega.' },
  { key: 'destino', title: 'Destino del archivo', short: 'Destino', req: 'RF9',
    what: 'Según el puntaje, el archivo se retiene en cuarentena o la IA lo clasifica por tema y lo guarda en la carpeta que le corresponde. Al final se redacta un aviso en lenguaje claro para el usuario.' },
];

const yesNo = (v) => (v ? 'Sí' : 'No');

/** Lista de comprobaciones [etiqueta, valor, tono] de cada fase a partir del registro del archivo. */
function checksFor(step, rec, ev) {
  const d = ev?.detail || {};
  const rep = rec.report || {};
  switch (step.key) {
    case 'hash_calculado':
      return [
        ['Algoritmo', d.algorithm || 'SHA-256', 'ok'],
        ['Huella', <code key="h" style={{ wordBreak: 'break-all' }}>{d.value || rec.sha256}</code>, 'ok'],
        ['Tamaño', fmtBytes(rec.size), 'ok'],
      ];
    case 'fase1_estatico': {
      const st = rep.static || {};
      const sig = d.signature_query || st.signature_lookup || {};
      const mismatch = d.extension_mismatch ?? st.extension_mismatch;
      const dbl = d.double_extension ?? st.double_extension;
      return [
        ['Tipo real según su contenido', d.real_type || rec.real_type, 'ok'],
        ['Extensión en el nombre', `.${d.declared_ext || st.declared_ext || '—'}`, 'ok'],
        ['¿Coinciden?', mismatch ? 'No, el nombre no dice la verdad' : 'Sí', mismatch ? 'warn' : 'ok'],
        ['Doble extensión', yesNo(dbl), dbl ? 'bad' : 'ok'],
        ['Contenido ejecutable', yesNo(st.executable_content), st.executable_content ? 'bad' : 'ok'],
        ['Puede contener macros', yesNo(st.macro_container), st.macro_container ? 'warn' : 'ok'],
        ['Repositorio de firmas', sig.malicious ? `Malware conocido (${sig.family || 'sin familia'})` : 'Sin coincidencias', sig.malicious ? 'bad' : 'ok'],
      ];
    }
    case 'fase2_heuristico': {
      const findings = rep.heuristic?.findings || [];
      const urls = d.urls || [];
      const rows = [['Enlaces encontrados', urls.length ? `${urls.length}` : 'Ninguno', 'ok']];
      if (!findings.length) rows.push(['Patrones de phishing o ransomware', 'Ninguno detectado', 'ok']);
      findings.forEach((f, i) => rows.push([
        f.kind === 'phishing' ? 'Indicio de phishing' : f.kind === 'ransomware' ? 'Indicio de ransomware' : 'Indicio',
        <span key={i}>{f.claro}<small className="muted" style={{ display: 'block' }}>{f.tecnico}</small></span>,
        f.severity === 'alta' ? 'bad' : 'warn',
      ]));
      return rows;
    }
    case 'fase3_sandbox': {
      const iso = d.isolation || rep.sandbox?.isolation || {};
      const status = d.status || rep.sandbox?.status;
      if (status === 'omitido') return [['Estado', 'Omitida: ya es malware conocido, abrirlo no aporta nada', 'warn']];
      return [
        ['Estado', { ok: 'Se abrió sin problemas', error: 'Error al abrirlo', timeout: 'Tiempo agotado' }[status] || status || '—', status === 'ok' ? 'ok' : 'warn'],
        ['Tipo de aislamiento', iso.backend || rep.sandbox?.backend || '—', 'ok'],
        ['Red bloqueada', yesNo(iso.network_blocked), iso.network_blocked ? 'ok' : 'warn'],
        ['Escritura en disco bloqueada', yesNo(iso.fs_write_blocked), iso.fs_write_blocked ? 'ok' : 'warn'],
      ];
    }
    default: return [];
  }
}

function Check({ label, value, tone }) {
  return (
    <div className={`check ${tone}`}>
      <span className="check-ic"><Icon name={tone === 'ok' ? 'check' : 'warning'} size={14} stroke={2.2} /></span>
      <span className="check-l">{label}</span>
      <span className="check-v">{value}</span>
    </div>
  );
}

function PhaseBody({ step, rec, ev }) {
  const rep = rec.report || {};
  if (step.key === 'fase4_puntaje') {
    const risk = rep.risk || {};
    return (
      <div className="row" style={{ gap: 28, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        <RiskGauge score={rec.risk_score} level={rec.risk_level} />
        <div className="stack" style={{ flex: 1, minWidth: 260 }}>
          <Check label="Puntaje por reglas" value={risk.rule_score ?? '—'} tone="ok" />
          <Check label="Probabilidad de ser malicioso (IA)" value={risk.p_malicious != null ? fmtPct(risk.p_malicious) : '—'} tone={risk.p_malicious > 0.5 ? 'bad' : 'ok'} />
          <Check label="Puntaje final" value={<RiskBadge level={rec.risk_level} score={rec.risk_score} />} tone={rec.risk_level === 'alto' ? 'bad' : rec.risk_level === 'medio' ? 'warn' : 'ok'} />
          {risk.rule_contributions?.length > 0 && (
            <table className="table"><thead><tr><th>Indicador que sumó puntos</th><th className="num">Puntos</th></tr></thead>
              <tbody>{risk.rule_contributions.map(([k, v]) => <tr key={k}><td className="mono">{k}</td><td className="num">+{v}</td></tr>)}</tbody></table>
          )}
          {risk.formula && <div className="small muted">Fórmula: {risk.formula}</div>}
        </div>
      </div>
    );
  }
  if (step.key === 'destino') {
    if (rec.status === 'cuarentena') {
      return (
        <div className="stack">
          <Check label="Decisión" value="Retenido en cuarentena: el puntaje supera 70" tone="bad" />
          <div className="alert alto">{rec.notification}</div>
        </div>
      );
    }
    const top = rep.topic?.top || [];
    return (
      <div className="stack">
        <Check label="Decisión" value="Entregado: el riesgo está por debajo del límite" tone="ok" />
        <Check label="Carpeta asignada por la IA" value={<CategoryChip category={rec.category} />} tone="ok" />
        {top.length > 0 && (
          <div className="bars">
            {top.map(([c, p]) => (
              <div className="bar-row" key={c}><span>{catLabel(c)}</span>
                <div className="bar-track"><div className="bar-fill" style={{ width: `${p * 100}%` }} /></div>
                <span className="num small">{Math.round(p * 100)}%</span></div>
            ))}
          </div>
        )}
        <div className={`alert ${rec.risk_level}`}>{rec.notification}</div>
      </div>
    );
  }
  if (step.key === 'controles_seguridad') return <SecurityControls controls={rep.controls} />;
  if (!ev && step.key !== 'hash_calculado') return <div className="muted">Esta fase no se ejecutó para este archivo.</div>;
  return <div className="checks">{checksFor(step, rec, ev).map(([l, v, t]) => <Check key={l + t} label={l} value={v} tone={t} />)}</div>;
}

function phaseTone(step, rec, ev) {
  if (step.key === 'controles_seguridad') return controlsTone(rec.report?.controls);
  if (step.key === 'fase4_puntaje' || step.key === 'destino') return rec.risk_level === 'alto' ? 'bad' : rec.risk_level === 'medio' ? 'warn' : 'ok';
  const tones = checksFor(step, rec, ev).map((c) => c[2]);
  return tones.includes('bad') ? 'bad' : tones.includes('warn') ? 'warn' : 'ok';
}

export default function Analyze() {
  const groups = useApi(api.groups, []);
  const cats = useApi(api.categories, []);
  const [file, setFile] = useState(null);
  const [group, setGroup] = useState('');
  const [sender, setSender] = useState('');
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [rec, setRec] = useState(null);
  const [step, setStep] = useState(0);
  const [done, setDone] = useState(false);
  const [seen, setSeen] = useState(0); // fase más avanzada que ya vio la persona
  const [open, setOpen] = useState(false);
  const input = useRef(null);
  const panel = useRef(null);
  const toast = useToast();

  useEffect(() => { if (!group && groups.data?.length) setGroup(groups.data[0]); }, [groups.data, group]);
  useEffect(() => { if (rec) panel.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, [rec, step, done]);

  const reset = () => { setRec(null); setStep(0); setDone(false); setSeen(0); };
  useEffect(() => { setSeen((m) => Math.max(m, done ? STEPS.length - 1 : step)); }, [step, done]);
  const pick = (f) => { if (f) { setFile(f); reset(); } };
  const run = async () => {
    setBusy(true); reset();
    try {
      const r = await api.ingest(file, group, sender);
      if (!r.procesado) { toast('El grupo no está monitoreado: el archivo se ignoró (RF1)', 'bad'); return; }
      setRec({ ...(await api.file(r.sha256)), duplicate: r.duplicate });
    } catch (e) { toast(e.message, 'bad'); } finally { setBusy(false); }
  };

  const byEvent = Object.fromEntries((rec?.eventos || []).map((e) => [e.event, e]));
  const cur = STEPS[step];
  const last = step === STEPS.length - 1;

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div className="grid g-main">
        <Card title="Archivo a analizar">
          <div className="stack">
            <div className={`dropzone ${drag ? 'drag' : ''}`} role="button" tabIndex={0}
              onClick={() => input.current?.click()} onKeyDown={(e) => e.key === 'Enter' && input.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
              onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files[0]); }}>
              <Icon name="upload" size={32} />
              {file ? <div><b>{file.name}</b><div className="small muted">{fmtBytes(file.size)}</div></div>
                : <div><b>Arrastra un archivo aquí</b><div className="small muted">o haz clic para elegirlo · máximo 20 MB</div></div>}
              <input ref={input} type="file" hidden onChange={(e) => pick(e.target.files[0])} />
            </div>
            <div className="grid g2">
              <div className="field"><label htmlFor="an-g">Grupo de WhatsApp</label>
                <select id="an-g" className="select" value={group} onChange={(e) => setGroup(e.target.value)}>
                  {(groups.data || []).map((g) => <option key={g}>{g}</option>)}
                  <option value="Grupo no monitoreado">Grupo no monitoreado (prueba RF1)</option>
                </select></div>
              <div className="field"><label htmlFor="an-s">Remitente (opcional)</label>
                <input id="an-s" className="input" value={sender} onChange={(e) => setSender(e.target.value)} placeholder="Ej.: +57 310 000 0000" /></div>
            </div>
            <div className="row"><div className="spacer" />
              <button className="btn btn-primary" disabled={!file || !group || busy} onClick={run}>
                <Icon name="shield" size={16} />{busy ? 'Analizando…' : 'Analizar con el protocolo'}</button></div>
          </div>
        </Card>
        <Card title="Cómo funciona">
          <div className="stack small">
            <div className="muted">El archivo pasa por el protocolo completo y luego te mostramos cada fase por separado. Lee qué se hizo y qué se encontró, y avanza a la siguiente cuando quieras.</div>
            {STEPS.map((s, i) => <div key={s.key}><b>{i + 1}. {s.short}</b> <span className="muted">({s.req})</span></div>)}
          </div>
        </Card>
      </div>

      {busy && <div className="card card-b row"><div className="spinner" /><span>Pasando el archivo por el protocolo de seguridad…</span></div>}

      {rec && (
        <div ref={panel} className="stack" style={{ gap: 16, scrollMarginTop: 80 }}>
          <div className="steps" role="list" aria-label="Fases del protocolo">
            {STEPS.map((s, i) => {
              const state = i === step && !done ? 'active' : i <= seen ? 'done' : '';
              const tone = state === 'done' ? phaseTone(s, rec, byEvent[s.key]) : '';
              return (
                <button key={s.key} role="listitem" type="button" className={`step ${state} ${tone}`}
                  disabled={!state} onClick={() => { setStep(i); setDone(false); }} aria-current={i === step && !done ? 'step' : undefined}>
                  <span className="row small">{state === 'done' ? <Icon name={tone === 'ok' ? 'check' : 'warning'} size={14} /> : <Icon name="clock" size={14} />}{i + 1}</span>
                  <b>{s.short}</b>
                </button>
              );
            })}
          </div>

          {rec.duplicate && <div className="alert">Este archivo ya se había analizado antes (misma huella SHA-256). Te mostramos las fases de ese análisis.</div>}

          {!done ? (
            <section className="card phase" key={cur.key} aria-live="polite">
              <div className="card-b stack" style={{ gap: 18 }}>
                <div className="row" style={{ flexWrap: 'wrap' }}>
                  <span className="eyebrow"><i />Paso {step + 1} de {STEPS.length} · {cur.req}</span>
                  <div className="spacer" />
                  <span className={`badge ${phaseTone(cur, rec, byEvent[cur.key])}`}>
                    {{ ok: 'Sin problemas', warn: 'Revisar', bad: 'Riesgo' }[phaseTone(cur, rec, byEvent[cur.key])]}
                  </span>
                </div>
                <h2 className="phase-title">{cur.title}</h2>
                <div className="phase-what"><b>Qué se hace</b><p>{cur.what}</p></div>
                <div><b className="phase-sub">Qué encontró FileMind en tu archivo</b>
                  <div style={{ marginTop: 10 }}><PhaseBody step={cur} rec={rec} ev={byEvent[cur.key]} /></div></div>
                <div className="row">
                  <button className="btn" disabled={step === 0} onClick={() => setStep((s) => s - 1)}>Anterior</button>
                  <div className="spacer" />
                  <button className="btn btn-ghost" onClick={() => setDone(true)}>Saltar al resultado</button>
                  <button className="btn btn-primary" autoFocus onClick={() => (last ? setDone(true) : setStep((s) => s + 1))}>
                    {last ? 'Ver resultado' : `Siguiente: ${STEPS[step + 1].short}`}<Icon name="arrowRight" size={16} />
                  </button>
                </div>
              </div>
            </section>
          ) : (
            <Card title="Resultado" actions={<>
              <button className="btn btn-sm" onClick={() => { setDone(false); setStep(0); }}>Repasar las fases</button>
              <button className="btn btn-sm" onClick={() => setOpen(true)}>Ver detalle completo</button></>}>
              <div className="row" style={{ gap: 28, flexWrap: 'wrap', alignItems: 'flex-start' }}>
                <RiskGauge score={rec.risk_score} level={rec.risk_level} />
                <div className="stack" style={{ flex: 1, minWidth: 260 }}>
                  <div className="row" style={{ flexWrap: 'wrap' }}><StatusBadge status={rec.status} /><RiskBadge level={rec.risk_level} score={rec.risk_score} />
                    {rec.category && <CategoryChip category={rec.category} />}
                    {rec.category_confidence != null && <span className="small muted">confianza {fmtPct(rec.category_confidence, 0)}</span>}</div>
                  <div className={`alert ${rec.risk_level}`}>{rec.notification}</div>
                  <div className="small muted">Tipo real {rec.real_type} · protocolo completo en {rec.protocol_seconds?.toFixed(2)} s (límite 15 s)</div>
                </div>
              </div>
            </Card>
          )}
        </div>
      )}
      {open && rec && <FileDrawer sha={rec.sha256} categories={cats.data || []} onClose={() => setOpen(false)} onChanged={() => {}} />}
    </div>
  );
}
