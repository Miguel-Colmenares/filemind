import { Fragment } from 'react';
import { api } from '../api/client.js';
import { useApi } from '../hooks/useApi.js';
import Icon from '../components/Icon.jsx';
import { Card, Loading } from '../components/ui.jsx';
import { BufeteSettings } from '../components/Bufete.jsx';

const LABELS = {
  monitored_groups: 'Grupos monitoreados', quarantine_threshold: 'Umbral de cuarentena', max_protocol_seconds: 'Tiempo máximo del protocolo (s)',
  max_file_mb: 'Tamaño máximo (MB)', log_retention_days: 'Retención de la auditoría (días)', sandbox_backend: 'Entorno aislado configurado',
  sandbox_efectivo: 'Entorno aislado en uso', sandbox_timeout_s: 'Tiempo límite del entorno aislado (s)', sandbox_image: 'Imagen de Docker',
  topic_min_confidence: 'Confianza mínima para clasificar', workers: 'Hilos de análisis', rdap_lookup: 'Consulta de dominios (RDAP)',
  external_lookup_timeout_s: 'Tiempo límite de consultas externas (s)', malwarebazaar_api_key: 'Clave de MalwareBazaar',
  virustotal_api_key: 'Clave de VirusTotal', notify_webhook: 'Webhook de notificaciones', api_token: 'Token de la API', data_dir: 'Carpeta de datos',
};
const SECRET = new Set(['malwarebazaar_api_key', 'virustotal_api_key', 'api_token']);
const show = (k, v) => {
  if (SECRET.has(k)) return v ? 'Configurada' : <span className="muted">Sin configurar</span>;
  if (Array.isArray(v)) return v.join(', ') || '—';
  if (typeof v === 'boolean') return v ? 'Sí' : 'No';
  return v === '' || v == null ? <span className="muted">—</span> : String(v);
};

export default function Settings() {
  const cfg = useApi(api.config, []);
  return (
    <div className="stack" style={{ gap: 20 }}>
    <BufeteSettings />
    <div className="grid g-main">
      <Card title="Parámetros activos">
        {cfg.loading ? <Loading /> : (
          <dl className="kv">
            {Object.entries(cfg.data || {}).map(([k, v]) => <Fragment key={k}><dt>{LABELS[k] || k}</dt><dd>{show(k, v)}</dd></Fragment>)}
          </dl>
        )}
        <div className="small muted" style={{ marginTop: 16 }}>Se cambian en <code>backend/config.json</code> o con variables de entorno <code>FILEMIND_*</code>. Las claves nunca se muestran.</div>
      </Card>
      <div className="stack">
        <Card title="Seguridad del acceso">
          <ul className="small stack" style={{ margin: 0, paddingLeft: 18, gap: 6 }}>
            <li>Cada persona entra con su usuario. Las contraseñas se guardan con PBKDF2-SHA256 y sal, nunca en texto plano.</li>
            <li>La sesión viaja en una cookie <code>HttpOnly</code> y <code>SameSite=Strict</code> que dura 12 horas.</li>
            <li>Cinco intentos fallidos bloquean la cuenta 5 minutos. Cada intento queda en la auditoría.</li>
            <li>Un miembro solo ve los archivos de los chats de sus espacios de trabajo, y de las etiquetas que filtre cada espacio. El administrador ve todo.</li>
            <li>El puente de WhatsApp usa su propio token de servicio, guardado en <code>backend/data/api_token.txt</code>.</li>
          </ul>
        </Card>
        <Card title="Documentación técnica">
          <div className="stack small">
            <a className="btn btn-sm" href="/docs" target="_blank" rel="noreferrer"><Icon name="server" size={14} />API interactiva (Swagger)</a>
            <span className="muted">Todos los puntos de la API con sus esquemas y ejemplos.</span>
          </div>
        </Card>
      </div>
    </div>
    </div>
  );
}
