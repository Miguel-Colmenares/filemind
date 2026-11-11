"""Inicio de sesión, usuarios (administración) y espacios de trabajo."""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ...infrastructure.accounts import AuthError
from ..deps import COOKIE, current_user, get_fm, optional_user, require_admin, session_token

router = APIRouter(prefix="/api", tags=["cuentas"])

# Freno por dirección IP además del bloqueo por cuenta: 20 intentos fallidos en 10 minutos.
_fails: dict[str, deque] = defaultdict(deque)
IP_WINDOW_S, IP_MAX_FAILS = 600, 20


def _ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def _throttle(ip: str) -> None:
    q = _fails[ip]
    while q and time.time() - q[0] > IP_WINDOW_S:
        q.popleft()
    if len(q) >= IP_MAX_FAILS:
        raise HTTPException(429, "Demasiados intentos desde este equipo. Espere unos minutos.")


def _open_session(request: Request, response: Response, user: dict) -> dict:
    acc = request.app.state.accounts
    token = acc.create_session(user["id"], _ip(request), request.headers.get("user-agent"))
    response.set_cookie(COOKIE, token, max_age=acc.session_hours * 3600, httponly=True, samesite="strict",
                        secure=request.url.scheme == "https", path="/")
    return _me(request, user)


def _me(request: Request, user: dict) -> dict:
    espacios = request.app.state.accounts.list_workspaces(user)
    return {"usuario": user, "espacios": [{"id": w["id"], "nombre": w["nombre"]} for w in espacios]}


# ----------------------------------------------------------------- sesión
class LoginIn(BaseModel):
    usuario: str = Field(..., max_length=64)
    contrasena: str = Field(..., max_length=256)


class SetupIn(BaseModel):
    usuario: str = Field(..., max_length=64)
    nombre: str = Field(..., max_length=120)
    contrasena: str = Field(..., max_length=256)


class PasswordIn(BaseModel):
    actual: str = Field(..., max_length=256)
    nueva: str = Field(..., max_length=256)


@router.get("/auth/estado")
def auth_state(request: Request, user=Depends(optional_user)):
    configured = request.app.state.accounts.count_users() > 0
    return {"configurado": configured, **(_me(request, user) if user else {"usuario": None, "espacios": []})}


@router.post("/auth/configurar")
def setup(body: SetupIn, request: Request, response: Response, fm=Depends(get_fm)):
    """Primer arranque: crea el administrador. Solo funciona mientras no exista ningún usuario."""
    acc = request.app.state.accounts
    if acc.count_users() > 0:
        raise HTTPException(409, "FileMind ya tiene administrador. Inicie sesión.")
    try:
        user = acc.create_user(body.usuario, body.nombre, body.contrasena, "admin")
    except ValueError as e:
        raise HTTPException(400, str(e))
    fm.audit.log("administrador_inicial_creado", usuario=user["username"], ip=_ip(request))
    return _open_session(request, response, user)


@router.post("/auth/entrar")
def login(body: LoginIn, request: Request, response: Response, fm=Depends(get_fm)):
    ip = _ip(request)
    _throttle(ip)
    try:
        user = request.app.state.accounts.authenticate(body.usuario, body.contrasena)
    except AuthError as e:
        _fails[ip].append(time.time())
        fm.audit.log("inicio_sesion_fallido", usuario=body.usuario.strip().lower()[:64], ip=ip, motivo=str(e))
        raise HTTPException(401, str(e))
    fm.audit.log("inicio_sesion", usuario=user["username"], ip=ip)
    return _open_session(request, response, user)


@router.post("/auth/salir")
def logout(request: Request, response: Response, fm=Depends(get_fm), user=Depends(optional_user)):
    request.app.state.accounts.end_session(session_token(request))
    response.delete_cookie(COOKIE, path="/")
    if user and not user.get("service"):
        fm.audit.log("cierre_sesion", usuario=user["username"], ip=_ip(request))
    return {"ok": True}


@router.get("/auth/yo")
def me(request: Request, user=Depends(current_user)):
    return _me(request, user)


@router.post("/auth/contrasena")
def change_password(body: PasswordIn, request: Request, response: Response, user=Depends(current_user),
                    fm=Depends(get_fm)):
    acc = request.app.state.accounts
    if user.get("service"):
        raise HTTPException(400, "El puente no tiene contraseña.")
    try:
        acc.authenticate(user["username"], body.actual)
    except AuthError:
        raise HTTPException(400, "La contraseña actual no es correcta.")
    try:
        acc.update_user(user["id"], password=body.nueva)  # cierra todas sus sesiones
    except ValueError as e:
        raise HTTPException(400, str(e))
    fm.audit.log("contrasena_cambiada", usuario=user["username"], ip=_ip(request))
    return _open_session(request, response, acc.get_user(user["id"]))


# ---------------------------------------------------------------- usuarios
class UserIn(BaseModel):
    usuario: str = Field(..., max_length=64)
    nombre: str = Field(..., max_length=120)
    contrasena: str = Field(..., max_length=256)
    rol: str = "miembro"


class UserPatch(BaseModel):
    nombre: str | None = Field(None, max_length=120)
    rol: str | None = None
    activo: bool | None = None
    contrasena: str | None = Field(None, max_length=256)


@router.get("/usuarios", dependencies=[Depends(require_admin)])
def list_users(request: Request):
    return request.app.state.accounts.list_users()


@router.post("/usuarios")
def create_user(body: UserIn, request: Request, admin=Depends(require_admin), fm=Depends(get_fm)):
    try:
        u = request.app.state.accounts.create_user(body.usuario, body.nombre, body.contrasena, body.rol)
    except ValueError as e:
        raise HTTPException(400, str(e))
    fm.audit.log("usuario_creado", usuario=u["username"], rol=u["role"], por=admin["username"])
    return u


@router.patch("/usuarios/{uid}")
def update_user(uid: int, body: UserPatch, request: Request, admin=Depends(require_admin), fm=Depends(get_fm)):
    if uid == admin.get("id") and (body.activo is False or (body.rol and body.rol != "admin")):
        raise HTTPException(400, "No puede quitarse a sí mismo el acceso de administrador.")
    try:
        u = request.app.state.accounts.update_user(uid, name=body.nombre, role=body.rol, active=body.activo,
                                                   password=body.contrasena)
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    cambios = [k for k, v in body.model_dump().items() if v is not None and k != "contrasena"]
    if body.contrasena:
        cambios.append("contrasena_restablecida")
    fm.audit.log("usuario_modificado", usuario=u["username"], cambios=cambios, por=admin["username"])
    return u


@router.delete("/usuarios/{uid}")
def delete_user(uid: int, request: Request, admin=Depends(require_admin), fm=Depends(get_fm)):
    if uid == admin.get("id"):
        raise HTTPException(400, "No puede eliminar su propia cuenta.")
    acc = request.app.state.accounts
    u = acc.get_user(uid)
    if not u:
        raise HTTPException(404, "Usuario no encontrado")
    try:
        acc.delete_user(uid)
    except ValueError as e:
        raise HTTPException(400, str(e))
    fm.audit.log("usuario_eliminado", usuario=u["username"], por=admin["username"])
    return {"ok": True}


# ------------------------------------------------------ espacios de trabajo
class WorkspaceIn(BaseModel):
    nombre: str = Field(..., max_length=80)
    descripcion: str = Field("", max_length=300)
    miembros: list[int] = []
    chats: list[str] = []
    categorias: list[str] = Field([], description="Etiquetas que se ven en el espacio (vacío = todas)")


@router.get("/espacios")
def list_workspaces(request: Request, user=Depends(current_user)):
    return request.app.state.accounts.list_workspaces(user)


@router.get("/espacios/chats-disponibles", dependencies=[Depends(require_admin)])
def available_chats(request: Request, fm=Depends(get_fm)):
    """Chats que se pueden asignar: los monitoreados, los que ya trajeron archivos y los que ve el puente."""
    seen = {r["group_name"] for r in fm.audit.list_files(None, 5000) if r.get("group_name")}
    wa = getattr(request.app.state, "whatsapp", None) or {}
    bridge = {c["nombre"] for c in wa.get("chats", [])}
    monitored = set(fm.groups)
    return [{"nombre": n, "monitoreado": n in monitored}
            for n in sorted(seen | bridge | monitored, key=str.lower)]


@router.post("/espacios")
def create_workspace(body: WorkspaceIn, request: Request, admin=Depends(require_admin), fm=Depends(get_fm)):
    try:
        w = request.app.state.accounts.save_workspace(None, body.nombre, body.descripcion, body.miembros, body.chats,
                                                      admin.get("id"), body.categorias)
    except ValueError as e:
        raise HTTPException(400, str(e))
    fm.audit.log("espacio_creado", espacio=w["nombre"], miembros=len(w["miembros"]), chats=w["chats"],
                 por=admin["username"])
    return w


@router.put("/espacios/{ws_id}")
def update_workspace(ws_id: int, body: WorkspaceIn, request: Request, admin=Depends(require_admin),
                     fm=Depends(get_fm)):
    try:
        w = request.app.state.accounts.save_workspace(ws_id, body.nombre, body.descripcion, body.miembros, body.chats,
                                                      categories=body.categorias)
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    fm.audit.log("espacio_modificado", espacio=w["nombre"], miembros=len(w["miembros"]), chats=w["chats"],
                 por=admin["username"])
    return w


@router.delete("/espacios/{ws_id}")
def delete_workspace(ws_id: int, request: Request, admin=Depends(require_admin), fm=Depends(get_fm)):
    acc = request.app.state.accounts
    w = acc.get_workspace(ws_id)
    if not w:
        raise HTTPException(404, "Espacio no encontrado")
    acc.delete_workspace(ws_id)
    fm.audit.log("espacio_eliminado", espacio=w["nombre"], por=admin["username"])
    return {"ok": True}
