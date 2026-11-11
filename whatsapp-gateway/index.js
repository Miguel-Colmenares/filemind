/**
 * Puente WhatsApp -> FileMind.
 *
 * Vinculación: el QR se muestra en la terminal y también en la interfaz web
 *      (página "Chats de WhatsApp"), que recibe el estado por POST /api/whatsapp/estado.
 * Selección de chats: el puente publica la lista de chats (grupos y privados) en
 *      POST /api/whatsapp/chats; en la interfaz se escoge cuáles se analizan.
 * RF1: solo se descargan archivos de los chats escogidos en FileMind
 *      (GET /api/grupos). Los mensajes de otros chats NO se descargan ni se envían.
 * RF2: cada adjunto se envía a /api/ingest apenas llega, junto con la hora del
 *      mensaje (message_ts) para medir la latencia de detección (<= 10 s).
 * RNF2: reconexión automática si la sesión se cae. Un vigilante consulta el estado del
 *      cliente cada minuto; si la página de WhatsApp Web muere (p. ej. "detached Frame")
 *      o deja de responder, se crea un cliente nuevo con espera exponencial (5 s, 10 s,
 *      20 s… hasta 5 min). Los archivos que no se pudieron entregar porque FileMind
 *      estaba apagado quedan en una cola en disco (.pendientes/) y se reenvían solos.
 * RNF7: las alertas en lenguaje claro se reenvían por WhatsApp.
 * RF9: exportación manual de un chat. La interfaz crea un trabajo; el puente lo toma
 *      de GET /api/exportaciones/pendiente, publica la lista de adjuntos del historial
 *      y los sube uno por uno para que cada archivo se analice antes del siguiente.
 *      La importación es incremental: con cada adjunto se envía la huella SHA-256 que
 *      trae WhatsApp y FileMind marca como omitidos los mensajes ya importados y los
 *      archivos que ya tiene, así solo se descargan los nuevos.
 *
 * Usa whatsapp-web.js (librería NO oficial, ver limitaciones del documento).
 */
const fs = require('fs');
const { execSync } = require('child_process');
const path = require('path');
const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const QRCode = require('qrcode');
const { isPageDead, backoffDelay, withRetry, withTimeout, Health, Outbox, hashHex } = require('./lib');

// Carga simple de .env sin dependencias
const envFile = path.join(__dirname, '.env');
if (fs.existsSync(envFile)) {
  for (const line of fs.readFileSync(envFile, 'utf8').split('\n')) {
    const m = line.match(/^\s*([A-Z_]+)\s*=\s*(.*)\s*$/);
    if (m && !(m[1] in process.env)) process.env[m[1]] = m[2];
  }
}
const API = process.env.FILEMIND_URL || 'http://127.0.0.1:8000';
// Token de servicio: FILEMIND_TOKEN o, si no se define, el que FileMind genera solo en
// backend/data/api_token.txt (FILEMIND_TOKEN_FILE para otra ruta). Desde la versión web toda la
// API exige sesión o este token.
const TOKEN_FILE = process.env.FILEMIND_TOKEN_FILE || path.join(__dirname, '..', 'backend', 'data', 'api_token.txt');
const NOTIFY_TO = process.env.NOTIFY_TO || '';
const NOTIFY_IN_GROUP = (process.env.NOTIFY_IN_GROUP || 'true') === 'true';
const EXPORT_LIMIT = Number(process.env.EXPORT_LIMIT || 1000); // mensajes del historial que se revisan
const headers = {};
function refreshToken() {
  let t = process.env.FILEMIND_TOKEN || '';
  if (!t) { try { t = fs.readFileSync(TOKEN_FILE, 'utf8').trim(); } catch { /* FileMind aún no lo crea */ } }
  if (t) headers['X-FileMind-Token'] = t; else delete headers['X-FileMind-Token'];
}
refreshToken();
setInterval(refreshToken, 30000).unref();

const log = (...a) => console.log(new Date().toISOString(), ...a);
let allowed = new Set();
let lastNotification = 0;
let status = { estado: 'iniciando', desde: Date.now() };
let client = null;
let restartTimer = null;
let restartAttempt = 0;
const health = new Health({ maxFailures: 2 });
const outbox = new Outbox(path.join(__dirname, '.pendientes'));
const WATCHDOG_MS = Number(process.env.WATCHDOG_MS || 60000);
const STUCK_START_MS = 300000; // si en 5 min no conecta ni pide QR, se reinicia (con 460 chats la carga tarda ~2,5 min)

async function postJSON(route, body) {
  try {
    const r = await fetch(`${API}${route}`, { method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    return r.ok ? await r.json().catch(() => null) : null;
  } catch (e) { return null; /* FileMind no disponible: se reenvía en el siguiente latido */ }
}

function statusPayload() {
  const { desde, ...rest } = status;
  return { ...rest, salud: { ...health.snapshot(), cola_pendiente: outbox.size() } };
}

async function setStatus(next) {
  status = { ...next, desde: next.estado === status.estado ? status.desde : Date.now() };
  onOrder(await postJSON('/api/whatsapp/estado', statusPayload()));
}

// Órdenes de la interfaz que llegan en la respuesta del estado
function onOrder(j) {
  if (j && j.accion === 'desvincular') unlink();
}

// Desvincular (botón «Desvincular y usar otro número»): cierra la sesión en WhatsApp, borra la sesión
// guardada y arranca un cliente nuevo, que mostrará un QR para escanear con el otro número.
let unlinking = false;
async function unlink() {
  if (unlinking) return;
  unlinking = true;
  log('[conexión] desvinculando el número actual por pedido del administrador');
  if (restartTimer) { clearTimeout(restartTimer); restartTimer = null; }
  const old = client;
  client = null;
  if (old) {
    await withTimeout(old.logout(), 20000, 'cerrar sesión').catch((e) => log('[conexión] cierre de sesión:', e.message));
    await withTimeout(old.destroy(), 20000, 'cerrar navegador').catch(() => {});
  }
  killBrowser(old);
  try { fs.rmSync(SESSION_DIR, { recursive: true, force: true }); } catch (e) { log('[conexión] no se pudo borrar la sesión:', e.message); }
  restartAttempt = 0;
  unlinking = false;
  await setStatus({ estado: 'iniciando' });
  start();
}

// Toda falla de la página pasa por aquí: decide si hay que reiniciar el cliente
function reportFailure(where, e) {
  log(`[${where}]`, e && e.message ? e.message : e);
  if (health.fail(e)) scheduleRestart(`${where}: ${health.lastError}`);
}

async function refreshGroups() {
  try {
    const r = await fetch(`${API}/api/grupos`, { headers });
    const j = await r.json();
    const next = new Set(j.grupos);
    if ([...next].join('|') !== [...allowed].join('|')) log('[chats] monitoreados:', [...next]);
    allowed = next;
  } catch (e) {
    log('[chats] FileMind no responde:', e.message);
  }
}

// Lectura directa del almacén de WhatsApp Web. Respaldo para cuando client.getChats() /
// msg.getChat() fallan con versiones nuevas de WhatsApp Web (error minificado "r").
function readChatsFromPage(onlyId) {
  return client.pupPage.evaluate((onlyId) => {
    const models = window.require('WAWebCollections').Chat.getModelsArray();
    return models
      .filter((c) => !onlyId || c.id._serialized === onlyId)
      .map((c) => ({
        id: c.id._serialized,
        nombre: c.formattedTitle || c.name || (c.contact && (c.contact.name || c.contact.pushname)) || c.id.user,
        grupo: !!(c.isGroup || c.id.server === 'g.us'),
      }));
  }, onlyId || null);
}

async function listChats() {
  try {
    return (await client.getChats()).map((c) => ({ id: c.id._serialized, nombre: c.name, grupo: !!c.isGroup }));
  } catch (e) {
    return readChatsFromPage();
  }
}

async function chatOf(msg) {
  try {
    const c = await msg.getChat();
    return { id: c.id._serialized, nombre: c.name };
  } catch (e) {
    const id = msg.fromMe ? msg.to : msg.from;
    const [c] = await readChatsFromPage(id);
    return c || { id, nombre: '' };
  }
}

async function syncChats() {
  if (status.estado !== 'conectado') return;
  try {
    const list = (await listChats()).filter((c) => c.nombre && c.id !== 'status@broadcast');
    await postJSON('/api/whatsapp/chats', { chats: list });
    log(`[chats] ${list.length} chats enviados a la interfaz`);
    health.ok();
  } catch (e) {
    reportFailure('chats', e);
  }
}

function createClient() {
  const c = new Client({
    authStrategy: new LocalAuth({ dataPath: path.join(__dirname, '.wwebjs_auth') }),
    // En Docker se usa el Chromium del sistema (PUPPETEER_EXECUTABLE_PATH); en Windows, el que trae puppeteer.
    puppeteer: { headless: true, executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
      args: ['--no-sandbox', '--disable-dev-shm-usage'] },
  });
  c.on('qr', async (qr) => {
    log('Escanee este código QR con WhatsApp > Dispositivos vinculados (también aparece en la interfaz web)');
    qrcode.generate(qr, { small: true });
    await setStatus({ estado: 'esperando_qr', qr: await QRCode.toDataURL(qr, { margin: 1, width: 320 }) });
  });
  c.on('authenticated', () => setStatus({ estado: 'iniciando' }));
  c.on('ready', async () => {
    log('[conexión] activa');
    if (restartTimer) { // conectó justo cuando el vigilante iba a reiniciar: se cancela el reinicio
      clearTimeout(restartTimer);
      restartTimer = null;
    }
    restartAttempt = 0;
    health.ok();
    const info = c.info || {};
    await setStatus({ estado: 'conectado', cuenta: [info.pushname, info.wid && info.wid.user].filter(Boolean).join(' · ') });
    await refreshGroups();
    await syncChats();
    flushOutbox();
  });
  c.on('change_state', (s) => log('[conexión] estado de WhatsApp:', s));
  c.on('loading_screen', (pct, msg) => log(`[conexión] cargando WhatsApp Web ${pct} % ${msg || ''}`));
  c.on('auth_failure', (m) => log('[conexión] la sesión guardada no sirve, hay que escanear el QR:', m));
  c.on('disconnected', (reason) => {
    if (unlinking) return; // la desvinculación pedida desde la interfaz ya crea el cliente nuevo
    log('[conexión] perdida:', reason, reason === 'LOGOUT' ? '(habrá que escanear el QR de nuevo)' : '');
    scheduleRestart(`desconexión: ${reason}`);
  });
  // Mensajes recibidos y también los que envía la cuenta vinculada (p. ej. reenviados por el abogado)
  c.on('message', handleMessage);
  c.on('message_create', (msg) => { if (msg.fromMe) handleMessage(msg); });
  return c;
}

// Si el navegador viejo no se cierra, deja bloqueada la carpeta de la sesión y todos los
// reinicios fallan con «The browser is already running» (210 veces entre el 28 de octubre y
// el 3 de noviembre). Por eso, además de destroy(), se mata el proceso y cualquier Chrome que
// siga usando esa carpeta. Solo toca los Chrome con el perfil del puente, no el del usuario.
const SESSION_DIR = path.join(__dirname, '.wwebjs_auth');

function killBrowser(c) {
  try {
    const proc = c && c.pupBrowser && c.pupBrowser.process();
    if (proc && !proc.killed) proc.kill('SIGKILL');
  } catch (e) { /* ya estaba cerrado */ }
  try {
    if (process.platform === 'win32') {
      execSync('powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \\"Name=\'chrome.exe\'\\" | '
        + 'Where-Object { $_.CommandLine -like \'*wwebjs_auth*\' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"',
      { stdio: 'ignore', timeout: 15000 });
    } else {
      execSync(`pkill -9 -f "${SESSION_DIR}"`, { stdio: 'ignore', timeout: 15000 });
    }
  } catch (e) { /* no había procesos sueltos */ }
}

// En Docker, al recrear el contenedor quedan los candados del Chromium anterior (SingletonLock con
// el nombre del contenedor viejo) y el navegador no arranca: «Code: 21, profile appears to be in use».
// Antes de arrancar no hay ningún Chromium nuestro vivo (killBrowser), así que se pueden borrar.
function clearProfileLocks() {
  for (const f of ['SingletonLock', 'SingletonCookie', 'SingletonSocket']) {
    try { fs.rmSync(path.join(SESSION_DIR, 'session', f), { force: true }); } catch (e) { /* no estaba */ }
  }
}

function start() {
  if (process.platform !== 'win32') clearProfileLocks();
  client = createClient();
  status.desde = Date.now();
  client.initialize().catch((e) => {
    log('[conexión] no se pudo iniciar:', e.message);
    if (/already running/i.test(e.message)) killBrowser(client);
    scheduleRestart(`inicio fallido: ${e.message}`);
  });
}

// Reinicio con espera exponencial: se destruye el navegador viejo y se crea un cliente
// nuevo (reusar el mismo objeto deja la página "detached" de la versión anterior).
function scheduleRestart(reason) {
  if (restartTimer) return;
  const wait = backoffDelay(restartAttempt, { base: 5000, max: 300000 });
  restartAttempt += 1;
  health.lastError = String(reason).slice(0, 300);
  log(`[conexión] reinicio #${restartAttempt} en ${(wait / 1000).toFixed(0)} s (${reason})`);
  setStatus({ estado: 'reconectando', reintento_en_s: Math.round(wait / 1000) });
  restartTimer = setTimeout(async () => {
    const old = client;
    client = null;
    if (old) await withTimeout(old.destroy(), 20000, 'cerrar navegador').catch(() => {});
    killBrowser(old);
    health.restarted();
    restartTimer = null;
    start();
  }, wait);
}

// Vigilante (RNF2): la librería no siempre emite "disconnected"; el registro del 7 de
// octubre muestra 29 fallas seguidas por "detached Frame" durante 7,5 h sin reconexión.
async function watchdog() {
  if (!client || restartTimer) return;
  if (status.estado === 'esperando_qr') return;
  if (status.estado !== 'conectado') {
    if (Date.now() - status.desde > STUCK_START_MS) scheduleRestart(`sin conectar en ${STUCK_START_MS / 1000} s`);
    return;
  }
  try {
    const st = await withTimeout(client.getState(), 15000, 'consulta de estado');
    if (st === 'CONNECTED') { health.ok(); return; }
    reportFailure('vigilante', new Error(`WhatsApp reporta estado ${st}`));
  } catch (e) {
    reportFailure('vigilante', e);
  }
}

// RNF2: un error de la librería (p. ej. el archivo de sesión bloqueado en Windows al cerrar
// sesión) no debe tumbar el puente; se registra y la reconexión sigue su curso.
process.on('uncaughtException', (e) => log('[error] no controlado:', e.message));
process.on('unhandledRejection', (e) => log('[error] promesa rechazada:', e && e.message ? e.message : e));

async function handleMessage(msg) {
  try {
    if (!msg.hasMedia) return;
    const chat = await chatOf(msg);
    chat.nombre = (chat.nombre || '').trim();
    if (!allowed.has(chat.nombre)) return;          // RF1: ni se descarga ni se procesa
    const t0 = Date.now();
    const msgId = msg.id && (msg.id._serialized || String(msg.id));
    const media = await withRetry(async () => {
      let m = null;
      try {
        m = await msg.downloadMedia();
      } catch (e) {
        if (isPageDead(e)) throw e;
        // Con algunas versiones de WhatsApp Web el ayudante de la librería falla (error «r»):
        // se descarga directo, igual que al exportar un chat.
        log(`[archivo] descarga normal falló (${e.message}); se intenta la descarga directa`);
      }
      if (!m || !m.data) {
        const d = await downloadById(chat.id, msgId);
        if (d && d.data) m = { data: d.data, mimetype: d.mimetype, filename: d.filename };
        else throw new Error(`WhatsApp no entregó el archivo (${(d && d.error) || 'sin datos'})`);
      }
      return m;
    }, { tries: 3, base: 2000, retryIf: (e) => !isPageDead(e) });
    const name = media.filename || `${msg.type}_${msg.timestamp}.${(media.mimetype || 'bin').split('/')[1].split(';')[0]}`;
    const contact = msg.fromMe ? null : await msg.getContact().catch(() => null);
    const meta = {
      name, mimetype: media.mimetype, grupo: chat.nombre, message_ts: msg.timestamp,
      remitente: msg.fromMe ? 'Yo' : ((contact && (contact.pushname || contact.number)) || msg.author || msg.from || ''),
    };
    const buffer = Buffer.from(media.data, 'base64');
    let j;
    try {
      j = await sendIngest(meta, buffer);
    } catch (e) { // FileMind apagado o reiniciándose: el archivo espera en disco
      outbox.push(meta, buffer);
      log(`[archivo] ${chat.nombre} · ${name} · FileMind no responde, queda en cola (${outbox.size()} pendiente/s)`);
      return;
    }
    log(`[archivo] ${chat.nombre} · ${name} · detección ${(t0 / 1000 - msg.timestamp).toFixed(1)} s · ` +
        `estado=${j.status} riesgo=${j.risk_score} categoría=${j.category}`);
    if (NOTIFY_IN_GROUP && j.status === 'cuarentena') {
      await msg.reply('⚠️ ' + j.notification);
    }
  } catch (e) {
    if (isPageDead(e)) reportFailure('archivo', e);
    else log('[error] procesando mensaje:', e.message);
  }
}

async function sendIngest(meta, buffer) {
  const form = new FormData();
  form.append('file', new Blob([buffer], { type: meta.mimetype }), meta.name);
  form.append('grupo', meta.grupo);
  form.append('remitente', meta.remitente || '');
  form.append('message_ts', String(meta.message_ts));
  const r = await fetch(`${API}/api/ingest`, { method: 'POST', body: form, headers });
  if (r.status >= 500) throw new Error(`FileMind respondió ${r.status}`);
  return r.json();
}

let flushing = false;
async function flushOutbox() {
  if (flushing || !outbox.size()) return;
  flushing = true;
  try {
    const n = await outbox.flush(sendIngest);
    if (n) log(`[cola] ${n} archivo(s) pendientes entregados a FileMind`);
  } finally {
    flushing = false;
  }
}

// Reenvío de alertas (RNF7) al número configurado
async function pumpNotifications() {
  if (!NOTIFY_TO || !client || status.estado !== 'conectado') return;
  try {
    const r = await fetch(`${API}/api/notificaciones?desde=${lastNotification}`, { headers });
    for (const n of await r.json()) {
      lastNotification = Math.max(lastNotification, n.id);
      await client.sendMessage(NOTIFY_TO, `FileMind (${n.level.toUpperCase()})\n${n.message}`);
    }
  } catch (e) { /* FileMind o WhatsApp no disponibles: se reintenta */ }
}

// ------------------------------------------------------------ RF9: exportar un chat
// Tipos que cuentan como archivo (se excluyen stickers y notas de voz)
const EXPORT_TYPES = new Set(['document', 'image', 'video', 'audio']);
let exporting = false;

async function apiJSON(route, opts = {}) {
  const r = await fetch(`${API}${route}`, { ...opts, headers: { ...headers, ...(opts.body ? { 'Content-Type': 'application/json' } : {}) } });
  if (!r.ok) throw new Error(`FileMind respondió ${r.status} en ${route}`);
  return r.json();
}

function extOf(mime) {
  return ((mime || 'bin').split('/')[1] || 'bin').split(';')[0];
}

// Adjuntos del historial del chat, del más antiguo al más reciente
async function mediaOfChat(chatId) {
  // Lectura directa del almacén de WhatsApp Web (chat.fetchMessages falla con versiones
  // nuevas), pidiendo mensajes anteriores hasta el límite
  const msgs = await client.pupPage.evaluate(async (chatId, limit) => {
    const C = window.require('WAWebCollections');
    const wid = window.require('WAWebWidFactory').createWid(chatId);
    const chat = C.Chat.get(wid) || (await C.Chat.find(wid));
    if (!chat) return [];
    let all = chat.msgs.getModelsArray();
    while (all.length < limit) {
      let older = null;
      try { older = await window.require('WAWebChatLoadMessages').loadEarlierMsgs({ chat }); } catch (e) { older = null; }
      if (!older || !older.length) break;
      all = [...older, ...all];
    }
    // Se guardan los modelos: los mensajes viejos no siempre quedan en las colecciones de WhatsApp Web
    const key = (m) => m.id._serialized || m.id.toString();
    window.__fmMsgs = new Map(all.map((m) => [key(m), m]));
    return all.filter((m) => !m.isNotification).map((m) => ({
      msg_id: key(m), tipo: m.type, fecha: m.t, desdeMi: m.id.fromMe, nombre: m.filename || '',
      tamano: m.size || null, mime: m.mimetype, autor: (m.author || m.from || {})._serialized || '',
      filehash: m.filehash || null,
    }));
  }, chatId, EXPORT_LIMIT);
  log(`[exportar] ${msgs.length} mensaje(s) revisados`);
  return msgs.filter((m) => EXPORT_TYPES.has(m.tipo)).map((m) => ({
    msg_id: m.msg_id, tipo: m.tipo, fecha: m.fecha, tamano: m.tamano, huella: hashHex(m.filehash),
    nombre: m.nombre || `${m.tipo}_${m.fecha}.${extOf(m.mime)}`,
    remitente: m.desdeMi ? 'Yo' : String(m.autor || '').split('@')[0],
  }));
}

// Descarga directa desde WhatsApp Web (no depende de los ayudantes de la librería,
// que fallan con algunas versiones de WhatsApp Web). Devuelve { data, mimetype, filename } o { error }.
function downloadById(chatId, msgId) {
  return client.pupPage.evaluate(async (chatId, msgId) => {
    const C = window.require('WAWebCollections');
    let msg = null;
    const steps = [
      () => window.__fmMsgs && window.__fmMsgs.get(msgId),
      () => C.Msg.get(msgId),
      () => { const chat = C.Chat.get(window.require('WAWebWidFactory').createWid(chatId)); return chat && chat.msgs.get(msgId); },
      () => { const chat = C.Chat.get(window.require('WAWebWidFactory').createWid(chatId)); return chat && chat.msgs.getModelsArray().find((m) => (m.id._serialized || m.id.toString()) === msgId); },
      async () => (await C.Msg.getMessagesById([msgId]))?.messages?.[0],
    ];
    for (const step of steps) {
      try { msg = await step(); } catch (e) { msg = null; }
      if (msg) break;
    }
    if (!msg) return { error: 'sin_mensaje' };
    const md = msg.mediaData;
    if (md && md.mediaStage === 'REUPLOADING') return { error: 'expirado' };
    if (md && md.mediaStage !== 'RESOLVED') {
      try { await msg.downloadMedia({ downloadEvenIfExpensive: true, rmrReason: 1 }); } catch (e) { /* se intenta igual */ }
      const stage = String(msg.mediaData.mediaStage || '');
      if (stage.includes('ERROR') || stage === 'FETCHING') return { error: 'expirado' };
    }
    if (!msg.directPath || !msg.mediaKey) {
      return { error: 'sin_media ' + JSON.stringify({ md: !!md, t: msg.type, k: Object.keys(msg.attributes || {}).slice(0, 30) }) };
    }
    // 1) Si WhatsApp Web ya tiene el archivo descifrado en memoria, se usa ese
    let buf = null;
    try {
      const blob = msg.mediaData && msg.mediaData.mediaBlob;
      if (blob) buf = typeof blob.forceToBlob === 'function' ? blob.forceToBlob() : blob._blob || null;
    } catch (e) { buf = null; }
    // 2) Si no, se descarga y descifra desde los servidores de WhatsApp
    if (!buf) {
      const qpl = { addAnnotations() { return this; }, addPoint() { return this; } };
      try {
        buf = await window.require('WAWebDownloadManager').downloadManager.downloadAndMaybeDecrypt({
          directPath: msg.directPath, encFilehash: msg.encFilehash, filehash: msg.filehash, mediaKey: msg.mediaKey,
          mediaKeyTimestamp: msg.mediaKeyTimestamp, type: msg.type, mediaType: msg.type, mimetype: msg.mimetype,
          signal: new AbortController().signal, downloadQpl: qpl,
        });
      } catch (e) {
        return { error: e && e.status === 404 ? 'expirado' : String((e && e.message) || e) };
      }
    }
    if (!buf) return { error: 'sin_datos' };
    const data = await new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => resolve(String(r.result).split(',')[1] || '');
      r.onerror = reject;
      r.readAsDataURL(buf instanceof Blob ? buf : new Blob([buf]));
    });
    return { data, mimetype: msg.mimetype, filename: msg.filename };
  }, chatId, msgId);
}

async function runExport(job) {
  log(`[exportar] ${job.chat_nombre}: leyendo historial`);
  const items = await mediaOfChat(job.chat_id);
  if (items.some((it) => !it.msg_id)) throw new Error('WhatsApp Web no entregó el identificador de los mensajes');
  const view = await apiJSON(`/api/exportaciones/${job.id}/items`, { method: 'POST', body: JSON.stringify({ items }) });
  // Importación incremental: FileMind ya marcó como omitidos los mensajes importados antes
  const todo = view.items.filter((it) => it.estado === 'en_cola').map((it) => it.idx);
  log(`[exportar] ${job.chat_nombre}: ${items.length} archivo(s) en el chat, ${todo.length} nuevo(s)`);
  for (const i of todo) {
    const current = await apiJSON(`/api/exportaciones/${job.id}`);
    if (current.estado !== 'en_proceso') { log(`[exportar] ${job.chat_nombre}: ${current.estado}`); return; }
    const it = items[i];
    await apiJSON(`/api/exportaciones/${job.id}/items/${i}/estado`, { method: 'POST', body: JSON.stringify({ estado: 'descargando' }) });
    let media = null;
    try {
      // Hasta 3 intentos; un archivo vencido en los servidores de WhatsApp no se reintenta
      media = await withRetry(async () => {
        const m = await downloadById(job.chat_id, it.msg_id);
        if (m && m.data) return m;
        const err = new Error((m && m.error) || 'sin datos');
        err.final = m && m.error === 'expirado';
        throw err;
      }, { tries: 3, base: 2000, retryIf: (e) => !e.final && !isPageDead(e) });
    } catch (e) {
      if (isPageDead(e)) throw e;
      media = { error: e.final ? 'expirado' : e.message };
    }
    if (!media || !media.data) {
      const motivo = media && media.error === 'expirado'
        ? 'El archivo es muy antiguo y WhatsApp ya no lo tiene en sus servidores.'
        : 'WhatsApp no entregó este archivo; ábrelo en el celular y vuelve a exportar.';
      log(`[exportar] ${i + 1}/${items.length} ${it.nombre} no descargado (${(media && media.error) || 'sin datos'})`);
      await apiJSON(`/api/exportaciones/${job.id}/items/${i}/estado`, {
        method: 'POST', body: JSON.stringify({ estado: 'error', motivo }),
      });
      continue;
    }
    const name = media.filename || it.nombre;
    const form = new FormData();
    form.append('file', new Blob([Buffer.from(media.data, 'base64')], { type: media.mimetype }), name);
    form.append('remitente', it.remitente || '');
    if (it.fecha) form.append('message_ts', String(it.fecha));
    const r = await fetch(`${API}/api/exportaciones/${job.id}/items/${i}/archivo`, { method: 'POST', body: form, headers });
    const j = await r.json().catch(() => ({}));
    log(`[exportar] ${i + 1}/${items.length} ${name} -> ${j.item ? j.item.estado : r.status}`);
    health.ok();
  }
  log(`[exportar] ${job.chat_nombre}: terminado`);
}

async function pumpExports() {
  if (exporting || status.estado !== 'conectado') return;
  let job = null;
  try { job = (await apiJSON('/api/exportaciones/pendiente')).trabajo; } catch (e) { return; }
  if (!job) return;
  exporting = true;
  try {
    await runExport(job);
  } catch (e) {
    log('[exportar] error:', e.message);
    await postJSON(`/api/exportaciones/${job.id}/error`, { motivo: `El puente de WhatsApp falló: ${e.message}` });
    if (isPageDead(e)) reportFailure('exportar', e);
  } finally {
    exporting = false;
  }
}

setStatus(status);
setInterval(refreshGroups, 30000);
// Latido para la interfaz. Si la API se reinició pierde la lista de chats (vive en memoria):
// se vuelve a enviar enseguida en lugar de esperar los 2 minutos de syncChats.
async function heartbeat() {
  onOrder(await postJSON('/api/whatsapp/estado', statusPayload()));
  if (status.estado !== 'conectado') return;
  try {
    const r = await fetch(`${API}/api/whatsapp`, { headers });
    if (r.ok && !((await r.json()).chats || []).length) await syncChats();
  } catch (e) { /* FileMind apagado: se intenta en el siguiente latido */ }
}
setInterval(heartbeat, 15000);
setInterval(syncChats, 120000);
setInterval(pumpNotifications, 5000);
setInterval(pumpExports, 2000);
setInterval(watchdog, WATCHDOG_MS);
setInterval(flushOutbox, 15000);
killBrowser(null);   // un Chrome que quedó de una ejecución anterior bloquearía la sesión
start();
