"""Encender el puente de WhatsApp desde FileMind.

El puente (``whatsapp-gateway``, Node.js) es un programa aparte: si nadie lo enciende, la
página de Chats muestra «Puente apagado». FileMind puede lanzarlo como proceso sin ventana,
con su salida en ``data/whatsapp-gateway.log``. Nunca lanza dos: guarda el número de proceso
en ``data/whatsapp-gateway.pid`` y antes de lanzar comprueba que no haya uno vivo, ni un
Chrome del puente usando la carpeta de la sesión (por si se encendió a mano).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from ..config import ROOT

GATEWAY_DIR = ROOT.parent / "whatsapp-gateway"
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0          # CREATE_NO_WINDOW
NEW_GROUP = 0x00000200 if sys.platform == "win32" else 0          # CREATE_NEW_PROCESS_GROUP


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _session_browser_running() -> bool:
    """Chrome sin ventana con la carpeta de sesión del puente (puente encendido a mano)."""
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


def running(data_dir: Path) -> bool:
    pid_file = Path(data_dir) / "whatsapp-gateway.pid"
    try:
        if _alive(int(pid_file.read_text().strip())):
            return True
    except (OSError, ValueError):
        pass
    return _session_browser_running()


def available() -> str | None:
    """Motivo por el que no se puede encender (o None si se puede)."""
    if not shutil.which("node"):
        return "Node.js no está instalado en este PC."
    if not (GATEWAY_DIR / "index.js").exists():
        return "No se encontró la carpeta whatsapp-gateway."
    if not (GATEWAY_DIR / "node_modules").exists():
        return "Faltan las dependencias del puente: ejecute «npm install» en whatsapp-gateway."
    return None


def start(data_dir: Path) -> int:
    """Lanza el puente sin ventana. Devuelve el número de proceso."""
    why = available()
    if why:
        raise RuntimeError(why)
    data_dir = Path(data_dir)
    log = open(data_dir / "whatsapp-gateway.log", "a", encoding="utf-8")
    p = subprocess.Popen([shutil.which("node"), "index.js"], cwd=GATEWAY_DIR, stdout=log, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, creationflags=NO_WINDOW | NEW_GROUP)
    (data_dir / "whatsapp-gateway.pid").write_text(str(p.pid))
    return p.pid
