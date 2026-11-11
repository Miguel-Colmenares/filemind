"""Clasificador temático de documentos (objetivo central del documento de IA).

Entrada: texto extraído del archivo + una marca del formato real
(``__fmt_pptx__``), porque "Presentaciones" se define también por su forma.
Representación: TF-IDF de palabras (1-2 gramas) y de caracteres (3-5 gramas,
robusto a errores de OCR y tildes). Se comparan varios algoritmos y se
elige el mejor en validación, siguiendo la idea de que un algoritmo más
complejo no garantiza una mejor predicción.

La retroalimentación del usuario (correcciones de categoría) se incorpora
al re-entrenar, cerrando el ciclo del diagrama de la propuesta.
"""
from __future__ import annotations

import re
import time
import unicodedata
from pathlib import Path

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.naive_bayes import ComplementNB
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.svm import LinearSVC

from ..domain.models import CATEGORIES
from . import evaluation as ev

STOP = ("de la que el en y a los del se las por un para con no una su al lo como más pero sus le ya o "
        "este sí porque esta entre cuando muy sin sobre también me hasta hay donde quien desde todo nos "
        "durante todos uno les ni contra otros ese eso ante ellos e esto mí antes algunos qué unos yo otro "
        "otras otra él tanto esa estos mucho quienes nada muchos cual poco ella estar estas algunas algo "
        "nosotros").split()


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"\d+", " 0 ", t)
    return re.sub(r"\s+", " ", t).strip()


def make_input(text: str, real_type: str) -> str:
    return f"__fmt_{real_type}__ " + normalize(text or "")


def _features():
    return FeatureUnion([
        ("word", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True,
                                 stop_words=[normalize(s) for s in STOP], token_pattern=r"(?u)\b\w\w+\b|__fmt_\w+__")),
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2,
                                 sublinear_tf=True, max_features=40000)),
    ])


def candidate_models() -> dict:
    return {
        "NaiveBayes": ComplementNB(alpha=0.3),
        "RegLogistica": LogisticRegression(max_iter=2000, C=8.0),
        "SVM-lineal": CalibratedClassifierCV(LinearSVC(C=0.7), cv=3),
        "RandomForest": RandomForestClassifier(n_estimators=300, random_state=0, n_jobs=-1),
    }


HYPERPARAMS = {
    "NaiveBayes": "ComplementNB, alpha = 0,3",
    "RegLogistica": "LogisticRegression multinomial, L2, C = 8, lbfgs, 2000 iteraciones",
    "SVM-lineal": "LinearSVC, C = 0,7, calibrada con 3 particiones (sigmoide)",
    "RandomForest": "300 árboles, Gini, raíz cuadrada de los rasgos por división, semilla 0",
}


def slug(name: str) -> str:
    return name.lower().replace("-", "_")


def _simple(params: dict) -> dict:
    """Solo los valores que se pueden mostrar (números, textos, tuplas); sin objetos ni listas largas."""
    out = {}
    for k, v in sorted(params.items()):
        if isinstance(v, (bool, int, float, str)) or v is None:
            out[k] = v
        elif isinstance(v, tuple) and all(isinstance(x, (int, float, str)) for x in v):
            out[k] = list(v)
    return out


def model_params(pipe: Pipeline) -> dict:
    """Parámetros e hiperparámetros reales del pipeline entrenado (los lee de scikit-learn, no de un texto)."""
    feats = dict(pipe.named_steps["feats"].transformer_list)
    keep = ("analyzer", "ngram_range", "min_df", "max_df", "max_features", "sublinear_tf", "norm", "use_idf")
    clf = pipe.named_steps["clf"]
    p = _simple(clf.get_params(deep=False))
    if isinstance(clf, CalibratedClassifierCV):  # la SVM va dentro del calibrador
        p = {**{f"svm__{k}": v for k, v in _simple(clf.estimator.get_params(deep=False)).items()},
             **{k: v for k, v in p.items() if k in ("cv", "method", "ensemble")}}
    learned = {"clases": [str(c) for c in clf.classes_],
               "rasgos": int(len(pipe.named_steps["feats"].get_feature_names_out()))}
    if hasattr(clf, "n_iter_"):
        learned["iteraciones_usadas"] = int(np.max(clf.n_iter_))
    if hasattr(clf, "estimators_"):
        learned["profundidad_media_arboles"] = round(float(np.mean([e.get_depth() for e in clf.estimators_])), 1)
    return {
        "vectorizador_palabras": {k: v for k, v in _simple(feats["word"].get_params()).items() if k in keep},
        "vectorizador_caracteres": {k: v for k, v in _simple(feats["char"].get_params()).items() if k in keep},
        "clasificador": p, "aprendidos": learned,
    }


def latency_ms(pipe: Pipeline, X, n: int = 150) -> dict:
    """Tiempo de respuesta por documento (uno a la vez, como llegan de WhatsApp)."""
    X = list(X)[:n]
    pipe.predict_proba(X[:1])  # calentamiento
    times = []
    for x in X:
        t0 = time.perf_counter()
        pipe.predict_proba([x])
        times.append((time.perf_counter() - t0) * 1000)
    t = np.array(times)
    return {"media": round(float(t.mean()), 3), "p50": round(float(np.percentile(t, 50)), 3),
            "p95": round(float(np.percentile(t, 95)), 3), "max": round(float(t.max()), 3),
            "documentos_por_s": round(float(1000 / t.mean()), 1), "n": len(t)}


def size_kb(pipe: Pipeline) -> float:
    import io
    buf = io.BytesIO()
    joblib.dump(pipe, buf)
    return round(buf.tell() / 1024, 1)


def per_class(metrics: dict) -> dict:
    return {c: {"precision": round(v["precision"], 4), "recall": round(v["recall"], 4),
                "f1": round(v["f1-score"], 4), "soporte": int(v["support"])}
            for c, v in metrics["per_class"].items()}


def learning_curve(model_name: str, X_tr, y_tr, X_va, y_va, seed: int = 42,
                   fractions=(0.1, 0.2, 0.35, 0.5, 0.75, 1.0)) -> list[dict]:
    """F1 macro según la cantidad de documentos de entrenamiento: dice si más datos ayudarían."""
    from sklearn.metrics import f1_score
    rng = np.random.RandomState(seed)
    out = []
    for fr in fractions:
        n = max(int(len(y_tr) * fr), 5 * len(set(y_tr)))
        if fr < 1.0:
            idx, _ = train_test_split(np.arange(len(y_tr)), train_size=n, stratify=y_tr, random_state=rng)
        else:
            idx = np.arange(len(y_tr))
        pipe = Pipeline([("feats", _features()), ("clf", candidate_models()[model_name])])
        try:
            pipe.fit(X_tr[idx], y_tr[idx])
        except ValueError:  # muy pocos ejemplos por clase para calibrar
            continue
        out.append({"documentos": int(len(idx)),
                    "f1_entrenamiento": float(f1_score(y_tr[idx], pipe.predict(X_tr[idx]), average="macro")),
                    "f1_validacion": float(f1_score(y_va, pipe.predict(X_va), average="macro"))})
    return out


def model_terms(pipe: Pipeline, name: str, k: int = 3) -> dict:
    """Términos (palabras o pares de palabras) que más empujan hacia cada categoría.

    Lineales: coeficiente. Naive Bayes: peso logarítmico frente al promedio de las clases.
    Random Forest no tiene pesos por clase: se devuelve la importancia global en ``"_global"``.
    """
    feats = pipe.named_steps["feats"]
    clf = pipe.named_steps["clf"]
    names = np.array(feats.get_feature_names_out()).astype(str)
    is_word = np.char.startswith(names, "word__")
    if name == "RandomForest":
        imp = clf.feature_importances_
        order = [i for i in np.argsort(imp)[::-1] if is_word[i]][:15]
        return {"_global": [(names[i][6:], round(float(imp[i]), 5)) for i in order]}
    if name == "NaiveBayes":
        W = clf.feature_log_prob_ - clf.feature_log_prob_.mean(0, keepdims=True)
    elif name == "SVM-lineal":
        W = np.mean([c.estimator.coef_ for c in clf.calibrated_classifiers_], axis=0)
    else:
        W = clf.coef_
    out = {}
    for ci, c in enumerate(clf.classes_):
        order = [i for i in np.argsort(W[ci])[::-1] if is_word[i] and "__fmt_" not in names[i]][:k]
        out[str(c)] = [(names[i][6:], round(float(W[ci][i]), 3)) for i in order]
    return out


def model_details(fitted, comparison, X_tr, y_tr, X_va, y_va, X_te, y_te, out_dir: Path, seed=42) -> dict:
    """Resultados y gráficas propias de cada algoritmo candidato, sobre TODOS los documentos.

    Validación cruzada de 5 particiones sobre los documentos completos (entrenamiento + validación + prueba):
    cada documento se clasifica una vez con un modelo que no lo vio, así las gráficas muestran el resultado de
    cada uno de los documentos analizados. Se conserva aparte el resultado en el grupo de prueba.
    """
    from sklearn.base import clone
    from sklearn.model_selection import StratifiedKFold

    X_all = np.concatenate([X_tr, X_va, X_te])
    y_all = np.concatenate([y_tr, y_va, y_te])
    folds = list(StratifiedKFold(5, shuffle=True, random_state=seed).split(X_all, y_all))
    out = {}
    for name, pipe in fitted.items():
        test = ev.metrics_dict(y_te, pipe.predict(X_te), CATEGORIES)
        proba = np.zeros((len(y_all), len(CATEGORIES)))
        cv_points = []
        for k, (a, b) in enumerate(folds):
            p = clone(pipe).fit(X_all[a], y_all[a])
            cols = [list(p.classes_).index(c) for c in CATEGORIES]
            proba[b] = p.predict_proba(X_all[b])[:, cols]
            cc = ev.per_class_counts(ev.metrics_dict(y_all[b], np.array(CATEGORIES)[proba[b].argmax(1)],
                                                     CATEGORIES)["confusion_matrix"], CATEGORIES)
            cv_points.append({"particion": k + 1, "fpr": float(np.mean([v["fpr"] for v in cc.values()])),
                              "tpr": float(np.mean([v["tpr"] for v in cc.values()]))})
        y_hat = np.array(CATEGORIES)[proba.argmax(1)]
        todos = ev.metrics_dict(y_all, y_hat, CATEGORIES)
        counts = ev.per_class_counts(todos["confusion_matrix"], CATEGORIES)
        s = slug(name)
        terms = model_terms(pipe, name)
        ev.plot_doc_scatter(y_all, proba, CATEGORIES, out_dir / f"tema_{s}_dispersion.png")
        aucs = ev.plot_roc_classes(y_all, proba, CATEGORIES, counts, out_dir / f"tema_{s}_roc.png")
        ev.plot_model_hits(counts, out_dir / f"tema_{s}_aciertos.png")
        ev.plot_confusion_color(todos["confusion_matrix"], CATEGORIES, out_dir / f"tema_{s}_matriz.png")
        if "_global" in terms:
            ev.plot_model_words(terms["_global"], out_dir / f"tema_{s}_palabras.png", "Importancia en el bosque")
        else:
            ev.plot_model_words([(f"{c} · {t}", w) for c in CATEGORIES for t, w in terms.get(c, [])[:3]],
                                out_dir / f"tema_{s}_palabras.png", classes=CATEGORIES)
        n_err = int((y_hat != y_all).sum())
        out[name] = {
            "hiperparametros": HYPERPARAMS.get(name, ""), "train_s": comparison[name]["train_s"],
            "parametros": model_params(pipe), "latencia_ms": latency_ms(pipe, X_te), "tamano_kb": size_kb(pipe),
            "por_clase_prueba": per_class(test), "por_clase_todos": per_class(todos),
            "val": {"accuracy": comparison[name]["accuracy"], "f1_macro": comparison[name]["f1_macro"]},
            "test": {k: test[k] for k in ("accuracy", "precision_macro", "recall_macro", "f1_macro", "confusion_matrix")},
            "test_aciertos": int(np.trace(np.asarray(test["confusion_matrix"]))), "total_prueba": int(len(y_te)),
            "todos": {k: todos[k] for k in ("accuracy", "precision_macro", "recall_macro", "f1_macro", "confusion_matrix")},
            "aciertos": int(len(y_all) - n_err), "errores": n_err, "total_documentos": int(len(y_all)),
            "por_categoria": counts, "auc_por_categoria": aucs,
            "fpr_macro": float(np.mean([v["fpr"] for v in counts.values()])),
            "tpr_macro": float(np.mean([v["tpr"] for v in counts.values()])),
            "validacion_cruzada": cv_points, "terminos": terms,
            "graficas": {k: f"tema_{s}_{k}.png" for k in ("dispersion", "roc", "aciertos", "matriz", "palabras")},
        }
    return out


class TopicClassifier:
    def __init__(self, pipeline: Pipeline | None = None, meta: dict | None = None):
        self.pipeline = pipeline
        self.meta = meta or {}

    # ------------------------------------------------------------ persistencia
    @classmethod
    def load(cls, path: Path) -> "TopicClassifier | None":
        path = Path(path)
        if not path.exists():
            return None
        obj = joblib.load(path)
        return cls(obj["pipeline"], obj["meta"])

    def save(self, path: Path) -> None:
        joblib.dump({"pipeline": self.pipeline, "meta": self.meta}, path)

    # -------------------------------------------------------------- predicción
    def predict(self, text: str, real_type: str, min_conf: float = 0.35) -> dict:
        if self.pipeline is None:
            return {"category": "Otros", "confidence": 0.0, "top": [], "needs_review": True,
                    "note": "modelo no entrenado"}
        x = make_input(text, real_type)
        proba = self.pipeline.predict_proba([x])[0]
        classes = list(self.pipeline.classes_)
        order = np.argsort(proba)[::-1]
        top = [(classes[i], round(float(proba[i]), 3)) for i in order[:3]]
        cat, conf = top[0]
        needs_review = conf < min_conf or not (text or "").strip()
        return {"category": "Otros" if needs_review else cat, "predicted": cat,
                "confidence": conf, "top": top, "needs_review": needs_review,
                "explicacion": self.explain(x, cat)}

    # ------------------------------------------------------------ explicación
    def _weights(self):
        """Matriz clase × rasgo con lo que cada término aporta a cada categoría (se calcula una vez)."""
        if getattr(self, "_w", None) is None:
            feats, clf = self.pipeline.named_steps["feats"], self.pipeline.named_steps["clf"]
            names = np.array(feats.get_feature_names_out()).astype(str)
            if isinstance(clf, RandomForestClassifier):
                W = np.tile(clf.feature_importances_, (len(clf.classes_), 1))
            elif isinstance(clf, ComplementNB):
                W = clf.feature_log_prob_ - clf.feature_log_prob_.mean(0, keepdims=True)
            elif isinstance(clf, CalibratedClassifierCV):
                W = np.mean([c.estimator.coef_ for c in clf.calibrated_classifiers_], axis=0)
            else:
                W = clf.coef_
            if W.shape[0] == 1:  # problema binario: una sola fila de coeficientes
                W = np.vstack([-W[0], W[0]])
            usable = np.char.startswith(names, "word__") & ~np.char.startswith(names, "word____fmt_")
            self._w = (W, names, usable, list(clf.classes_))
        return self._w

    def explain(self, x: str, category: str, k: int = 6) -> list[dict]:
        """Palabras del propio documento que más empujaron hacia la categoría elegida.

        Aporte de cada término = peso TF-IDF en el documento × peso del término para esa clase.
        Es una explicación local: cambia con cada archivo y se puede leer sin saber de IA.
        """
        try:
            W, names, usable, classes = self._weights()
            v = self.pipeline.named_steps["feats"].transform([x]).tocsr()
            ci = classes.index(category)
        except (ValueError, AttributeError, KeyError):
            return []
        idx, vals = v.indices, v.data
        contrib = vals * W[ci, idx]
        keep = usable[idx] & (contrib > 0)
        order = np.argsort(contrib[keep])[::-1][:k]
        sel_idx, sel_val = idx[keep][order], contrib[keep][order]
        total = float(contrib[contrib > 0].sum()) or 1.0
        return [{"termino": names[i][6:], "peso": round(float(c), 4), "porcentaje": round(100 * float(c) / total, 1)}
                for i, c in zip(sel_idx, sel_val)]

    # ----------------------------------------------------------- entrenamiento
    @classmethod
    def train(cls, texts: list[str], types: list[str], labels: list[str], out_dir: Path,
              seed: int = 42, extra: list[tuple[str, str, str]] | None = None) -> "TopicClassifier":
        """Entrena y evalúa. División 70 % / 20 % / 10 % (entrenamiento / validación / prueba).

        ``extra`` = retroalimentación del usuario ``(texto, tipo, categoría)``; se
        añade solo al entrenamiento para no contaminar la evaluación.
        """
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        X = np.array([make_input(t, ty) for t, ty in zip(texts, types)], dtype=object)
        y = np.array(labels)
        X_tr, X_tmp, y_tr, y_tmp = train_test_split(X, y, test_size=0.30, stratify=y, random_state=seed)
        X_va, X_te, y_va, y_te = train_test_split(X_tmp, y_tmp, test_size=1 / 3, stratify=y_tmp, random_state=seed)
        if extra:
            X_tr = np.concatenate([X_tr, [make_input(t, ty) for t, ty, _ in extra]])
            y_tr = np.concatenate([y_tr, [c for _, _, c in extra]])

        comparison, fitted = {}, {}
        for name, model in candidate_models().items():
            t0 = time.perf_counter()
            pipe = Pipeline([("feats", _features()), ("clf", model)])
            pipe.fit(X_tr, y_tr)
            yp = pipe.predict(X_va)
            m = ev.metrics_dict(y_va, yp, CATEGORIES)
            comparison[name] = {"accuracy": m["accuracy"], "f1_macro": m["f1_macro"],
                                "train_s": round(time.perf_counter() - t0, 2)}
            fitted[name] = pipe
        best = max(comparison, key=lambda n: (round(comparison[n]["f1_macro"], 3), -comparison[n]["train_s"]))
        pipe = fitted[best]

        # evaluación final en el conjunto de prueba (no visto)
        y_pred = pipe.predict(X_te)
        proba = pipe.predict_proba(X_te)
        classes = list(pipe.classes_)
        test = ev.metrics_dict(y_te, y_pred, CATEGORIES)
        ev.plot_confusion(test["confusion_matrix"], CATEGORIES, out_dir / "tema_matriz_confusion.png",
                          "Matriz de confusión — clasificación temática (prueba)")
        aps = ev.plot_pr_curves(y_te, proba, classes, out_dir / "tema_curva_pr.png",
                                "Precisión-Recall por categoría")
        thr, f1best = ev.plot_f1_confidence(y_te, proba, classes, out_dir / "tema_curva_f1_confianza.png")
        ev.plot_model_comparison(comparison, out_dir / "tema_comparacion_modelos.png")

        detalle = model_details(fitted, comparison, X_tr, y_tr, X_va, y_va, X_te, y_te, out_dir, seed)
        curva = learning_curve(best, X_tr, y_tr, X_va, y_va, seed)
        if curva:
            ev.plot_learning_curve(curva, out_dir / "tema_curva_aprendizaje.png", f"Curva de aprendizaje ({best})")
        cal = ev.calibration(y_te, proba, classes)
        ev.plot_calibration(cal, out_dir / "tema_calibracion.png", f"Calibración ({best}, prueba)")
        ev.plot_latency_f1({n: {"latencia_ms": d["latencia_ms"]["p50"], "f1_macro": d["test"]["f1_macro"]}
                            for n, d in detalle.items()}, out_dir / "tema_latencia_f1.png",
                           "Algoritmos candidatos: F1 en prueba frente a tiempo por documento")

        meta = {
            "task": "clasificacion_tematica", "best_model": best, "comparison": comparison, "modelos": detalle,
            "n_rasgos": int(len(pipe.named_steps["feats"].get_feature_names_out())),
            "split": {"train": int(len(y_tr)), "val": int(len(y_va)), "test": int(len(y_te))},
            "test": test, "average_precision": aps, "f1_conf_best": {"threshold": thr, "f1": f1best},
            "feedback_samples": len(extra or []), "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "parametros": detalle[best]["parametros"], "latencia_ms": detalle[best]["latencia_ms"],
            "curva_aprendizaje": curva, "calibracion": cal, "semilla": seed,
            "criterio_seleccion": "mayor F1 macro en validación; en empate, menor tiempo de entrenamiento",
        }
        ev.save_json(meta, out_dir / "tema_metricas.json")
        clf = cls(pipe, meta)
        return clf
