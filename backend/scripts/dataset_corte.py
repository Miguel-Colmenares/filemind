#!/usr/bin/env python3
"""Construye el dataset REAL del perfil "constitucional" a partir de sentencias de la Corte Constitucional.

Fuentes (públicas):
  * Texto completo: Hugging Face, Manuel/sentencias-corte-cons-colombia-1992-2021 (CC-BY-4.0),
    archivo Juris1992_2022.csv (23 750 sentencias, una por fila).
  * Etiqueta: datos.gov.co, conjunto v2k4-2t8s "Sentencias proferidas por la Corte Constitucional",
    columna ``proceso`` (tipo de proceso que originó la sentencia).

Cada sentencia se une con su etiqueta por la referencia (p. ej. T-001/21) que aparece al inicio del
texto. Luego se limpia (se borran las referencias y números de expediente, que delatarían la clase),
se recorta y se guarda como .txt en data/dataset_real/<Categoría>/. El muestreo es balanceado y con
semilla fija, así que el resultado es reproducible.

    python scripts/dataset_corte.py --csv ruta/Juris1992_2022.csv --por-clase 250 --fragmento 3000
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "dataset_real"
META_URL = ("https://www.datos.gov.co/resource/v2k4-2t8s.json?"
            "$select=sentencia,proceso,fecha_sentencia&$limit=50000")

# proceso (datos.gov.co) -> categoría de FileMind
CATEGORIA = {
    "Tutela": "Tutela",
    "Demanda de inconstitucionalidad": "Inconstitucionalidad",
    "Ley Aprobatoria de Tratado": "Tratados",
    "Tratado Internacional": "Tratados",
    "Decreto Legislativo": "DecretosLegislativos",
    "Objeción de Inconstitucionalidad": "Objeciones",
    "Objeción Gubernamental": "Objeciones",
}
REF = re.compile(r"\b(SU|T|C|A)\s*-\s*(\d{1,4})\s*[/-]\s*(\d{2,4})\b")
# referencias de sentencias y números de expediente (D-1234, T-7.654.321, RE-123, LAT-456, OG-12, OP-3, PE-1…)
LEAK = re.compile(r"\b(?:SU|T|C|A|D|RE|LAT|OG|OP|PE|RDL|RPZ|CRF|E|ICC|L)\s*-\s*\d[\d.]*(?:\s*/\s*\d+)?\b", re.I)
MAX_CHARS = 20000


def norm_ref(m) -> str:
    year = m.group(3)[-2:]
    return f"{m.group(1).upper()}-{int(m.group(2)):03d}/{year}"


def load_meta() -> dict:
    with urllib.request.urlopen(META_URL, timeout=120) as r:
        rows = json.load(r)
    meta = {}
    for row in rows:
        m = REF.search(row.get("sentencia", ""))
        if m and row.get("proceso") in CATEGORIA:
            meta[norm_ref(m)] = {"proceso": row["proceso"], "fecha": row.get("fecha_sentencia", "")[:10]}
    return meta


def clean(text: str) -> str:
    t = LEAK.sub(" ", text)
    t = re.sub(r"(?m)^\s*[-/]\s*\d{2,4}\b", " ", t)  # restos de referencias partidas en dos líneas
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()


def fragment(t: str, n: int) -> str:
    """Toma ``n`` caracteres del cuerpo, desde un tercio del texto, cortando en palabras completas.

    Se evita el encabezado y los descriptores iniciales porque nombran literalmente el tipo de
    proceso (ACCIÓN DE TUTELA, Revisión de constitucionalidad del Decreto Legislativo…), y se imita
    el caso real de un fragmento de sentencia reenviado por WhatsApp.
    """
    if not n:
        return t[:MAX_CHARS]
    a = len(t) // 3
    a = t.find(" ", a) + 1
    frag = t[a:a + n]
    return frag[:frag.rfind(" ")].strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--por-clase", type=int, default=250)
    ap.add_argument("--semilla", type=int, default=42)
    ap.add_argument("--fragmento", type=int, default=3000, help="caracteres por documento; 0 = texto completo")
    a = ap.parse_args()

    print("[1] etiquetas oficiales de datos.gov.co…")
    meta = load_meta()
    print(f"    {len(meta)} sentencias con proceso conocido")

    print("[2] uniendo con los textos completos…")
    csv.field_size_limit(sys.maxsize if sys.maxsize < 2**31 else 2**31 - 1)
    pool = defaultdict(list)
    sin_ref = sin_meta = total = 0
    with open(a.csv, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            total += 1
            text = row.get("Texto") or ""
            m = REF.search(text[:400])
            if not m:
                sin_ref += 1
                continue
            ref = norm_ref(m)
            info = meta.get(ref)
            if not info:
                sin_meta += 1
                continue
            pool[CATEGORIA[info["proceso"]]].append((ref, info, text))
    print(f"    sin referencia legible {sin_ref}, sin etiqueta {sin_meta}")
    for c, v in pool.items():
        print(f"    {c:22s} {len(v)} disponibles")

    print("[3] muestreo balanceado, limpieza y escritura…")
    rng = random.Random(a.semilla)
    manifest = []
    for cat, items in sorted(pool.items()):
        items = sorted(items, key=lambda t: t[0])
        rng.shuffle(items)
        d = OUT / cat
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("*.txt"):
            old.unlink()
        for i, (ref, info, text) in enumerate(items[:a.por_clase]):
            name = f"{cat.lower()}_{i:03d}.txt"
            (d / name).write_text(fragment(clean(text), a.fragmento), encoding="utf-8")
            manifest.append({"archivo": f"{cat}/{name}", "categoria": cat, "sentencia": ref,
                             "proceso": info["proceso"], "fecha": info["fecha"]})
    (OUT / "manifiesto.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    usados = Counter(m["categoria"] for m in manifest)
    fechas = sorted(m["fecha"] for m in manifest)
    fuente = {
        "descripcion": "Sentencias reales de la Corte Constitucional de Colombia",
        "texto": "Hugging Face, conjunto Manuel/sentencias-corte-cons-colombia-1992-2021 (licencia CC-BY-4.0)",
        "etiquetas": "datos.gov.co, conjunto oficial Sentencias proferidas por la Corte Constitucional (columna proceso)",
        "sentencias_publicadas": total, "con_etiqueta_oficial": len(meta),
        "descartadas_sin_referencia": sin_ref, "descartadas_sin_etiqueta": sin_meta,
        "disponibles": {c: len(v) for c, v in sorted(pool.items())}, "usadas": dict(sorted(usados.items())),
        "total_usadas": len(manifest), "desde": fechas[0], "hasta": fechas[-1],
        "fragmento_caracteres": a.fragmento, "por_clase_max": a.por_clase, "semilla": a.semilla,
    }
    (OUT / "fuente.json").write_text(json.dumps(fuente, ensure_ascii=False, indent=1), encoding="utf-8")
    print("    ", dict(Counter(m["categoria"] for m in manifest)))
    print(f"listo: {len(manifest)} documentos en {OUT}")


if __name__ == "__main__":
    main()
