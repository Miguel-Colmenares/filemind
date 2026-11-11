import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client.js';
import { useApi } from '../hooks/useApi.js';
import FileDrawer from '../components/FileDrawer.jsx';
import { AcademicHero } from '../components/Academic.jsx';
import ActivityChart from '../components/ActivityChart.jsx';
import { BufeteCard } from '../components/Bufete.jsx';
import { AddChats, FirstSteps } from '../components/GettingStarted.jsx';
import { Card, CategoryChip, Empty, Kpi, Loading, RiskBadge, StatusBadge } from '../components/ui.jsx';
import { catColor, catLabel, fmtDate, fmtNum, fmtPct } from '../utils/format.js';

export default function Dashboard() {
  const stats = useApi(api.stats, [], { interval: 10000 });
  const recent = useApi(() => api.files({ limite: 8 }), [], { interval: 10000 });
  const avail = useApi(api.availability, [], { interval: 30000 });
  const models = useApi(api.models, []);
  const cats = useApi(api.categories, []);
  const [open, setOpen] = useState(null);

  const s = stats.data || {};
  const byStatus = s.por_estado || {};
  const total = Object.values(byStatus).reduce((a, b) => a + b, 0);
  const byCat = s.por_categoria || {};
  const maxCat = Math.max(1, ...Object.values(byCat));
  const risk = models.data?.riesgo?.cuarentena_umbral_70;

  return (
    <div className="stack" style={{ gap: 20 }}>
      <AcademicHero />
      <FirstSteps />
      <div className="grid g4">
        <Kpi icon="files" label="Archivos recibidos" value={total} hint={`${byStatus.duplicado || 0} duplicados detectados`} />
        <Kpi icon="folder" label="Clasificados" value={byStatus.clasificado || 0} hint="Guardados en su carpeta" tone="ok" />
        <Kpi icon="lock" label="En cuarentena" value={byStatus.cuarentena || 0} hint="Riesgo mayor a 70" tone="bad" />
        <Kpi icon="clock" label="Tiempo del protocolo" value={s.tiempo_promedio_s != null ? `${fmtNum(s.tiempo_promedio_s, 2)} s` : '—'}
          hint={s.tiempo_maximo_s != null ? `máximo ${fmtNum(s.tiempo_maximo_s, 2)} s · límite 15 s` : 'Límite 15 s por archivo (RNF1)'} tone="warn" />
      </div>

      <ActivityChart />

      <div className="grid g-main">
        <Card title="Últimos archivos" pad={false} actions={<div className="row" style={{ gap: 6 }}><AddChats compact /><Link className="btn btn-sm btn-ghost" to="/archivos">Ver todos</Link></div>}>
          {recent.loading ? <Loading /> : recent.data?.length ? (
            <div className="table-wrap">
              <table className="table stack-sm">
                <thead><tr><th>Archivo</th><th>Estado</th><th>Riesgo</th><th>Categoría</th></tr></thead>
                <tbody>
                  {recent.data.map((f) => (
                    <tr key={f.sha256} className="clickable" onClick={() => setOpen(f.sha256)}>
                      <td className="file-name">{f.original_name}<small>{f.group_name} · {fmtDate(f.detected_at)}</small></td>
                      <td><StatusBadge status={f.status} /></td>
                      <td><RiskBadge level={f.risk_level} score={f.risk_score} /></td>
                      <td><CategoryChip category={f.category} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty title="Aún no llegan archivos">
              Cuando alguien comparta un documento en un grupo monitoreado aparecerá aquí. También puedes <Link to="/analizar">analizar uno a mano</Link>.
            </Empty>
          )}
        </Card>

        <div className="stack">
          <BufeteCard compact onChanged={recent.reload} />
          <Card title="Archivos por etiqueta" actions={<Link className="btn btn-sm btn-ghost" to="/archivos">Filtrar</Link>}>
            {Object.keys(byCat).length ? (
              <div className="bars">
                {[...new Set([...(s.categorias || []), ...Object.keys(byCat)])].filter((c) => byCat[c]).sort((a, b) => byCat[b] - byCat[a]).map((c) => (
                  <Link className="bar-row link-row" key={c} to={`/archivos?categoria=${encodeURIComponent(c)}`}>
                    <span><i className="cat-dot" style={{ background: catColor(c) }} />{catLabel(c)}</span>
                    <div className="bar-track"><div className="bar-fill" style={{ width: `${((byCat[c] || 0) / maxCat) * 100}%`, background: catColor(c) }} /></div>
                    <span className="num small">{byCat[c] || 0}</span></Link>
                ))}
              </div>
            ) : <div className="small muted">Sin archivos clasificados todavía.</div>}
          </Card>
          <Card title="Estado del sistema">
            <div className="stack small">
              <div className="row"><span>Disponibilidad del mes</span><div className="spacer" />
                <b>{avail.data ? `${fmtNum(avail.data.disponibilidad, 2)} %` : '—'}</b>
                {avail.data && <span className={`badge ${avail.data.rnf2_cumple ? 'ok' : 'bad'}`}>meta 98 %</span>}</div>
              <div className="row"><span>Modelo temático</span><div className="spacer" />
                <b>{models.data?.tema?.best_model || '—'}</b><span className="muted">F1 {fmtNum(models.data?.tema?.test?.f1_macro)}</span></div>
              <div className="row"><span>Falsos negativos (riesgo)</span><div className="spacer" />
                <b>{risk ? fmtPct(risk.tasa_falsos_negativos) : '—'}</b><span className="muted">meta ≤ 5 %</span></div>
              <div className="row"><span>Falsos positivos (riesgo)</span><div className="spacer" />
                <b>{risk ? fmtPct(risk.tasa_falsos_positivos) : '—'}</b><span className="muted">meta ≤ 10 %</span></div>
              <div className="row"><span>Firmas de malware locales</span><div className="spacer" /><b>{s.firmas ?? '—'}</b></div>
            </div>
          </Card>
        </div>
      </div>
      {open && <FileDrawer sha={open} categories={cats.data || []} onClose={() => setOpen(null)} onChanged={() => { recent.reload(); stats.reload(); }} />}
    </div>
  );
}
