"""Dependencias compartidas por los routers: servicio, sesión, roles y alcance de los datos.

Quién puede llamar a la API:
- Una persona con sesión iniciada (cookie HttpOnly ``fm_session`` o ``Authorization: Bearer``).
- El puente de WhatsApp, con el token de servicio en ``X-FileMind-Token``. Cuenta como
  administrador técnico; el token sale de ``api_token`` en config.json o se genera solo
  en ``data/api_token.txt`` la primera vez.
"""
from __future__ import annotations

import hmac

from fastapi import Depends, Header, HTTPException, Request

from ..services.analysis_service import FileMind

COOKIE = "fm_session"
SERVICE_USER = {"id": 0, "username": "puente", "name": "Puente de WhatsApp", "role": "admin", "service": True}


def get_fm(request: Request) -> FileMind:
    return request.app.state.fm


def session_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(COOKIE)


def optional_user(request: Request, x_filemind_token: str | None = Header(default=None)) -> dict | None:
    token = request.app.state.service_token
    if x_filemind_token and token and hmac.compare_digest(x_filemind_token, token):
        return SERVICE_USER
    return request.app.state.accounts.user_for_token(session_token(request))


def current_user(user: dict | None = Depends(optional_user)) -> dict:
    if not user:
        raise HTTPException(401, "Inicie sesión para continuar.")
    return user


def require_admin(user: dict = Depends(current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(403, "Solo un administrador puede hacer esto.")
    return user


# Compatibilidad: las rutas que antes pedían el token compartido ahora piden un administrador
# (persona con rol admin o el puente con su token de servicio).
require_token = require_admin


def scope(request: Request, espacio: int | None = None, user: dict = Depends(current_user)) -> set[str] | None:
    """Chats visibles para el usuario (``None`` = todos). ``espacio`` limita a un espacio de trabajo."""
    try:
        return request.app.state.accounts.visible_groups(user, espacio)
    except PermissionError as e:
        raise HTTPException(403, str(e))


def in_scope(rec: dict | None, groups: set[str] | None) -> bool:
    if not rec:
        return False
    if groups is None:
        return True
    if hasattr(groups, "allows"):  # espacios que además filtran por etiquetas
        return groups.allows(rec)
    return rec.get("group_name") in groups
