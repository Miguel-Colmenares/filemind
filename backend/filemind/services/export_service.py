"""Exportación de un chat de WhatsApp (RF9 a RF11).

El usuario escoge un chat y pulsa "Exportar archivos". FileMind crea un trabajo
y el puente de WhatsApp, que consulta los trabajos pendientes, lee el historial
del chat, publica la lista de adjuntos y los sube **uno por uno**. Cada archivo
pasa por el protocolo completo (huella, fases 1 a 4, cuarentena o clasificación)
antes de pedir el siguiente, así la cola avanza en orden y se ve en la interfaz.

Al terminar, los archivos seguros se pueden descargar (ZIP) o guardar en una
carpeta del equipo escogida por el usuario, organizados en subcarpetas por
categoría. Los riesgosos siguen en la cuarentena cifrada y nunca se copian.

Importación incremental: cada mensaje importado queda registrado (chat, id del
mensaje, huella). Al volver a exportar el mismo chat, los mensajes ya importados
y los archivos cuya huella SHA-256 ya está en FileMind se marcan como omitidos
**antes de descargarlos**, así solo viajan los archivos nuevos. Con
``completo=True`` se ignora ese registro y se procesa todo de nuevo.
"""
from __future__ import annotations

import io
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path

from ..domain.models import CATEGORY_LABELS, category_label
from ..infrastructure.repository import now_iso
from ..infrastructure.storage import safe_name

# Nombre de la subcarpeta en el equipo del usuario para cada categoría (el mismo de toda la app)
FOLDER_LABEL = CATEGORY_LABELS

ITEM_DONE = {"seguro", "cuarentena", "error", "omitido"}
SKIP_REASON = {
    "ya_importado": "Ya se importó en una exportación anterior de este chat.",
    "misma_huella": "FileMind ya tiene este mismo archivo (misma huella SHA-256), no se vuelve a descargar.",
}


def _hex64(value) -> str | None:
    """Huella SHA-256 en hexadecimal (64 caracteres) o None si no viene o no es válida."""
    v = str(value or "").strip().lower()
    return v if len(v) == 64 and all(c in "0123456789abcdef" for c in v) else None


def folder_label(category: str | None) -> str:
    return category_label(category)


class ExportManager:
    """Trabajos de exportación en memoria (el resultado de cada archivo queda en la auditoría)."""

    def __init__(self, fm):
        self.fm = fm
        self.jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------ interfaz
    def create(self, chat_id: str, chat_name: str, completo: bool = False) -> dict:
        with self._lock:
            for j in self.jobs.values():  # un solo trabajo activo por chat
                if j["chat_id"] == chat_id and j["estado"] in ("esperando_puente", "leyendo_chat", "en_proceso"):
                    return j
            job = {"id": uuid.uuid4().hex[:12], "chat_id": chat_id, "chat_nombre": chat_name,
                   "estado": "esperando_puente", "creado": now_iso(), "actualizado": time.time(),
                   "terminado": None, "motivo": None, "items": [], "destino": None, "guardado": None,
                   "completo": completo}
            self.jobs[job["id"]] = job
        self.fm.audit.log("exportacion_solicitada", group=chat_name, export_id=job["id"], completo=completo)
        return job

    def history(self, chat_id: str) -> dict:
        """Cuántos mensajes de este chat ya se importaron (lo muestra la interfaz antes de exportar)."""
        done = self.fm.audit.imported_ids(chat_id)
        return {"chat_id": chat_id, "importados": len(done), "archivos_distintos": len({h for h in done.values() if h})}

    def get(self, job_id: str) -> dict:
        job = self.jobs.get(job_id)
        if not job:
            raise KeyError("Exportación no encontrada")
        return job

    def view(self, job_id: str) -> dict:
        job = self.get(job_id)
        counts = {k: 0 for k in ("en_cola", "descargando", "analizando", "seguro", "cuarentena", "error", "omitido")}
        for it in job["items"]:
            counts[it["estado"]] = counts.get(it["estado"], 0) + 1
        done = sum(counts[k] for k in ITEM_DONE)
        skipped = {r: sum(1 for it in job["items"] if it.get("omision") == r) for r in SKIP_REASON}
        incremental = {**skipped, "nuevos": len(job["items"]) - sum(skipped.values())}
        return {**{k: v for k, v in job.items() if k != "actualizado"}, "conteo": counts,
                "total": len(job["items"]), "procesados": done, "incremental": incremental}

    def list(self) -> list[dict]:
        rows = sorted(self.jobs.values(), key=lambda j: j["creado"], reverse=True)[:20]
        return [{k: v for k, v in self.view(j["id"]).items() if k != "items"} for j in rows]

    def cancel(self, job_id: str) -> dict:
        job = self.get(job_id)
        if job["estado"] in ("esperando_puente", "leyendo_chat", "en_proceso"):
            for it in job["items"]:
                if it["estado"] in ("en_cola", "descargando"):
                    it["estado"] = "omitido"
            self._finish(job, "cancelado")
        return self.view(job_id)

    # -------------------------------------------------------------- puente
    def next_pending(self) -> dict | None:
        with self._lock:
            for job in sorted(self.jobs.values(), key=lambda j: j["creado"]):
                if job["estado"] == "esperando_puente":
                    job.update(estado="leyendo_chat", actualizado=time.time())
                    return {"id": job["id"], "chat_id": job["chat_id"], "chat_nombre": job["chat_nombre"]}
        return None

    def set_items(self, job_id: str, items: list[dict]) -> dict:
        job = self.get(job_id)
        job["items"] = [{"idx": i, "msg_id": it.get("msg_id"), "nombre": it.get("nombre") or f"archivo_{i + 1}",
                         "tipo": it.get("tipo"), "tamano": it.get("tamano"), "remitente": it.get("remitente"),
                         "fecha": it.get("fecha"), "huella": _hex64(it.get("huella")), "estado": "en_cola",
                         "sha256": None, "categoria": None, "riesgo": None, "nivel": None, "motivo": None,
                         "duplicado": False, "omision": None}
                        for i, it in enumerate(items)]
        if not job.get("completo"):
            self._skip_known(job)
        pending = sum(1 for it in job["items"] if it["estado"] == "en_cola")
        job.update(estado="en_proceso" if pending else "terminado", actualizado=time.time())
        self.fm.audit.log("exportacion_iniciada", group=job["chat_nombre"], export_id=job_id, files=len(items),
                          nuevos=pending)
        if not pending:
            self._finish(job, "terminado")
        return self.view(job_id)

    def _skip_known(self, job: dict) -> None:
        """Marca como omitidos, sin descargarlos, los mensajes ya importados y los archivos repetidos."""
        done = self.fm.audit.imported_ids(job["chat_id"])
        known = self.fm.audit.known_hashes([it["huella"] for it in job["items"]])
        seen: set[str] = set()
        for it in job["items"]:
            reason = None
            if it["msg_id"] and it["msg_id"] in done:
                reason, it["sha256"] = "ya_importado", done[it["msg_id"]]
            elif it["huella"] and (it["huella"] in known or it["huella"] in seen):
                reason, it["sha256"] = "misma_huella", it["huella"]
                if it["msg_id"] and it["huella"] in known:
                    self.fm.audit.mark_imported(job["chat_id"], it["msg_id"], it["huella"])
            if reason:
                it.update(estado="omitido", omision=reason, motivo=SKIP_REASON[reason], duplicado=True)
            elif it["huella"]:
                seen.add(it["huella"])  # el mismo archivo reenviado varias veces en el chat se baja una vez

    def item_state(self, job_id: str, idx: int, state: str, reason: str | None = None) -> dict:
        job = self.get(job_id)
        it = job["items"][idx]
        if it["estado"] not in ITEM_DONE:
            it.update(estado=state, motivo=reason)
        job["actualizado"] = time.time()
        self._maybe_finish(job)
        return it

    def analyze(self, job_id: str, idx: int, data: bytes, filename: str, sender: str | None,
                message_ts: float | None) -> dict:
        job = self.get(job_id)
        it = job["items"][idx]
        if job["estado"] == "cancelado":
            return it
        it.update(estado="analizando", nombre=filename or it["nombre"], tamano=len(data))
        job["actualizado"] = time.time()
        try:
            rec = self.fm.process(data, it["nombre"], job["chat_nombre"], sender, message_ts, explicit=True)
        except Exception as e:  # un archivo dañado no detiene la cola
            it.update(estado="error", motivo=f"No se pudo analizar: {e}")
        else:
            it.update(estado="seguro" if rec["status"] == "clasificado" else "cuarentena",
                      sha256=rec["sha256"], categoria=rec.get("category"), riesgo=rec.get("risk_score"),
                      nivel=rec.get("risk_level"), duplicado=bool(rec.get("duplicate")),
                      motivo=(rec.get("reasons") or [None])[0] if rec["status"] == "cuarentena" else None)
            if it["msg_id"]:
                self.fm.audit.mark_imported(job["chat_id"], it["msg_id"], rec["sha256"])
        self._maybe_finish(job)
        return it

    def fail(self, job_id: str, reason: str) -> dict:
        job = self.get(job_id)
        job["motivo"] = reason
        self._finish(job, "error")
        return self.view(job_id)

    def _maybe_finish(self, job: dict) -> None:
        if job["estado"] == "en_proceso" and all(it["estado"] in ITEM_DONE for it in job["items"]):
            self._finish(job, "terminado")

    def _finish(self, job: dict, state: str) -> None:
        job.update(estado=state, terminado=now_iso(), actualizado=time.time())
        c = {s: sum(1 for it in job["items"] if it["estado"] == s) for s in ("seguro", "cuarentena", "error")}
        self.fm.audit.log("exportacion_" + state, group=job["chat_nombre"], export_id=job["id"], **c)

    # ------------------------------------------------------------ salida
    def _safe_files(self, job: dict) -> list[tuple[str, Path]]:
        """(subcarpeta, ruta en la biblioteca) de cada archivo seguro, con la categoría vigente."""
        out, seen = [], set()
        for it in job["items"]:
            if it["estado"] != "seguro" or not it["sha256"] or it["sha256"] in seen:
                continue  # el mismo archivo reenviado varias veces se entrega una sola vez
            seen.add(it["sha256"])
            rec = self.fm.audit.get_file(it["sha256"])
            if rec and rec["status"] == "clasificado" and rec.get("stored_path") and Path(rec["stored_path"]).exists():
                out.append((folder_label(rec.get("category")), Path(rec["stored_path"])))
        return out

    def save_to(self, job_id: str, destination: str) -> dict:
        job = self.get(job_id)
        from ..infrastructure.bufete import to_server_path   # ruta de Windows -> carpeta montada en Docker
        root = Path(to_server_path(destination.strip().strip('"'))).expanduser()
        if not root.is_absolute():
            raise ValueError("Escoge una carpeta completa del equipo, por ejemplo C:\\Users\\...\\Documentos")
        root.mkdir(parents=True, exist_ok=True)
        saved, per_folder = [], {}
        for folder, src in self._safe_files(job):
            target_dir = root / safe_name(folder)
            target_dir.mkdir(exist_ok=True)
            target = target_dir / src.name
            if target.exists() and target.stat().st_size != src.stat().st_size:
                target = target_dir / f"{src.stem}_{len(saved) + 1}{src.suffix}"
            shutil.copy2(src, target)
            saved.append(str(target))
            per_folder[folder] = per_folder.get(folder, 0) + 1
        job.update(destino=str(root), guardado={"archivos": len(saved), "por_carpeta": per_folder, "ts": now_iso()})
        self.fm.audit.log("exportacion_guardada", group=job["chat_nombre"], export_id=job_id,
                          destination=str(root), files=len(saved), folders=per_folder)
        return {"carpeta": str(root), "archivos": len(saved), "por_carpeta": per_folder}

    def zip_bytes(self, job_id: str) -> tuple[bytes, str]:
        job = self.get(job_id)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for folder, src in self._safe_files(job):
                z.write(src, f"{safe_name(folder)}/{src.name}")
        self.fm.audit.log("exportacion_descargada", group=job["chat_nombre"], export_id=job_id)
        return buf.getvalue(), f"FileMind_{safe_name(job['chat_nombre'])}.zip"
