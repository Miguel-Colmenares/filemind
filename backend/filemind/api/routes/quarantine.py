"""Cuarentena (RF8): listado, liberación controlada y eliminación."""
from fastapi import APIRouter, Depends, HTTPException

from ...domain.models import LABELS, FileStatus
from ..deps import get_fm, require_admin, require_token
from ..schemas import ReleaseIn

router = APIRouter(prefix="/api/cuarentena", tags=["cuarentena"])


@router.post("/{sha}/liberar", dependencies=[Depends(require_token)])
def release(sha: str, body: ReleaseIn, fm=Depends(get_fm), admin=Depends(require_admin)):
    if not body.confirmar:
        raise HTTPException(400, "Debe confirmar la liberación.")
    if body.categoria not in LABELS:
        raise HTTPException(400, "Categoría inválida")
    try:
        return fm.release(sha, body.categoria, body.motivo, admin.get("username", "admin"))
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.delete("/{sha}", dependencies=[Depends(require_token)])
def delete_quarantined(sha: str, fm=Depends(get_fm)):
    rec = fm.audit.get_file(sha)
    if not rec or rec["status"] != FileStatus.QUARANTINED:
        raise HTTPException(404, "No está en cuarentena")
    fm.storage.delete_quarantined(sha)
    fm.audit.upsert_file({"sha256": sha, "status": FileStatus.DELETED.value, "stored_path": None})
    fm.audit.log("eliminado_de_cuarentena", sha, rec["group_name"])
    return {"ok": True}
