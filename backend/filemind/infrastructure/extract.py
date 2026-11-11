"""Extracción de texto y enlaces de los formatos del alcance.

Alcance (filemind_seguridad.pdf): PDF, Word, Excel, PowerPoint e imágenes.
Además se aceptan texto plano/CSV. Nunca se ejecuta contenido: solo se lee.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

URL_RE = re.compile(r"""(?i)\b((?:https?://|www\.)[^\s<>"'\)\]\}]{3,})""")
MAX_TEXT = 200_000


def extract_urls(text: str) -> list[str]:
    seen, out = set(), []
    for m in URL_RE.findall(text or ""):
        u = m.rstrip(".,;:")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _pdf_text(data: bytes) -> tuple[str, list[str]]:
    links: list[str] = []
    try:
        import pymupdf
    except ImportError:  # pragma: no cover
        import fitz as pymupdf  # type: ignore
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        return "", links
    parts = []
    for page in doc:
        parts.append(page.get_text())
        for ln in page.get_links():
            if ln.get("uri"):
                links.append(ln["uri"])
        if sum(map(len, parts)) > MAX_TEXT:
            break
    return "\n".join(parts), links


def _ooxml_links(z: zipfile.ZipFile) -> list[str]:
    links = []
    for n in z.namelist():
        if n.endswith(".rels"):
            xml = z.read(n).decode("utf-8", "ignore")
            links += re.findall(r'Target="(https?://[^"]+)"[^>]*TargetMode="External"', xml)
            links += re.findall(r'TargetMode="External"[^>]*Target="(https?://[^"]+)"', xml)
    return links


def _docx_text(data: bytes) -> tuple[str, list[str]]:
    import docx
    d = docx.Document(io.BytesIO(data))
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts.append(" ".join(c.text for c in row.cells))
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        links = _ooxml_links(z)
    return "\n".join(parts), links


def _xlsx_text(data: bytes) -> tuple[str, list[str]]:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    parts, total = [], 0
    # Una hoja con formato hasta la fila 1.048.576 entrega un millón de filas vacías. Antes se
    # sumaba todo el texto en cada fila (costo cuadrático) y un Excel de 130 KB congeló la API.
    # Ahora se lleva el total acumulado, se saltan las filas vacías y se corta tras muchas seguidas.
    for ws in wb.worksheets:
        parts.append(ws.title)
        empty = 0
        for row in ws.iter_rows(values_only=True):
            line = " ".join(str(v) for v in row if v is not None)
            if not line:
                empty += 1
                if empty > 2000:
                    break
                continue
            empty = 0
            parts.append(line)
            total += len(line)
            if total > MAX_TEXT:
                break
        if total > MAX_TEXT:
            break
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        links = _ooxml_links(z)
    return "\n".join(parts), links


def _pptx_text(data: bytes) -> tuple[str, list[str]]:
    import pptx
    prs = pptx.Presentation(io.BytesIO(data))
    parts = []
    for slide in prs.slides:
        for shp in slide.shapes:
            if shp.has_text_frame:
                parts.append(shp.text_frame.text)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        links = _ooxml_links(z)
    return "\n".join(parts), links


def _ooxml_raw_text(data: bytes) -> str:
    """Respaldo para .docm/.xlsm/.pptm u OOXML que las librerías no abren."""
    out = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for n in z.namelist():
                if n.endswith(".xml") and ("document" in n or "slide" in n or "sharedStrings" in n):
                    xml = z.read(n).decode("utf-8", "ignore")
                    out.append(re.sub(r"<[^>]+>", " ", xml))
    except zipfile.BadZipFile:
        pass
    return re.sub(r"\s+", " ", " ".join(out))


def _image_text(data: bytes) -> str:
    """OCR opcional (requiere tesseract + pytesseract instalados)."""
    try:
        import pytesseract
        from PIL import Image
        return pytesseract.image_to_string(Image.open(io.BytesIO(data)), lang="spa")
    except Exception:
        return ""


def extract(data: bytes, real_type: str) -> dict:
    """Devuelve ``{"text", "urls", "error"}`` según el tipo real detectado."""
    text, links, err = "", [], None
    try:
        if real_type == "pdf":
            text, links = _pdf_text(data)
        elif real_type in ("docx", "docm"):
            try:
                text, links = _docx_text(data)
            except Exception:
                text = _ooxml_raw_text(data)
        elif real_type in ("xlsx", "xlsm"):
            try:
                text, links = _xlsx_text(data)
            except Exception:
                text = _ooxml_raw_text(data)
        elif real_type in ("pptx", "pptm"):
            try:
                text, links = _pptx_text(data)
            except Exception:
                text = _ooxml_raw_text(data)
        elif real_type in ("png", "jpg", "gif", "webp", "bmp"):
            text = _image_text(data)
        elif real_type in ("txt", "csv", "html"):
            text = data[:MAX_TEXT].decode("utf-8", "ignore")
        elif real_type in ("ole",):
            # Office 97-2003: se extraen cadenas legibles
            text = " ".join(re.findall(rb"[\x20-\x7e\xc0-\xff]{5,}", data[:2_000_000])
                            ).decode("latin-1", "ignore")
    except Exception as e:  # archivo corrupto o malformado
        err = f"{type(e).__name__}: {e}"
    text = (text or "")[:MAX_TEXT]
    urls = extract_urls(text)
    for l in links:
        if l not in urls:
            urls.append(l)
    return {"text": text, "urls": urls, "error": err}


def read_text_file(path: Path) -> str:
    from ..security.static import detect_type
    data = Path(path).read_bytes()
    return extract(data, detect_type(data, Path(path).name))["text"]
