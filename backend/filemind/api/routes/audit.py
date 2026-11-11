"""Trazabilidad (RNF8) y notificaciones (RNF7)."""
from fastapi import APIRouter, Depends

from ..deps import get_fm, require_admin, scope

router = APIRouter(prefix="/api", tags=["auditoría"])


@router.get("/eventos", dependencies=[Depends(require_admin)])
def events(sha: str | None = None, limite: int = 200, fm=Depends(get_fm)):
    return fm.audit.events(sha, limite)


@router.get("/auditoria/retencion", dependencies=[Depends(require_admin)])
def retention(fm=Depends(get_fm)):
    return fm.audit.retention_report()


@router.get("/notificaciones")
def notifications(desde: int = 0, fm=Depends(get_fm), groups=Depends(scope)):
    items = fm.notifier.pending(desde)
    if groups is None:
        return items
    return [n for n in items if not isinstance(n, dict) or n.get("group") in groups]
