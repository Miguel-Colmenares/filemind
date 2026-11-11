"""Salud, disponibilidad (RNF2), estadísticas y configuración."""
import time

from fastapi import APIRouter, Depends, Request

from ...domain.models import LABEL_DESCRIPTIONS, LABELS, category_label
from ..deps import current_user, get_fm, require_admin, scope

router = APIRouter(tags=["sistema"])


@router.get("/health")
def health(request: Request, fm=Depends(get_fm)):
    return {"ok": True, "uptime_s": round(time.time() - request.app.state.started, 1),
            "grupos": len(fm.groups), "modelo_tema": fm.topic.pipeline is not None,
            "modelo_riesgo": fm.risk_model.model is not None}


@router.get("/api/disponibilidad", dependencies=[Depends(current_user)])
def availability(request: Request):
    return request.app.state.uptime.report()


@router.get("/api/estadisticas")
def stats(fm=Depends(get_fm), groups=Depends(scope)):
    return {**fm.audit.stats(groups), "categorias": LABELS, "firmas": len(fm.signatures)}


@router.get("/api/estadisticas/serie")
def series(dias: int = 30, fm=Depends(get_fm), groups=Depends(scope)):
    """Archivos por día de los últimos ``dias`` días (7 a 180): estado, riesgo y categoría."""
    return {"dias": fm.audit.series(min(max(dias, 7), 180), groups), "categorias": LABELS}


@router.get("/api/categorias", dependencies=[Depends(current_user)])
def categories():
    return [{"nombre": c, "etiqueta": category_label(c), "descripcion": LABEL_DESCRIPTIONS[c]} for c in LABELS]


@router.get("/api/configuracion", dependencies=[Depends(require_admin)])
def config(request: Request):
    from ...security.sandbox import pick_backend
    s = request.app.state.settings
    return {**s.to_dict(), "sandbox_efectivo": pick_backend(s.sandbox_backend)}
