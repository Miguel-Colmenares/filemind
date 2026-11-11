"""Métricas y gráficas de evaluación (compartidas por los dos modelos).

Genera las mismas piezas que se usan en la literatura de referencia de la
presentación: matriz de confusión, curvas Precisión-Recall, curva
F1-confianza y comparación de algoritmos.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker  # noqa: F401  (formato de ejes logarítmicos)
import numpy as np
from sklearn.metrics import (accuracy_score, auc, classification_report, confusion_matrix,
                             f1_score, precision_recall_curve, precision_score, recall_score)

PALETTE = ["#2a6fdb", "#e8833a", "#3aa76d", "#c94c4c", "#8a5cc2", "#1fa2b5", "#b5a01f", "#6b6b6b"]


def metrics_dict(y_true, y_pred, labels) -> dict:
    rep = classification_report(y_true, y_pred, labels=labels, output_dict=True, zero_division=0)
    return {
        "accuracy": accuracy_score(y_true, y_pred),
        "precision_macro": precision_score(y_true, y_pred, labels=labels, average="macro", zero_division=0),
        "recall_macro": recall_score(y_true, y_pred, labels=labels, average="macro", zero_division=0),
        "f1_macro": f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0),
        "per_class": {k: v for k, v in rep.items() if k in labels},
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=labels).tolist(),
        "labels": list(labels),
    }


def plot_confusion(cm, labels, path: Path, title="Matriz de confusión"):
    cm = np.asarray(cm)
    fig, ax = plt.subplots(figsize=(1.1 * len(labels) + 3, 0.9 * len(labels) + 2.5))
    im = ax.imshow(cm, cmap="Blues")
    ax.set_xticks(range(len(labels)), labels, rotation=40, ha="right")
    ax.set_yticks(range(len(labels)), labels)
    ax.set_xlabel("Predicho")
    ax.set_ylabel("Real")
    thr = cm.max() / 2 if cm.size else 0
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(j, i, cm[i, j], ha="center", va="center",
                    color="white" if cm[i, j] > thr else "#222", fontsize=10)
    fig.colorbar(im, ax=ax, fraction=0.046)
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_pr_curves(y_true, proba, classes, path: Path, title="Curva Precisión-Recall"):
    y_true = np.asarray(y_true)
    fig, ax = plt.subplots(figsize=(7, 5.5))
    aps = {}
    for i, c in enumerate(classes):
        yb = (y_true == c).astype(int)
        if yb.sum() == 0:
            continue
        p, r, _ = precision_recall_curve(yb, proba[:, i])
        aps[c] = auc(r, p)
        ax.plot(r, p, lw=1.3, color=PALETTE[i % len(PALETTE)], label=f"{c} {aps[c]:.3f}")
    ax.set_xlabel("Recall")
    ax.set_ylabel("Precisión")
    ax.set_xlim(0, 1.01)
    ax.set_ylim(0, 1.02)
    ax.set_title(f"{title} (área media {np.mean(list(aps.values())):.3f})")
    ax.legend(loc="lower left", fontsize=8)
    ax.grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return aps


def plot_f1_confidence(y_true, proba, classes, path: Path, title="Curva F1-Confianza"):
    """F1 macro al exigir una confianza mínima (predicciones por debajo = 'sin decidir')."""
    y_true = np.asarray(y_true)
    classes = np.asarray(classes)
    pred = classes[proba.argmax(1)]
    conf = proba.max(1)
    ths = np.linspace(0, 1, 101)
    f1s = []
    for t in ths:
        keep = conf >= t
        yp = np.where(keep, pred, "__none__")
        f1s.append(f1_score(y_true, yp, labels=list(classes), average="macro", zero_division=0))
    f1s = np.array(f1s)
    best = int(f1s.argmax())
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.plot(ths, f1s, color=PALETTE[0], lw=2, label=f"todas las clases {f1s[best]:.2f} en {ths[best]:.2f}")
    ax.axvline(ths[best], ls="--", color="#999")
    ax.set_xlabel("Confianza")
    ax.set_ylabel("F1")
    ax.set_ylim(0, 1.02)
    ax.set_title(title)
    ax.legend(loc="lower left")
    ax.grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return float(ths[best]), float(f1s[best])


def plot_model_comparison(results: dict, path: Path, metric="f1_macro", title="Comparación de algoritmos (validación)"):
    names = list(results)
    vals = [results[n][metric] for n in names]
    fig, ax = plt.subplots(figsize=(7, 4))
    bars = ax.bar(names, vals, color=PALETTE[:len(names)])
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.01, f"{v:.3f}", ha="center")
    ax.set_ylim(0, 1.08)
    ax.set_ylabel(metric)
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def save_json(obj, path: Path):
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=float), encoding="utf-8")


# ------------------------------------------------- detalle de cada modelo candidato
OK, FN_C, FP_C = "#2e9d5b", "#f0a030", "#d64545"


def per_class_counts(cm, labels) -> dict:
    """Aciertos, no reconocidos, falsos positivos y tasas uno contra el resto por categoría."""
    cm = np.asarray(cm)
    n = cm.sum()
    out = {}
    for i, c in enumerate(labels):
        tp = int(cm[i, i]); fn = int(cm[i].sum() - tp); fp = int(cm[:, i].sum() - tp); tn = int(n - tp - fn - fp)
        out[c] = {"aciertos": tp, "no_reconocidos": fn, "falsos_positivos": fp, "verdaderos_negativos": tn,
                  "tpr": tp / max(tp + fn, 1), "fpr": fp / max(fp + tn, 1)}
    return out


def doc_points(y_true, proba, classes):
    """Por documento, probabilidad de la categoría real y la más alta entre las demás."""
    y_true = np.asarray(y_true)
    classes = list(classes)
    idx = np.array([classes.index(c) for c in y_true])
    p_true = proba[np.arange(len(y_true)), idx]
    other = proba.copy()
    other[np.arange(len(y_true)), idx] = -1
    return idx, p_true, other.max(1)


def plot_doc_scatter(y_true, proba, classes, path: Path, jitter: float = 0.004):
    """Diagrama de dispersión con un punto por DOCUMENTO analizado.

    x = probabilidad que el modelo dio a la categoría real; y = probabilidad más alta que dio a otra categoría.
    Debajo de la diagonal el documento quedó en su categoría (acierto); encima quedó en otra (error, que es un
    falso positivo para la categoría elegida). El color es la categoría real.
    """
    classes = list(classes)
    idx, p_true, p_other = doc_points(y_true, proba, classes)
    ok = p_true > p_other
    rng = np.random.default_rng(0)
    jit = lambda a: np.clip(a + rng.normal(0, jitter, len(a)), 0, 1)  # separa puntos superpuestos
    fig, ax = plt.subplots(figsize=(7.2, 6))
    ax.fill_between([0, 1], [0, 1], 0, color=OK, alpha=0.06)
    ax.fill_between([0, 1], [0, 1], 1, color=FP_C, alpha=0.06)
    ax.plot([0, 1], [0, 1], ls="--", color="#555", lw=0.9)
    for i, c in enumerate(classes):
        m = idx == i
        col = PALETTE[i % len(PALETTE)]
        ax.scatter(jit(p_true[m & ok]), jit(p_other[m & ok]), s=16, color=col, alpha=0.65, edgecolors="none",
                   label=f"{c} ({int((m & ok).sum())} aciertos, {int((m & ~ok).sum())} errores)")
        ax.scatter(jit(p_true[m & ~ok]), jit(p_other[m & ~ok]), s=46, color=col, marker="X", edgecolors="black",
                   linewidths=0.6)
    ax.text(0.97, 0.03, "zona de aciertos", ha="right", color=OK, fontsize=9, weight="bold")
    ax.text(0.03, 0.95, "zona de errores", ha="left", va="top", color=FP_C, fontsize=9, weight="bold")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("Probabilidad asignada a la categoría real")
    ax.set_ylabel("Probabilidad más alta asignada a otra categoría")
    ax.set_title(f"{len(idx)} documentos, {int(ok.sum())} aciertos y {int((~ok).sum())} errores (marcados con X)",
                 fontsize=10)
    ax.legend(loc="center left", bbox_to_anchor=(1.01, 0.5), fontsize=8, frameon=False)
    ax.grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(path, dpi=170, bbox_inches="tight")
    plt.close(fig)


def plot_roc_classes(y_true, proba, classes, counts: dict, path: Path):
    """Curva ROC uno contra el resto de cada categoría, con el punto de decisión real del modelo."""
    from sklearn.metrics import roc_auc_score, roc_curve
    y_true = np.asarray(y_true)
    fig, ax = plt.subplots(figsize=(7.2, 5.6))
    ax.plot([0, 1], [0, 1], ls="--", color="#777", lw=0.8, label="Azar")
    ins = ax.inset_axes([0.38, 0.38, 0.32, 0.32])
    aucs = {}
    for i, c in enumerate(classes):
        yb = (y_true == c).astype(int)
        f, t, _ = roc_curve(yb, proba[:, i])
        aucs[c] = float(roc_auc_score(yb, proba[:, i]))
        col = PALETTE[i % len(PALETTE)]
        ax.plot(f, t, color=col, lw=1.6, label=f"{c} (AUC {aucs[c]:.3f})".replace(".", ","))
        ins.plot(f, t, color=col, lw=1.2)
        if c in counts:
            ax.scatter(counts[c]["fpr"], counts[c]["tpr"], color=col, s=60, edgecolors="black", zorder=5)
            ins.scatter(counts[c]["fpr"], counts[c]["tpr"], color=col, s=25, edgecolors="black", zorder=5)
    ins.set_xlim(0, 0.15)
    ins.set_ylim(0.75, 1.0)
    ins.set_title("ampliación", fontsize=7)
    ins.tick_params(labelsize=6)
    ax.set_xlabel("Tasa de falsos positivos (FPR)")
    ax.set_ylabel("Tasa de verdaderos positivos (TPR)")
    ax.set_title("Los puntos son la decisión real del modelo en cada categoría", fontsize=9)
    ax.legend(loc="lower right", fontsize=8)
    ax.grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)
    return aucs


def plot_model_hits(counts: dict, path: Path):
    """Barras por categoría: aciertos, documentos no reconocidos y falsos positivos de UN modelo."""
    cats = list(counts)
    y = np.arange(len(cats))
    h = 0.27
    fig, ax = plt.subplots(figsize=(7.2, 0.5 * len(cats) + 1.8))
    vals = [[counts[c][k] for c in cats] for k in ("aciertos", "no_reconocidos", "falsos_positivos")]
    for off, v, col, lab in ((-h, vals[0], OK, "Aciertos (verdaderos positivos)"),
                             (0, vals[1], FN_C, "No reconocidos (falsos negativos)"),
                             (h, vals[2], FP_C, "Falsos positivos")):
        bars = ax.barh(y + off, v, height=h, label=lab, color=col)
        for b, n in zip(bars, v):
            ax.text(b.get_width() + 1, b.get_y() + h / 2, str(n), va="center", fontsize=7)
    ax.set_yticks(y, cats)
    ax.invert_yaxis()
    ax.set_xlabel("Número de documentos")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12 - 0.6 / len(cats)), ncol=3, fontsize=7, frameon=False)
    ax.grid(alpha=.3, axis="x")
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)


def plot_model_words(words: list, path: Path, xlabel="Peso en el modelo", classes=None):
    """Barras horizontales con los términos de mayor peso de UN modelo, coloreadas por categoría."""
    fig, ax = plt.subplots(figsize=(7.2, 0.3 * len(words) + 1.2))
    labels = [w for w, _ in words]
    vals = [v for _, v in words]
    cols = [PALETTE[classes.index(w.split(" · ")[0]) % len(PALETTE)] if classes and w.split(" · ")[0] in classes
            else PALETTE[0] for w in labels]
    ax.barh(range(len(words)), vals, color=cols)
    ax.set_yticks(range(len(words)), labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel(xlabel)
    ax.grid(alpha=.3, axis="x")
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)


def plot_confusion_color(cm, labels, path: Path):
    cm = np.asarray(cm)
    fig, ax = plt.subplots(figsize=(0.75 * len(labels) + 3.4, 0.65 * len(labels) + 2.6))
    im = ax.imshow(cm, cmap="Blues")
    ax.set_xticks(range(len(labels)), labels, rotation=35, ha="right", fontsize=8)
    ax.set_yticks(range(len(labels)), labels, fontsize=8)
    ax.set_xlabel("Categoría predicha")
    ax.set_ylabel("Categoría real")
    thr = cm.max() / 2 if cm.size else 0
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(j, i, cm[i, j], ha="center", va="center", fontsize=9,
                    color="white" if cm[i, j] > thr else ("#b02020" if i != j and cm[i, j] else "black"))
    fig.colorbar(im, ax=ax, fraction=0.046, label="documentos")
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)


def plot_learning_curve(points: list[dict], path: Path, title="Curva de aprendizaje"):
    """F1 macro en entrenamiento y validación según cuántos documentos ve el modelo."""
    n = [p["documentos"] for p in points]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.plot(n, [p["f1_entrenamiento"] for p in points], "o-", color=PALETTE[0], label="Entrenamiento")
    ax.plot(n, [p["f1_validacion"] for p in points], "s-", color=PALETTE[1], label="Validación")
    ax.set_xlabel("Documentos de entrenamiento")
    ax.set_ylabel("F1 macro")
    ax.set_ylim(min(0.5, min(p["f1_validacion"] for p in points) - 0.05), 1.01)
    ax.grid(alpha=0.3)
    ax.legend(loc="lower right")
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def calibration(y_true, proba, classes, bins: int = 10) -> dict:
    """Diagrama de confiabilidad sobre la confianza de la clase elegida y error de calibración esperado (ECE)."""
    y_true = np.asarray(y_true)
    conf = proba.max(1)
    hit = (np.asarray(classes)[proba.argmax(1)] == y_true).astype(float)
    edges = np.linspace(0, 1, bins + 1)
    rows, ece = [], 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            rows.append({"desde": round(float(lo), 2), "hasta": round(float(hi), 2), "n": int(m.sum()),
                         "confianza": float(conf[m].mean()), "exactitud": float(hit[m].mean())})
            ece += m.mean() * abs(conf[m].mean() - hit[m].mean())
    return {"bins": rows, "ece": float(ece), "confianza_media": float(conf.mean()), "exactitud": float(hit.mean())}


def plot_calibration(cal: dict, path: Path, title="Calibración de la confianza"):
    fig, ax = plt.subplots(figsize=(5.5, 5))
    ax.plot([0, 1], [0, 1], "--", color="#888", label="Calibración perfecta")
    b = cal["bins"]
    ax.plot([r["confianza"] for r in b], [r["exactitud"] for r in b], "o-", color=PALETTE[0], label="Modelo")
    for r in b:
        ax.annotate(str(r["n"]), (r["confianza"], r["exactitud"]), textcoords="offset points", xytext=(4, -10), fontsize=8)
    ax.set_xlabel("Confianza que da el modelo")
    ax.set_ylabel("Exactitud real")
    ax.set_xlim(0, 1.02)
    ax.set_ylim(0, 1.02)
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left")
    ax.set_title(f"{title} (ECE = {cal['ece']:.3f})")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_latency_f1(models: dict, path: Path, title="Exactitud frente a tiempo de respuesta"):
    """Cada sistema es un punto: más arriba es más exacto, más a la izquierda responde más rápido."""
    fig, ax = plt.subplots(figsize=(7, 4.8))
    for i, (name, m) in enumerate(models.items()):
        ax.scatter(m["latencia_ms"], m["f1_macro"], s=90, color=PALETTE[i % len(PALETTE)], zorder=3)
        ax.annotate(name, (m["latencia_ms"], m["f1_macro"]), textcoords="offset points", xytext=(7, 4), fontsize=9)
    ax.set_xscale("log")
    fmt = matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}".replace(".", ","))
    ax.xaxis.set_major_formatter(fmt)
    ax.xaxis.set_minor_formatter(fmt)
    ax.tick_params(axis="x", which="minor", labelsize=7)
    ax.set_xlabel("Tiempo por documento (ms, escala logarítmica)")
    ax.set_ylabel("F1 macro")
    ax.grid(alpha=0.3, which="both")
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
