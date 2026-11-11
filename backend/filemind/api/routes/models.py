"""Métricas de los modelos de IA y reentrenamiento con retroalimentación."""
import json
import subprocess
import sys
import threading

from fastapi import APIRouter, Depends, HTTPException

from ...ai.health import VENTANA, model_health
from ...config import ROOT
from ..deps import current_user, get_fm, require_token

router = APIRouter(prefix="/api", tags=["modelos"])
_lock = threading.Lock()
_state = {"en_curso": False, "ultimo_error": None}


@router.get("/modelos", dependencies=[Depends(current_user)])
def models(fm=Depends(get_fm)):
    bench = ROOT / "reportes" / "benchmark.json"
    return {"tema": fm.topic.meta, "riesgo": fm.risk_model.meta,
            "correcciones_pendientes": len(fm.audit.feedback_rows()), "reentrenamiento": _state,
            "salud": model_health(fm.audit.list_files("clasificado", VENTANA), fm.topic.meta,
                                  fm.s.topic_min_confidence),
            "benchmark": json.loads(bench.read_text(encoding="utf-8")) if bench.exists() else None}


@router.post("/reentrenar", dependencies=[Depends(require_token)])
def retrain(fm=Depends(get_fm)):
    if not _lock.acquire(blocking=False):
        raise HTTPException(409, "Ya hay un reentrenamiento en curso")
    _state.update(en_curso=True, ultimo_error=None)

    def job():
        try:
            subprocess.run([sys.executable, str(ROOT / "scripts" / "entrenar.py"), "--solo", "tema"],
                           check=True, cwd=ROOT, capture_output=True)
            fm.reload_models()
            fm.audit.log("modelo_reentrenado", feedback=len(fm.audit.feedback_rows()))
        except Exception as e:  # se informa en /api/modelos
            _state["ultimo_error"] = str(e)
        finally:
            _state["en_curso"] = False
            _lock.release()
    threading.Thread(target=job, daemon=True).start()
    return {"iniciado": True, "correcciones": len(fm.audit.feedback_rows())}
