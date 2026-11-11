// Accesos para agregar chats y la guía de «Primeros pasos» del Panel.
import { Link } from 'react-router-dom';
import { api } from '../api/client.js';
import { useApi } from '../hooks/useApi.js';
import { useAuth } from './Auth.jsx';
import Icon from './Icon.jsx';
import { Card } from './ui.jsx';

/** Botón «+ Agregar chats» (administrador) o aviso para pedírselo al administrador (miembro). */
export function AddChats({ compact = false }) {
  const { isAdmin } = useAuth();
  if (!isAdmin) {
    return <span className="small muted"><Icon name="whatsapp" size={14} /> ¿Falta un chat? Pídele al administrador que lo agregue.</span>;
  }
  return (
    <Link className={`btn ${compact ? 'btn-sm' : ''}`} to="/grupos" title="Escoger de qué chats de WhatsApp se analizan y clasifican los archivos">
      <Icon name="plus" size={16} />Agregar chats
    </Link>
  );
}

/** Tarjeta con los 3 pasos para dejar FileMind funcionando; desaparece cuando todo está listo. */
export function FirstSteps() {
  const { isAdmin } = useAuth();
  const none = () => Promise.resolve(null); // un miembro no ve esta guía (y no puede consultar WhatsApp)
  const wa = useApi(isAdmin ? api.whatsapp : none, [isAdmin], { interval: 15000 });
  const groups = useApi(isAdmin ? api.groups : none, [isAdmin], { interval: 30000 });
  const bufete = useApi(isAdmin ? api.bufeteSummary : none, [isAdmin], { interval: 30000 });
  if (!isAdmin || !wa.data || !groups.data || !bufete.data) return null;
  const steps = [
    { done: wa.data.estado === 'conectado', title: 'Conectar WhatsApp', text: wa.data.estado === 'conectado'
      ? `Conectado${wa.data.cuenta ? ` como ${wa.data.cuenta}` : ''}.` : 'Enciende el puente y escanea el código QR con el celular del bufete.', to: '/grupos', cta: 'Conectar' },
    { done: groups.data.length > 0, title: 'Escoger los chats', text: groups.data.length
      ? `${groups.data.length} chat(s) en análisis.` : 'Marca los chats o grupos cuyos archivos quieres revisar y clasificar.', to: '/grupos', cta: 'Escoger chats' },
    { done: bufete.data.configurada, title: 'Elegir la carpeta del bufete', text: bufete.data.configurada
      ? 'Los archivos se guardan solos en su subcarpeta.' : 'Escoge una carpeta del PC: cada documento se guardará en la subcarpeta de su etiqueta.', to: '/configuracion#carpeta', cta: 'Elegir carpeta' },
  ];
  if (steps.every((s) => s.done)) return null;
  return (
    <Card className="first-steps" title={<><Icon name="checklist" size={18} /> Primeros pasos</>}>
      <ol>
        {steps.map((s, i) => (
          <li key={s.title} className={s.done ? 'done' : ''}>
            <span className="step-n">{s.done ? <Icon name="check" size={12} /> : i + 1}</span>
            <div className="grow"><b>{s.title}</b><div className="small muted">{s.text}</div></div>
            {!s.done && <Link className="btn btn-primary btn-sm" to={s.to}>{s.cta}<Icon name="arrowRight" size={14} /></Link>}
          </li>
        ))}
      </ol>
    </Card>
  );
}
