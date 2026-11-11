"""Carpeta del bufete: copia de los archivos seguros en una carpeta del equipo, una subcarpeta por etiqueta.

El administrador escoge una carpeta del PC (el servidor corre en el mismo equipo) y FileMind
crea dentro una subcarpeta por cada etiqueta (por ejemplo «Tutela» o «Tratados internacionales»).
Cada archivo clasificado se copia a la subcarpeta de su etiqueta; si alguien corrige la
etiqueta, la copia se mueve a la subcarpeta nueva. Los archivos en cuarentena nunca se copian.

Por archivo se registra si ya está en la carpeta y dónde, y al consultarlo se comprueba que el
archivo siga existiendo (si alguien lo borró del PC vuelve a figurar como «falta guardar»).
La configuración y el registro viven en la misma base SQLite de la auditoría.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from ..domain.models import LABELS, LABEL_DESCRIPTIONS, category_label
from .repository import AuditStore, now_iso
from .storage import safe_name

SCHEMA = """
CREATE TABLE IF NOT EXISTS bufete_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bufete_saved (
    sha256 TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    category TEXT,
    saved_at TEXT NOT NULL
);
"""

# Estado de un archivo frente a la carpeta del bufete
SAVED, MISSING, QUARANTINE, NO_FOLDER = "guardado", "falta", "cuarentena", "sin_carpeta"


class BufeteFolder:
    def __init__(self, audit: AuditStore):
        self.audit = audit
        self._conn, self._lock = audit._conn, audit._lock
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # ------------------------------------------------------------ configuración
    def config(self) -> dict:
        with self._lock:
            row = self._conn.execute("SELECT value FROM bufete_config WHERE key = 'config'").fetchone()
        raw = json.loads(row[0]) if row else {}
        subs = raw.get("subcarpetas") or {}
        return {"ruta": raw.get("ruta") or "", "auto": bool(raw.get("auto", True)),
                "subcarpetas": {c: subs.get(c) or category_label(c) for c in self.categories()}}

    def categories(self) -> list[str]:
        """Etiquetas del perfil activo más las que ya tienen archivos (p. ej. de un perfil anterior)."""
        with self._lock:
            used = [r[0] for r in self._conn.execute(
                "SELECT DISTINCT category FROM files WHERE status = 'clasificado' AND category IS NOT NULL")]
        return LABELS + sorted(c for c in used if c not in LABELS)

    def set_config(self, ruta: str | None = None, auto: bool | None = None,
                   subcarpetas: dict[str, str] | None = None, crear: bool = False) -> dict:
        cfg = self.config()
        if ruta is not None:
            ruta = to_server_path(ruta.strip().strip('"'))
            if ruta:
                root = Path(ruta).expanduser()
                if not root.is_absolute():
                    raise ValueError("Escriba la ruta completa de la carpeta, por ejemplo C:\\Users\\...\\Documentos\\Bufete")
                if not root.exists():
                    if not crear:
                        raise FileNotFoundError("Esa carpeta no existe todavía.")
                    root.mkdir(parents=True, exist_ok=True)
                elif not root.is_dir():
                    raise ValueError("Esa ruta es un archivo, no una carpeta.")
                ruta = str(root)
            cfg["ruta"] = ruta
        if auto is not None:
            cfg["auto"] = bool(auto)
        if subcarpetas:
            for cat, name in subcarpetas.items():
                if cat in cfg["subcarpetas"]:
                    clean = safe_name((name or "").strip()) if (name or "").strip() else category_label(cat)
                    cfg["subcarpetas"][cat] = clean
            names = [n.lower() for n in cfg["subcarpetas"].values()]
            if len(names) != len(set(names)):
                raise ValueError("Dos etiquetas no pueden usar la misma subcarpeta.")
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO bufete_config(key, value) VALUES ('config', ?)",
                               (json.dumps(cfg, ensure_ascii=False),))
            self._conn.commit()
        return self.config()

    @property
    def root(self) -> Path | None:
        ruta = self.config()["ruta"]
        return Path(ruta) if ruta else None

    @property
    def auto(self) -> bool:
        cfg = self.config()
        return bool(cfg["ruta"]) and cfg["auto"]

    def subfolder(self, category: str | None) -> str:
        return self.config()["subcarpetas"].get(category or "Otros") or category_label(category)

    def view(self) -> dict:
        """Configuración con cada etiqueta, su subcarpeta y si ya existe en el equipo."""
        cfg = self.config()
        root = Path(cfg["ruta"]) if cfg["ruta"] else None
        cats = []
        for c in self.categories():
            sub = cfg["subcarpetas"][c]
            cats.append({"nombre": c, "etiqueta": category_label(c), "descripcion": LABEL_DESCRIPTIONS.get(c, ""),
                         "subcarpeta": sub, "ruta": str(root / sub) if root else None,
                         "existe": bool(root and (root / sub).is_dir())})
        return {**cfg, "ruta_pc": pc_path(cfg["ruta"]), "carpeta_existe": bool(root and root.is_dir()), "categorias": cats}

    def create_folders(self) -> list[str]:
        root = self.root
        if not root:
            raise ValueError("Primero escoja la carpeta del bufete.")
        root.mkdir(parents=True, exist_ok=True)
        made = []
        for c in self.categories():
            p = root / self.subfolder(c)
            if not p.is_dir():
                p.mkdir(parents=True, exist_ok=True)
                made.append(p.name)
        return made

    # ------------------------------------------------------- estado por archivo
    def _saved_rows(self, shas: list[str] | None = None) -> dict[str, dict]:
        with self._lock:
            if shas is None:
                rows = self._conn.execute("SELECT * FROM bufete_saved").fetchall()
            else:
                rows = []
                for i in range(0, len(shas), 500):
                    part = shas[i:i + 500]
                    rows += self._conn.execute(
                        f"SELECT * FROM bufete_saved WHERE sha256 IN ({','.join('?' * len(part))})", part).fetchall()
        return {r["sha256"]: dict(r) for r in rows}

    def status_many(self, recs: list[dict]) -> dict[str, dict]:
        """sha256 -> {estado, ruta, subcarpeta} para una lista de archivos."""
        cfg = self.config()
        root = Path(cfg["ruta"]) if cfg["ruta"] else None
        saved = self._saved_rows([r["sha256"] for r in recs])
        return {r["sha256"]: self._status(r, saved.get(r["sha256"]), root, cfg["subcarpetas"]) for r in recs}

    def status(self, rec: dict) -> dict:
        return self.status_many([rec])[rec["sha256"]]

    @staticmethod
    def _status(rec: dict, saved: dict | None, root: Path | None, subs: dict[str, str]) -> dict:
        if rec.get("status") != "clasificado":
            return {"estado": QUARANTINE if rec.get("status") == "cuarentena" else "no_aplica", "ruta": None,
                    "subcarpeta": None}
        cat = rec.get("category") or "Otros"
        sub = subs.get(cat) or category_label(cat)
        # una copia en una carpeta anterior (antes de «Cambiar carpeta») no cuenta como guardada
        if saved and root and _inside(Path(saved["path"]), root) and Path(saved["path"]).is_file():
            return {"estado": SAVED, "ruta": saved["path"], "subcarpeta": Path(saved["path"]).parent.name}
        return {"estado": MISSING if root else NO_FOLDER, "ruta": None, "subcarpeta": sub}

    def summary(self, recs: list[dict]) -> dict:
        st = self.status_many(recs)
        counts = {SAVED: 0, MISSING: 0, QUARANTINE: 0, NO_FOLDER: 0}
        for v in st.values():
            counts[v["estado"]] = counts.get(v["estado"], 0) + 1
        cfg = self.config()
        return {"configurada": bool(cfg["ruta"]), "ruta": cfg["ruta"], "ruta_pc": pc_path(cfg["ruta"]), "auto": self.auto,
                "guardados": counts[SAVED], "faltan": counts[MISSING] + counts[NO_FOLDER],
                "cuarentena": counts[QUARANTINE], "total": len(recs)}

    # ----------------------------------------------------------------- copiar
    def save(self, rec: dict) -> dict:
        """Copia (o mueve, si cambió la etiqueta) el archivo a la subcarpeta de su etiqueta."""
        root = self.root
        if not root:
            raise ValueError("Primero escoja la carpeta del bufete en Configuración.")
        if rec.get("status") != "clasificado":
            raise ValueError("Los archivos en cuarentena no se guardan en la carpeta del bufete.")
        src = Path(rec.get("stored_path") or "")
        if not src.is_file():
            raise FileNotFoundError("FileMind ya no tiene la copia de este archivo.")
        target_dir = root / self.subfolder(rec.get("category"))
        prev = self._saved_rows([rec["sha256"]]).get(rec["sha256"])
        prev_path = Path(prev["path"]) if prev and _inside(Path(prev["path"]), root) else None
        if prev_path and prev_path.is_file() and prev_path.parent == target_dir:
            return self.status(rec)  # ya está donde debe
        target_dir.mkdir(parents=True, exist_ok=True)
        target = self._free_name(target_dir, src.name, rec["sha256"])
        if prev_path and prev_path.is_file():
            shutil.move(str(prev_path), target)  # cambió la etiqueta: se mueve, no se duplica
            action = "movido"
        else:
            shutil.copy2(src, target)
            action = "copiado"
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO bufete_saved(sha256, path, category, saved_at) VALUES (?,?,?,?)",
                               (rec["sha256"], str(target), rec.get("category"), now_iso()))
            self._conn.commit()
        self.audit.log("guardado_en_carpeta_bufete", rec["sha256"], rec.get("group_name"), ruta=str(target),
                       accion=action, categoria=rec.get("category"))
        return self.status(rec)

    @staticmethod
    def _free_name(folder: Path, name: str, sha256: str) -> Path:
        """Nunca sobrescribe: si el nombre ya existe se agrega un sufijo."""
        target = folder / safe_name(name)
        if not target.exists():
            return target
        stem, suf = target.stem, target.suffix
        cand = folder / f"{stem} ({sha256[:6]}){suf}"
        n = 2
        while cand.exists():
            cand = folder / f"{stem} ({sha256[:6]}-{n}){suf}"
            n += 1
        return cand

    def save_pending(self, recs: list[dict], limit: int | None = None) -> dict:
        """Guarda los archivos que faltan (hasta ``limit``). Devuelve cuántos y en qué subcarpetas."""
        if not self.root:
            raise ValueError("Primero escoja la carpeta del bufete.")
        st = self.status_many(recs)
        pending = [r for r in recs if st[r["sha256"]]["estado"] in (MISSING, NO_FOLDER)]
        batch = pending[:limit] if limit else pending
        done, errors, per_folder = 0, [], {}
        for r in batch:
            try:
                s = self.save(r)
                done += 1
                per_folder[s["subcarpeta"]] = per_folder.get(s["subcarpeta"], 0) + 1
            except (OSError, ValueError) as e:
                errors.append({"sha256": r["sha256"], "nombre": r.get("original_name"), "motivo": str(e)})
        return {"guardados": done, "errores": errors, "por_carpeta": per_folder,
                "restantes": len(pending) - done - len(errors), "carpeta": str(self.root)}

    def on_classified(self, rec: dict) -> None:
        """Guardado automático al clasificar, liberar o corregir la etiqueta de un archivo."""
        if not rec or rec.get("status") != "clasificado":
            return
        prev = self._saved_rows([rec["sha256"]]).get(rec["sha256"])
        has_copy = bool(prev and self.root and _inside(Path(prev["path"]), self.root))
        if not (self.auto or has_copy):
            return
        try:
            self.save(rec)
        except (OSError, ValueError) as e:  # la carpeta del PC no debe frenar el análisis
            self.audit.log("error_carpeta_bufete", rec["sha256"], rec.get("group_name"), motivo=str(e))


def _inside(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError):
        return False


def list_dir(path: str | None) -> dict:
    """Explorador de carpetas del servidor (respaldo cuando no hay diálogo nativo)."""
    if not path:
        if os.name == "nt":
            drives = [f"{d}:\\" for d in "CDEFGHIJKLMNOPQRSTUVWXYZ" if Path(f"{d}:\\").exists()]
            home = Path.home()
            return {"ruta": "", "padre": None, "carpetas": [
                {"nombre": n, "ruta": str(p)} for n, p in
                [("Documentos", home / "Documents"), ("Escritorio", home / "Desktop"), ("Mi usuario", home)]
                if p.is_dir()] + [{"nombre": d, "ruta": d} for d in drives]}
        # En Docker solo se ven las carpetas del PC montadas en el contenedor (docker-compose.yml).
        shared = [(m, label) for m, label in _docker_mounts() if Path(m).is_dir()]
        if shared:
            names = {"/pc": "Mi PC", "/bufete": "Carpeta del bufete"}
            items = []
            # accesos directos como en Windows: Escritorio, Documentos y Descargas del usuario
            m = re.match(r"(?i)^[a-z]:\\users\\[^\\]+", dict(_docker_mounts()).get("/bufete", ""))
            if m:
                try:
                    home = Path(to_server_path(m.group(0)))
                    for n, sub in (("Escritorio", "Desktop"), ("Documentos", "Documents"), ("Descargas", "Downloads")):
                        if (home / sub).is_dir():
                            items.append({"nombre": n, "ruta": str(home / sub), "ruta_pc": pc_path(str(home / sub))})
                except ValueError:
                    pass
            items += [{"nombre": f"{names.get(m, m)} ({label.rstrip(chr(92)) or m})", "ruta": m, "ruta_pc": pc_path(m)}
                      for m, label in shared]
            return {"ruta": "", "padre": None, "nativo": False, "carpetas": items}
        path = "/"
    p = Path(to_server_path(path)).expanduser()
    if not p.is_dir():
        raise FileNotFoundError("Esa carpeta no existe.")
    try:
        subs = sorted((c for c in p.iterdir() if c.is_dir() and not c.name.startswith((".", "$"))),
                      key=lambda c: c.name.lower())[:400]
    except PermissionError:
        subs = []
    parent = str(p.parent) if p.parent != p else ""
    if os.name != "nt" and str(p) in {m for m, _ in _docker_mounts()}:
        parent = ""   # subir desde una carpeta compartida vuelve al inicio, no a la raíz del contenedor
    return {"ruta": str(p), "ruta_pc": pc_path(str(p)), "padre": parent, "nativo": os.name == "nt",
            "carpetas": [{"nombre": c.name, "ruta": str(c), "ruta_pc": pc_path(str(c))} for c in subs]}


def _docker_mounts() -> list[tuple[str, str]]:
    """Carpetas del PC montadas en Docker y cómo se llaman en Windows (FILEMIND_*_LABEL)."""
    def win(s: str) -> str:
        return s.replace("/", "\\") if s else ""
    return [(os.environ.get("FILEMIND_PC_DIR", "/pc"), win(os.environ.get("FILEMIND_PC_LABEL", ""))),
            (os.environ.get("FILEMIND_BUFETE_DIR", "/bufete"), win(os.environ.get("FILEMIND_BUFETE_LABEL", "")))]


def to_server_path(path: str) -> str:
    """Traduce una ruta de Windows (C:\\Users\\...) a la carpeta montada en Docker (/pc/Users/...).

    En Windows o con rutas que no son de Windows la deja igual. Si la ruta es de Windows pero no
    está dentro de ninguna carpeta compartida con Docker, explica qué hacer.
    """
    if not path or os.name == "nt" or not re.match(r"^[A-Za-z]:[\\/]?", path):
        return path
    norm = path.replace("/", "\\").rstrip("\\").lower()
    best = None
    for mount, label in _docker_mounts():
        lab = label.rstrip("\\").lower()
        if lab and (norm == lab or norm.startswith(lab + "\\")) and (best is None or len(lab) > len(best[1])):
            best = (mount, lab)
    if not best:
        raise ValueError("Esa carpeta no está compartida con Docker. Escógela con el botón «Escoger carpeta» "
                         "o agrégala en FILEMIND_PC_HOST del archivo .env.")
    rest = path.replace("/", "\\").rstrip("\\")[len(best[1]):].strip("\\").replace("\\", "/")
    return f"{best[0]}/{rest}" if rest else best[0]


def pc_path(path: str) -> str:
    """Ruta tal como se ve en el PC (p. ej. /pc/Users/x → C:\\Users\\x). Vacía si no aplica."""
    if not path or os.name == "nt":
        return ""
    for mount, label in _docker_mounts():
        if label and (path == mount or path.startswith(mount + "/")):
            rest = path[len(mount):].lstrip("/").replace("/", "\\")
            return label.rstrip("\\") + "\\" + rest if rest else label
    return ""
