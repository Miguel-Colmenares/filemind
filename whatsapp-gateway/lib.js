/**
 * Piezas del puente que no dependen de WhatsApp, para poder probarlas solas (npm test).
 *
 * - backoffDelay / withRetry: reintentos con espera exponencial y algo de azar,
 *   para no golpear a WhatsApp o a la API con reintentos en ráfaga.
 * - isPageDead: reconoce los errores que indican que la página de WhatsApp Web
 *   murió (p. ej. "Attempted to use detached Frame"). Con esos errores no sirve
 *   reintentar la misma llamada: hay que reiniciar el cliente.
 * - Health: cuenta fallas seguidas y decide cuándo reiniciar.
 * - Outbox: cola en disco de los archivos que no se pudieron entregar a FileMind
 *   (API apagada o reiniciándose). Se reenvían solos cuando la API vuelve.
 * - hashHex: convierte la huella SHA-256 que trae WhatsApp (base64) a hexadecimal,
 *   el mismo formato que usa FileMind, para la importación incremental.
 */
const fs = require('fs');
const path = require('path');

const PAGE_DEAD = [
  /detached frame/i, /session closed/i, /target closed/i, /execution context was destroyed/i,
  /protocol error/i, /browser has disconnected/i, /navigating frame was detached/i,
  /cannot read properties of (null|undefined) \(reading '(evaluate|pupPage)'\)/i,
];

function isPageDead(err) {
  const msg = String((err && err.message) || err || '');
  return PAGE_DEAD.some((re) => re.test(msg));
}

function backoffDelay(attempt, { base = 5000, max = 300000, jitter = 0.2, random = Math.random } = {}) {
  const raw = Math.min(max, base * 2 ** Math.max(0, attempt));
  const spread = raw * jitter;
  return Math.round(Math.max(0, raw - spread + random() * 2 * spread));
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function withRetry(fn, { tries = 3, base = 1000, max = 10000, retryIf = () => true, onError, wait = sleep } = {}) {
  let last;
  for (let i = 0; i < tries; i += 1) {
    try {
      return await fn(i);
    } catch (e) {
      last = e;
      if (onError) onError(e, i);
      if (i === tries - 1 || !retryIf(e)) break;
      await wait(backoffDelay(i, { base, max, jitter: 0 }));
    }
  }
  throw last;
}

function withTimeout(promise, ms, label = 'operación') {
  let t;
  const timer = new Promise((_, reject) => { t = setTimeout(() => reject(new Error(`${label}: sin respuesta en ${ms} ms`)), ms); });
  return Promise.race([promise, timer]).finally(() => clearTimeout(t));
}

class Health {
  constructor({ maxFailures = 2 } = {}) {
    this.maxFailures = maxFailures;
    this.failures = 0;
    this.restarts = 0;
    this.lastError = null;
    this.since = null;
  }

  ok() {
    this.failures = 0;
    if (!this.since) this.since = new Date().toISOString();
  }

  /** Registra una falla. Devuelve true si toca reiniciar el cliente. */
  fail(err) {
    this.lastError = String((err && err.message) || err || 'desconocido').slice(0, 300);
    this.failures += isPageDead(err) ? this.maxFailures : 1;
    return this.failures >= this.maxFailures;
  }

  restarted() {
    this.restarts += 1;
    this.failures = 0;
    this.since = null;
  }

  snapshot() {
    return { reconexiones: this.restarts, fallas_seguidas: this.failures, ultimo_error: this.lastError, conectado_desde: this.since };
  }
}

class Outbox {
  constructor(dir) {
    this.dir = dir;
    fs.mkdirSync(dir, { recursive: true });
  }

  push(meta, buffer) {
    const id = `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    fs.writeFileSync(path.join(this.dir, `${id}.bin`), buffer);
    fs.writeFileSync(path.join(this.dir, `${id}.json`), JSON.stringify(meta));
    return id;
  }

  size() {
    return fs.readdirSync(this.dir).filter((f) => f.endsWith('.json')).length;
  }

  /** Reenvía en orden de llegada; se detiene en la primera falla para no desordenar la cola. */
  async flush(send) {
    const ids = fs.readdirSync(this.dir).filter((f) => f.endsWith('.json')).map((f) => f.slice(0, -5)).sort();
    let sent = 0;
    for (const id of ids) {
      const metaFile = path.join(this.dir, `${id}.json`);
      const binFile = path.join(this.dir, `${id}.bin`);
      let meta;
      try {
        meta = JSON.parse(fs.readFileSync(metaFile, 'utf8'));
      } catch (e) { // registro dañado: se descarta para no bloquear la cola
        fs.rmSync(metaFile, { force: true });
        fs.rmSync(binFile, { force: true });
        continue;
      }
      try {
        await send(meta, fs.readFileSync(binFile));
      } catch (e) {
        break;
      }
      fs.rmSync(metaFile, { force: true });
      fs.rmSync(binFile, { force: true });
      sent += 1;
    }
    return sent;
  }
}

function hashHex(b64) {
  if (!b64 || typeof b64 !== 'string') return null;
  const buf = Buffer.from(b64, 'base64');
  return buf.length === 32 ? buf.toString('hex') : null;
}

module.exports = { isPageDead, backoffDelay, withRetry, withTimeout, sleep, Health, Outbox, hashHex };
