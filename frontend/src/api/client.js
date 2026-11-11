// Cliente de la API de FileMind. Todas las llamadas pasan por aquí.
// La sesión viaja en una cookie HttpOnly (el código de la página no puede leerla).

// Espacio de trabajo elegido en la barra superior: limita archivos, estadísticas y avisos.
let space = null;
export const setSpace = (id) => { space = id || null; };
const SCOPED = ['/api/archivos', '/api/estadisticas', '/api/notificaciones', '/api/bufete/resumen'];
const SCOPED_POST = ['/api/bufete/guardar-pendientes'];

// Varias partes de la pantalla piden lo mismo a la vez (p. ej. las estadísticas las piden la
// barra superior, el Panel y Archivos): mientras una petición GET igual está en camino se comparte.
const inflight = new Map();

function request(path, opts = {}) {
  if ((opts.method || 'GET') !== 'GET') return doRequest(path, opts);
  const key = `${path}|${space || ''}`;
  if (inflight.has(key)) return inflight.get(key);
  const p = doRequest(path, opts).finally(() => inflight.delete(key));
  inflight.set(key, p);
  return p;
}

async function doRequest(path, { method = 'GET', body, form } = {}) {
  const headers = {};
  const scoped = method === 'GET'
    ? SCOPED.some((p) => path === p || path.startsWith(`${p}?`) || path.startsWith(`${p}/serie`))
    : SCOPED_POST.some((p) => path === p || path.startsWith(`${p}?`));
  if (space && scoped) {
    path += `${path.includes('?') ? '&' : '?'}espacio=${space}`;
  }
  let payload;
  if (form) payload = form;
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
  const res = await fetch(path, { method, headers, body: payload, credentials: 'same-origin' });
  if (res.status === 401 && !path.startsWith('/api/auth/')) window.dispatchEvent(new Event('filemind:sin-sesion'));
  const isJson = (res.headers.get('content-type') || '').includes('json');
  const data = isJson ? await res.json() : await res.text();
  if (!res.ok) {
    const detail = isJson ? data.detail : data;
    const msg = Array.isArray(detail) ? detail.map((d) => d.msg).join('; ') : detail;
    throw new Error(msg || `Error ${res.status}`);
  }
  return data;
}

export const api = {
  // sesión y cuentas
  authState: () => request('/api/auth/estado'),
  login: (usuario, contrasena) => request('/api/auth/entrar', { method: 'POST', body: { usuario, contrasena } }),
  setup: (usuario, nombre, contrasena) => request('/api/auth/configurar', { method: 'POST', body: { usuario, nombre, contrasena } }),
  logout: () => request('/api/auth/salir', { method: 'POST' }),
  changePassword: (actual, nueva) => request('/api/auth/contrasena', { method: 'POST', body: { actual, nueva } }),
  users: () => request('/api/usuarios'),
  createUser: (u) => request('/api/usuarios', { method: 'POST', body: u }),
  updateUser: (id, patch) => request(`/api/usuarios/${id}`, { method: 'PATCH', body: patch }),
  deleteUser: (id) => request(`/api/usuarios/${id}`, { method: 'DELETE' }),
  spaces: () => request('/api/espacios'),
  spaceChats: () => request('/api/espacios/chats-disponibles'),
  saveSpace: (id, w) => request(id ? `/api/espacios/${id}` : '/api/espacios', { method: id ? 'PUT' : 'POST', body: w }),
  deleteSpace: (id) => request(`/api/espacios/${id}`, { method: 'DELETE' }),
  series: (dias = 30) => request(`/api/estadisticas/serie?dias=${dias}`),
  reportUrl: (sha) => `/api/archivos/${sha}/reporte.pdf`,
  health: () => request('/health'),
  stats: () => request('/api/estadisticas'),
  availability: () => request('/api/disponibilidad'),
  config: () => request('/api/configuracion'),
  categories: () => request('/api/categorias'),
  groups: () => request('/api/grupos').then((r) => r.grupos),
  groupCounts: () => request('/api/grupos/conteo'),
  whatsapp: () => request('/api/whatsapp'),
  whatsappConnection: () => request('/api/whatsapp/conexion'),
  unlinkWhatsapp: () => request('/api/whatsapp/desvincular', { method: 'POST' }),
  startBridge: () => request('/api/whatsapp/encender', { method: 'POST' }),
  saveGroups: (grupos) => request('/api/grupos', { method: 'PUT', body: { grupos } }),
  files: (params = {}) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v)).toString();
    return request(`/api/archivos${q ? `?${q}` : ''}`);
  },
  file: (sha) => request(`/api/archivos/${sha}`),
  downloadUrl: (sha) => `/api/archivos/${sha}/descargar`,
  correct: (sha, categoria) => request(`/api/archivos/${sha}/categoria`, { method: 'POST', body: { categoria } }),
  release: (sha, categoria, motivo) =>
    request(`/api/cuarentena/${sha}/liberar`, { method: 'POST', body: { categoria, motivo, confirmar: true } }),
  remove: (sha) => request(`/api/cuarentena/${sha}`, { method: 'DELETE' }),
  ingest: (file, grupo, remitente) => {
    const form = new FormData();
    form.append('file', file);
    form.append('grupo', grupo);
    form.append('remitente', remitente || '');
    form.append('message_ts', String(Date.now() / 1000));
    return request('/api/ingest', { method: 'POST', form });
  },
  models: () => request('/api/modelos'),
  retrain: () => request('/api/reentrenar', { method: 'POST' }),
  events: (sha, limite = 300) => request(`/api/eventos?limite=${limite}${sha ? `&sha=${sha}` : ''}`),
  retention: () => request('/api/auditoria/retencion'),
  notifications: () => request('/api/notificaciones'),
  // RF9 a RF11: exportar los archivos de un chat
  exports: () => request('/api/exportaciones'),
  exportJob: (id) => request(`/api/exportaciones/${id}`),
  startExport: (chat, completo = false) => request('/api/exportaciones', { method: 'POST', body: { chat_id: chat.id, chat_nombre: chat.nombre, completo } }),
  exportHistory: (chatId) => request(`/api/exportaciones/historial?chat_id=${encodeURIComponent(chatId)}`),
  cancelExport: (id) => request(`/api/exportaciones/${id}/cancelar`, { method: 'POST' }),
  saveExport: (id, destino) => request(`/api/exportaciones/${id}/guardar`, { method: 'POST', body: { destino } }),
  exportZipUrl: (id) => `/api/exportaciones/${id}/zip`,
  // Carpeta del bufete: una subcarpeta por etiqueta en el PC
  bufete: () => request('/api/bufete'),
  saveBufete: (cfg) => request('/api/bufete', { method: 'PUT', body: cfg }),
  createBufeteFolders: () => request('/api/bufete/crear-carpetas', { method: 'POST' }),
  bufeteSummary: () => request('/api/bufete/resumen'),
  savePending: (limite = 25) => request(`/api/bufete/guardar-pendientes?limite=${limite}`, { method: 'POST' }),
  saveFileToBufete: (sha) => request(`/api/archivos/${sha}/guardar-en-carpeta`, { method: 'POST' }),
  browseFolders: (ruta = '') => request(`/api/bufete/explorar?ruta=${encodeURIComponent(ruta)}`),
  newFolder: (ruta, nombre) => request('/api/bufete/nueva-carpeta', { method: 'POST', body: { ruta, nombre } }),
  // Diálogo de Windows para escoger carpeta (lo abre el servidor, que corre en este mismo PC)
  pickBufeteFolder: async () => {
    const r = await nativeFolder('Carpeta del bufete');
    if (r !== null) return r;
    return (await request('/api/bufete/elegir-carpeta', { method: 'POST' })).ruta;
  },
  // En la app de escritorio el selector es nativo (pywebview); en la web lo abre el servidor local
  pickFolder: async () => {
    const r = await nativeFolder('Carpeta donde guardar los archivos seguros');
    if (r !== null) return r;
    return (await request('/api/exportaciones/elegir-carpeta', { method: 'POST' })).ruta;
  },
  nativeFolder: (titulo) => nativeFolder(titulo),
  hasNativeFolder: () => fetch(`${SELECTOR}/ping`).then((r) => r.ok).catch(() => false),
};

// Selector de carpetas de Windows (tools/selector_carpetas.py): corre en el PC, fuera de Docker.
const SELECTOR = 'http://127.0.0.1:8765';

/** Abre la ventana «Seleccionar carpeta» de Windows. Devuelve la ruta, '' si se canceló o null si no hay selector. */
async function nativeFolder(titulo) {
  if (window.pywebview?.api?.elegir_carpeta) return (await window.pywebview.api.elegir_carpeta()) || '';
  let r;
  try {
    r = await fetch(`${SELECTOR}/elegir`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ titulo }) });
  } catch { return null; }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || 'No se pudo abrir la ventana de Windows.');
  return j.ruta || '';
}
