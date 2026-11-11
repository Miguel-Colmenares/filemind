// Pruebas del puente sin WhatsApp: node --test (o npm test)
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
const { isPageDead, backoffDelay, withRetry, withTimeout, Health, Outbox, hashHex } = require('../lib');

const DETACHED = "Attempted to use detached Frame 'C18E1DC48C3F0BF9684B5E29FDF7FA16'."; // texto real del registro

test('reconoce los errores de página muerta del registro real', () => {
  assert.ok(isPageDead(new Error(DETACHED)));
  assert.ok(isPageDead(new Error('Protocol error (Runtime.callFunctionOn): Session closed.')));
  assert.ok(isPageDead(new Error("Cannot read properties of null (reading 'pupPage')")));
  assert.ok(!isPageDead(new Error('FileMind respondió 404')));
});

test('espera exponencial con tope y sin ráfagas', () => {
  const fixed = { jitter: 0 };
  assert.deepStrictEqual([0, 1, 2, 3].map((a) => backoffDelay(a, fixed)), [5000, 10000, 20000, 40000]);
  assert.strictEqual(backoffDelay(20, fixed), 300000);
  for (let i = 0; i < 50; i += 1) {
    const d = backoffDelay(0);
    assert.ok(d >= 4000 && d <= 6000, `azar dentro de ±20 %: ${d}`);
  }
});

test('el escenario del 7 de octubre ahora termina en reinicio al primer error', () => {
  // Antes: 29 errores "detached Frame" seguidos durante 7,5 h y nunca se reinició.
  const h = new Health({ maxFailures: 2 });
  h.ok();
  let restartAt = null;
  for (let i = 0; i < 29 && restartAt === null; i += 1) {
    if (h.fail(new Error(DETACHED))) restartAt = i;
  }
  assert.strictEqual(restartAt, 0);
  // tiempo máximo hasta recuperar = un ciclo del vigilante (60 s) + primera espera (5 s + 20 %)
  const worst = 60000 + backoffDelay(0, { random: () => 1 });
  assert.ok(worst <= 66000);
  h.restarted();
  assert.strictEqual(h.snapshot().reconexiones, 1);
  assert.strictEqual(h.snapshot().fallas_seguidas, 0);
});

test('una falla pasajera no reinicia, dos seguidas sí', () => {
  const h = new Health({ maxFailures: 2 });
  assert.strictEqual(h.fail(new Error('consulta de estado: sin respuesta en 15000 ms')), false);
  h.ok();
  assert.strictEqual(h.fail(new Error('timeout')), false);
  assert.strictEqual(h.fail(new Error('timeout')), true);
});

test('reintenta descargas fallidas y respeta los errores definitivos', async () => {
  let calls = 0;
  const wait = async () => {};
  const out = await withRetry(async () => { calls += 1; if (calls < 3) throw new Error('red'); return 'ok'; }, { tries: 3, wait });
  assert.strictEqual(out, 'ok');
  assert.strictEqual(calls, 3);
  calls = 0;
  const final = new Error('expirado');
  final.final = true;
  await assert.rejects(withRetry(async () => { calls += 1; throw final; }, { tries: 3, wait, retryIf: (e) => !e.final }));
  assert.strictEqual(calls, 1);
});

test('corta llamadas que se quedan colgadas', async () => {
  await assert.rejects(withTimeout(new Promise(() => {}), 20, 'getState'), /getState: sin respuesta/);
});

test('cola en disco: guarda si la API cae y reenvía en orden cuando vuelve', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'fm-outbox-'));
  const box = new Outbox(dir);
  box.push({ name: 'a.pdf' }, Buffer.from('A'));
  await new Promise((r) => setTimeout(r, 5));
  box.push({ name: 'b.pdf' }, Buffer.from('B'));
  assert.strictEqual(box.size(), 2);
  assert.strictEqual(await box.flush(async () => { throw new Error('API apagada'); }), 0);
  assert.strictEqual(box.size(), 2);
  const got = [];
  assert.strictEqual(await box.flush(async (meta, buf) => { got.push(meta.name + buf.toString()); }), 2);
  assert.deepStrictEqual(got, ['a.pdfA', 'b.pdfB']);
  assert.strictEqual(box.size(), 0);
  fs.rmSync(dir, { recursive: true, force: true });
});

test('la huella de WhatsApp (base64) se convierte al SHA-256 hexadecimal de FileMind', () => {
  const data = Buffer.from('%PDF-1.4 contrato de prueba');
  const hex = crypto.createHash('sha256').update(data).digest('hex');
  const b64 = crypto.createHash('sha256').update(data).digest('base64');
  assert.strictEqual(hashHex(b64), hex);
  assert.strictEqual(hashHex(''), null);
  assert.strictEqual(hashHex('no-es-un-hash'), null);
});
