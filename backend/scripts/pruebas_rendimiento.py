#!/usr/bin/env python3
"""Pruebas de rendimiento y escalabilidad con evidencia en reportes/rendimiento.json.

* RNF1: tiempo promedio del protocolo completo sobre 30 archivos (hasta 20 MB) <= 15 s.
* RF2 : latencia de detección con el conector por carpeta (archivo escrito -> detectado) <= 10 s.
* RNF6: tiempo de respuesta con 1 grupo vs 10 grupos simultáneos, degradación <= 20 %.
"""
from __future__ import annotations

import io
import json
import os
import random
import statistics
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from filemind.ai.dataset import generate_text, render, to_docx   # noqa: E402
from filemind.config import CATEGORIES, load_settings             # noqa: E402
from filemind.infrastructure.folder_connector import watch_folder               # noqa: E402
from filemind.services.analysis_service import FileMind                            # noqa: E402
from filemind.security import samples                             # noqa: E402

import shutil  # noqa: E402


def big_docx(mb: int, rng) -> bytes:
    """DOCX con una imagen/medio aleatorio para alcanzar ~mb MB."""
    base = to_docx(generate_text(rng.choice(CATEGORIES), rng))
    src = zipfile.ZipFile(io.BytesIO(base))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        for it in src.infolist():
            z.writestr(it, src.read(it))
        z.writestr("word/media/foto_obra.jpg", os.urandom(mb * 1024 * 1024 - len(base) - 4096))
    return out.getvalue()


def test_files(rng, n=30):
    files = []
    sizes = [20, 15, 10, 5, 2]
    for i in range(n):
        r = i % 6
        if r == 0:
            files.append((f"grande_{i}.docx", big_docx(sizes[(i // 6) % len(sizes)], rng)))
        elif r == 1:
            files.append(samples.phishing_sample(rng)[:2])
        elif r == 2:
            files.append(samples.ransomware_sample(rng)[:2])
        else:
            fmt = rng.choice(["pdf", "docx", "xlsx", "pptx"])
            files.append((f"doc_{i}.{fmt}", render(generate_text(rng.choice(CATEGORIES), rng), fmt)))
    return files


def fresh_fm(tmp: Path, groups: list[str], workers: int = 4) -> FileMind:
    s = load_settings(data_dir=tmp, monitored_groups=groups, workers=workers)
    s.ensure_dirs()
    for f in (s.topic_model_path.name, "riesgo.joblib"):
        src = ROOT / "data" / "modelos" / f
        if src.exists():
            shutil.copy(src, s.models_dir / f)
    return FileMind(s)


def rnf1(rng):
    with tempfile.TemporaryDirectory() as t:
        fm = fresh_fm(Path(t), ["G"])
        times, sizes = [], []
        for name, data in test_files(rng):
            t0 = time.perf_counter()
            fm.process(data, name, "G")
            times.append(time.perf_counter() - t0)
            sizes.append(len(data))
        fm.shutdown()
    return {"archivos": len(times), "tamano_max_mb": round(max(sizes) / 2**20, 1),
            "promedio_s": round(statistics.mean(times), 3), "maximo_s": round(max(times), 3),
            "p95_s": round(sorted(times)[int(.95 * len(times)) - 1], 3), "cumple": max(times) <= 15}


def rf2(rng):
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        inbox = t / "whatsapp_media"
        inbox.mkdir()
        fm = fresh_fm(t / "data", ["G"])
        lat = []
        stop = threading.Event()
        written: dict[str, float] = {}

        def on_file(p, rec):
            lat.append(time.time() - written[p.name])
        th = threading.Thread(target=watch_folder, args=(fm, inbox, "G"),
                              kwargs={"interval": 1.0, "stop": stop, "on_file": on_file}, daemon=True)
        th.start()
        time.sleep(1.5)
        for i in range(10):
            name, data = (f"f{i}.pdf", render(generate_text("Informes", rng), "pdf")) if i % 2 else \
                         (f"g{i}.docx", big_docx(rng.choice([1, 5, 10]), rng))
            written[name] = time.time()
            (inbox / name).write_bytes(data)
            time.sleep(rng.uniform(0.3, 2.0))
        deadline = time.time() + 30
        while len(lat) < 10 and time.time() < deadline:
            time.sleep(0.2)
        stop.set()
        fm.shutdown()
    return {"archivos": len(lat), "promedio_s": round(statistics.mean(lat), 3), "maximo_s": round(max(lat), 3),
            "cumple": len(lat) == 10 and max(lat) <= 10,
            "nota": "Latencia medida desde que el archivo aparece en la carpeta hasta que termina la detección. "
                    "Con el puente de WhatsApp se suma el tiempo de descarga del medio."}


def load_test(n_groups: int, rng, duration=30.0, period=3.0, workers=4):
    """Cada grupo envía un archivo cada ``period`` s (±30 %) durante ``duration`` s."""
    groups = [f"Grupo {i + 1}" for i in range(n_groups)]
    pool = [f for f in test_files(random.Random(99), 24) if len(f[1]) < 3 * 2**20]
    with tempfile.TemporaryDirectory() as t:
        fm = fresh_fm(Path(t), groups, workers)
        resp, lock = [], threading.Lock()

        def sender(g):
            r = random.Random(hash(g))
            end = time.time() + duration
            k = 0
            while time.time() < end:
                name, data = pool[r.randrange(len(pool))]
                data = data + f"\n<!-- {g} {k} -->".encode()   # contenido único (evita duplicados)
                t0 = time.perf_counter()
                fut = fm.submit(data, f"{k}_{name}", g, message_ts=time.time())
                fut.add_done_callback(lambda _f, t0=t0: (lock.acquire(), resp.append(time.perf_counter() - t0), lock.release()))
                k += 1
                time.sleep(period * r.uniform(0.7, 1.3))
        ths = [threading.Thread(target=sender, args=(g,)) for g in groups]
        [x.start() for x in ths]
        [x.join() for x in ths]
        fm.shutdown()
    return {"grupos": n_groups, "archivos": len(resp), "promedio_s": round(statistics.mean(resp), 3),
            "p95_s": round(sorted(resp)[int(.95 * len(resp)) - 1], 3)}


def main():
    rng = random.Random(2026)
    out = {}
    print("RNF1: 30 archivos…")
    out["RNF1"] = rnf1(rng)
    print(out["RNF1"])
    print("RF2: detección por carpeta…")
    out["RF2"] = rf2(rng)
    print(out["RF2"])
    print("RNF6: carga 1 grupo vs 10 grupos…")
    one = load_test(1, rng)
    ten = load_test(10, rng)
    deg = (ten["promedio_s"] - one["promedio_s"]) / one["promedio_s"] * 100
    out["RNF6"] = {"un_grupo": one, "diez_grupos": ten, "degradacion_pct": round(deg, 1), "cumple": deg <= 20}
    print(out["RNF6"])
    (ROOT / "reportes").mkdir(exist_ok=True)
    (ROOT / "reportes" / "rendimiento.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
