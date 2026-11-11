"""Controles de ciberseguridad que refuerzan las fases 1 y 2.

Cada control es local (sin servicios externos) y devuelve un resultado que la
interfaz muestra por separado, para que se vea qué revisó y qué encontró:

========================  =====  ==============================================
Control                   Fase   Qué revisa
========================  =====  ==============================================
tipo_real                 1      Tipo real por bytes mágicos frente a la
                                 extensión, doble extensión, RTLO y archivos
                                 políglotas (p. ej. una imagen con un ZIP pegado).
hashes                    1      MD5, SHA-1 y SHA-256 (del archivo y de lo que
                                 trae adentro) contra las listas locales de
                                 malware conocido.
macros_ole                2      Macros VBA y Excel 4.0 (XLM) con oletools,
                                 VBA stomping, indicadores en el código y objetos
                                 OLE incrustados (paquetes con ejecutables, clases
                                 usadas en exploits como Equation.3 u OLE2Link).
pdf_activo                2      JavaScript (incluido el escondido en flujos de
                                 objetos), acciones automáticas al abrir, /Launch,
                                 archivos incrustados y PDF cifrados o dañados.
comprimidos               2      ZIP/GZIP: anidamiento, bombas de descompresión,
                                 entradas con contraseña, rutas que escapan de la
                                 carpeta y programas o macros adentro.
yara                      2      Reglas YARA (security/reglas/*.yar) sobre el
                                 archivo y todo lo desempaquetado.
entropia                  2      Entropía de Shannon global y por bloques para
                                 detectar contenido cifrado u ofuscado donde no
                                 debería haberlo.
urls                      2      Enlaces visibles y ocultos (metadatos, anotaciones
                                 PDF, relaciones OOXML, código) con su veredicto.
html                      2      Formularios que piden contraseña, envíos a otros
                                 sitios, iframes ocultos, redirecciones y enlaces
                                 cuyo texto no coincide con su destino.
ingenieria_social         2      Petición de claves o datos bancarios junto a un
                                 enlace que no es de un sitio oficial.
========================  =====  ==============================================

Los puntos de cada indicador están en ``risk.RULE_WEIGHTS`` (documentados en
docs/protocolo_riesgo.md). Estos indicadores no entran al modelo de IA (que se
entrenó con las características originales) sino al puntaje por reglas, que es
reproducible y explicable.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import math
import re
import tarfile
import threading
import zipfile
import zlib
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from .heuristic import BRANDS, SHORTENERS, _registered_domain, analyze_urls, shannon_entropy
from .static import DANGEROUS_EXT, EXECUTABLE_REAL, MACRO_TYPES, analyze_name, detect_type

RULES_DIR = Path(__file__).with_name("reglas")
OOXML = {"docx", "xlsx", "pptx", "docm", "xlsm", "pptm"}
ARCHIVES = {"zip", "gz", "rar", "7z", "cab", "iso", "xz", "bz2"}
MEDIA = {"png", "jpg", "gif", "webp", "bmp", "ogg", "mp3", "flac", "wav", "mp4", "mkv", "avi"}
SHORT_TEXT = 4000        # los señuelos de phishing son cortos; un documento largo que menciona "contraseña" no lo es

MAX_DEPTH = 3                    # zip dentro de zip dentro de zip
MAX_ENTRIES = 2000
MAX_ENTRY_READ = 30 * 1024 * 1024
MAX_TOTAL_READ = 120 * 1024 * 1024
MAX_BLOBS_BYTES = 60 * 1024 * 1024

# Nombres de cada control para la interfaz (en el orden en que se muestran)
NAMES = {
    "tipo_real": ("Tipo real frente a la extensión", 1),
    "hashes": ("Hashes contra listas de malware", 1),
    "macros_ole": ("Macros y objetos OLE", 2),
    "pdf_activo": ("JavaScript, acciones y adjuntos en PDF", 2),
    "comprimidos": ("Archivos comprimidos", 2),
    "yara": ("Reglas YARA", 2),
    "entropia": ("Entropía (contenido cifrado u ofuscado)", 2),
    "urls": ("Enlaces extraídos", 2),
    "html": ("Formularios y scripts HTML", 2),
    "ingenieria_social": ("Petición de claves o datos con enlace", 2),
}

# Indicadores (de risk.RULE_WEIGHTS) que se atribuyen a cada control para mostrar sus puntos
OWNS = {
    "tipo_real": ["executable_content", "double_extension", "bidi_override", "dangerous_ext",
                  "extension_mismatch", "polyglot"],
    "hashes": ["known_malware", "known_malware_hash", "inner_known_malware"],
    "macros_ole": ["has_macros", "macro_autoexec", "macro_suspicious", "vba_ioc", "vba_obfuscation",
                   "vba_stomping", "xlm_macros", "dde", "remote_template", "ole_objects",
                   "ole_package_exe", "ole_exploit_class", "office_encrypted"],
    "pdf_activo": ["pdf_launch", "pdf_javascript", "pdf_hex_obfuscation", "pdf_openaction", "pdf_autoaction",
                   "pdf_embedded", "pdf_js_autorun", "pdf_js_suspicious_api", "pdf_embedded_exe",
                   "pdf_embedded_macro", "pdf_encrypted", "pdf_malformed"],
    "comprimidos": ["archive_encrypted", "archive_dangerous_entry", "archive_executable",
                    "archive_path_traversal", "archive_ratio_high", "archive_bomb", "archive_nested_deep",
                    "archive_macro_doc", "archive_uninspectable"],
    "yara": ["yara_alta", "yara_media"],
    "entropia": ["entropy_anomaly", "long_base64", "js_obfuscation"],
    "urls": ["url_ip_host", "url_shortener", "url_punycode", "url_risky_tld", "url_at_sign",
             "url_brand_impersonation", "url_recent_domain", "url_credential_path", "url_hidden_suspicious"],
    "html": ["html_password_form", "html_form_external", "html_brand_title", "url_text_mismatch",
             "html_meta_refresh", "html_hidden_iframe"],
    "ingenieria_social": ["phish_phrases", "cred_request_link"],
}

# Frases que piden credenciales, datos financieros o cambios de cuenta (más fuertes que la simple urgencia)
CRED_PHRASES = [
    "contraseña", "clave dinámica", "clave de acceso", "clave del cajero", "código de verificación",
    "número de tarjeta", "cvv", "datos bancarios", "verifique su cuenta", "verifica tu cuenta",
    "ha sido suspendida", "será bloqueada", "cuenta bloqueada", "actualice sus datos", "actualiza tus datos",
    "confirme su identidad", "confirma tu identidad", "inicie sesión", "inicia sesión",
    "cambió su cuenta bancaria", "nueva cuenta bancaria", "cambio de cuenta bancaria", "ha sido seleccionado",
    "descargar la factura", "consulte el documento en el siguiente enlace",
]
OFFICIAL_SUFFIXES = (".gov.co", ".edu.co", ".gov", ".mil.co", ".org.co")
NAMESPACE_HOSTS = ("schemas.openxmlformats.org", "schemas.microsoft.com", "www.w3.org", "purl.org",
                   "ns.adobe.com", "www.openxmlformats.org", "schemas.xmlsoap.org", "www.ecma-international.org",
                   "openoffice.org", "www.iana.org")
RAW_URL_RE = re.compile(rb"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'*+,;=%]{4,200}")
PDF_JS_APIS = ["app.launchURL", "exportDataObject", "util.printf", "getAnnots", "spell.customDictionaryOpen",
               "Collab.collectEmailInfo", "Collab.getIcon", "media.newPlayer", "eval(", "unescape(",
               "String.fromCharCode", "app.openDoc", "submitForm", "this.getURL", "app.setTimeOut"]
EXPLOIT_CLASSES = {"equation.3": "Equation Editor (CVE-2017-11882)",
                   "ole2link": "OLE2Link (CVE-2017-0199)",
                   "0002ce02-0000-0000-c000-000000000046": "Equation Editor (CVE-2017-11882)",
                   "00000300-0000-0000-c000-000000000046": "OLE2Link (CVE-2017-0199)"}


# ------------------------------------------------------------------ utilidades
def _f(fid: str, kind: str, sev: str, tecnico: str, claro: str) -> dict:
    return {"id": fid, "kind": kind, "severity": sev, "tecnico": tecnico, "claro": claro}


class _Ctx:
    def __init__(self, data: bytes, filename: str, st: dict, text: str, urls: list[str], sigs):
        self.data, self.filename, self.st, self.text, self.urls, self.sigs = data, filename, st, text or "", urls, sigs
        self.real = st.get("real_type", "unknown")
        self.blobs: list[tuple[str, bytes]] = []        # contenido desempaquetado para YARA/URL
        self.blob_bytes = 0
        self.inner_hashes: list[tuple[str, str, str]] = []   # (nombre, sha256, md5)
        self.extra_urls: list[str] = []
        self.features: dict = {}
        self.findings: list[dict] = []

    def add_blob(self, label: str, blob: bytes) -> None:
        if not blob or self.blob_bytes + len(blob) > MAX_BLOBS_BYTES or len(self.blobs) >= 400:
            return
        self.blobs.append((label, blob))
        self.blob_bytes += len(blob)

    def feat(self, name: str, value: float = 1) -> None:
        self.features[name] = self.features.get(name, 0) + value


def _result(cid: str, estado: str, resumen: str, detalles: list[str] | None = None) -> dict:
    nombre, fase = NAMES[cid]
    return {"id": cid, "nombre": nombre, "fase": fase, "estado": estado, "resumen": resumen,
            "detalles": (detalles or [])[:40], "puntos": 0}


def _ext(name: str) -> str:
    return analyze_name(name.rsplit("/", 1)[-1])["declared_ext"]


# ------------------------------------------------------------------ 1. tipo real
def _polyglot_entries(c: _Ctx) -> list[str]:
    """Imagen o PDF válidos que además llevan un ZIP pegado (zipfile lee el índice del final)."""
    if c.real not in MEDIA | {"pdf"} or c.data.find(b"PK\x03\x04", 1) <= 0:
        return []
    try:
        with zipfile.ZipFile(io.BytesIO(c.data)) as z:
            return z.namelist()
    except (zipfile.BadZipFile, ValueError, OSError):
        return []


def control_tipo_real(c: _Ctx) -> dict:
    st = c.st
    det = [f"Tipo real según sus bytes: {c.real}", f"Extensión en el nombre: .{st.get('declared_ext') or '—'}"]
    try:   # descripción de libmagic, si python-magic está instalado (opcional)
        import magic  # type: ignore
        det.append("libmagic: " + magic.from_buffer(c.data[:8192]))
    except Exception:
        pass
    problems = []
    if st.get("executable_content"):
        problems.append(f"el contenido es ejecutable ({c.real})")
    if st.get("double_extension"):
        problems.append("tiene doble extensión")
    if st.get("bidi_override"):
        problems.append("usa caracteres invisibles que invierten el nombre (RTLO)")
    if st.get("extension_mismatch"):
        problems.append("la extensión no coincide con el contenido")
    if st.get("dangerous_ext"):
        problems.append(f"la extensión .{st.get('declared_ext')} es de programa o script")
    inner = _polyglot_entries(c)
    if inner:
        c.feat("polyglot")
        problems.append(f"es un archivo políglota: además de {c.real} contiene un ZIP con {len(inner)} entradas")
        c.findings.append(_f("polyglot", "ransomware", "alta",
                             f"Archivo políglota {c.real}+ZIP ({', '.join(inner[:5])}).",
                             "El archivo se hace pasar por imagen o documento pero esconde un comprimido."))
    if problems:
        return _result("tipo_real", "alerta", "No es lo que dice ser: " + "; ".join(problems) + ".", det)
    return _result("tipo_real", "ok", f"Es realmente {c.real} y coincide con su extensión.", det)


# ------------------------------------------------------------------ 2. hashes
def control_hashes(c: _Ctx) -> dict:
    md5 = hashlib.md5(c.data).hexdigest()
    sha1 = hashlib.sha1(c.data).hexdigest()
    sha256 = c.st.get("sha256") or hashlib.sha256(c.data).hexdigest()
    det = [f"MD5 {md5}", f"SHA-1 {sha1}", f"SHA-256 {sha256}"]
    n_sigs = len(c.sigs) if c.sigs is not None else 0
    det.append(f"Firmas cargadas en las listas locales: {n_sigs}")
    hits = []
    lk = c.st.get("signature_lookup") or {}
    if c.st.get("known_malware"):
        hits.append(f"SHA-256 registrado como {lk.get('family') or 'malware'} (fuente: {lk.get('source')})")
    if c.sigs is not None and hasattr(c.sigs, "lookup_local"):
        m = c.sigs.lookup_local(md5, sha1)
        if m:
            c.feat("known_malware_hash")
            hits.append(f"{m['algoritmo']} registrado como {m['family']}")
        for name, h256, hmd5 in c.inner_hashes[:500]:
            m = c.sigs.lookup_local(h256, hmd5)
            if m:
                c.feat("inner_known_malware")
                hits.append(f"lo que trae adentro («{name}») está registrado como {m['family']}")
        if c.inner_hashes:
            det.append(f"Huellas internas revisadas: {len(c.inner_hashes)}")
    if c.features.get("known_malware_hash") or c.features.get("inner_known_malware"):
        c.findings.append(_f("known_malware_hash", "ransomware", "alta", "Coincidencia en lista local: " + "; ".join(hits),
                             "El archivo, o algo que trae adentro, ya está registrado como un virus conocido."))
    if hits:
        return _result("hashes", "alerta", "Coincide con malware conocido: " + "; ".join(hits) + ".", det)
    return _result("hashes", "ok", "Ninguna huella coincide con las listas de malware conocido.", det)


# ------------------------------------------------------------------ 3. macros y OLE
def _ole_inspect(c: _Ctx, blob: bytes, where: str, det: list[str]) -> None:
    """Revisa un contenedor OLE: paquetes Ole10Native, CLSID de exploits y cifrado de Office."""
    try:
        import olefile
        if not olefile.isOleFile(blob):
            return
        ole = olefile.OleFileIO(blob)
    except Exception:
        return
    try:
        clsid = (ole.root.clsid or "").lower()
        if clsid in EXPLOIT_CLASSES:
            c.feat("ole_exploit_class")
            det.append(f"{where}: clase OLE {EXPLOIT_CLASSES[clsid]}")
        streams = ["/".join(s) for s in ole.listdir()]
        if any(s.lower().endswith("encryptedpackage") for s in streams):
            c.feat("office_encrypted")
            det.append(f"{where}: documento de Office protegido con contraseña (no se puede inspeccionar por dentro)")
        for s in ole.listdir():
            if s[-1].lower() == "\x01ole10native":
                from oletools.oleobj import OleNativeStream
                ns = OleNativeStream(ole.openstream(s).read())
                fname = (ns.filename or ns.src_path or "")
                fname = fname.decode("latin-1") if isinstance(fname, bytes) else str(fname)
                _package(c, fname, ns.data or b"", where, det)
    except Exception as e:
        det.append(f"{where}: no se pudo leer el objeto OLE ({type(e).__name__})")
    finally:
        ole.close()


def _package(c: _Ctx, fname: str, payload: bytes, where: str, det: list[str]) -> None:
    rtype = detect_type(payload, fname) if payload else "unknown"
    nm = analyze_name(fname.replace("\\", "/").rsplit("/", 1)[-1]) if fname else {"dangerous_ext": False}
    det.append(f"{where}: paquete OLE «{fname or 'sin nombre'}» (tipo real {rtype})")
    if nm.get("dangerous_ext") or rtype in EXECUTABLE_REAL:
        c.feat("ole_package_exe")
    if payload:
        c.add_blob(f"{where}/{fname}", payload)
        c.inner_hashes.append((fname, hashlib.sha256(payload).hexdigest(), hashlib.md5(payload).hexdigest()))


def control_macros_ole(c: _Ctx) -> dict:
    if c.real not in OOXML | {"ole", "rtf"}:
        return _result("macros_ole", "no_aplica", "No es un documento de Office ni RTF.")
    det: list[str] = []
    # --- VBA y XLM con oletools
    try:
        from oletools.olevba import VBA_Parser
        vp = VBA_Parser("archivo", data=c.data)
        try:
            has_vba = vp.detect_vba_macros()
            try:
                xlm = vp.detect_xlm_macros()
            except Exception:
                xlm = False
            if has_vba:
                code = "\n".join(src for (_, _, _, src) in vp.extract_macros())
                c.add_blob("código VBA", code.encode("latin-1", "ignore"))
                kinds = Counter()
                kws: dict[str, list[str]] = {}
                for typ, kw, _desc in vp.analyze_macros():
                    kinds[typ] += 1
                    kws.setdefault(typ, []).append(str(kw))
                for typ, words in kws.items():
                    det.append(f"oletools · {typ}: {', '.join(sorted(set(words))[:8])}")
                if kinds["IOC"]:
                    c.feat("vba_ioc", kinds["IOC"])
                obf = kinds["Hex String"] + kinds["Base64 String"] + kinds["Dridex String"] + kinds["VBA string"]
                if obf:
                    c.feat("vba_obfuscation", obf)
                try:
                    if vp.detect_vba_stomping():
                        c.feat("vba_stomping")
                        det.append("VBA stomping: el código compilado no coincide con el código fuente")
                except Exception:
                    pass
            if xlm:
                c.feat("xlm_macros")
                det.append("Macros de Excel 4.0 (XLM) detectadas por oletools")
        finally:
            vp.close()
    except Exception as e:
        det.append(f"oletools no pudo abrir el archivo ({type(e).__name__})")
    # --- contenedores OOXML: proyecto VBA no estándar, hojas de macros XLM y objetos incrustados
    if c.real in OOXML:
        try:
            with zipfile.ZipFile(io.BytesIO(c.data)) as z:
                for i in z.infolist()[:MAX_ENTRIES]:
                    n = i.filename.lower()
                    if n.endswith("vbaproject.bin") and not c.features.get("vba_obfuscation") \
                            and not any("oletools ·" in d for d in det):
                        blob = z.read(i)
                        if blob[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
                            det.append("El proyecto de macros no es un contenedor OLE válido "
                                       "(oletools no lo puede leer; se revisó como texto)")
                    if n.startswith(("xl/macrosheets/", "xl/intlmacrosheets/")):
                        c.features["xlm_macros"] = 1
                        det.append(f"Hoja de macros Excel 4.0: {i.filename}")
                    if ("embeddings/" in n or "oleobject" in n) and i.file_size < MAX_ENTRY_READ:
                        blob = z.read(i)
                        _ole_inspect(c, blob, i.filename, det)
        except zipfile.BadZipFile:
            pass
    elif c.real == "ole":
        _ole_inspect(c, c.data, "documento", det)
    elif c.real == "rtf":
        try:
            from oletools import rtfobj
            parser = rtfobj.RtfObjParser(c.data)
            parser.parse()
            if parser.objects:
                det.append(f"Objetos incrustados en el RTF: {len(parser.objects)}")
                c.feat("ole_objects", len(parser.objects))
            for o in parser.objects:
                if o.is_package:
                    _package(c, o.filename or "", o.olepkgdata or b"", "RTF", det)
                elif o.is_ole:
                    cls = (o.class_name or b"")
                    cls = cls.decode("latin-1", "ignore") if isinstance(cls, bytes) else str(cls)
                    cls = cls.strip("\x00")
                    det.append(f"RTF: objeto OLE de clase «{cls}»")
                    if cls.lower() in EXPLOIT_CLASSES or (o.clsid or "").lower() in EXPLOIT_CLASSES:
                        c.feat("ole_exploit_class")
                    if o.oledata:
                        c.add_blob(f"RTF/{cls}", o.oledata)
                        _ole_inspect(c, o.oledata, f"RTF/{cls}", det)
        except Exception as e:
            det.append(f"No se pudo analizar el RTF ({type(e).__name__})")
    f = c.features
    if f.get("ole_package_exe"):
        c.findings.append(_f("ole_package_exe", "ransomware", "alta", "Objeto OLE de tipo paquete con un programa o script.",
                             "El documento trae un programa escondido como si fuera un adjunto."))
    if f.get("ole_exploit_class"):
        c.findings.append(_f("ole_exploit_class", "ransomware", "alta", "Objeto OLE de una clase usada en exploits de Office.",
                             "El documento trae un objeto usado en ataques conocidos contra Office."))
    if f.get("xlm_macros"):
        c.findings.append(_f("xlm_macros", "ransomware", "alta", "Hoja de macros Excel 4.0 (XLM).",
                             "La hoja de cálculo trae macros antiguas que se usan para esconder ataques."))
    if f.get("vba_stomping"):
        c.findings.append(_f("vba_stomping", "ransomware", "alta", "VBA stomping (código compilado distinto del fuente).",
                             "Las macros esconden su verdadero código."))
    if f.get("office_encrypted"):
        c.findings.append(_f("office_encrypted", "ransomware", "media", "Documento de Office cifrado con contraseña.",
                             "El documento viene con contraseña y no se pudo revisar por dentro."))
    bad = any(f.get(k) for k in ("ole_package_exe", "ole_exploit_class", "xlm_macros", "vba_stomping"))
    warn = any(f.get(k) for k in ("vba_ioc", "vba_obfuscation", "office_encrypted", "ole_objects"))
    if bad:
        return _result("macros_ole", "alerta", "Encontró macros u objetos incrustados peligrosos.", det)
    if warn or det:
        return _result("macros_ole", "aviso" if warn else "ok",
                       "Hay macros u objetos incrustados; revise el detalle." if warn else
                       "Sin macros peligrosas ni objetos incrustados sospechosos.", det)
    return _result("macros_ole", "ok", "Sin macros ni objetos incrustados.", det)


# ------------------------------------------------------------------ 4. PDF activo
def _pdf_action_kind(obj: str) -> set[str]:
    out = set()
    if re.search(r"/S\s*/JavaScript|/JS[\s(<\[]|/JS\s*\d", obj):
        out.add("javascript")
    if re.search(r"/S\s*/Launch|/Launch\b", obj):
        out.add("launch")
    return out


def _pdf_resolved(doc, t: str, v: str) -> str:
    """Texto de un valor del PDF con sus referencias directas resueltas (un nivel)."""
    if t == "xref":
        v = doc.xref_object(int(v.split()[0]), compressed=True)
    for ref in re.findall(r"(\d+)\s+0\s+R", v)[:20]:
        try:
            v += " " + doc.xref_object(int(ref), compressed=True)
        except Exception:
            pass
    return v


def control_pdf_activo(c: _Ctx) -> dict:
    if c.real != "pdf":
        return _result("pdf_activo", "no_aplica", "No es un PDF.")
    try:
        import pymupdf
    except ImportError:  # pragma: no cover
        import fitz as pymupdf  # type: ignore
    det: list[str] = []
    try:
        doc = pymupdf.open(stream=c.data, filetype="pdf")
    except Exception as e:
        c.feat("pdf_malformed")
        c.findings.append(_f("pdf_malformed", "ransomware", "media", f"PDF dañado o manipulado ({type(e).__name__}).",
                             "El PDF está dañado o fue alterado a propósito y no se puede revisar bien."))
        return _result("pdf_activo", "aviso", "El PDF está dañado y no se pudo abrir para revisarlo.")
    if doc.needs_pass:
        c.feat("pdf_encrypted")
        c.findings.append(_f("pdf_encrypted", "ransomware", "media", "PDF cifrado con contraseña de apertura.",
                             "El PDF viene con contraseña y no se pudo revisar por dentro."))
        return _result("pdf_activo", "aviso", "El PDF tiene contraseña de apertura y no se puede inspeccionar.")
    js_codes: list[str] = []
    launch = uris = submit = 0
    autorun: set[str] = set()
    try:
        cat = doc.pdf_catalog()
        for key in ("OpenAction", "AA"):
            t, v = doc.xref_get_key(cat, key)
            if t != "null":
                autorun |= {f"{k} al abrir (/{key})" for k in _pdf_action_kind(_pdf_resolved(doc, t, v))}
        t, _ = doc.xref_get_key(cat, "Names/JavaScript")
        if t != "null":
            autorun.add("javascript al abrir (árbol /Names)")
        for page in doc:
            t, v = doc.xref_get_key(page.xref, "AA")
            if t != "null" and _pdf_action_kind(_pdf_resolved(doc, t, v)):
                autorun.add(f"acción automática en la página {page.number + 1}")
        for x in range(1, doc.xref_length()):
            try:
                obj = doc.xref_object(x, compressed=True)
            except Exception:
                continue
            kinds = _pdf_action_kind(obj)
            if "javascript" in kinds:
                m = re.search(r"/JS\s*\((.*)\)", obj, re.S)
                if m:
                    js_codes.append(m.group(1))
                else:
                    m = re.search(r"/JS\s+(\d+)\s+0\s+R", obj)
                    if m:
                        try:
                            js_codes.append(doc.xref_stream(int(m.group(1))).decode("latin-1", "ignore"))
                        except Exception:
                            pass
                    else:
                        js_codes.append(obj)
            if "launch" in kinds:
                launch += 1
            for u in re.findall(r"/URI\s*\(([^)]{4,300})\)", obj):
                c.extra_urls.append(u)
                uris += 1
            if "/SubmitForm" in obj:
                submit += 1
            if doc.xref_is_stream(x) and "/Image" not in obj and "/FontFile" not in obj:
                try:
                    st = doc.xref_stream(x)
                    if st and len(st) < 5_000_000:
                        c.add_blob(f"flujo PDF {x}", st)
                except Exception:
                    pass
        # Archivos incrustados (adjuntos del documento y anotaciones de archivo)
        attached: list[tuple[str, bytes]] = []
        for i in range(doc.embfile_count()):
            info = doc.embfile_info(i)
            attached.append((info.get("filename") or info.get("name") or f"adjunto{i}", doc.embfile_get(i)))
        for page in doc:
            for annot in page.annots() or []:
                if annot.type[1] == "FileAttachment":
                    try:
                        attached.append((annot.file_info.get("filename", "adjunto"), annot.get_file()))
                    except Exception:
                        pass
        for name, blob in attached:
            rtype = detect_type(blob, name)
            nm = analyze_name(name)
            det.append(f"Archivo incrustado «{name}» (tipo real {rtype}, {len(blob)} bytes)")
            if rtype in EXECUTABLE_REAL or nm["dangerous_ext"] or nm["double_extension"]:
                c.feat("pdf_embedded_exe")
            elif rtype in MACRO_TYPES or rtype == "ole":
                c.feat("pdf_embedded_macro")
            c.add_blob(f"adjunto PDF/{name}", blob)
            c.inner_hashes.append((name, hashlib.sha256(blob).hexdigest(), hashlib.md5(blob).hexdigest()))
    finally:
        doc.close()
    apis = sorted({a for code in js_codes for a in PDF_JS_APIS if a.lower() in code.lower()})
    if js_codes:
        det.append(f"Bloques de JavaScript: {len(js_codes)}")
    if apis:
        c.feat("pdf_js_suspicious_api", len(apis))
        det.append("Funciones de JavaScript peligrosas: " + ", ".join(apis))
    if autorun:
        det.append("Se ejecuta solo al abrir: " + "; ".join(sorted(autorun)))
        if any("javascript" in a or "launch" in a or "acción" in a for a in autorun):
            c.feat("pdf_js_autorun")
    if launch:
        det.append(f"Acciones /Launch (abrir programas): {launch}")
    if uris:
        det.append(f"Enlaces en acciones /URI: {uris}")
    if submit:
        det.append(f"Formularios que envían datos (/SubmitForm): {submit}")
    f = c.features
    if f.get("pdf_js_autorun"):
        c.findings.append(_f("pdf_js_autorun", "ransomware", "alta", "JavaScript o /Launch que se ejecuta al abrir el PDF: "
                             + "; ".join(sorted(autorun)), "El PDF ejecuta código apenas se abre."))
    if f.get("pdf_embedded_exe"):
        c.findings.append(_f("pdf_embedded_exe", "ransomware", "alta", "PDF con un programa o script incrustado.",
                             "El PDF esconde un programa adentro."))
    if f.get("pdf_embedded_macro"):
        c.findings.append(_f("pdf_embedded_macro", "ransomware", "media", "PDF con un documento de Office con macros incrustado.",
                             "El PDF trae adentro un documento con macros."))
    if any(f.get(k) for k in ("pdf_js_autorun", "pdf_embedded_exe")) or launch:
        return _result("pdf_activo", "alerta", "El PDF tiene código o programas que se activan solos.", det)
    if js_codes or apis or f.get("pdf_embedded_macro") or submit:
        return _result("pdf_activo", "aviso", "El PDF tiene contenido activo; revise el detalle.", det)
    return _result("pdf_activo", "ok", "Sin JavaScript, acciones automáticas peligrosas ni adjuntos riesgosos.", det)


# ------------------------------------------------------------------ 5. comprimidos
def _scan_zip(c: _Ctx, data: bytes, prefix: str, depth: int, plain: bool, stats: dict) -> None:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError, OSError):
        stats.setdefault("dañados", []).append(prefix)
        return
    stats["max_depth"] = max(stats.get("max_depth", 1), depth)
    infos = z.infolist()
    stats["entries"] = stats.get("entries", 0) + len(infos)
    declared = sum(i.file_size for i in infos)
    comp = sum(i.compress_size for i in infos) or 1
    ratio = declared / comp
    stats["max_ratio"] = max(stats.get("max_ratio", 0), ratio)
    stats["declared"] = stats.get("declared", 0) + declared
    for i in infos[:MAX_ENTRIES]:
        name = i.filename
        label = f"{prefix}/{name}" if prefix else name
        if i.is_dir():
            continue
        parts = name.replace("\\", "/").split("/")
        if name.startswith(("/", "\\")) or ".." in parts or re.match(r"^[A-Za-z]:", name):
            stats.setdefault("traversal", []).append(label)
        nm = analyze_name(parts[-1])
        if plain and (nm["dangerous_ext"] or nm["double_extension"] or nm["bidi_override"]):
            stats.setdefault("dangerous", []).append(label)
        elif not plain and nm["dangerous_ext"]:   # dentro de un Office no debería haber .exe, .js, .lnk…
            stats.setdefault("dangerous", []).append(label)
        if i.flag_bits & 0x1:
            stats.setdefault("encrypted", []).append(label)
            continue
        if i.file_size > MAX_ENTRY_READ or (i.compress_size and i.file_size / i.compress_size > 1000
                                             and i.file_size > 10 * 1024 * 1024):
            stats.setdefault("no_leidos", []).append(label)
            continue
        if stats["read"] + i.file_size > MAX_TOTAL_READ:
            stats.setdefault("no_leidos", []).append(label)
            continue
        try:
            blob = z.read(i)
        except Exception:
            stats.setdefault("dañados", []).append(label)
            continue
        stats["read"] += len(blob)
        rtype = detect_type(blob, parts[-1])
        if rtype in EXECUTABLE_REAL:
            stats.setdefault("executables", []).append(f"{label} ({rtype})")
        elif rtype in MACRO_TYPES or (rtype == "ole" and (b"_VBA_PROJECT" in blob or b"V\x00B\x00A\x00" in blob)):
            if plain:
                stats.setdefault("macro_docs", []).append(label)
        c.inner_hashes.append((label, hashlib.sha256(blob).hexdigest(), hashlib.md5(blob).hexdigest()))
        if rtype not in MEDIA:
            c.add_blob(label, blob)
        if rtype in {"zip"} | OOXML and depth < MAX_DEPTH:
            _scan_zip(c, blob, label, depth + 1, plain=(rtype == "zip"), stats=stats)
        elif rtype in {"zip"} | OOXML:
            stats.setdefault("no_leidos", []).append(f"{label} (demasiado anidado)")


def control_comprimidos(c: _Ctx) -> dict:
    polyglot = bool(_polyglot_entries(c))
    if c.real not in ARCHIVES | OOXML and not polyglot:
        return _result("comprimidos", "no_aplica", "No es un archivo comprimido ni un contenedor.")
    plain = c.real not in OOXML
    stats: dict = {"read": 0}
    det: list[str] = []
    if c.real in OOXML or c.real == "zip" or polyglot:
        _scan_zip(c, c.data, "", 1, plain=plain, stats=stats)
    elif c.real == "gz":
        try:
            d = zlib.decompressobj(16 + zlib.MAX_WBITS)
            blob = d.decompress(c.data, MAX_ENTRY_READ)
            stats["declared"] = len(blob) + (len(d.unconsumed_tail) * 1000 if d.unconsumed_tail else 0)
            stats["max_ratio"] = len(blob) / max(len(c.data), 1) if not d.unconsumed_tail else 10_000
            stats["entries"] = 1
            if blob[257:262] == b"ustar":
                with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
                    for m in tf.getmembers()[:MAX_ENTRIES]:
                        nm = analyze_name(m.name.rsplit("/", 1)[-1])
                        if nm["dangerous_ext"] or nm["double_extension"]:
                            stats.setdefault("dangerous", []).append(m.name)
                        if m.name.startswith("/") or ".." in m.name.split("/"):
                            stats.setdefault("traversal", []).append(m.name)
            else:
                rtype = detect_type(blob, "")
                if rtype in EXECUTABLE_REAL:
                    stats.setdefault("executables", []).append(f"contenido ({rtype})")
                c.add_blob("contenido gzip", blob)
        except (zlib.error, OSError, tarfile.TarError, EOFError) as e:
            stats.setdefault("dañados", []).append(f"gzip ({type(e).__name__})")
    else:
        c.feat("archive_uninspectable")
        det.append(f"Formato {c.real}: no se puede listar su contenido con las librerías instaladas")
    if stats.get("entries"):
        det.append(f"Entradas: {stats['entries']} · profundidad máxima: {stats.get('max_depth', 1)} · "
                   f"tamaño declarado: {stats.get('declared', 0):,} bytes · relación de compresión: "
                   f"{stats.get('max_ratio', 0):.0f}:1".replace(",", "."))
    labels = {"encrypted": "Con contraseña", "dangerous": "Nombres de programa o script",
              "executables": "Programas reales adentro", "traversal": "Rutas que escapan de la carpeta",
              "macro_docs": "Documentos con macros adentro", "no_leidos": "No revisados (tamaño o anidamiento)",
              "dañados": "Dañados"}
    for k, lab in labels.items():
        if stats.get(k):
            det.append(f"{lab}: " + ", ".join(stats[k][:10]) + (" …" if len(stats[k]) > 10 else ""))
    ratio, declared = stats.get("max_ratio", 0), stats.get("declared", 0)
    bomb_ratio = 1000 if plain else 1500
    if ratio > bomb_ratio or declared > 1024 ** 3:
        c.feat("archive_bomb")
    elif plain and ratio > 100:
        c.feat("archive_ratio_high")
    if plain and stats.get("encrypted"):
        c.feat("archive_encrypted")
    if stats.get("dangerous"):
        c.feat("archive_dangerous_entry", len(stats["dangerous"]))
    if stats.get("executables"):
        c.feat("archive_executable", len(stats["executables"]))
    if stats.get("traversal"):
        c.feat("archive_path_traversal")
    if plain and stats.get("max_depth", 1) >= MAX_DEPTH:
        c.feat("archive_nested_deep")
    if stats.get("macro_docs"):
        c.feat("archive_macro_doc")
    f = c.features
    if f.get("archive_executable") or f.get("archive_dangerous_entry"):
        c.findings.append(_f("archive_exe", "ransomware", "alta",
                             "Comprimido con programas o scripts: " + ", ".join((stats.get("executables") or stats.get("dangerous"))[:4]),
                             "El comprimido trae adentro un programa o script."))
    if f.get("archive_bomb") or f.get("archive_ratio_high"):
        c.findings.append(_f("archive_bomb", "ransomware", "alta" if f.get("archive_bomb") else "media",
                             f"Relación de compresión {ratio:.0f}:1, {declared:,} bytes declarados.",
                             "El comprimido crece de forma anormal al abrirse y podría bloquear el equipo."))
    if f.get("archive_encrypted"):
        c.findings.append(_f("archive_encrypted", "ransomware", "media",
                             "Entradas cifradas con contraseña: " + ", ".join(stats["encrypted"][:4]),
                             "El comprimido tiene contraseña, un truco común para que el antivirus no lo revise."))
    if f.get("archive_path_traversal"):
        c.findings.append(_f("archive_traversal", "ransomware", "alta", "Rutas con '..' o absolutas en el comprimido.",
                             "El comprimido intenta guardar archivos fuera de la carpeta donde se abre."))
    if f.get("archive_nested_deep"):
        c.findings.append(_f("archive_nested", "ransomware", "media", f"Comprimidos anidados {stats.get('max_depth')} niveles.",
                             "Hay comprimidos dentro de comprimidos, algo usado para esconder archivos."))
    if f.get("archive_macro_doc"):
        c.findings.append(_f("archive_macro_doc", "ransomware", "media", "Documentos con macros dentro del comprimido.",
                             "El comprimido trae documentos con macros."))
    alert = any(f.get(k) for k in ("archive_executable", "archive_dangerous_entry", "archive_bomb",
                                   "archive_path_traversal"))
    warn = any(f.get(k) for k in ("archive_encrypted", "archive_ratio_high", "archive_nested_deep",
                                  "archive_macro_doc", "archive_uninspectable")) or stats.get("dañados")
    what = "el contenedor del documento" if not plain else "el comprimido"
    if alert:
        return _result("comprimidos", "alerta", f"Encontró contenido peligroso en {what}.", det)
    if warn:
        return _result("comprimidos", "aviso", f"{what.capitalize()} tiene características para revisar.", det)
    return _result("comprimidos", "ok", f"Se revisó {what} entrada por entrada sin hallazgos.", det)


# ------------------------------------------------------------------ 6. YARA
_RULES = None
_RULES_LOCK = threading.Lock()
_RULES_ERR: str | None = None


def _rules():
    global _RULES, _RULES_ERR
    with _RULES_LOCK:
        if _RULES is None and _RULES_ERR is None:
            try:
                import yara
                files = {p.stem: str(p) for p in sorted(RULES_DIR.glob("*.yar"))}
                _RULES = yara.compile(filepaths=files) if files else None
                if _RULES is None:
                    _RULES_ERR = "no hay reglas en security/reglas"
            except ImportError:
                _RULES_ERR = "yara-python no está instalado"
            except Exception as e:
                _RULES_ERR = f"error al compilar reglas: {e}"
        return _RULES


def rules_count() -> int:
    r = _rules()
    return len(list(r)) if r is not None else 0


def control_yara(c: _Ctx) -> dict:
    rules = _rules()
    if rules is None:
        return _result("yara", "no_disponible", f"No se aplicaron reglas YARA: {_RULES_ERR}.")
    hits: dict[str, dict] = {}
    targets = [("archivo", c.data)] + c.blobs
    for label, blob in targets:
        try:
            for m in rules.match(data=blob, timeout=10):
                h = hits.setdefault(m.rule, {"meta": m.meta, "where": []})
                if len(h["where"]) < 3:
                    h["where"].append(label)
        except Exception:
            continue
    det = [f"Reglas aplicadas: {rules_count()} · objetos revisados: {len(targets)}"]
    for rule, h in sorted(hits.items(), key=lambda kv: kv[1]["meta"].get("severidad") != "alta"):
        meta = h["meta"]
        sev = meta.get("severidad", "media")
        c.feat("yara_alta" if sev == "alta" else "yara_media")
        det.append(f"{rule} ({sev}) en {', '.join(h['where'])}")
        c.findings.append(_f(f"yara_{rule}", meta.get("tipo", "ransomware"), sev,
                             f"Regla YARA {rule} en {', '.join(h['where'])}.", meta.get("claro", "Coincide con una regla de malware.")))
    if not hits:
        return _result("yara", "ok", "Ninguna regla YARA coincidió.", det)
    estado = "alerta" if c.features.get("yara_alta") else "aviso"
    return _result("yara", estado, f"Coincidieron {len(hits)} reglas: " + ", ".join(sorted(hits)) + ".", det)


# ------------------------------------------------------------------ 7. entropía
def control_entropia(c: _Ctx) -> dict:
    data = c.data[:8_000_000]
    h = shannon_entropy(data)
    block = 65536 if len(data) > 262144 else 4096
    blocks = [shannon_entropy(data[i:i + block]) for i in range(0, len(data), block) if len(data[i:i + block]) >= 512]
    hmax = max(blocks) if blocks else h
    high = sum(b > 7.2 for b in blocks) / len(blocks) if blocks else 0
    n = lambda x: f"{x:.2f}".replace(".", ",")   # noqa: E731  (coma decimal, como en el resto de la interfaz)
    det = [f"Entropía global: {n(h)} bits/byte (máximo 8)",
           f"Bloque con más entropía: {n(hmax)} · bloques casi aleatorios (>7,2): {high:.0%}"]
    reason = None
    if c.real in ("txt", "html", "script", "rtf") and len(data) > 2048 and h > 5.8:
        reason = f"un archivo de texto con entropía {n(h)} (lo normal es 4-5): probablemente trae datos codificados"
    elif c.real == "unknown" and len(data) > 1024 and h > 7.5:
        reason = f"contenido sin formato reconocible y casi aleatorio ({n(h)}): parece cifrado o empaquetado"
    elif c.real in ("exe", "elf", "macho") and h > 7.2:
        reason = f"programa con entropía {n(h)}: probablemente está empaquetado para ocultar su código"
    if reason:
        c.feat("entropy_anomaly")
        c.findings.append(_f("entropy_anomaly", "ransomware", "media", "Entropía anómala: " + reason,
                             "El archivo tiene partes cifradas o disfrazadas que no son normales en este tipo de archivo."))
        return _result("entropia", "aviso", "Entropía fuera de lo normal: " + reason + ".", det)
    note = " (es normal en imágenes, comprimidos y PDF)" if c.real in MEDIA | ARCHIVES | OOXML | {"pdf"} else ""
    return _result("entropia", "ok", f"Entropía {n(h)}, dentro de lo esperado para {c.real}{note}.", det)


# ------------------------------------------------------------------ 8. URLs
def _raw_urls(blob: bytes) -> list[str]:
    out = [m.decode("latin-1") for m in RAW_URL_RE.findall(blob[:5_000_000])]
    if b"h\x00t\x00t\x00p" in blob[:5_000_000]:   # cadenas UTF-16 (documentos OLE)
        out += [m.decode("latin-1") for m in RAW_URL_RE.findall(blob[:5_000_000].decode("utf-16le", "ignore").encode("latin-1", "ignore"))]
    return out


def _norm_url(u: str) -> str:
    u = u.strip().rstrip(".,;:)'\"]>")
    return u


def control_urls(c: _Ctx) -> dict:
    visible = {_norm_url(u) for u in c.urls}
    found = set(visible) | {_norm_url(u) for u in c.extra_urls}
    for _, blob in [("archivo", c.data)] + c.blobs:
        found |= {_norm_url(u) for u in _raw_urls(blob)}
    found = {u for u in found if u and (urlparse(u if "://" in u else "http://" + u).hostname or "")
             not in NAMESPACE_HOSTS and not any(h in u for h in NAMESPACE_HOSTS)}
    if not found:
        return _result("urls", "ok", "No contiene enlaces.")
    vis_host = {(urlparse(u if "://" in u else "http://" + u).hostname or "") for u in visible}
    hidden = sorted(u for u in found if (urlparse(u if "://" in u else "http://" + u).hostname or "") not in vis_host)
    _, f_all = analyze_urls(sorted(found))
    _, f_hidden = analyze_urls(hidden)
    if f_hidden:
        c.feat("url_hidden_suspicious", len(f_hidden))
        c.findings.append(_f("url_hidden", "phishing", "alta",
                             f"{len(f_hidden)} enlaces sospechosos que no se ven en el texto: " + ", ".join(hidden[:3]),
                             "El archivo esconde enlaces sospechosos que no aparecen a simple vista."))
    det = [f"Enlaces encontrados: {len(found)} (visibles {len(visible & found)}, ocultos en el contenido {len(hidden)})"]
    det += [fnd["tecnico"] for fnd in f_all]
    for u in sorted(found)[:25]:
        flag = any(u[:120] in t for t in (x["tecnico"] for x in f_all))
        det.append(("⚠ " if flag else "· ") + u[:160] + ("" if u in visible else "  [oculto]"))
    if f_all:
        return _result("urls", "alerta" if f_hidden or len(f_all) > 1 else "aviso",
                       f"{len(f_all)} de {len(found)} enlaces son sospechosos.", det)
    return _result("urls", "ok", f"{len(found)} enlaces revisados, ninguno sospechoso.", det)


# ------------------------------------------------------------------ 9. HTML
def _is_official(host: str) -> bool:
    reg = _registered_domain(host)
    return any(reg in doms for doms in BRANDS.values()) or host.endswith(OFFICIAL_SUFFIXES)


def control_html(c: _Ctx) -> dict:
    src = c.text if c.real in ("html", "txt") else ""
    if c.real == "txt" and not re.search(r"(?i)<(form|script|iframe|html|a\s)", src):
        src = ""
    if not src:
        return _result("html", "no_aplica", "No es una página HTML.")
    det: list[str] = []
    low = src.lower()
    forms = re.findall(r"(?is)<form\b([^>]*)>(.*?)(?:</form>|$)", src)
    pwd = re.search(r"(?i)type\s*=\s*[\"']?password", src)
    for attrs, body in forms:
        act = re.search(r"(?i)action\s*=\s*[\"']?([^\"'\s>]+)", attrs)
        target = act.group(1) if act else "(misma página)"
        det.append(f"Formulario que envía a {target}" + (" con campo de contraseña" if re.search(r"(?i)password", body) else ""))
        if act and target.lower().startswith(("http://", "https://")):
            host = (urlparse(target).hostname or "").lower()
            if not _is_official(host):
                c.feat("html_form_external")
    if pwd and forms:
        c.feat("html_password_form")
    title = re.search(r"(?is)<title>(.*?)</title>", src)
    if title:
        t = title.group(1).lower()
        brand = next((b for b in BRANDS if b in t.replace(" ", "")), None)
        if brand and (c.features.get("html_form_external") or pwd):
            c.feat("html_brand_title")
            det.append(f"El título imita a «{brand}» pero el formulario no va a su sitio oficial")
    for href, text in re.findall(r"(?is)<a\b[^>]*href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", src)[:200]:
        shown = re.sub(r"<[^>]+>", "", text).strip()
        m = re.search(r"(?i)((?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,})", shown)
        if m and href.lower().startswith("http"):
            h_shown = (urlparse(m.group(1) if "://" in m.group(1) else "http://" + m.group(1)).hostname or "").lower()
            h_real = (urlparse(href).hostname or "").lower()
            if h_shown and h_real and _registered_domain(h_shown) != _registered_domain(h_real):
                c.feat("url_text_mismatch")
                det.append(f"Enlace que muestra «{h_shown}» pero lleva a «{h_real}»")
    if re.search(r"(?i)<meta[^>]+http-equiv\s*=\s*[\"']?refresh[^>]+url\s*=\s*https?://", src):
        c.feat("html_meta_refresh")
        det.append("Redirección automática a otro sitio (meta refresh)")
    if re.search(r"(?is)<iframe\b[^>]*(width\s*=\s*[\"']?0|height\s*=\s*[\"']?0|display\s*:\s*none|visibility\s*:\s*hidden)", src):
        c.feat("html_hidden_iframe")
        det.append("Marco (iframe) oculto que carga otra página")
    n_scripts = len(re.findall(r"(?i)<script\b", low))
    if n_scripts:
        det.append(f"Bloques <script>: {n_scripts}")
    f = c.features
    if f.get("html_password_form"):
        c.findings.append(_f("html_password_form", "phishing", "alta", "Formulario HTML con campo de contraseña.",
                             "Es una página falsa que pide su usuario y contraseña."))
    if f.get("url_text_mismatch"):
        c.findings.append(_f("url_text_mismatch", "phishing", "alta", "El texto del enlace no coincide con su destino.",
                             "Un enlace muestra una dirección pero lleva a otra distinta."))
    if f.get("html_hidden_iframe") or f.get("html_meta_refresh"):
        c.findings.append(_f("html_redirect", "phishing", "media", "Redirección automática o iframe oculto.",
                             "La página lo lleva a otro sitio sin que usted lo note."))
    if any(f.get(k) for k in ("html_password_form", "url_text_mismatch", "html_hidden_iframe")):
        return _result("html", "alerta", "La página tiene elementos típicos de suplantación.", det)
    if any(f.get(k) for k in ("html_form_external", "html_meta_refresh")):
        return _result("html", "aviso", "La página envía datos o redirige a otro sitio.", det)
    return _result("html", "ok", "Página sin formularios de credenciales ni redirecciones ocultas.", det)


# ------------------------------------------------------------------ 10. ingeniería social
def control_ingenieria_social(c: _Ctx) -> dict:
    low = c.text.lower()
    if not low.strip():
        return _result("ingenieria_social", "no_aplica", "El archivo no tiene texto que revisar.")
    hits = [p for p in CRED_PHRASES if p in low]
    urls = c.urls + c.extra_urls
    risky, suspicious = [], []
    for u in urls:
        host = (urlparse(u if "://" in u else "http://" + u).hostname or "").lower()
        if host and not _is_official(host):
            risky.append(host + (" (acortador)" if host in SHORTENERS else ""))
            if analyze_urls([u])[1]:
                suspicious.append(host)
    det = []
    if hits:
        det.append("Frases que piden datos o presionan: " + ", ".join(hits[:8]))
    if risky:
        det.append("Enlaces a sitios no oficiales: " + ", ".join(sorted(set(risky))[:8]))
    det.append(f"Longitud del texto: {len(low):,} caracteres".replace(",", "."))
    # Pide datos + enlace sospechoso, o pide datos + enlace no oficial en un mensaje corto (señuelo)
    if hits and (suspicious or (risky and len(low) <= SHORT_TEXT)):
        c.feat("cred_request_link")
        c.findings.append(_f("cred_request_link", "phishing", "alta",
                             f"Pide datos ({', '.join(hits[:3])}) y da un enlace no oficial ({risky[0]}).",
                             "El documento le pide claves o datos y lo manda a un enlace que no es del sitio oficial."))
        return _result("ingenieria_social", "alerta", "Pide claves o datos y ofrece un enlace no oficial para darlos.", det)
    if hits:
        return _result("ingenieria_social", "ok", "Menciona claves o datos, pero no los pide a través de un enlace "
                       "sospechoso.", det)
    return _result("ingenieria_social", "ok", "No pide claves ni datos bancarios.", det)


# ------------------------------------------------------------------ orquestación
ORDER = [control_comprimidos, control_macros_ole, control_pdf_activo, control_tipo_real, control_hashes,
         control_html, control_urls, control_ingenieria_social, control_entropia, control_yara]


def run_controls(data: bytes, filename: str, static: dict, extracted: dict, signatures=None) -> dict:
    """Ejecuta todos los controles. Devuelve ``{"controls", "features", "findings", "urls"}``.

    El orden de ejecución importa (los desempaquetadores alimentan a YARA, URL y
    hashes); el orden de presentación es el de ``NAMES``.
    """
    c = _Ctx(data, filename, static, extracted.get("text", ""), list(extracted.get("urls", [])), signatures)
    results = {}
    for fn in ORDER:
        cid = fn.__name__.removeprefix("control_")
        try:
            results[cid] = fn(c)
        except Exception as e:   # un control que falla no detiene el protocolo, pero queda registrado
            results[cid] = _result(cid, "error", f"El control falló: {type(e).__name__}: {e}")
    controls = [results[k] for k in NAMES]
    return {"controls": controls, "features": c.features, "findings": c.findings,
            "urls": sorted(set(c.extra_urls))}


def attach_points(controls: list[dict], contributions: list) -> None:
    """Suma a cada control los puntos de riesgo que aportaron sus indicadores."""
    pts = dict((k, v) for k, v in contributions)
    for ctl in controls:
        ctl["puntos"] = int(sum(pts.get(k, 0) for k in OWNS.get(ctl["id"], [])))
        ctl["indicadores"] = [[k, pts[k]] for k in OWNS.get(ctl["id"], []) if k in pts]
        if ctl["puntos"] and ctl["estado"] == "ok":
            ctl["estado"] = "aviso"
