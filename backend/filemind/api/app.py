"""Fábrica de la aplicación FastAPI.

La API expone los casos de uso de la capa de servicios y, si existe
``frontend/dist`` (``npm run build``), sirve también la interfaz web en ``/``.
Documentación interactiva de la API: ``/docs``.
"""
from __future__ import annotations

import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..config import ROOT, Settings, load_settings
from ..infrastructure.accounts import Accounts
from ..infrastructure.uptime import UptimeMonitor
from ..services.analysis_service import FileMind
from ..services.export_service import ExportManager
from .routes import audit, bufete, cuentas, exports, files, groups, models, quarantine, system, whatsapp

FRONTEND_DIST = ROOT.parent / "frontend" / "dist"


def service_token(s: Settings) -> str:
    """Token del puente de WhatsApp: ``api_token`` de config.json o uno aleatorio guardado en data/api_token.txt."""
    if s.api_token:
        return s.api_token
    path = Path(s.data_dir) / "api_token.txt"
    if path.exists() and path.read_text(encoding="utf-8").strip():
        return path.read_text(encoding="utf-8").strip()
    token = secrets.token_urlsafe(32)
    path.write_text(token, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return token


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or load_settings()
    fm = FileMind(s)
    up = UptimeMonitor(s.data_dir / "uptime.log")

    @asynccontextmanager
    async def lifespan(_app):
        up.start()
        fm.audit.log("servicio_iniciado", groups=fm.groups, sandbox=s.sandbox_backend)
        fm.audit.purge_expired()
        yield
        up.stop()
        fm.audit.log("servicio_detenido")

    app = FastAPI(title="FileMind API", version="2.0.0", lifespan=lifespan,
                  description="Verificación de seguridad y clasificación inteligente de archivos de WhatsApp")
    app.state.fm, app.state.settings, app.state.uptime = fm, s, up
    app.state.accounts = Accounts(fm.audit, s.session_hours)
    app.state.service_token = service_token(s)
    app.state.exports = ExportManager(fm)
    app.state.started = time.time()

    @app.middleware("http")
    async def security_headers(request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if request.url.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    for r in (cuentas, system, groups, files, quarantine, models, audit, whatsapp, exports, bufete):
        app.include_router(r.router)

    reports = ROOT / "reportes"
    reports.mkdir(exist_ok=True)
    app.mount("/reportes", StaticFiles(directory=reports), name="reportes")

    if FRONTEND_DIST.exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith(("api/", "docs", "openapi")):
                raise HTTPException(404, "No encontrado")
            target = FRONTEND_DIST / path
            if path and target.is_file():
                return FileResponse(target)
            # Sin caché: así el navegador siempre toma la versión recién compilada de la interfaz.
            return FileResponse(FRONTEND_DIST / "index.html", headers={"Cache-Control": "no-cache"})
    else:
        @app.get("/", include_in_schema=False, response_class=HTMLResponse)
        def no_frontend():
            return ("<h1>FileMind API</h1><p>La interfaz no está compilada. Ejecute "
                    "<code>npm install && npm run build</code> en <code>frontend/</code> "
                    "o use <code>npm run dev</code>. Documentación de la API en <a href='/docs'>/docs</a>.</p>")
    return app
