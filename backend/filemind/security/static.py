"""Fase 1 — Análisis estático.

* RF3: SHA-256 del archivo antes de cualquier otro procesamiento.
* RF4: comparación de la extensión declarada con la firma real de bytes
  (magic number), incluida la inspección interna de contenedores ZIP/OOXML.
* RF5: consulta del hash contra un repositorio de firmas (ver ``signatures``).
"""
from __future__ import annotations

import hashlib
import io
import unicodedata
import zipfile
from pathlib import Path

# Firmas de bytes (magic numbers) -> tipo real
MAGIC = [
    (b"%PDF-", "pdf"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "ole"),      # Office 97-2003 / MSI
    (b"MZ", "exe"),                                    # PE de Windows
    (b"\x7fELF", "elf"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"BM", "bmp"),
    (b"Rar!\x1a\x07", "rar"),
    (b"7z\xbc\xaf\x27\x1c", "7z"),
    (b"\x1f\x8b", "gz"),
    (b"{\\rtf", "rtf"),
    (b"#!", "script"),
    (b"L\x00\x00\x00\x01\x14\x02\x00", "lnk"),        # acceso directo de Windows
    (b"MSCF", "cab"),
    (b"\xca\xfe\xba\xbe", "java"),
    (b"\xfd7zXZ\x00", "xz"),
    (b"BZh", "bz2"),
    (b"OggS", "ogg"),                                  # notas de voz de WhatsApp (Opus)
    (b"ID3", "mp3"), (b"\xff\xfb", "mp3"), (b"\xff\xf3", "mp3"), (b"\xff\xf2", "mp3"),
    (b"fLaC", "flac"),
    (b"\x1a\x45\xdf\xa3", "mkv"),                      # Matroska / WebM
    (b"\xcf\xfa\xed\xfe", "macho"),
    (b"\xfe\xed\xfa\xcf", "macho"),
    (b"PK\x03\x04", "zip"),
    (b"PK\x05\x06", "zip"),
]

# Extensión declarada -> tipos reales aceptables
EXPECTED = {
    "pdf": {"pdf"},
    "doc": {"ole", "rtf"}, "xls": {"ole"}, "ppt": {"ole"},
    "docx": {"docx"}, "xlsx": {"xlsx"}, "pptx": {"pptx"},
    "docm": {"docm"}, "xlsm": {"xlsm"}, "pptm": {"pptm"},
    "png": {"png"}, "jpg": {"jpg"}, "jpeg": {"jpg"}, "gif": {"gif"},
    "webp": {"webp"}, "bmp": {"bmp"},
    "txt": {"txt"}, "csv": {"txt"}, "rtf": {"rtf"},
    "zip": {"zip", "docx", "xlsx", "pptx"}, "rar": {"rar"}, "7z": {"7z"},
    "exe": {"exe"}, "html": {"html", "txt"}, "htm": {"html", "txt"},
    "lnk": {"lnk"}, "iso": {"iso"}, "img": {"iso"}, "cab": {"cab"}, "gz": {"gz"}, "tgz": {"gz"},
    "xz": {"xz"}, "bz2": {"bz2"}, "jar": {"zip"}, "apk": {"zip"},
    "ogg": {"ogg"}, "opus": {"ogg"}, "oga": {"ogg"}, "mp3": {"mp3"}, "flac": {"flac"}, "wav": {"wav"},
    "mp4": {"mp4"}, "m4a": {"mp4"}, "mov": {"mp4"}, "3gp": {"mp4"}, "webm": {"mkv"}, "mkv": {"mkv"},
    "avi": {"avi"},
}
# Imágenes, audio y video: confundir un formato con otro del mismo grupo (p. ej. un
# sticker .webp guardado como .jpeg) no es un riesgo y no se marca como suplantación.
MEDIA_GROUPS = [{"png", "jpg", "gif", "webp", "bmp"}, {"ogg", "mp3", "flac", "wav", "mp4", "mkv", "avi"}]

DANGEROUS_EXT = {
    "exe", "scr", "com", "bat", "cmd", "pif", "vbs", "vbe", "js", "jse", "wsf",
    "wsh", "ps1", "psm1", "hta", "msi", "jar", "lnk", "iso", "img", "dll", "cpl",
    "reg", "apk", "sh", "elf",
}
EXECUTABLE_REAL = {"exe", "elf", "script", "lnk", "macho"}
MACRO_TYPES = {"docm", "xlsm", "pptm"}
SUPPORTED_REAL = {"pdf", "docx", "xlsx", "pptx", "docm", "xlsm", "pptm", "ole",
                  "png", "jpg", "gif", "webp", "bmp", "txt", "rtf", "html"}

BIDI_CHARS = {"‮", "‭", "‪", "‫", "‏", "‎", "⁦", "⁧", "⁨"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _zip_kind(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = set(z.namelist())
    except zipfile.BadZipFile:
        return "zip"
    has_vba = any(n.lower().endswith("vbaproject.bin") for n in names)
    for prefix, base in (("word/", "doc"), ("xl/", "xls"), ("ppt/", "ppt")):
        if any(n.startswith(prefix) for n in names):
            return base + ("m" if has_vba else "x")
    return "zip"


def detect_type(data: bytes, filename: str = "") -> str:
    head = data[:16]
    if head.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    if head.startswith(b"RIFF") and data[8:12] in (b"WAVE", b"AVI "):
        return "wav" if data[8:12] == b"WAVE" else "avi"
    if data[4:8] == b"ftyp":                # MP4 / M4A / MOV / 3GP
        return "mp4"
    if data[0x8001:0x8006] == b"CD001":   # imagen de disco ISO 9660
        return "iso"
    for sig, kind in MAGIC:
        if head.startswith(sig):
            if kind == "zip":
                return _zip_kind(data)
            if kind == "bmp" and len(data) < 26:
                continue
            return kind
    sample = data[:4096]
    low = sample.lower().lstrip()
    if low.startswith((b"<!doctype html", b"<html", b"<script")):
        return "html"
    if b"\x00" not in sample:
        try:
            sample.decode("utf-8")
            return "txt"
        except UnicodeDecodeError:
            try:
                sample.decode("latin-1")
                return "txt"
            except UnicodeDecodeError:
                pass
    return "unknown"


def analyze_name(filename: str) -> dict:
    """Detecta doble extensión, caracteres de control bidireccional y extensiones peligrosas."""
    has_bidi = any(ch in BIDI_CHARS for ch in filename)
    clean = "".join(ch for ch in filename if ch not in BIDI_CHARS)
    clean = unicodedata.normalize("NFKC", clean).strip().rstrip(".")
    parts = clean.lower().split(".")
    ext = parts[-1] if len(parts) > 1 else ""
    inner = parts[-2] if len(parts) > 2 else ""
    double = bool(inner) and inner in EXPECTED and ext in DANGEROUS_EXT
    return {
        "declared_ext": ext,
        "double_extension": double,
        "bidi_override": has_bidi,
        "dangerous_ext": ext in DANGEROUS_EXT,
        "many_spaces": "     " in filename,
    }


def run_static(data: bytes, filename: str, signatures) -> dict:
    """Ejecuta la Fase 1 completa. ``signatures`` es un ``SignatureRepository``."""
    digest = sha256_bytes(data)
    real = detect_type(data, filename)
    name = analyze_name(filename)
    ext = name["declared_ext"]
    expected = EXPECTED.get(ext)
    if expected is None:
        mismatch = ext not in ("",) and real not in ("txt", "unknown")
    else:
        mismatch = real not in expected
        if mismatch and any(real in g and expected <= g for g in MEDIA_GROUPS):
            mismatch = False
    lookup = signatures.lookup(digest)
    return {
        "sha256": digest,
        "size": len(data),
        "real_type": real,
        **name,
        "extension_mismatch": bool(mismatch),
        "executable_content": real in EXECUTABLE_REAL,
        "macro_container": real in MACRO_TYPES,
        "supported_type": real in SUPPORTED_REAL,
        "known_malware": lookup["malicious"],
        "signature_lookup": lookup,
    }
