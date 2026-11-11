"""Ingesta (RF2), consulta, descarga y corrección de archivos."""
import asyncio
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from ...domain.models import FileStatus
from ...infrastructure.report_pdf import render_pdf, report_filename
from ..deps import current_user, get_fm, in_scope, scope
from ..schemas import CategoryIn, summary as _summary

router = APIRouter(prefix="/api", tags=["archivos"])


@router.post("/ingest")
async def ingest(file: UploadFile = File(...), grupo: str = Form(...), remitente: str = Form(""),
                 message_ts: float | None = Form(None), fm=Depends(get_fm), groups=Depends(scope)):
    if groups is not None and grupo not in groups:   # un miembro solo analiza en los chats de sus espacios
        raise HTTPException(403, "Ese chat no pertenece a sus espacios de trabajo.")
    if not fm.is_monitored(grupo):
        fm.audit.log("ignorado_grupo_no_monitoreado", group=grupo)
        return {"procesado": False, "motivo": "grupo no monitoreado"}
    data = await file.read()
    # Se espera el análisis sin bloquear el servidor (un fut.result() aquí congelaba toda la API)
    try:
        rec = await asyncio.wait_for(asyncio.wrap_future(
            fm.submit(data, file.filename or "archivo", grupo, remitente or None, message_ts)), timeout=120)
    except asyncio.TimeoutError:
        raise HTTPException(504, "El análisis del archivo tardó más de 120 s")
    return {"procesado": True, **_summary(rec)}


@router.get("/archivos")
def files(estado: str | None = None, categoria: str | None = None, q: str | None = None,
          contenido: bool = True, limite: int = 500, carpeta: str | None = None,
          fm=Depends(get_fm), groups=Depends(scope)):
    """Lista de archivos visibles. ``q`` busca en nombre, chat y remitente y, con ``contenido``,
    también dentro del texto de los documentos (sin importar tildes ni mayúsculas).
    ``carpeta`` filtra por su estado en la carpeta del bufete: guardado | falta | cuarentena."""
    rows = fm.audit.list_files(estado, limite if not (q or carpeta) else 100000, groups)
    if categoria:
        rows = [r for r in rows if (r.get("category") or "") == categoria]
    st = fm.bufete.status_many(rows)
    if carpeta:
        want = {"falta": {"falta", "sin_carpeta"}}.get(carpeta, {carpeta})
        rows = [r for r in rows if st[r["sha256"]]["estado"] in want]
        if not q:
            rows = rows[:limite]
    summary = lambda r: _summary(r) | {"carpeta": st[r["sha256"]]}  # noqa: E731
    if q:
        ql = q.lower().strip()
        hits = dict(fm.audit.search(q, groups, 1000)) if contenido else {}
        out = []
        for r in rows:
            meta = any(ql in (r.get(k) or "").lower() for k in ("original_name", "group_name", "sender"))
            if meta or r["sha256"] in hits:
                out.append(summary(r) | ({"coincidencia": hits[r["sha256"]]} if r["sha256"] in hits and not meta else {}))
        return out[:limite]
    return [summary(r) for r in rows]


def _visible(sha: str, fm, groups) -> dict:
    rec = fm.audit.get_file(sha)
    if not in_scope(rec, groups):  # mismo mensaje exista o no, para no revelar archivos ajenos
        raise HTTPException(404, "No encontrado")
    return rec


@router.get("/archivos/{sha}")
def file_detail(sha: str, fm=Depends(get_fm), groups=Depends(scope)):
    rec = _visible(sha, fm, groups)
    rec["eventos"] = fm.audit.events(sha)
    rec["carpeta"] = fm.bufete.status(rec)
    return rec


@router.post("/archivos/{sha}/guardar-en-carpeta")
def save_to_bufete(sha: str, fm=Depends(get_fm), groups=Depends(scope)):
    """Guarda este archivo en la subcarpeta de su etiqueta dentro de la carpeta del bufete."""
    rec = _visible(sha, fm, groups)
    try:
        return fm.bufete.save(rec)
    except (ValueError, OSError) as e:
        raise HTTPException(400, str(e))


@router.get("/archivos/{sha}/reporte.pdf")
def report(sha: str, fm=Depends(get_fm), groups=Depends(scope), user=Depends(current_user)):
    rec = _visible(sha, fm, groups)
    pdf = render_pdf(rec, fm.audit.events(sha, 300), user.get("name"))
    fm.audit.log("reporte_pdf_generado", sha, rec.get("group_name"), usuario=user.get("username"))
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(report_filename(rec))}"})


@router.get("/archivos/{sha}/descargar")
def download(sha: str, fm=Depends(get_fm), groups=Depends(scope)):
    rec = _visible(sha, fm, groups)
    if not rec.get("stored_path"):
        raise HTTPException(404, "No encontrado")
    if rec["status"] == FileStatus.QUARANTINED:  # RF8: acceso restringido
        fm.audit.log("acceso_denegado_cuarentena", sha, rec["group_name"])
        raise HTTPException(403, "Archivo en cuarentena: no se puede abrir.")
    return FileResponse(rec["stored_path"], filename=Path(rec["stored_path"]).name)


@router.post("/archivos/{sha}/categoria")
def correct(sha: str, body: CategoryIn, fm=Depends(get_fm), groups=Depends(scope)):
    """Cualquier miembro del espacio puede corregir: la corrección queda para todo el equipo y para el reentrenamiento."""
    _visible(sha, fm, groups)
    try:
        return fm.correct_category(sha, body.categoria)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))
