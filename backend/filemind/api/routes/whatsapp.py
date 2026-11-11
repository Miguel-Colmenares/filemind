"""Vinculación con WhatsApp: el puente publica aquí su estado, el QR y la lista de chats.

La interfaz lo lee para mostrar el código QR de vinculación y dejar escoger
qué chats se analizan (la selección se guarda como grupos monitoreados, RF1).
El estado vive en memoria: si la API se reinicia, el puente lo vuelve a enviar.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ..deps import current_user, get_fm, require_admin, require_token

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])


class EstadoIn(BaseModel):
    estado: str = Field(..., description="iniciando | esperando_qr | conectado | reconectando | desconectado")
    qr: str | None = Field(None, description="Imagen del QR como data URL (solo en esperando_qr)")
    cuenta: str | None = None
    reintento_en_s: int | None = Field(None, description="Segundos para el siguiente intento (reconectando)")
    salud: dict | None = Field(None, description="Reconexiones, fallas seguidas, último error y archivos en cola")


class Chat(BaseModel):
    id: str
    nombre: str
    grupo: bool = False


class ChatsIn(BaseModel):
    chats: list[Chat]


def _state(request: Request) -> dict:
    st = getattr(request.app.state, "whatsapp", None)
    if st is None:
        st = request.app.state.whatsapp = {"estado": "sin_puente", "qr": None, "cuenta": None,
                                           "actualizado": None, "chats": []}
    return st


@router.get("", dependencies=[Depends(require_token)])
def get_whatsapp(request: Request, fm=Depends(get_fm)):
    st = _state(request)
    # Si el puente deja de reportar, la interfaz no debe mostrar un QR viejo
    if st["actualizado"] and time.time() - st["actualizado"] > 90:
        st.update(estado="sin_puente", qr=None)
    monitored = set(fm.groups)
    chats = [{**c, "monitoreado": c["nombre"] in monitored} for c in st["chats"]]
    return {**st, "chats": chats}


@router.get("/conexion", dependencies=[Depends(current_user)])
def get_conexion(request: Request):
    """Estado liviano para el aviso de conexión de la barra superior (sin QR ni lista de chats)."""
    st = _state(request)
    if st["actualizado"] and time.time() - st["actualizado"] > 90:
        st.update(estado="sin_puente", qr=None)
    return {"estado": st["estado"], "cuenta": st.get("cuenta"), "conectado": st["estado"] == "conectado"}


@router.post("/estado", dependencies=[Depends(require_token)])
def post_estado(body: EstadoIn, request: Request):
    st = _state(request)
    st.update(estado=body.estado, qr=body.qr if body.estado == "esperando_qr" else None,
              cuenta=body.cuenta or (st["cuenta"] if body.estado == "conectado" else None),
              reintento_en_s=body.reintento_en_s, salud=body.salud or st.get("salud"), actualizado=time.time())
    # el puente recoge aquí las órdenes de la interfaz (p. ej. desvincular el número)
    return {"ok": True, "accion": st.pop("accion", None)}


@router.post("/desvincular")
def unlink(request: Request, user: dict = Depends(require_admin), fm=Depends(get_fm)):
    """Cierra la sesión de WhatsApp del puente para vincular otro número con un QR nuevo."""
    st = _state(request)
    if st["estado"] == "sin_puente":
        from fastapi import HTTPException
        raise HTTPException(409, "El puente de WhatsApp no está corriendo.")
    st.update(accion="desvincular", estado="iniciando", qr=None, cuenta=None, chats=[])
    fm.audit.log("whatsapp_desvinculado", por=user.get("username"))
    return {"ok": True}


@router.post("/chats", dependencies=[Depends(require_token)])
def post_chats(body: ChatsIn, request: Request):
    st = _state(request)
    st["chats"] = sorted((c.model_dump() for c in body.chats), key=lambda c: (not c["grupo"], c["nombre"].lower()))
    st["actualizado"] = time.time()
    return {"ok": True, "chats": len(st["chats"])}


LOCAL = {"127.0.0.1", "::1", "localhost"}


@router.post("/encender")
def start_bridge(request: Request, user: dict = Depends(require_admin), fm=Depends(get_fm)):
    """Enciende el puente de WhatsApp en este PC (solo administrador y desde el mismo PC)."""
    from fastapi import HTTPException
    from ...infrastructure import gateway
    host = request.client.host if request.client else ""
    if host not in LOCAL:
        raise HTTPException(409, "El puente solo se puede encender desde el PC donde corre FileMind.")
    st = _state(request)
    data_dir = request.app.state.settings.data_dir
    recent = st["actualizado"] and time.time() - st["actualizado"] < 45
    if recent or gateway.running(data_dir):
        return {"ok": True, "ya_encendido": True}
    try:
        pid = gateway.start(data_dir)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    st.update(estado="iniciando", qr=None, actualizado=time.time())
    fm.audit.log("puente_whatsapp_encendido", por=user.get("username"), pid=pid)
    return {"ok": True, "pid": pid}
