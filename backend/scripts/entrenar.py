#!/usr/bin/env python3
"""Construye los datasets y entrena los dos modelos de IA de FileMind.

    python scripts/entrenar.py            # todo
    python scripts/entrenar.py --solo tema
    python scripts/entrenar.py --solo riesgo

Salidas:
  data/modelos/tema.joblib, data/modelos/riesgo.joblib
  reportes/*.png, reportes/*_metricas.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from filemind.ai.classifier import TopicClassifier            # noqa: E402
from filemind.ai.dataset import generate_topic_dataset       # noqa: E402
from filemind.infrastructure.repository import AuditStore                        # noqa: E402
from filemind.config import CATEGORIES, load_settings        # noqa: E402
from filemind.infrastructure.extract import extract                         # noqa: E402
from filemind.security.heuristic import run_heuristic        # noqa: E402
from filemind.security.risk import build_vector, train_risk_model  # noqa: E402
from filemind.security.samples import generate_security_dataset    # noqa: E402
from filemind.security.sandbox import run_sandbox, sandbox_features  # noqa: E402
from filemind.security.signatures import SignatureRepository  # noqa: E402
from filemind.security.static import detect_type, run_static  # noqa: E402

REPORTS = ROOT / "reportes"


def train_topic(s):
    ds = s.data_dir / "dataset" / ("tema" if s.perfil == "general" else f"tema_{s.perfil}")
    print(f"[tema] perfil {s.perfil}: preparando documentos de entrenamiento…")
    items = generate_topic_dataset(ds, per_class=90)
    real = s.data_dir / "dataset_real"
    if real.exists():
        for cat in CATEGORIES:
            for p in sorted((real / cat).glob("*")) if (real / cat).exists() else []:
                items.append((p, cat))
    texts, types, labels = [], [], []
    for p, cat in items:
        data = Path(p).read_bytes()
        t = detect_type(data, Path(p).name)
        texts.append(extract(data, t)["text"])
        types.append(t)
        labels.append(cat)
    extra = []
    audit = AuditStore(s.db_path)
    for fb in audit.feedback_rows():
        first, _, rest = (fb["text_excerpt"] or "").partition("\n")
        ty = first.removeprefix("__type=").removesuffix("__") if first.startswith("__type=") else "txt"
        extra.append((rest, ty, fb["corrected"]))
    print(f"[tema] {len(texts)} documentos, {len(extra)} correcciones de usuario. Entrenando…")
    clf = TopicClassifier.train(texts, types, labels, REPORTS, extra=extra)
    fuente = real / "fuente.json"
    if fuente.exists():  # origen de los documentos reales (lo muestra la pantalla de Modelos)
        clf.meta["origen_datos"] = json.loads(fuente.read_text(encoding="utf-8"))
        (REPORTS / "tema_metricas.json").write_text(json.dumps(clf.meta, indent=2, ensure_ascii=False, default=float),
                                                    encoding="utf-8")
    clf.save(s.topic_model_path)
    m = clf.meta
    print(f"[tema] mejor modelo: {m['best_model']}  prueba: acc={m['test']['accuracy']:.3f} "
          f"F1-macro={m['test']['f1_macro']:.3f}")
    for n, r in m["comparison"].items():
        print(f"        {n:14s} val F1={r['f1_macro']:.3f}  ({r['train_s']} s)")


def features_for(item, sigs, base):
    data = (Path(base) / item["path"]).read_bytes()
    st = run_static(data, item["name"], sigs)
    ex = extract(data, st["real_type"])
    heur = run_heuristic(data, st["real_type"], ex["text"], ex["urls"])
    sbx = run_sandbox(data, item["name"], "auto", 8.0)
    sf, _ = sandbox_features(sbx)
    return build_vector(st, heur["features"], sf)


def train_risk(s):
    ds = s.data_dir / "dataset" / "seguridad"
    print("[riesgo] generando dataset de seguridad (muestras inertes)…")
    items = generate_security_dataset(ds)
    (ds / "manifiesto.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    sigs = SignatureRepository(s.data_dir / "firmas_malware.txt")
    t0 = time.time()
    with ThreadPoolExecutor(8) as pool:
        X = list(pool.map(lambda it: features_for(it, sigs, ds), items))
    print(f"[riesgo] {len(X)} vectores de características en {time.time() - t0:.1f} s. Entrenando…")
    y = [it["label"] for it in items]
    rm = train_risk_model(X, y, REPORTS, kinds=[it["kind"] for it in items])
    rm.save(s.models_dir / "riesgo.joblib")
    q = rm.meta["cuarentena_umbral_70"]
    print(f"[riesgo] mejor modelo: {rm.meta['best_model']}")
    print(f"[riesgo] cuarentena (>70): FN={q['tasa_falsos_negativos']:.3f} (RNF3 <=5%: {q['RNF3_cumple(<=5%)']})  "
          f"FP={q['tasa_falsos_positivos']:.3f} (RNF4 <=10%: {q['RNF4_cumple(<=10%)']})")
    cv = rm.meta["validacion_cruzada_5"]
    print(f"[riesgo] validación cruzada 5 particiones: FN medio={cv['fnr_media']:.3f}  FP medio={cv['fpr_media']:.3f}")
    print("[riesgo] ataques no vistos (tipo excluido del entrenamiento):")
    for k, v in rm.meta["ataques_no_vistos"].items():
        print(f"        {k:18s} n={v['n']:3d}  detectado final={v['detectados_puntaje_final']:.2f}  solo IA={v['detectados_solo_modelo']:.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo", choices=["tema", "riesgo"])
    a = ap.parse_args()
    s = load_settings()
    s.ensure_dirs()
    REPORTS.mkdir(exist_ok=True)
    if a.solo in (None, "tema"):
        train_topic(s)
    if a.solo in (None, "riesgo"):
        train_risk(s)


if __name__ == "__main__":
    main()
