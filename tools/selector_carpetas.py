"""Selector de carpetas de Windows para FileMind cuando la API corre en Docker.

Dentro de Docker no se puede abrir la ventana «Seleccionar carpeta» de Windows. Este programita
corre en el PC (fuera de Docker), escucha solo en 127.0.0.1:8765 y, cuando la página de FileMind
se lo pide, abre esa ventana y devuelve la ruta escogida (por ejemplo C:\\Users\\...\\Expedientes).
La API la traduce a la carpeta compartida con Docker.

    pythonw tools\\selector_carpetas.py        (sin ventana de consola)
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8765
# solo la página de FileMind puede pedir el selector
ORIGENES = {"http://127.0.0.1:8000", "http://localhost:8000"}
_lock = threading.Lock()


def elegir(titulo: str) -> str:
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.update()
    try:
        ruta = filedialog.askdirectory(parent=root, title=titulo, mustexist=False) or ""
    finally:
        root.destroy()
    return ruta.replace("/", "\\")


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        origin = self.headers.get("Origin", "")
        if origin in ORIGENES:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Private-Network", "true")

    def _json(self, code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/ping"):
            return self._json(200, {"ok": True})
        self._json(404, {"error": "no encontrado"})

    def do_POST(self):  # noqa: N802
        if not self.path.startswith("/elegir"):
            return self._json(404, {"error": "no encontrado"})
        if self.headers.get("Origin", "") not in ORIGENES:
            return self._json(403, {"error": "origen no permitido"})
        if not _lock.acquire(blocking=False):
            return self._json(409, {"error": "Ya hay una ventana de selección abierta."})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            titulo = (json.loads(self.rfile.read(n) or b"{}").get("titulo") if n else None) or "Escoge la carpeta para FileMind"
            self._json(200, {"ruta": elegir(titulo)})
        finally:
            _lock.release()

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
