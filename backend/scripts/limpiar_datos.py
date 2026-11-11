#!/usr/bin/env python3
"""Deja FileMind sin archivos (por ejemplo, para empezar de cero en un equipo nuevo).

Borra la lista de archivos, la cuarentena, la actividad y el registro de mensajes importados.
Conserva usuarios, chats monitoreados, espacios, la carpeta del bufete y los modelos.
Antes de borrar guarda un respaldo de la base y mueve los documentos a data/respaldo_<carpeta>.

Con Docker (con el servicio detenido para no chocar con la API):
    docker compose stop filemind
    docker compose run --rm --no-deps filemind python scripts/limpiar_datos.py
    docker compose start filemind
"""
from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"


def main():
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    c = sqlite3.connect(DATA / "filemind.db")
    bk = sqlite3.connect(DATA / f"respaldo_{stamp}.db")
    c.backup(bk)
    bk.close()
    for t in ("files", "file_search", "imported", "bufete_saved", "events"):
        try:
            print(f"{t}: {c.execute(f'DELETE FROM {t}').rowcount} filas borradas")
        except sqlite3.OperationalError:
            pass
    c.commit()
    c.execute("VACUUM")
    c.close()
    for d in ("biblioteca", "cuarentena", "inbox"):
        p = DATA / d
        if p.is_dir() and any(p.iterdir()):
            shutil.move(str(p), str(DATA / f"respaldo_{d}_{stamp}"))
            p.mkdir()
    print(f"Listo. Respaldo en data/respaldo_{stamp}.db")


if __name__ == "__main__":
    main()
