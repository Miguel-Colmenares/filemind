"""Almacenamiento: biblioteca por categorías, duplicados y cuarentena (RF8).

La cuarentena **impide la apertura directa**: el archivo se guarda cifrado
(AES-128 Fernet) con extensión ``.fmq``, permisos 0400 dentro de una
carpeta 0700 y sin su extensión original. Solo la acción explícita de
liberación (con motivo, registrada en auditoría) lo descifra.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from cryptography.fernet import Fernet


def safe_name(name: str) -> str:
    name = re.sub(r"[‪-‮⁦-⁩‎‏]", "", name)
    name = re.sub(r"[^\w.\- ()áéíóúÁÉÍÓÚñÑ]", "_", name).strip(" .")
    return name[:150] or "archivo"


class Storage:
    def __init__(self, library: Path, quarantine: Path):
        self.library, self.quarantine = Path(library), Path(quarantine)
        self.library.mkdir(parents=True, exist_ok=True)
        self.quarantine.mkdir(parents=True, exist_ok=True)
        os.chmod(self.quarantine, 0o700)
        key_path = self.quarantine / ".clave"
        if not key_path.exists():
            key_path.write_bytes(Fernet.generate_key())
            os.chmod(key_path, 0o400)
        self._fernet = Fernet(key_path.read_bytes())

    def store(self, data: bytes, name: str, category: str, sha256: str) -> Path:
        folder = self.library / category
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / safe_name(name)
        if target.exists():
            target = folder / f"{target.stem}_{sha256[:8]}{target.suffix}"
        target.write_bytes(data)
        os.chmod(target, 0o644)
        return target

    def quarantine_file(self, data: bytes, name: str, sha256: str, report: dict) -> Path:
        target = self.quarantine / f"{sha256}.fmq"
        if target.exists():
            os.chmod(target, 0o600)
        target.write_bytes(self._fernet.encrypt(data))
        os.chmod(target, 0o400)
        meta = self.quarantine / f"{sha256}.json"
        meta.write_text(json.dumps({"original_name": name, **report}, ensure_ascii=False, default=str),
                        encoding="utf-8")
        os.chmod(meta, 0o600)
        return target

    def release(self, sha256: str, category: str) -> Path:
        src = self.quarantine / f"{sha256}.fmq"
        meta = json.loads((self.quarantine / f"{sha256}.json").read_text(encoding="utf-8"))
        data = self._fernet.decrypt(src.read_bytes())
        dest = self.store(data, meta["original_name"], category, sha256)
        os.chmod(src, 0o600)
        src.unlink()
        return dest

    def delete_quarantined(self, sha256: str) -> None:
        for ext in (".fmq", ".json"):
            p = self.quarantine / f"{sha256}{ext}"
            if p.exists():
                os.chmod(p, 0o600)
                p.unlink()

    def move(self, path: Path, category: str) -> Path:
        folder = self.library / category
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / Path(path).name
        shutil.move(str(path), dest)
        return dest
