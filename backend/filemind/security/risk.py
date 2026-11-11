"""Fase 4 — Puntaje de riesgo 0-100 (RF7) y modelo de IA de riesgo.

El puntaje final combina dos componentes, ambos reproducibles:

1. **Puntaje por reglas** (``rule_score``): suma de pesos documentados en
   ``RULE_WEIGHTS`` (tabla también publicada en docs/protocolo_riesgo.md),
   con tope en 100.
2. **Probabilidad del modelo de IA** (``RiskModel``): un bosque aleatorio
   entrenado con las características extraídas en las fases 1-3 que estima
   P(legítimo), P(phishing) y P(ransomware).

``puntaje = max(reglas, round(100 * P(malicioso)))``: basta con que la
evidencia documentada **o** el modelo sean contundentes (se prioriza no dejar
pasar amenazas, RNF3). Además hay dos pisos
duros: hash de malware conocido => 100; contenido ejecutable o doble
extensión => al menos 90. Si el modelo no está entrenado se usa solo el
puntaje por reglas.

Niveles: bajo (0-39), medio (40-70), alto (>70 => cuarentena, RF8).
"""
from __future__ import annotations

import math
import time
from pathlib import Path

import joblib
import numpy as np

FEATURES = [
    # Fase 1
    "known_malware", "executable_content", "double_extension", "bidi_override", "dangerous_ext",
    "extension_mismatch", "macro_container", "unsupported_type", "size_log",
    # Fase 2
    "url_count", "url_ip_host", "url_shortener", "url_punycode", "url_risky_tld", "url_at_sign",
    "url_many_subdomains", "url_no_tls", "url_credential_path", "url_brand_impersonation",
    "url_recent_domain", "phish_phrases", "ransom_phrases", "has_macros", "macro_autoexec",
    "macro_suspicious", "pdf_javascript", "pdf_openaction", "pdf_autoaction", "pdf_launch",
    "pdf_embedded", "pdf_hex_obfuscation", "remote_template", "dde", "ole_objects",
    "long_base64", "js_obfuscation", "powershell", "entropy",
    # Fase 3
    "sbx_embedded_exe", "sbx_hidden_scripts", "sbx_active_content", "sbx_ransom_markers",
    "sbx_hidden_objstm", "sbx_expansion_limit", "sbx_nested", "sbx_urls", "sbx_failed",
]

# (característica, peso por ocurrencia, tope de la característica)
# Los indicadores de "alta confianza" (DDE, plantilla remota, PowerShell codificado,
# ejecutable o script escondido, JavaScript oculto en flujos comprimidos, nota de
# rescate) pesan 75: prácticamente no aparecen en documentos legítimos y, por sí
# solos, deben llevar a cuarentena aunque el modelo nunca haya visto ese ataque.
RULE_WEIGHTS = [
    ("known_malware", 100, 100),
    ("executable_content", 90, 90),
    ("double_extension", 60, 60),
    ("bidi_override", 50, 50),
    ("dangerous_ext", 40, 40),
    ("extension_mismatch", 35, 35),
    ("macro_autoexec", 35, 35),
    ("has_macros", 15, 15),
    ("macro_suspicious", 10, 30),
    ("pdf_launch", 40, 40),
    ("pdf_javascript", 25, 25),
    ("pdf_hex_obfuscation", 25, 25),
    ("pdf_openaction", 8, 8),
    ("pdf_autoaction", 8, 8),
    ("pdf_embedded", 15, 15),
    ("remote_template", 75, 75),
    ("dde", 75, 75),
    ("ole_objects", 10, 20),
    ("powershell", 75, 75),
    ("url_ip_host", 20, 40),
    ("url_shortener", 10, 20),
    ("url_punycode", 25, 25),
    ("url_risky_tld", 15, 30),
    ("url_at_sign", 20, 20),
    ("url_brand_impersonation", 35, 35),
    ("url_recent_domain", 25, 25),
    ("phish_phrases", 8, 32),
    ("ransom_phrases", 25, 75),
    ("sbx_embedded_exe", 75, 75),
    ("sbx_hidden_scripts", 75, 75),
    ("sbx_ransom_markers", 10, 30),
    ("sbx_hidden_objstm", 75, 75),
    ("sbx_expansion_limit", 30, 30),
    # Controles de ciberseguridad (security/controls.py). No entran al modelo de IA.
    ("known_malware_hash", 100, 100),
    ("inner_known_malware", 100, 100),
    ("polyglot", 40, 40),
    ("yara_alta", 75, 75),
    ("yara_media", 20, 40),
    ("pdf_js_autorun", 50, 50),
    ("pdf_js_suspicious_api", 20, 40),
    ("pdf_embedded_exe", 75, 75),
    ("pdf_embedded_macro", 30, 30),
    ("pdf_encrypted", 15, 15),
    ("pdf_malformed", 20, 20),
    ("vba_ioc", 10, 20),
    ("vba_obfuscation", 10, 20),
    ("vba_stomping", 60, 60),
    ("xlm_macros", 40, 40),
    ("ole_package_exe", 75, 75),
    ("ole_exploit_class", 75, 75),
    ("office_encrypted", 20, 20),
    ("archive_executable", 75, 75),
    ("archive_dangerous_entry", 60, 60),
    ("archive_path_traversal", 40, 40),
    ("archive_bomb", 75, 75),
    ("archive_ratio_high", 40, 40),
    ("archive_encrypted", 30, 30),
    ("archive_nested_deep", 20, 20),
    ("archive_macro_doc", 25, 25),
    ("archive_uninspectable", 10, 10),
    ("entropy_anomaly", 15, 15),
    ("url_hidden_suspicious", 20, 40),
    ("html_password_form", 35, 35),
    ("html_form_external", 20, 20),
    ("html_brand_title", 20, 20),
    ("url_text_mismatch", 30, 30),
    ("html_meta_refresh", 15, 15),
    ("html_hidden_iframe", 30, 30),
    ("cred_request_link", 30, 30),
]
# Indicadores que solo producen los controles (no forman parte del vector del modelo de IA)
CONTROL_FEATURES = [name for name, _, _ in RULE_WEIGHTS[RULE_WEIGHTS.index(("known_malware_hash", 100, 100)):]]
# Condicionales (se documentan aparte porque dependen de umbrales)
#  js_obfuscation >= 2  -> +15 ; long_base64 >= 3 -> +10
#  url_credential_path  -> +10 solo si hay otro indicador de URL sospechosa
#  sbx_failed (timeout) -> +20

LABELS = ["legitimo", "phishing", "ransomware"]


def build_vector(static: dict, heur: dict, sbx: dict, controls: dict | None = None) -> dict:
    """Vector de características. ``controls`` (opcional) agrega los indicadores de
    ``security/controls.py``, que solo usa el puntaje por reglas."""
    f = {k: 0.0 for k in FEATURES}
    for k in ("known_malware", "executable_content", "double_extension", "bidi_override",
              "dangerous_ext", "extension_mismatch", "macro_container"):
        f[k] = float(bool(static.get(k)))
    f["unsupported_type"] = float(not static.get("supported_type", True))
    f["size_log"] = round(math.log10(max(static.get("size", 1), 1)), 3)
    for src in (heur, sbx):
        for k, v in src.items():
            if k in f:
                f[k] = float(v)
    for k, v in (controls or {}).items():
        if k in CONTROL_FEATURES:
            f[k] = float(v)
        elif k in f:   # p. ej. ole_objects de un RTF, que la fase 2 no ve
            f[k] = max(f[k], float(v))
    return f


def rule_score(f: dict) -> tuple[int, list[tuple[str, int]]]:
    contrib = []
    for name, w, cap in RULE_WEIGHTS:
        v = f.get(name, 0)
        if v:
            pts = min(int(round(w * v)), cap)
            contrib.append((name, pts))
    if f.get("js_obfuscation", 0) >= 2:
        contrib.append(("js_obfuscation", 15))
    if f.get("long_base64", 0) >= 3:
        contrib.append(("long_base64", 10))
    url_flags = sum(f.get(k, 0) for k in ("url_ip_host", "url_shortener", "url_punycode", "url_risky_tld",
                                           "url_at_sign", "url_brand_impersonation", "url_recent_domain"))
    if f.get("url_credential_path", 0) and url_flags:
        contrib.append(("url_credential_path", 10))
    if f.get("sbx_failed", 0):
        contrib.append(("sbx_failed", 20))
    return min(100, sum(p for _, p in contrib)), contrib


def level(score: int) -> str:
    return "alto" if score > 70 else ("medio" if score >= 40 else "bajo")


class RiskModel:
    def __init__(self, model=None, meta: dict | None = None):
        self.model, self.meta = model, meta or {}

    @classmethod
    def load(cls, path: Path) -> "RiskModel":
        path = Path(path)
        if path.exists():
            obj = joblib.load(path)
            return cls(obj["model"], obj["meta"])
        return cls()

    def save(self, path: Path) -> None:
        joblib.dump({"model": self.model, "meta": self.meta}, path)

    def proba(self, f: dict) -> dict | None:
        if self.model is None:
            return None
        x = np.array([[f[k] for k in FEATURES]])
        p = self.model.predict_proba(x)[0]
        out = {c: float(p[list(self.model.classes_).index(c)]) if c in self.model.classes_ else 0.0
               for c in LABELS}
        return out


def score(f: dict, model: RiskModel | None) -> dict:
    rules, contrib = rule_score(f)
    probs = model.proba(f) if model else None
    if probs is None:
        final = rules
        p_mal = None
    else:
        p_mal = 1.0 - probs["legitimo"]
        final = max(rules, int(round(100 * p_mal)))
    floors = []
    if f.get("known_malware") or f.get("known_malware_hash") or f.get("inner_known_malware"):
        final, floors = 100, ["hash de malware conocido"]
    elif f.get("executable_content") or f.get("double_extension") or f.get("bidi_override"):
        if final < 90:
            floors.append("archivo ejecutable o extensión engañosa")
        final = max(final, 90)
    kind = None
    if probs:
        kind = max(("phishing", "ransomware"), key=lambda k: probs[k]) if p_mal and p_mal >= 0.5 else None
    return {"score": int(min(max(final, 0), 100)), "level": level(final), "rule_score": rules,
            "rule_contributions": contrib, "ml_probabilities": probs, "p_malicious": p_mal,
            "floors": floors, "threat_type": kind, "formula": "max(reglas, 100*P(malicioso))"}


def train_risk_model(X: list[dict], y: list[str], out_dir: Path, seed: int = 42,
                     kinds: list[str] | None = None) -> RiskModel:
    """Entrena, evalúa (RNF3/RNF4) y guarda gráficas y métricas."""
    from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.tree import DecisionTreeClassifier

    from ..ai import evaluation as ev

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    M = np.array([[x[k] for k in FEATURES] for x in X])
    Y = np.array(y)
    X_tr, X_tmp, y_tr, y_tmp = train_test_split(M, Y, test_size=0.30, stratify=Y, random_state=seed)
    X_va, X_te, y_va, y_te = train_test_split(X_tmp, y_tmp, test_size=0.5, stratify=y_tmp, random_state=seed)

    cands = {
        "RegLogistica": make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000, C=1.0)),
        "ArbolDecision": DecisionTreeClassifier(max_depth=6, random_state=seed),
        "RandomForest": RandomForestClassifier(n_estimators=300, min_samples_leaf=1, random_state=seed,
                                               class_weight="balanced"),
        "GradientBoosting": GradientBoostingClassifier(random_state=seed),
    }
    comp, fitted = {}, {}
    for n, m in cands.items():
        t0 = time.perf_counter()
        m.fit(X_tr, y_tr)
        yp = m.predict(X_va)
        md = ev.metrics_dict(y_va, yp, LABELS)
        comp[n] = {"accuracy": md["accuracy"], "f1_macro": md["f1_macro"],
                   "train_s": round(time.perf_counter() - t0, 2)}
        fitted[n] = m
    best = max(comp, key=lambda n: (round(comp[n]["f1_macro"], 3), -comp[n]["train_s"]))
    model = fitted[best]

    rm = RiskModel(model)
    # Evaluación binaria sobre prueba usando el PUNTAJE FINAL y el umbral 70 (lo que decide la cuarentena)
    finals = []
    for row in X_te:
        f = dict(zip(FEATURES, row))
        finals.append(score(f, rm)["score"])
    finals = np.array(finals)
    y_bin = np.where(y_te == "legitimo", "legitimo", "malicioso")
    p_bin = np.where(finals > 70, "malicioso", "legitimo")
    from sklearn.metrics import confusion_matrix
    cm = confusion_matrix(y_bin, p_bin, labels=["malicioso", "legitimo"])
    tp, fn, fp, tn = int(cm[0, 0]), int(cm[0, 1]), int(cm[1, 0]), int(cm[1, 1])
    fnr = fn / max(tp + fn, 1)
    fpr = fp / max(fp + tn, 1)
    multi = ev.metrics_dict(y_te, model.predict(X_te), LABELS)
    ev.plot_confusion(cm, ["malicioso", "legitimo"], out_dir / "riesgo_matriz_confusion_binaria.png",
                      "Matriz de confusión — cuarentena (puntaje > 70)")
    ev.plot_confusion(multi["confusion_matrix"], LABELS, out_dir / "riesgo_matriz_confusion_3clases.png",
                      "Matriz de confusión — tipo de amenaza")
    aps = ev.plot_pr_curves(y_te, model.predict_proba(X_te), list(model.classes_),
                            out_dir / "riesgo_curva_pr.png", "Precisión-Recall — modelo de riesgo")
    ev.plot_model_comparison(comp, out_dir / "riesgo_comparacion_modelos.png")
    importances = None
    if hasattr(model, "feature_importances_"):
        importances = sorted(zip(FEATURES, map(float, model.feature_importances_)), key=lambda t: -t[1])[:15]
    elif hasattr(model, "named_steps") and hasattr(model[-1], "coef_"):
        w = np.abs(model[-1].coef_).sum(0)
        importances = sorted(zip(FEATURES, map(float, w / w.sum())), key=lambda t: -t[1])[:15]

    # Validación cruzada estratificada (5 particiones) del puntaje final con umbral 70
    from sklearn.base import clone
    from sklearn.model_selection import StratifiedKFold
    cv_rows = []
    for k, (tr, te) in enumerate(StratifiedKFold(5, shuffle=True, random_state=seed).split(M, Y)):
        mk = RiskModel(clone(cands[best]).fit(M[tr], Y[tr]))
        sc = np.array([score(dict(zip(FEATURES, r)), mk)["score"] for r in M[te]])
        mal = Y[te] != "legitimo"
        cv_rows.append({"fold": k + 1, "fnr": float(((sc <= 70) & mal).sum() / max(mal.sum(), 1)),
                        "fpr": float(((sc > 70) & ~mal).sum() / max((~mal).sum(), 1))})
    cv = {"folds": cv_rows, "fnr_media": float(np.mean([r["fnr"] for r in cv_rows])),
          "fpr_media": float(np.mean([r["fpr"] for r in cv_rows]))}

    # Generalización a ataques NO vistos: se excluye un tipo de ataque del entrenamiento
    loko = {}
    if kinds is not None:
        K = np.array(kinds)
        for kind in sorted(set(K[Y != "legitimo"])):
            held = K == kind
            mk = RiskModel(clone(cands[best]).fit(M[~held], Y[~held]))
            sc = np.array([score(dict(zip(FEATURES, r)), mk)["score"] for r in M[held]])
            only_ml = np.array([100 * (1 - mk.proba(dict(zip(FEATURES, r)))["legitimo"]) for r in M[held]])
            loko[kind] = {"n": int(held.sum()), "detectados_puntaje_final": float((sc > 70).mean()),
                          "detectados_solo_modelo": float((only_ml > 70).mean())}
    rm.meta = {
        "task": "riesgo", "best_model": best, "comparison": comp,
        "split": {"train": int(len(y_tr)), "val": int(len(y_va)), "test": int(len(y_te))},
        "test_multiclase": multi, "average_precision": aps,
        "cuarentena_umbral_70": {"tp": tp, "fn": fn, "fp": fp, "tn": tn,
                                 "tasa_falsos_negativos": fnr, "tasa_falsos_positivos": fpr,
                                 "RNF3_cumple(<=5%)": fnr <= 0.05, "RNF4_cumple(<=10%)": fpr <= 0.10},
        "feature_importances_top15": importances,
        "validacion_cruzada_5": cv,
        "ataques_no_vistos": loko,
        "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    ev.save_json(rm.meta, out_dir / "riesgo_metricas.json")
    return rm
