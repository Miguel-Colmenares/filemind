"""Conector alterno por carpeta.

Útil para pruebas y para usar la carpeta de descargas de WhatsApp Desktop
(``WhatsApp/Media``) cuando no se quiere usar el puente no oficial. Cada
subcarpeta o la carpeta completa se asocia a un grupo.
"""
from __future__ import annotations

import time
from pathlib import Path


def watch_folder(fm, folder: Path, group: str, interval: float = 1.0, once: bool = False, stop=None, on_file=None):
    folder = Path(folder)
    seen: set[Path] = set(folder.glob("*")) if not once else set()
    fm.audit.log("conector_carpeta_iniciado", group=group, folder=str(folder))
    print(f"Vigilando {folder} como grupo '{group}' (Ctrl+C para salir)")
    while stop is None or not stop.is_set():
        for p in sorted(folder.glob("*")):
            if p in seen or not p.is_file() or p.name.startswith("."):
                continue
            size = -1
            while size != p.stat().st_size:  # esperar a que termine de copiarse
                size = p.stat().st_size
                time.sleep(0.2)
            seen.add(p)
            rec = fm.process(p.read_bytes(), p.name, group, message_ts=p.stat().st_mtime)
            if on_file:
                on_file(p, rec)
            if rec:
                print(f"{p.name}: {rec['status']} · riesgo {rec['risk_score']} · {rec.get('category')}")
        if once:
            return
        time.sleep(interval)
