"""Carpeta del bufete: dónde se guardan en el PC los archivos seguros, una subcarpeta por etiqueta."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ...infrastructure.bufete import list_dir, to_server_path
from ...infrastructure.storage import safe_name
from ..deps import get_fm, require_admin, scope
from .exports import pick_folder

router = APIRouter(prefix="/api/bufete", tags=["carpeta del bufete"])
LOCAL = {"127.0.0.1", "::1", "localhost", "testclient"}


class BufeteIn(BaseModel):
    ruta: str | None = None
    auto: bool | None = None
    subcarpetas: dict[str, str] | None = None
    crear: bool = False       # crear la carpeta si no existe
    preparar: bool = False    # crear de una vez las subcarpetas de las etiquetas


class NuevaCarpetaIn(BaseModel):
    ruta: str
    nombre: str


@router.get("", dependencies=[Depends(require_admin)])
def get_config(fm=Depends(get_fm)):
    return fm.bufete.view()


@router.put("")
def put_config(body: BufeteIn, admin=Depends(require_admin), fm=Depends(get_fm)):
    try:
        fm.bufete.set_config(body.ruta, body.auto, body.subcarpetas, body.crear)
        made = fm.bufete.create_folders() if body.preparar and fm.bufete.root else []
    except FileNotFoundError as e:
        raise HTTPException(409, str(e))
    except (ValueError, OSError) as e:
        raise HTTPException(400, f"No se pudo usar esa carpeta: {e}")
    cfg = fm.bufete.config()
    fm.audit.log("carpeta_bufete_configurada", ruta=cfg["ruta"], auto=cfg["auto"], por=admin.get("username"),
                 subcarpetas_creadas=made)
    return {**fm.bufete.view(), "creadas": made}


@router.post("/crear-carpetas", dependencies=[Depends(require_admin)])
def create_folders(fm=Depends(get_fm)):
    try:
        made = fm.bufete.create_folders()
    except (ValueError, OSError) as e:
        raise HTTPException(400, str(e))
    return {**fm.bufete.view(), "creadas": made}


@router.post("/elegir-carpeta", dependencies=[Depends(require_admin)])
def choose(request: Request):
    """Abre el diálogo de Windows para escoger carpeta. Solo si la página se usa en el mismo PC del servidor."""
    host = request.client.host if request.client else ""
    if host not in LOCAL:
        raise HTTPException(409, "El selector de Windows solo se abre en el PC donde corre FileMind.")
    return pick_folder()


@router.get("/explorar", dependencies=[Depends(require_admin)])
def explore(ruta: str = ""):
    try:
        return list_dir(ruta)
    except (OSError, ValueError) as e:
        raise HTTPException(400, str(e))


@router.post("/nueva-carpeta", dependencies=[Depends(require_admin)])
def new_folder(body: NuevaCarpetaIn):
    name = safe_name(body.nombre.strip()) if body.nombre.strip() else ""
    if not name:
        raise HTTPException(400, "Escriba el nombre de la carpeta nueva.")
    try:
        parent = Path(to_server_path(body.ruta))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not parent.is_absolute() or not parent.is_dir():
        raise HTTPException(400, "Esa carpeta no existe.")
    try:
        (parent / name).mkdir(exist_ok=True)
    except OSError as e:
        raise HTTPException(400, f"No se pudo crear: {e}")
    return list_dir(str(parent / name))


@router.get("/resumen")
def summary(fm=Depends(get_fm), groups=Depends(scope)):
    """Cuántos archivos ya están en la carpeta del bufete y cuántos faltan (según lo que ve el usuario)."""
    return fm.bufete.summary(fm.audit.list_files(None, 100000, groups))


@router.post("/guardar-pendientes")
def save_pending(limite: int = 25, fm=Depends(get_fm), groups=Depends(scope)):
    """Guarda en sus subcarpetas los archivos que faltan, de a ``limite`` para mostrar el avance."""
    try:
        r = fm.bufete.save_pending(fm.audit.list_files("clasificado", 100000, groups), max(1, min(limite, 500)))
    except ValueError as e:
        raise HTTPException(409, str(e))
    if r["guardados"]:
        fm.audit.log("carpeta_bufete_pendientes_guardados", archivos=r["guardados"], por_carpeta=r["por_carpeta"])
    return r
