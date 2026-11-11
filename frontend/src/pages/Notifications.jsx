import { api } from '../api/client.js';
import { useApi } from '../hooks/useApi.js';
import { Card, Empty, Loading, RiskBadge } from '../components/ui.jsx';
import { fmtDate } from '../utils/format.js';

export default function Notifications() {
  const notes = useApi(api.notifications, [], { interval: 10000 });
  const list = [...(notes.data || [])].reverse();
  return (
    <div className="grid g-main">
      <div className="stack">
        {notes.loading ? <Loading /> : list.length ? list.map((n) => (
          <Card key={n.id}>
            <div className="stack">
              <div className="row small"><RiskBadge level={n.level} /><span>{n.group}</span><div className="spacer" /><span className="muted">{fmtDate(n.ts)}</span></div>
              <div className={`alert ${n.level}`}>{n.message}</div>
            </div>
          </Card>
        )) : <Card><Empty icon="bell" title="Sin avisos">Solo se avisa cuando un archivo tiene riesgo medio o alto.</Empty></Card>}
      </div>
      <Card title="Cómo se redactan">
        <div className="stack small">
          <p>Los avisos se escriben para cualquier persona, no para técnicos (RNF7):</p>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            <li>Primero qué pasó y con qué archivo.</li>
            <li>Luego por qué, en palabras simples.</li>
            <li>Al final qué hacer, con una acción concreta.</li>
            <li>Sin siglas ni términos como «hash», «macro VBA» o «sandbox».</li>
          </ul>
          <p className="muted">El puente de WhatsApp envía estos mensajes por chat privado. Una prueba automática revisa que no aparezcan términos técnicos; la encuesta a 5 usuarios está en <code>docs/encuesta_rnf7.md</code>.</p>
        </div>
      </Card>
    </div>
  );
}
