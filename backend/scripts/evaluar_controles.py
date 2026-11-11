#!/usr/bin/env python3
"""Mide qué cambió en la detección al agregar los controles de ciberseguridad.

    python scripts/evaluar_controles.py

Evalúa dos conjuntos de muestras inertes con el protocolo completo (fases 1-4):

* ``data/dataset/seguridad``: el dataset original (700 archivos con los que se
  entrenó el modelo de riesgo).
* ``data/dataset/seguridad_controles``: técnicas que el dataset original no
  cubre (comprimidos, políglotas, RTF, PDF con adjuntos, contrabando HTML, XLM…)
  más casos legítimos difíciles. Se regenera en cada ejecución.

Para cada archivo calcula el puntaje SIN los controles nuevos ("antes") y CON
ellos ("después"), tanto solo por reglas (lo que se detecta aunque el modelo
nunca haya visto el ataque) como el puntaje final (reglas + IA). Guarda
``reportes/controles_metricas.json``.
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from filemind.config import load_settings                                  # noqa: E402
from filemind.infrastructure.extract import extract                        # noqa: E402
from filemind.security.controls import run_controls                        # noqa: E402
from filemind.security.heuristic import run_heuristic                      # noqa: E402
from filemind.security.risk import RiskModel, build_vector, score          # noqa: E402
from filemind.security.samples import generate_control_dataset             # noqa: E402
from filemind.security.sandbox import run_sandbox, sandbox_features        # noqa: E402
from filemind.security.signatures import SignatureRepository               # noqa: E402
from filemind.security.static import run_static                            # noqa: E402

REPORTS = ROOT / "reportes"


def evaluate(item: dict, base: Path, sigs, rm) -> dict:
    data = (base / item["path"]).read_bytes()
    t0 = time.perf_counter()
    st = run_static(data, item["name"], sigs)
    ex = extract(data, st["real_type"])
    heur = run_heuristic(data, st["real_type"], ex["text"], ex["urls"])
    ctl = run_controls(data, item["name"], st, ex, sigs)
    sbx = run_sandbox(data, item["name"], "auto", 8.0)
    sf, _ = sandbox_features(sbx)
    before = score(build_vector(st, heur["features"], sf), rm)
    after = score(build_vector(st, heur["features"], sf, ctl["features"]), rm)
    return {**item, "seconds": round(time.perf_counter() - t0, 3),
            "rules_before": before["rule_score"], "rules_after": after["rule_score"],
            "final_before": before["score"], "final_after": after["score"],
            "controls": {c["id"]: c["estado"] for c in ctl["controls"]},
            "errors": [f"{c['id']}: {c['resumen']}" for c in ctl["controls"] if c["estado"] == "error"]}


def summarize(rows: list[dict]) -> dict:
    groups: dict[tuple, list] = defaultdict(list)
    for r in rows:
        groups[(r["label"], r["kind"])].append(r)
    out = {}
    for (label, kind), rs in sorted(groups.items()):
        n = len(rs)
        pct = lambda key, thr: round(sum(r[key] > thr for r in rs) / n, 3)    # noqa: E731
        trig = Counter(cid for r in rs for cid, e in r["controls"].items() if e in ("alerta", "aviso"))
        out[f"{label}/{kind}"] = {
            "n": n,
            "cuarentena_antes": pct("final_before", 70), "cuarentena_despues": pct("final_after", 70),
            "solo_reglas_cuarentena_antes": pct("rules_before", 70), "solo_reglas_cuarentena_despues": pct("rules_after", 70),
            "solo_reglas_aviso_o_mas_antes": pct("rules_before", 39), "solo_reglas_aviso_o_mas_despues": pct("rules_after", 39),
            "reglas_media_antes": round(sum(r["rules_before"] for r in rs) / n, 1),
            "reglas_media_despues": round(sum(r["rules_after"] for r in rs) / n, 1),
            "controles_que_alertaron": dict(trig.most_common()),
            "segundos_max": max(r["seconds"] for r in rs),
            "errores": sorted({e for r in rs for e in r["errors"]}),
        }
    return out


def binary(rows: list[dict], key: str) -> dict:
    mal = [r for r in rows if r["label"] != "legitimo"]
    leg = [r for r in rows if r["label"] == "legitimo"]
    return {"falsos_negativos": round(sum(r[key] <= 70 for r in mal) / max(len(mal), 1), 3),
            "falsos_positivos": round(sum(r[key] > 70 for r in leg) / max(len(leg), 1), 3),
            "maliciosos": len(mal), "legitimos": len(leg)}


def main():
    s = load_settings()
    sigs = SignatureRepository(s.data_dir / "firmas_malware.txt")
    rm = RiskModel.load(s.models_dir / "riesgo.joblib")
    original = s.data_dir / "dataset" / "seguridad"
    nuevo = s.data_dir / "dataset" / "seguridad_controles"
    print("[controles] generando muestras inertes de técnicas nuevas…")
    items_new = generate_control_dataset(nuevo)
    (nuevo / "manifiesto.json").write_text(json.dumps(items_new, ensure_ascii=False, indent=1), encoding="utf-8")
    items_orig = json.loads((original / "manifiesto.json").read_text(encoding="utf-8"))
    result = {"generado": time.strftime("%Y-%m-%d %H:%M:%S")}
    for name, base, items in (("dataset_original", original, items_orig), ("tecnicas_nuevas", nuevo, items_new)):
        t0 = time.time()
        with ThreadPoolExecutor(8) as pool:
            rows = list(pool.map(lambda it: evaluate(it, base, sigs, rm), items))
        result[name] = {
            "por_tipo": summarize(rows),
            "global_final": {"antes": binary(rows, "final_before"), "despues": binary(rows, "final_after")},
            "global_solo_reglas": {"antes": binary(rows, "rules_before"), "despues": binary(rows, "rules_after")},
            "segundos_max_por_archivo": max(r["seconds"] for r in rows),
        }
        print(f"\n== {name} ({len(rows)} archivos, {time.time() - t0:.1f} s)")
        print(f"{'tipo':38s} {'n':>3s}  cuarentena antes→después   solo reglas antes→después   aviso+ (reglas)")
        for k, v in result[name]["por_tipo"].items():
            print(f"{k:38s} {v['n']:3d}  {v['cuarentena_antes']:6.0%} → {v['cuarentena_despues']:<6.0%}"
                  f"          {v['solo_reglas_cuarentena_antes']:6.0%} → {v['solo_reglas_cuarentena_despues']:<6.0%}"
                  f"          {v['solo_reglas_aviso_o_mas_antes']:5.0%} → {v['solo_reglas_aviso_o_mas_despues']:.0%}"
                  + (f"   ERRORES {v['errores']}" if v["errores"] else ""))
        g = result[name]
        print(f"FN/FP final:       antes {g['global_final']['antes']}  después {g['global_final']['despues']}")
        print(f"FN/FP solo reglas: antes {g['global_solo_reglas']['antes']}  después {g['global_solo_reglas']['despues']}")
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "controles_metricas.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nGuardado en {REPORTS / 'controles_metricas.json'}")


if __name__ == "__main__":
    main()
