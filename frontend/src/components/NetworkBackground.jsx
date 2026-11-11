import { useEffect, useRef } from 'react';

/**
 * Fondo animado de toda la app: una red de nodos que se desplazan y se unen con líneas finas
 * (tema de ciberseguridad e IA) en el naranja de la marca. Hay UN solo canvas y UN solo bucle
 * para toda la aplicación; el componente solo cambia la variante:
 *   - "page":  red suave detrás de las páginas internas.
 *   - "home":  más intensa en el Panel, con pulsos de luz que viajan por las conexiones.
 *   - "login": versión «héroe» del inicio de sesión: más nodos, pulsos, y la red reacciona al
 *              mouse (los nodos cercanos se acercan y se unen con el cursor).
 *
 * Rendimiento:
 *   - devicePixelRatio con tope 1,5; ~30 cuadros/s en escritorio y ~24 en celular.
 *   - número de nodos según el área de la ventana (con tope).
 *   - vecinos con una rejilla espacial (no se comparan todos contra todos).
 *   - las líneas y los puntos se dibujan en lote: un trazo por cada nivel de opacidad.
 *   - se pausa si la pestaña no se ve; el redimensionado espera 150 ms (debounce).
 * Se mueve aunque Windows tenga las animaciones apagadas, pero más despacio.
 */

const BUCKETS = 6; // niveles de opacidad de las líneas (un trazo por nivel)
const VARIANT = {
  page: { density: 15000, max: 90, maxMobile: 50, link: 140, alpha: 0.2, speed: 1, pulses: 0, mouse: false },
  home: { density: 11500, max: 120, maxMobile: 60, link: 150, alpha: 0.32, speed: 1.5, pulses: 6, mouse: true },
  login: { density: 9000, max: 150, maxMobile: 70, link: 160, alpha: 0.38, speed: 1.3, pulses: 10, mouse: true },
};

const engine = {
  canvas: null, ctx: null, variant: 'page', pts: [], pulses: [], w: 0, h: 0, dpr: 1,
  raf: 0, last: 0, running: false, mobile: false, dark: true, reduce: false,
  mouse: { x: -9999, y: -9999, active: false }, frameMs: 33, t0: 0,
};

function readTheme() { engine.dark = document.documentElement.dataset.theme !== 'light'; }

function cfg() {
  return VARIANT[engine.variant] || VARIANT.page;
}

function seed() {
  const c = cfg();
  // en celular la pantalla es pequeña: más densidad para que la red se vea igual de llena
  const n = Math.round(Math.min(engine.mobile ? c.maxMobile : c.max, (engine.w * engine.h) / (c.density * (engine.mobile ? 0.55 : 1))));
  const { pts } = engine;
  while (pts.length < n) {
    const a = Math.random() * Math.PI * 2, v = 0.15 + Math.random() * 0.35;
    pts.push({ x: Math.random() * engine.w, y: Math.random() * engine.h, vx: Math.cos(a) * v, vy: Math.sin(a) * v,
      r: 0.9 + Math.random() * 1.5, ph: Math.random() * 6.28, ox: 0, oy: 0 });
  }
  pts.length = n;
  engine.pulses.length = 0;
}

function resize() {
  const { canvas, ctx } = engine;
  if (!canvas) return;
  engine.mobile = window.innerWidth < 700 || window.matchMedia('(pointer: coarse)').matches;
  engine.frameMs = engine.mobile ? 41 : 33; // ~24 o ~30 cuadros por segundo
  engine.dpr = Math.min(window.devicePixelRatio || 1, 1.5);
  engine.w = window.innerWidth; engine.h = window.innerHeight;
  canvas.width = Math.round(engine.w * engine.dpr); canvas.height = Math.round(engine.h * engine.dpr);
  canvas.style.width = `${engine.w}px`; canvas.style.height = `${engine.h}px`;
  ctx.setTransform(engine.dpr, 0, 0, engine.dpr, 0, 0);
  seed();
}

function frame(t) {
  engine.raf = requestAnimationFrame(frame);
  if (t - engine.last < engine.frameMs) return;
  const dt = Math.min(3, engine.last ? (t - engine.last) / 16.7 : 1);
  engine.last = t;
  draw(t, dt);
}

function draw(t, dt) {
  const { ctx, pts, w, h, dark, mouse } = engine;
  const c = cfg();
  const speed = c.speed * (engine.reduce ? 0.5 : 1) * dt;
  const maxD = engine.mobile ? c.link * 0.8 : c.link;
  const maxD2 = maxD * maxD;
  ctx.clearRect(0, 0, w, h);

  // 1) mover nodos (con atracción suave hacia el mouse en login/panel)
  const mr = 180, mr2 = mr * mr;
  const useMouse = c.mouse && mouse.active;
  for (const p of pts) {
    p.x += p.vx * speed; p.y += p.vy * speed;
    if (p.x < -30) p.x = w + 30; else if (p.x > w + 30) p.x = -30;
    if (p.y < -30) p.y = h + 30; else if (p.y > h + 30) p.y = -30;
    let tx = 0, ty = 0;
    if (useMouse) {
      const dx = mouse.x - p.x, dy = mouse.y - p.y, d2 = dx * dx + dy * dy;
      if (d2 < mr2) { const k = (1 - Math.sqrt(d2) / mr) * 18; const d = Math.sqrt(d2) || 1; tx = (dx / d) * k; ty = (dy / d) * k; }
    }
    p.ox += (tx - p.ox) * 0.08; p.oy += (ty - p.oy) * 0.08; // desplazamiento suavizado (parallax)
  }

  // 2) rejilla espacial: cada nodo solo se compara con las celdas vecinas
  const cell = maxD, cols = Math.ceil((w + 60) / cell) + 1;
  const grid = new Map();
  for (let i = 0; i < pts.length; i += 1) {
    const p = pts[i];
    const key = Math.floor((p.x + 30) / cell) + Math.floor((p.y + 30) / cell) * cols;
    const list = grid.get(key);
    if (list) list.push(i); else grid.set(key, [i]);
  }
  const lines = Array.from({ length: BUCKETS }, () => []);
  const links = [];
  for (let i = 0; i < pts.length; i += 1) {
    const a = pts[i];
    const cx = Math.floor((a.x + 30) / cell), cy = Math.floor((a.y + 30) / cell);
    for (let gy = cy - 1; gy <= cy + 1; gy += 1) {
      for (let gx = cx - 1; gx <= cx + 1; gx += 1) {
        const list = grid.get(gx + gy * cols);
        if (!list) continue;
        for (const j of list) {
          if (j <= i) continue;
          const b = pts[j];
          const dx = a.x - b.x, dy = a.y - b.y, d2 = dx * dx + dy * dy;
          if (d2 >= maxD2) continue;
          const k = 1 - Math.sqrt(d2) / maxD;
          lines[Math.min(BUCKETS - 1, Math.floor(k * BUCKETS))].push(a.x + a.ox, a.y + a.oy, b.x + b.ox, b.y + b.oy);
          if (c.pulses && k > 0.35) links.push(i, j);
        }
      }
    }
  }

  // 3) líneas en lote por opacidad
  const hue = 24, light = dark ? 58 : 48;
  const baseA = c.alpha * (dark ? 1 : 0.8);
  ctx.lineWidth = 1;
  for (let bkt = 0; bkt < BUCKETS; bkt += 1) {
    const L = lines[bkt];
    if (!L.length) continue;
    ctx.strokeStyle = `hsla(${hue}, 95%, ${light}%, ${(((bkt + 0.5) / BUCKETS) * baseA).toFixed(3)})`;
    ctx.beginPath();
    for (let k = 0; k < L.length; k += 4) { ctx.moveTo(L[k], L[k + 1]); ctx.lineTo(L[k + 2], L[k + 3]); }
    ctx.stroke();
  }

  // 4) líneas al cursor (login/panel)
  if (useMouse) {
    ctx.beginPath();
    for (const p of pts) {
      const x = p.x + p.ox, y = p.y + p.oy, dx = mouse.x - x, dy = mouse.y - y;
      if (dx * dx + dy * dy < mr2) { ctx.moveTo(mouse.x, mouse.y); ctx.lineTo(x, y); }
    }
    ctx.strokeStyle = `hsla(${hue}, 100%, ${light + 6}%, ${baseA * 0.9})`;
    ctx.stroke();
  }

  // 5) nodos en lote (tres niveles de brillo que titilan)
  const pulse = t / 900;
  for (let lvl = 0; lvl < 3; lvl += 1) {
    ctx.beginPath();
    for (let i = lvl; i < pts.length; i += 3) {
      const p = pts[i];
      const x = p.x + p.ox, y = p.y + p.oy;
      ctx.moveTo(x + p.r, y); ctx.arc(x, y, p.r, 0, Math.PI * 2);
    }
    const glow = 0.55 + 0.35 * Math.sin(pulse + lvl * 2.1);
    ctx.fillStyle = `hsla(${hue}, 95%, ${light + 2}%, ${Math.min(0.95, glow * baseA * 2.2).toFixed(3)})`;
    ctx.fill();
  }

  // 6) pulsos de luz que viajan por las conexiones
  if (c.pulses) {
    const P = engine.pulses;
    while (P.length < c.pulses && links.length) {
      const k = (Math.random() * (links.length / 2)) | 0;
      P.push({ i: links[k * 2], j: links[k * 2 + 1], t: 0, v: 0.012 + Math.random() * 0.02 });
    }
    ctx.beginPath();
    for (let k = P.length - 1; k >= 0; k -= 1) {
      const q = P[k];
      q.t += q.v * dt * (engine.reduce ? 0.6 : 1);
      const a = pts[q.i], b = pts[q.j];
      if (!a || !b || q.t >= 1) { P.splice(k, 1); continue; }
      const x = a.x + a.ox + (b.x + b.ox - a.x - a.ox) * q.t, y = a.y + a.oy + (b.y + b.oy - a.y - a.oy) * q.t;
      ctx.moveTo(x + 2.2, y); ctx.arc(x, y, 2.2, 0, Math.PI * 2);
    }
    ctx.fillStyle = `hsla(32, 100%, ${dark ? 64 : 50}%, .9)`;
    ctx.fill();
  }
}

function start() {
  if (engine.running || document.hidden) return;
  engine.running = true; engine.last = 0;
  engine.raf = requestAnimationFrame(frame);
}
function stop() { engine.running = false; cancelAnimationFrame(engine.raf); }

export default function NetworkBackground({ variant = 'page' }) {
  const ref = useRef(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext('2d', { alpha: true });
    if (!ctx) return undefined;
    engine.canvas = canvas; engine.ctx = ctx;
    try { engine.reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch { /* sin soporte */ }
    readTheme();
    resize();
    let timer = 0;
    const onResize = () => { clearTimeout(timer); timer = setTimeout(resize, 150); };
    const onVis = () => (document.hidden ? stop() : start());
    const onMove = (e) => { engine.mouse.x = e.clientX; engine.mouse.y = e.clientY; engine.mouse.active = true; };
    const onLeave = () => { engine.mouse.active = false; };
    const mo = new MutationObserver(readTheme);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    window.addEventListener('resize', onResize, { passive: true });
    window.addEventListener('pointermove', onMove, { passive: true });
    document.addEventListener('pointerleave', onLeave);
    window.addEventListener('blur', onLeave);
    document.addEventListener('visibilitychange', onVis);
    start();
    return () => {
      stop(); clearTimeout(timer); mo.disconnect();
      window.removeEventListener('resize', onResize);
      window.removeEventListener('pointermove', onMove);
      document.removeEventListener('pointerleave', onLeave);
      window.removeEventListener('blur', onLeave);
      document.removeEventListener('visibilitychange', onVis);
    };
  }, []);

  // cambiar de variante no reinicia el bucle: solo ajusta la cantidad de nodos
  useEffect(() => {
    if (engine.variant === variant) return;
    engine.variant = variant;
    if (engine.ctx) seed();
  }, [variant]);

  return <canvas ref={ref} className="bg-net" aria-hidden="true" />;
}
