"""Salud del modelo temático en uso (detección simple de deriva).

El modelo se evaluó con un conjunto de prueba; en uso real llegan documentos que
pueden ser distintos (otro vocabulario, otros formatos). Sin etiquetas no se puede
medir la exactitud real, pero sí dos señales que la anticipan:

- la confianza media de los últimos archivos frente a la que tuvo en la prueba, y
- el porcentaje de archivos que el modelo no se atrevió a clasificar (van a revisión).

Si la confianza cae o la revisión sube, el vocabulario cambió y conviene corregir
algunos archivos y reentrenar. Es la alarma que pide ISO/IEC 42001 para la
evaluación continua del modelo.
"""
from __future__ import annotations

import numpy as np

VENTANA = 200            # últimos archivos que se miran
MIN_ARCHIVOS = 10        # con menos, la señal es ruido
CAIDA_VIGILAR, CAIDA_REENTRENAR = 0.07, 0.15
REVISION_VIGILAR, REVISION_REENTRENAR = 10.0, 25.0


def model_health(rows: list[dict], meta: dict, min_conf: float = 0.35) -> dict:
    rows = [r for r in rows[:VENTANA] if r.get("category_confidence") is not None]
    ref = (meta.get("calibracion") or {}).get("confianza_media")
    base = {"referencia_prueba": ref, "ventana": VENTANA, "archivos": len(rows)}
    if len(rows) < 1:
        return {**base, "estado": "sin_datos", "mensaje": "Aún no hay archivos clasificados para medir."}
    conf = np.array([float(r["category_confidence"]) for r in rows])
    review = float(np.mean([(c < min_conf) or r.get("category") == "Otros" for c, r in zip(conf, rows)]) * 100)
    mean = float(conf.mean())
    drop = (ref - mean) if ref is not None else 0.0
    por_cat: dict[str, int] = {}
    for r in rows:
        por_cat[r.get("category") or "Otros"] = por_cat.get(r.get("category") or "Otros", 0) + 1
    if len(rows) < MIN_ARCHIVOS:
        estado, msg = "estable", f"Solo hay {len(rows)} archivo(s); se necesita al menos {MIN_ARCHIVOS} para juzgar."
    elif drop > CAIDA_REENTRENAR or review > REVISION_REENTRENAR:
        estado = "reentrenar"
        msg = (f"La confianza media bajó a {mean:.2f} y el {review:.0f} % va a revisión. Los documentos que llegan "
               "ya no se parecen a los del entrenamiento: corrija algunos y reentrene.")
    elif drop > CAIDA_VIGILAR or review > REVISION_VIGILAR:
        estado = "vigilar"
        msg = f"La confianza media es {mean:.2f} y el {review:.0f} % va a revisión. Conviene revisar las correcciones."
    else:
        estado, msg = "estable", f"Confianza media {mean:.2f}, {review:.0f} % a revisión. El modelo se comporta como en la prueba."
    return {**base, "estado": estado, "mensaje": msg, "confianza_media": round(mean, 4),
            "confianza_p10": round(float(np.percentile(conf, 10)), 4), "caida": round(drop, 4),
            "revision_pct": round(review, 1), "por_categoria": por_cat}
