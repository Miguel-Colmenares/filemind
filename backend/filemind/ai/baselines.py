"""Sistemas de referencia para el benchmark de FileMind (scripts/benchmark.py).

Todos tienen la misma interfaz (fit, predict, predict_proba) para medirlos igual:

- KeywordRules: reglas por palabras clave escritas a mano, sin IA. Es lo que haría
  un programa tradicional de organización de archivos.
- ZeroShotTfidf: IA mínima sin entrenamiento. Compara el documento con la
  descripción de cada categoría (similitud del coseno sobre TF-IDF). No usa
  ninguna etiqueta, solo el texto de la descripción.
- ZeroShotEmbeddings: modelo de lenguaje preentrenado pequeño y genérico
  (MiniLM multilingüe, 118 millones de parámetros) usado en modo zero-shot.
  Es opcional porque necesita ``sentence-transformers`` y descargar el modelo.

``fit`` en los dos zero-shot no mira las etiquetas; existe para que el benchmark
los trate igual que a los modelos supervisados.
"""
from __future__ import annotations

import re
from collections import Counter

import numpy as np

from ..domain.models import PROFILES
from .classifier import normalize

# Frases típicas de cada categoría, escritas a partir de la definición de cada tipo de
# proceso (no ajustadas con el conjunto de prueba). Van sin tildes, como el texto normalizado.
KEYWORDS: dict[str, dict[str, list[str]]] = {
    "constitucional": {
        "Tutela": ["accion de tutela", "tutela", "derecho fundamental", "derechos fundamentales", "accionante",
                   "accionado", "juez de instancia", "fallo de tutela", "amparo", "revision de tutela"],
        "Inconstitucionalidad": ["demanda de inconstitucionalidad", "accion publica de inconstitucionalidad",
                                 "inexequible", "exequible", "norma demandada", "cargo", "demandante",
                                 "inconstitucionalidad"],
        "Tratados": ["tratado", "convenio", "ley aprobatoria", "acuerdo entre", "protocolo", "canje de notas",
                     "instrumento internacional", "ratificacion"],
        "DecretosLegislativos": ["decreto legislativo", "estado de emergencia", "estado de excepcion",
                                 "conmocion interior", "emergencia economica", "decreto declaratorio"],
        "Objeciones": ["objeciones", "objecion", "proyecto de ley", "objeciones gubernamentales",
                       "objeciones presidenciales", "insistencia", "objeciones por inconstitucionalidad"],
    },
    "general": {
        "Academico": ["tarea", "taller", "universidad", "estudiante", "docente", "asignatura", "parcial"],
        "Informes": ["informe", "avance", "resultados", "conclusiones", "seguimiento"],
        "Facturas": ["factura", "subtotal", "iva", "nit", "total a pagar", "cliente"],
        "Contratos": ["contrato", "clausula", "contratista", "contratante", "obligaciones", "poliza"],
        "Reuniones": ["acta", "reunion", "asistentes", "orden del dia", "compromisos"],
        "Presentaciones": ["__fmt_pptx__", "diapositiva", "presentacion", "agenda"],
        "Financiero": ["presupuesto", "flujo de caja", "balance", "costos", "utilidad"],
        "Otros": [],
    },
}


class KeywordRules:
    """Cuenta las frases de cada categoría en el texto; gana la que más suma (frases largas pesan más)."""

    name = "Reglas por palabras clave"

    def __init__(self, perfil: str = "constitucional"):
        self.rules = {c: [normalize(k) for k in ks] for c, ks in KEYWORDS.get(perfil, {}).items()}
        self.classes_ = list(PROFILES[perfil])
        self.default = self.classes_[0]

    def fit(self, X, y):
        self.default = Counter(y).most_common(1)[0][0]  # sin coincidencias: la clase más común
        return self

    def _scores(self, x: str) -> np.ndarray:
        t = normalize(x)
        return np.array([sum(len(k.split()) * len(re.findall(r"\b" + re.escape(k) + r"\b", t))
                             for k in self.rules.get(c, [])) for c in self.classes_], dtype=float)

    def predict_proba(self, X) -> np.ndarray:
        out = []
        for x in X:
            s = self._scores(x)
            if s.sum() == 0:
                s = np.array([1.0 if c == self.default else 0.0 for c in self.classes_])
            out.append(s / s.sum())
        return np.array(out)

    def predict(self, X) -> np.ndarray:
        return np.array(self.classes_)[self.predict_proba(X).argmax(1)]


class ZeroShotTfidf:
    """Similitud entre el documento y la descripción de cada categoría, sin ejemplos etiquetados."""

    name = "Zero-shot TF-IDF (sin entrenamiento)"

    def __init__(self, perfil: str = "constitucional", temperature: float = 20.0):
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.desc = PROFILES[perfil]
        self.classes_ = list(self.desc)
        self.temperature = temperature
        self.vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)

    def fit(self, X, y=None):
        # El vocabulario se aprende del texto sin etiquetas más las descripciones
        self.vec.fit([normalize(x) for x in X] + [normalize(d) for d in self.desc.values()])
        self.D = self.vec.transform([normalize(f"{c} {d}") for c, d in self.desc.items()])
        return self

    def predict_proba(self, X) -> np.ndarray:
        sims = (self.vec.transform([normalize(x) for x in X]) @ self.D.T).toarray()
        e = np.exp(self.temperature * (sims - sims.max(1, keepdims=True)))
        return e / e.sum(1, keepdims=True)

    def predict(self, X) -> np.ndarray:
        return np.array(self.classes_)[self.predict_proba(X).argmax(1)]


class ZeroShotEmbeddings:
    """Modelo de lenguaje preentrenado (MiniLM multilingüe) en modo zero-shot."""

    name = "Zero-shot MiniLM multilingüe"
    model_id = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    def __init__(self, perfil: str = "constitucional", temperature: float = 20.0):
        from sentence_transformers import SentenceTransformer  # opcional
        self.desc = PROFILES[perfil]
        self.classes_ = list(self.desc)
        self.temperature = temperature
        self.model = SentenceTransformer(self.model_id, device="cpu")
        self.params = int(sum(p.numel() for p in self.model.parameters()))

    def fit(self, X=None, y=None):
        prompts = [f"Sentencia de la Corte Constitucional. {d}" for d in self.desc.values()]
        self.D = self.model.encode(prompts, normalize_embeddings=True)
        return self

    def predict_proba(self, X) -> np.ndarray:
        E = self.model.encode(list(X), normalize_embeddings=True, batch_size=16)
        sims = E @ self.D.T
        e = np.exp(self.temperature * (sims - sims.max(1, keepdims=True)))
        return e / e.sum(1, keepdims=True)

    def predict(self, X) -> np.ndarray:
        return np.array(self.classes_)[self.predict_proba(X).argmax(1)]
