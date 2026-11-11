#!/usr/bin/env python3
"""Benchmark de FileMind frente a sistemas más simples.

Pregunta: ¿vale la pena el modelo entrenado de FileMind frente a reglas escritas a
mano o a una IA genérica sin entrenamiento? Se mide exactitud y tiempo de respuesta
con los mismos documentos reales para todos.

    python scripts/benchmark.py            # todos los sistemas disponibles
    python scripts/benchmark.py --sin-minilm

Datos: sentencias reales de la Corte Constitucional (data/dataset_real, ver fuente.json).
Procedimiento:
  1. Validación cruzada estratificada de 5 particiones sobre todos los documentos:
     cada documento se predice una vez con un sistema que no lo vio. Da F1 macro,
     exactitud, F1 por clase, intervalo de confianza (bootstrap) y prueba de McNemar.
  2. División 70/20/10 igual a la del entrenamiento (semilla 42): el 10 % de prueba
     sirve para medir el tiempo por documento (uno a la vez) y la robustez frente a
     textos cortos y ruido de OCR.
Salidas: reportes/benchmark.json y reportes/benchmark_*.png
"""
from __future__ import annotations

import argparse
import io
import json
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FILEMIND_PERFIL", "constitucional")

import joblib  # noqa: E402
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy.stats import binomtest  # noqa: E402
from sklearn.base import clone  # noqa: E402
from sklearn.dummy import DummyClassifier  # noqa: E402
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score  # noqa: E402
from sklearn.model_selection import StratifiedKFold, train_test_split  # noqa: E402
from sklearn.pipeline import Pipeline  # noqa: E402

from filemind.ai import evaluation as ev  # noqa: E402
from filemind.ai.baselines import KeywordRules, ZeroShotEmbeddings, ZeroShotTfidf  # noqa: E402
from filemind.ai.classifier import _features, candidate_models, make_input  # noqa: E402
from filemind.domain.models import PROFILE, PROFILES  # noqa: E402

REPORTS = ROOT / "reportes"
SEED = 42
FILEMIND = "FileMind (SVM lineal)"


def load_docs():
    real = ROOT / "data" / "dataset_real"
    texts, labels = [], []
    for cat in PROFILES[PROFILE]:
        for p in sorted((real / cat).glob("*.txt")):
            texts.append(p.read_text(encoding="utf-8", errors="ignore"))
            labels.append(cat)
    fuente = real / "fuente.json"
    return texts, np.array(labels), (json.loads(fuente.read_text(encoding="utf-8")) if fuente.exists() else {})


def systems(with_minilm: bool) -> dict:
    """nombre -> (fábrica, tipo, entrada). La entrada 'fm' agrega la marca de formato como en producción."""
    sup = lambda m: (lambda: Pipeline([("feats", _features()), ("clf", clone(candidate_models()[m]))]))  # noqa: E731
    out = {
        "Clase más frecuente": (lambda: DummyClassifier(strategy="most_frequent"), "trivial", "texto"),
        "Reglas por palabras clave": (lambda: KeywordRules(PROFILE), "reglas", "texto"),
        "Zero-shot TF-IDF": (lambda: ZeroShotTfidf(PROFILE), "zero-shot", "texto"),
    }
    if with_minilm:
        try:
            import sentence_transformers  # noqa: F401
            shared = {}

            def minilm():  # el modelo se carga una vez y se reutiliza en cada partición
                if "m" not in shared:
                    shared["m"] = ZeroShotEmbeddings(PROFILE)
                return shared["m"]
            out["Zero-shot MiniLM"] = (minilm, "zero-shot preentrenado", "texto")
        except ImportError:
            print("[benchmark] sentence-transformers no está instalado: se omite MiniLM")
    out["Naive Bayes (supervisado simple)"] = (sup("NaiveBayes"), "supervisado", "fm")
    out[FILEMIND] = (sup("SVM-lineal"), "supervisado", "fm")
    return out


def inputs(kind, texts):
    return np.array([make_input(t, "txt") for t in texts], dtype=object) if kind == "fm" else np.array(texts, dtype=object)


def per_doc_latency(model, X, n=118):
    X = list(X)[:n]
    model.predict_proba(X[:1])
    t = []
    for x in X:
        t0 = time.perf_counter()
        model.predict_proba([x])
        t.append((time.perf_counter() - t0) * 1000)
    t = np.array(t)
    return {"media": float(t.mean()), "p50": float(np.percentile(t, 50)), "p95": float(np.percentile(t, 95)),
            "documentos_por_s": float(1000 / t.mean())}


def model_size_kb(model, name):
    if isinstance(model, ZeroShotEmbeddings):
        return round(model.params * 4 / 1024, 1)  # pesos en float32
    buf = io.BytesIO()
    joblib.dump(model, buf)
    return round(buf.tell() / 1024, 1)


def bootstrap_f1(y, yp, n=1000, seed=SEED):
    rng = np.random.RandomState(seed)
    vals = []
    for _ in range(n):
        i = rng.randint(0, len(y), len(y))
        vals.append(f1_score(y[i], yp[i], average="macro", zero_division=0))
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]


def mcnemar(y, a, b):
    """¿Los aciertos de a y b difieren más de lo que explicaría el azar? (prueba exacta)."""
    a_ok, b_ok = a == y, b == y
    n01, n10 = int((a_ok & ~b_ok).sum()), int((~a_ok & b_ok).sum())
    p = binomtest(n01, n01 + n10, 0.5).pvalue if n01 + n10 else 1.0
    return {"solo_filemind_acierta": n01, "solo_el_otro_acierta": n10, "p_valor": float(p)}


def ocr_noise(text, rate, rng):
    chars = list(text)
    for i in range(len(chars)):
        if chars[i].isalpha() and rng.random() < rate:
            chars[i] = rng.choice("abcdefghijklmnopqrstuvwxyz0l1I|")
    return "".join(chars)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sin-minilm", action="store_true")
    a = ap.parse_args()
    texts, y, fuente = load_docs()
    classes = list(PROFILES[PROFILE])
    print(f"[benchmark] perfil {PROFILE}: {len(texts)} documentos reales, {len(classes)} clases")
    idx = np.arange(len(y))
    tr, tmp = train_test_split(idx, test_size=0.30, stratify=y, random_state=SEED)
    va, te = train_test_split(tmp, test_size=1 / 3, stratify=y[tmp], random_state=SEED)
    folds = list(StratifiedKFold(5, shuffle=True, random_state=SEED).split(idx, y))
    rng = random.Random(SEED)
    variants = {"normal": texts, "corto_500": [t[:500] for t in texts],
                "ruido_ocr_10": [ocr_noise(t, 0.10, rng) for t in texts]}

    res, oof = {}, {}
    for name, (factory, tipo, kind) in systems(not a.sin_minilm).items():
        print(f"[benchmark] {name}…", flush=True)
        X = inputs(kind, texts)
        pred = np.empty(len(y), dtype=object)
        for k, (f_tr, f_te) in enumerate(folds):
            m = factory().fit(X[f_tr], y[f_tr])
            pred[f_te] = m.predict(X[f_te])
        oof[name] = pred.astype(str)
        t0 = time.perf_counter()
        m = factory().fit(X[tr], y[tr])
        train_s = time.perf_counter() - t0
        robust = {}
        for v, tx in variants.items():
            Xv = inputs(kind, tx)
            robust[v] = float(f1_score(y[te], m.predict(Xv[te]), average="macro", zero_division=0))
        lat = per_doc_latency(m, X[te]) if tipo != "trivial" else {"media": 0.0, "p50": 0.0, "p95": 0.0,
                                                                  "documentos_por_s": None}
        f1c = f1_score(y, oof[name], labels=classes, average=None, zero_division=0)
        res[name] = {
            "tipo": tipo, "accuracy": float(accuracy_score(y, oof[name])),
            "f1_macro": float(f1_score(y, oof[name], average="macro", zero_division=0)),
            "f1_macro_ic95": bootstrap_f1(y, oof[name]),
            "f1_por_clase": {c: float(v) for c, v in zip(classes, f1c)},
            "f1_por_particion": [float(f1_score(y[f], oof[name][f], average="macro", zero_division=0)) for _, f in folds],
            "prueba_f1_macro": robust["normal"], "robustez_f1": robust,
            "latencia_ms": lat, "entrenamiento_s": round(train_s, 3), "tamano_kb": model_size_kb(m, name),
            "matriz_confusion": confusion_matrix(y, oof[name], labels=classes).tolist(),
        }
        r = res[name]
        print(f"    F1={r['f1_macro']:.3f} [{r['f1_macro_ic95'][0]:.3f}-{r['f1_macro_ic95'][1]:.3f}] "
              f"acc={r['accuracy']:.3f} p50={lat['p50']:.2f} ms  robustez={robust}")

    for name in res:
        if name != FILEMIND:
            res[name]["mcnemar_vs_filemind"] = mcnemar(y, oof[FILEMIND], oof[name])

    out = {"fecha": time.strftime("%Y-%m-%d %H:%M"), "perfil": PROFILE, "documentos": int(len(y)),
           "clases": classes, "particion_prueba": int(len(te)), "semilla": SEED,
           "procedimiento": "Validación cruzada estratificada de 5 particiones (cada documento se predice con un "
                            "sistema que no lo vio). Tiempo por documento y robustez en el 10 % de prueba de la "
                            "división 70/20/10 usada en el entrenamiento.",
           "origen_datos": {k: fuente.get(k) for k in ("descripcion", "texto", "etiquetas", "desde", "hasta")},
           "sistemas": res}
    REPORTS.mkdir(exist_ok=True)
    ev.save_json(out, REPORTS / "benchmark.json")
    plots(out)
    print("[benchmark] listo: reportes/benchmark.json")


def plots(out):
    res, classes = out["sistemas"], out["clases"]
    names = [n for n in res if res[n]["tipo"] != "trivial"]
    pal = ev.PALETTE
    # 1) exactitud frente a tiempo
    ev.plot_latency_f1({n: {"latencia_ms": max(res[n]["latencia_ms"]["p50"], 1e-3), "f1_macro": res[n]["f1_macro"]}
                        for n in names}, REPORTS / "benchmark_f1_latencia.png",
                       "FileMind frente a sistemas más simples")
    # 2) F1 por clase
    fig, ax = plt.subplots(figsize=(10, 4.8))
    w = 0.8 / len(names)
    for i, n in enumerate(names):
        ax.bar(np.arange(len(classes)) + i * w, [res[n]["f1_por_clase"][c] for c in classes], w,
               label=n, color=pal[i % len(pal)])
    ax.set_xticks(np.arange(len(classes)) + 0.4 - w / 2, classes, rotation=15)
    ax.set_ylabel("F1 (validación cruzada)")
    ax.set_ylim(0, 1.05)
    ax.legend(fontsize=8, ncol=3, loc="lower center", bbox_to_anchor=(0.5, 1.0))
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(REPORTS / "benchmark_f1_por_clase.png", dpi=150)
    plt.close(fig)
    # 3) robustez
    conds = {"normal": "Texto completo", "corto_500": "Solo 500 caracteres", "ruido_ocr_10": "Ruido de OCR 10 %"}
    fig, ax = plt.subplots(figsize=(9, 4.5))
    w = 0.8 / len(names)
    for i, n in enumerate(names):
        ax.bar(np.arange(len(conds)) + i * w, [res[n]["robustez_f1"][c] for c in conds], w, label=n,
               color=pal[i % len(pal)])
    ax.set_xticks(np.arange(len(conds)) + 0.4 - w / 2, list(conds.values()))
    ax.set_ylabel("F1 macro (10 % de prueba)")
    ax.set_ylim(0, 1.05)
    ax.legend(fontsize=8, ncol=3, loc="lower center", bbox_to_anchor=(0.5, 1.0))
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(REPORTS / "benchmark_robustez.png", dpi=150)
    plt.close(fig)
    # 4) matrices de confusión
    show = [n for n in ("Reglas por palabras clave", "Zero-shot MiniLM", "Zero-shot TF-IDF", FILEMIND) if n in res]
    fig, axes = plt.subplots(1, len(show), figsize=(4.6 * len(show), 4.4))
    short = [c[:6] + "." if len(c) > 7 else c for c in classes]
    for ax, n in zip(np.atleast_1d(axes), show):
        cm = np.asarray(res[n]["matriz_confusion"])
        ax.imshow(cm, cmap="Blues")
        for i in range(cm.shape[0]):
            for j in range(cm.shape[1]):
                ax.text(j, i, cm[i, j], ha="center", va="center", fontsize=8,
                        color="white" if cm[i, j] > cm.max() / 2 else "#222")
        ax.set_xticks(range(len(classes)), short, rotation=45, ha="right", fontsize=8)
        ax.set_yticks(range(len(classes)), short, fontsize=8)
        ax.set_title(f"{n}\nF1 = {res[n]['f1_macro']:.2f}", fontsize=10)
        ax.set_xlabel("Predicho")
    np.atleast_1d(axes)[0].set_ylabel("Real")
    fig.tight_layout()
    fig.savefig(REPORTS / "benchmark_matrices.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main()
