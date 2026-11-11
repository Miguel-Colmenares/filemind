"""Exportación de los archivos de un chat de WhatsApp (RF9 a RF11).

La interfaz crea el trabajo y consulta su avance; el puente de WhatsApp toma
los trabajos pendientes, publica la lista de adjuntos y los sube uno por uno.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..deps import require_token

router = APIRouter(prefix="/api/exportaciones", tags=["exportaciones"])
ANALYSIS_TIMEOUT_S = 120   # muy por encima del límite de 15 s de RNF1; solo corta archivos que se traban


def get_ex(request: Request):
    return request.app.state.exports


class ExportIn(BaseModel):
    chat_id: str
    chat_nombre: str
    completo: bool = Field(False, description="True = ignorar lo ya importado y procesar todo el chat de nuevo")


class ItemIn(BaseModel):
    msg_id: str | None = None
    huella: str | None = Field(None, description="SHA-256 del archivo según WhatsApp (hex), para omitir repetidos")
    nombre: str | None = None
    tipo: str | None = None
    tamano: int | None = None
    remitente: str | None = None
    fecha: float | None = None


class ItemsIn(BaseModel):
    items: list[ItemIn]


class ItemStateIn(BaseModel):
    estado: str = Field(..., pattern="^(descargando|error|omitido)$")
    motivo: str | None = None


class FailIn(BaseModel):
    motivo: str


class SaveIn(BaseModel):
    destino: str = Field(..., min_length=2)


def _404(fn, *a):
    try:
        return fn(*a)
    except (KeyError, IndexError) as e:
        raise HTTPException(404, str(e).strip("'"))


@router.post("", dependencies=[Depends(require_token)])
def create(body: ExportIn, ex=Depends(get_ex)):
    return ex.view(ex.create(body.chat_id, body.chat_nombre, body.completo)["id"])


@router.get("", dependencies=[Depends(require_token)])
def list_jobs(ex=Depends(get_ex)):
    return ex.list()


@router.get("/historial", dependencies=[Depends(require_token)])
def history(chat_id: str, ex=Depends(get_ex)):
    return ex.history(chat_id)


@router.get("/pendiente", dependencies=[Depends(require_token)])
def pending(ex=Depends(get_ex)):
    return {"trabajo": ex.next_pending()}


@router.get("/{job_id}", dependencies=[Depends(require_token)])
def detail(job_id: str, ex=Depends(get_ex)):
    return _404(ex.view, job_id)


@router.post("/{job_id}/cancelar", dependencies=[Depends(require_token)])
def cancel(job_id: str, ex=Depends(get_ex)):
    return _404(ex.cancel, job_id)


@router.post("/{job_id}/items", dependencies=[Depends(require_token)])
def items(job_id: str, body: ItemsIn, ex=Depends(get_ex)):
    return _404(ex.set_items, job_id, [i.model_dump() for i in body.items])


@router.post("/{job_id}/items/{idx}/estado", dependencies=[Depends(require_token)])
def item_state(job_id: str, idx: int, body: ItemStateIn, ex=Depends(get_ex)):
    return _404(ex.item_state, job_id, idx, body.estado, body.motivo)


@router.post("/{job_id}/items/{idx}/archivo", dependencies=[Depends(require_token)])
async def item_file(job_id: str, idx: int, file: UploadFile = File(...), remitente: str = Form(""),
                    message_ts: float | None = Form(None), ex=Depends(get_ex)):
    data = await file.read()
    # El análisis es bloqueante: se ejecuta en el grupo de hilos del servicio y se espera sin
    # bloquear el servidor. Antes, fut.result() dentro de una ruta async congelaba toda la API
    # mientras un archivo se analizaba, y un Excel que tardó de más la dejó sin responder.
    fut = ex.fm.pool.submit(ex.analyze, job_id, idx, data, file.filename or "", remitente or None, message_ts)
    try:
        it = await asyncio.wait_for(asyncio.wrap_future(fut), timeout=ANALYSIS_TIMEOUT_S)
    except (KeyError, IndexError) as e:
        raise HTTPException(404, str(e))
    except asyncio.TimeoutError:
        it = _404(ex.item_state, job_id, idx, "error",
                  f"El análisis tardó más de {ANALYSIS_TIMEOUT_S} s y se saltó para no detener la cola.")
    return {"item": it, "estado_trabajo": ex.get(job_id)["estado"]}


@router.post("/{job_id}/error", dependencies=[Depends(require_token)])
def fail(job_id: str, body: FailIn, ex=Depends(get_ex)):
    return _404(ex.fail, job_id, body.motivo)


@router.post("/{job_id}/guardar", dependencies=[Depends(require_token)])
def save(job_id: str, body: SaveIn, ex=Depends(get_ex)):
    try:
        return ex.save_to(job_id, body.destino)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except (ValueError, OSError) as e:
        raise HTTPException(400, f"No se pudo guardar en esa carpeta: {e}")


@router.get("/{job_id}/zip", dependencies=[Depends(require_token)])
def download_zip(job_id: str, ex=Depends(get_ex)):
    data, name = _404(ex.zip_bytes, job_id)
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


# El servidor corre en el mismo equipo del usuario, así que puede abrir el
# selector de carpetas nativo (versión web). La app de escritorio usa el suyo.
PICKER = ("import tkinter as tk\nfrom tkinter import filedialog\nr = tk.Tk(); r.withdraw(); "
          "r.attributes('-topmost', True)\nprint(filedialog.askdirectory(title='Carpeta donde FileMind "
          "guardará los archivos seguros', mustexist=False) or '')")


@router.post("/elegir-carpeta", dependencies=[Depends(require_token)], include_in_schema=False)
def pick_folder_route():
    return pick_folder()


def pick_folder() -> dict:
    try:
        out = subprocess.run([sys.executable, "-c", PICKER], capture_output=True, text=True, timeout=600,
                             encoding="utf-8")
    except (OSError, subprocess.TimeoutExpired):
        raise HTTPException(500, "No se pudo abrir el selector de carpetas; escribe la ruta a mano.")
    path = out.stdout.strip()
    return {"ruta": path.replace("/", "\\") if sys.platform == "win32" else path}
