"""FileMind como aplicación de escritorio.

    python -m filemind escritorio

Abre la misma interfaz web en una ventana nativa (pywebview, que en Windows usa
el motor Edge WebView2 ya incluido en el sistema). Por dentro arranca la API y
el puente de WhatsApp si no estaban corriendo, y al cerrar la ventana detiene
solo lo que ella misma arrancó. La versión web sigue igual en
http://127.0.0.1:8000.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from .config import ROOT

HOST, PORT = "127.0.0.1", 8000
URL = f"http://{HOST}:{PORT}"
GATEWAY_DIR = ROOT.parent / "whatsapp-gateway"
LOG_DIR = ROOT / "data"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _get(path: str, timeout: float = 1.5) -> dict | None:
    try:
        with urllib.request.urlopen(URL + path, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _start_api():
    """Arranca uvicorn en un hilo; devuelve el servidor para poder detenerlo."""
    import uvicorn
    from .api.app import create_app
    server = uvicorn.Server(uvicorn.Config(create_app(), host=HOST, port=PORT, log_level="warning"))
    threading.Thread(target=server.run, name="filemind-api", daemon=True).start()
    for _ in range(120):
        if _get("/health"):
            return server
        time.sleep(0.25)
    raise RuntimeError("La API de FileMind no arrancó en 30 s")


def _gateway_running() -> bool:
    """El puente usa un Chrome sin ventana con su propia carpeta de sesión: si existe, ya está corriendo."""
    if sys.platform != "win32":
        return False
    cmd = ("Get-CimInstance Win32_Process -Filter \"name='chrome.exe'\" | "
           "Where-Object { $_.CommandLine -like '*wwebjs_auth*' } | Measure-Object | % Count")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True,
                             timeout=15, creationflags=NO_WINDOW)
        return int((out.stdout or "0").strip() or 0) > 0
    except Exception:
        return False


def _start_gateway():
    node = shutil.which("node")
    if not node or not (GATEWAY_DIR / "node_modules").exists() or _gateway_running():
        return None
    log = open(LOG_DIR / "puente_whatsapp.log", "a", encoding="utf-8")
    return subprocess.Popen([node, "index.js"], cwd=GATEWAY_DIR, stdout=log, stderr=subprocess.STDOUT,
                            creationflags=NO_WINDOW)


class Api:
    """Funciones de Python que la interfaz puede llamar como ``window.pywebview.api.*``."""

    def __init__(self):
        self._window = None  # privado: pywebview no expone a JS lo que empieza por _

    def elegir_carpeta(self) -> str:
        import webview
        kind = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or webview.FOLDER_DIALOG
        res = self._window.create_file_dialog(kind)
        return (res[0] if isinstance(res, (list, tuple)) else res) or ""

    def abrir_carpeta(self, ruta: str) -> bool:
        if ruta and Path(ruta).is_dir():
            os.startfile(ruta) if sys.platform == "win32" else subprocess.Popen(["xdg-open", ruta])
            return True
        return False


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None or sys.stderr is None:  # pythonw.exe no tiene consola
        sys.stdout = sys.stderr = open(LOG_DIR / "escritorio.log", "a", encoding="utf-8", buffering=1)
    import webview

    server = None if _get("/health") else _start_api()
    gateway = _start_gateway()

    api = Api()
    api._window = webview.create_window("FileMind", URL, js_api=api, width=1360, height=880,
                                       min_size=(960, 640), background_color="#141414")
    webview.settings["ALLOW_DOWNLOADS"] = True
    try:
        webview.start(private_mode=False, storage_path=str(LOG_DIR / "escritorio_webview"))
    finally:
        if gateway and gateway.poll() is None:
            if sys.platform == "win32":  # también cierra el Chrome sin ventana que abre el puente
                subprocess.run(["taskkill", "/PID", str(gateway.pid), "/T", "/F"], capture_output=True,
                               creationflags=NO_WINDOW)
            else:
                gateway.terminate()
        if server:
            server.should_exit = True
            time.sleep(1)


if __name__ == "__main__":
    main()
