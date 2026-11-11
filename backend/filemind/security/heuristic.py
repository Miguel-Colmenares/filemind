"""Fase 2 — Análisis heurístico (RF6).

Busca en el contenido extraído patrones de:

* **Phishing**: URLs sospechosas (IP directa, acortadores, punycode, TLD de
  alto abuso, suplantación de marcas, dominios recientes vía RDAP opcional) y
  lenguaje de urgencia/robo de credenciales.
* **Ransomware**: macros con autoejecución, llamadas peligrosas en VBA,
  acciones automáticas/JavaScript en PDF, scripts ofuscados, DDE, inyección
  de plantillas remotas y notas de rescate.

Cada hallazgo lleva una explicación técnica y otra en lenguaje claro (RNF7).
"""
from __future__ import annotations

import io
import ipaddress
import json
import math
import re
import threading
import urllib.request
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

SHORTENERS = {"bit.ly", "tinyurl.com", "goo.gl", "t.co", "ow.ly", "is.gd", "cutt.ly",
              "rebrand.ly", "shorturl.at", "rb.gy", "tiny.cc", "acortar.link", "s.id"}
RISKY_TLDS = {"xyz", "top", "tk", "ml", "ga", "cf", "gq", "zip", "mov", "click", "monster",
              "rest", "cyou", "icu", "buzz", "live", "shop", "work", "support", "cam", "sbs"}
# Marca -> dominios oficiales
BRANDS = {
    "bancolombia": {"bancolombia.com", "grupobancolombia.com"},
    "davivienda": {"davivienda.com"},
    "bbva": {"bbva.com.co", "bbva.com"},
    "nequi": {"nequi.com.co"},
    "daviplata": {"daviplata.com"},
    "dian": {"dian.gov.co"},
    "microsoft": {"microsoft.com", "live.com", "office.com", "microsoftonline.com"},
    "office365": {"office.com", "microsoftonline.com"},
    "outlook": {"outlook.com", "live.com", "office.com"},
    "whatsapp": {"whatsapp.com", "whatsapp.net"},
    "paypal": {"paypal.com"},
    "google": {"google.com", "google.com.co"},
}
CRED_PATH = re.compile(r"(?i)(login|signin|verify|verific|update|actualiz|secure|account|cuenta|password|clave|wp-admin|confirm)")

PHISH_PHRASES = [
    "verifique su cuenta", "verifica tu cuenta", "su cuenta ha sido suspendida",
    "tu cuenta será bloqueada", "cuenta bloqueada", "actualice sus datos", "actualiza tus datos",
    "ingrese su contraseña", "ingresa tu contraseña", "confirme su identidad", "haga clic aquí",
    "haz clic aquí", "de inmediato", "en las próximas 24 horas", "urgente", "pago pendiente",
    "factura vencida", "evite la suspensión", "datos bancarios", "clave dinámica",
    "número de tarjeta", "código de verificación", "premio", "ha sido seleccionado",
]
RANSOM_PHRASES = [
    "sus archivos han sido cifrados", "tus archivos han sido cifrados", "your files have been encrypted",
    "bitcoin", "monero", "rescate", "ransom", "decrypt", "descifrar", ".onion", "tor browser",
    "clave privada para recuperar",
]
VBA_AUTOEXEC = ["autoopen", "auto_open", "document_open", "workbook_open", "autoexec",
                "autoclose", "document_close", "auto_close", "presentation_open", "workbook_activate"]
VBA_SUSPICIOUS = ["shell", "wscript.shell", "createobject", "powershell", "urldownloadtofile",
                  "xmlhttp", "adodb.stream", "environ", "callbyname", "strreverse", "chr(",
                  "frombase64string", "-enc", "vssadmin", "bcdedit", "cipher /w", "kill ",
                  "savetofile", "run(", "shellexecute", "getobject(", "winmgmts", "cmd.exe"]
PDF_KEYS = {
    "/JavaScript": "pdf_javascript", "/JS": "pdf_javascript", "/OpenAction": "pdf_openaction",
    "/AA": "pdf_autoaction", "/Launch": "pdf_launch", "/EmbeddedFile": "pdf_embedded",
    "/RichMedia": "pdf_richmedia", "/XFA": "pdf_xfa", "/SubmitForm": "pdf_submitform",
}
B64_RE = re.compile(rb"[A-Za-z0-9+/]{200,}={0,2}")
JS_OBF_RE = re.compile(r"(?i)(eval\s*\(|unescape\s*\(|fromcharcode|atob\s*\(|\\x[0-9a-f]{2}\\x[0-9a-f]{2})")
PS_RE = re.compile(r"(?i)(powershell(\.exe)?\s+[^\n]{0,40}-(e|en|enc|encodedcommand)\b|iex\s*\(|invoke-expression|downloadstring)")


def shannon_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = Counter(data)
    n = len(data)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


# ------------------------------------------------------------------ RDAP opcional
class DomainAgeLookup:
    """Consulta la fecha de registro de un dominio vía RDAP (con caché).

    Desactivado por defecto: requiere red. Un dominio con menos de 30 días se
    marca como "dominio reciente" (indicador típico de phishing).
    """

    def __init__(self, cache_path: Path | None = None, enabled: bool = False, timeout: float = 2.5):
        self.enabled, self.timeout = enabled, timeout
        self.cache_path = cache_path
        self._lock = threading.Lock()
        self._cache: dict[str, int | None] = {}
        if cache_path and cache_path.exists():
            try:
                self._cache = json.loads(cache_path.read_text())
            except ValueError:
                pass

    def age_days(self, domain: str) -> int | None:
        if domain in self._cache:
            return self._cache[domain]
        if not self.enabled:
            return None
        age = None
        try:
            with urllib.request.urlopen(f"https://rdap.org/domain/{domain}", timeout=self.timeout) as r:
                data = json.loads(r.read())
            for ev in data.get("events", []):
                if ev.get("eventAction") == "registration":
                    reg = datetime.fromisoformat(ev["eventDate"].replace("Z", "+00:00"))
                    age = (datetime.now(timezone.utc) - reg).days
        except Exception:
            age = None
        with self._lock:
            self._cache[domain] = age
            if self.cache_path:
                self.cache_path.write_text(json.dumps(self._cache))
        return age


def _registered_domain(host: str) -> str:
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in ("com", "gov", "edu", "org", "net", "co") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def analyze_urls(urls: list[str], domain_age: DomainAgeLookup | None = None) -> tuple[dict, list[dict]]:
    f = Counter()
    findings: list[dict] = []
    for raw in urls[:200]:
        u = raw if "://" in raw else "http://" + raw
        try:
            p = urlparse(u)
            host = (p.hostname or "").lower()
        except ValueError:
            continue
        if not host:
            continue
        f["url_count"] += 1
        reasons = []
        try:
            ipaddress.ip_address(host)
            f["url_ip_host"] += 1
            reasons.append("usa una dirección IP en vez de un nombre")
        except ValueError:
            pass
        if host in SHORTENERS:
            f["url_shortener"] += 1
            reasons.append("es un enlace acortado que oculta el destino")
        if "xn--" in host:
            f["url_punycode"] += 1
            reasons.append("usa caracteres que imitan letras normales (punycode)")
        tld = host.rsplit(".", 1)[-1]
        if tld in RISKY_TLDS:
            f["url_risky_tld"] += 1
            reasons.append(f"termina en '.{tld}', muy usado en fraudes")
        if "@" in (p.netloc or ""):
            f["url_at_sign"] += 1
            reasons.append("contiene '@' para disfrazar el destino real")
        if host.count(".") >= 4:
            f["url_many_subdomains"] += 1
        if p.scheme == "http":
            f["url_no_tls"] += 1
        if CRED_PATH.search(p.path or "") or CRED_PATH.search(host):
            f["url_credential_path"] += 1
        reg = _registered_domain(host)
        for brand, official in BRANDS.items():
            if brand in host and reg not in official:
                f["url_brand_impersonation"] += 1
                reasons.append(f"menciona a '{brand}' pero no es su sitio oficial")
                break
        if domain_age is not None:
            age = domain_age.age_days(reg)
            if age is not None and age < 30:
                f["url_recent_domain"] += 1
                reasons.append(f"el dominio se registró hace solo {age} días")
        if reasons:
            findings.append({
                "id": "phishing_url", "kind": "phishing", "severity": "alta" if len(reasons) > 1 else "media",
                "tecnico": f"URL sospechosa {raw[:120]}: " + "; ".join(reasons),
                "claro": f"El archivo contiene un enlace que {reasons[0]}.",
            })
    return dict(f), findings


# --------------------------------------------------------------------- macros
def _vba_source(data: bytes, real_type: str) -> str | None:
    """Devuelve el código VBA (texto) si el archivo contiene macros."""
    blob = None
    if real_type in ("docm", "xlsm", "pptm", "docx", "xlsx", "pptx"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for n in z.namelist():
                    if n.lower().endswith("vbaproject.bin"):
                        blob = z.read(n)
                        break
        except zipfile.BadZipFile:
            return None
        if blob is None:
            return None
    elif real_type == "ole":
        if b"_VBA_PROJECT" not in data and b"V\x00B\x00A\x00" not in data and b"Attribute VB_" not in data:
            return None
        blob = data
    else:
        return None
    try:  # decompresión real de VBA con oletools, si está instalado
        from oletools.olevba import VBA_Parser
        vp = VBA_Parser("f", data=data)
        if vp.detect_vba_macros():
            code = "\n".join(c for (_, _, _, c) in vp.extract_macros())
            vp.close()
            if code.strip():
                return code
        vp.close()
    except Exception:
        pass
    return blob.decode("latin-1", "ignore")


def analyze_macros(data: bytes, real_type: str) -> tuple[dict, list[dict]]:
    src = _vba_source(data, real_type)
    if src is None:
        return {"has_macros": 0, "macro_autoexec": 0, "macro_suspicious": 0}, []
    low = src.lower()
    auto = [k for k in VBA_AUTOEXEC if k in low]
    sus = [k for k in VBA_SUSPICIOUS if k in low]
    findings = [{
        "id": "macros", "kind": "ransomware", "severity": "media",
        "tecnico": "Contiene proyecto VBA (macros).",
        "claro": "El documento trae macros, pequeños programas que pueden ejecutarse al abrirlo.",
    }]
    if auto:
        findings.append({
            "id": "macro_autoexec", "kind": "ransomware", "severity": "alta",
            "tecnico": "Macro con autoejecución: " + ", ".join(auto),
            "claro": "Las macros están configuradas para ejecutarse solas apenas se abra el archivo.",
        })
    if sus:
        findings.append({
            "id": "macro_suspicious", "kind": "ransomware", "severity": "alta",
            "tecnico": "Llamadas peligrosas en VBA: " + ", ".join(sus[:8]),
            "claro": "Las macros intentan ejecutar comandos del sistema o descargar algo de internet.",
        })
    return {"has_macros": 1, "macro_autoexec": len(auto), "macro_suspicious": len(sus)}, findings


# ------------------------------------------------------------------------ PDF
def analyze_pdf(data: bytes) -> tuple[dict, list[dict]]:
    f = Counter()
    # nombres ofuscados con #xx (p.ej. /J#61vaScript) se normalizan antes de contar
    norm = re.sub(rb"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), data)
    f["pdf_hex_obfuscation"] = int(norm != data and re.search(rb"/[A-Za-z]*#[0-9A-Fa-f]{2}", data) is not None)
    for key, feat in PDF_KEYS.items():
        f[feat] += len(re.findall(re.escape(key.encode()) + rb"(?![A-Za-z])", norm))
    f["pdf_objects"] = len(re.findall(rb"\bobj\b", data))
    findings = []
    if f["pdf_javascript"]:
        findings.append({"id": "pdf_js", "kind": "ransomware", "severity": "alta",
                         "tecnico": f"PDF con JavaScript embebido ({f['pdf_javascript']} referencias).",
                         "claro": "El PDF trae código oculto que se ejecuta dentro del lector."})
    if f["pdf_openaction"] or f["pdf_autoaction"]:
        findings.append({"id": "pdf_autoaction", "kind": "ransomware", "severity": "media",
                         "tecnico": "PDF con acciones automáticas (/OpenAction o /AA).",
                         "claro": "El PDF intenta hacer algo automáticamente al abrirse."})
    if f["pdf_launch"]:
        findings.append({"id": "pdf_launch", "kind": "ransomware", "severity": "alta",
                         "tecnico": "PDF con acción /Launch (ejecución de programas).",
                         "claro": "El PDF intenta abrir o ejecutar otro programa en su computador."})
    if f["pdf_embedded"]:
        findings.append({"id": "pdf_embedded", "kind": "ransomware", "severity": "media",
                         "tecnico": "PDF con archivos incrustados (/EmbeddedFile).",
                         "claro": "El PDF esconde otros archivos adentro."})
    if f["pdf_hex_obfuscation"]:
        findings.append({"id": "pdf_obfuscation", "kind": "ransomware", "severity": "alta",
                         "tecnico": "Nombres de objetos PDF ofuscados con codificación #xx.",
                         "claro": "El PDF usa trucos para ocultar lo que hace."})
    return dict(f), findings


# -------------------------------------------------------------------- OOXML
def analyze_ooxml(data: bytes) -> tuple[dict, list[dict]]:
    f = Counter()
    findings = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos = z.infolist()
            total = sum(i.file_size for i in infos)
            comp = sum(i.compress_size for i in infos) or 1
            f["zip_ratio"] = round(total / comp, 1)
            for i in infos:
                n = i.filename.lower()
                if n.endswith(".rels"):
                    xml = z.read(i).decode("utf-8", "ignore")
                    if re.search(r'attachedTemplate"[^>]*Target="https?://', xml) or \
                       re.search(r'Target="https?://[^"]+\.(dotm|docm|xlsm)"', xml):
                        f["remote_template"] += 1
                if n.startswith(("word/", "xl/", "ppt/")) and n.endswith(".xml") and i.file_size < 20_000_000:
                    xml = z.read(i).decode("utf-8", "ignore")
                    if re.search(r"(?i)DDEAUTO|\bDDE\b\s", xml):
                        f["dde"] += 1
                if n.startswith(("word/embeddings", "xl/embeddings", "ppt/embeddings")) or "oleobject" in n:
                    f["ole_objects"] += 1
    except zipfile.BadZipFile:
        return {}, []
    if f["remote_template"]:
        findings.append({"id": "remote_template", "kind": "ransomware", "severity": "alta",
                         "tecnico": "Inyección de plantilla remota en relaciones OOXML.",
                         "claro": "El documento descarga contenido de internet al abrirse."})
    if f["dde"]:
        findings.append({"id": "dde", "kind": "ransomware", "severity": "alta",
                         "tecnico": "Campo DDE/DDEAUTO que puede ejecutar comandos.",
                         "claro": "El documento intenta ejecutar comandos mediante un campo oculto."})
    if f["ole_objects"]:
        findings.append({"id": "ole_objects", "kind": "ransomware", "severity": "media",
                         "tecnico": f"{f['ole_objects']} objetos OLE incrustados.",
                         "claro": "El documento tiene otros archivos o programas incrustados."})
    if f["zip_ratio"] > 100:
        findings.append({"id": "zip_bomb", "kind": "ransomware", "severity": "media",
                         "tecnico": f"Relación de compresión anómala ({f['zip_ratio']}:1).",
                         "claro": "El archivo está inflado artificialmente para saturar el equipo."})
    return dict(f), findings


# ------------------------------------------------------------------ principal
def run_heuristic(data: bytes, real_type: str, text: str, urls: list[str],
                  domain_age: DomainAgeLookup | None = None) -> dict:
    feats: dict = {}
    findings: list[dict] = []

    uf, ufind = analyze_urls(urls, domain_age)
    feats.update(uf)
    findings += ufind

    low = (text or "").lower()
    phish_hits = [p for p in PHISH_PHRASES if p in low]
    ransom_hits = [p for p in RANSOM_PHRASES if p in low]
    feats["phish_phrases"] = len(phish_hits)
    feats["ransom_phrases"] = len(ransom_hits)
    if len(phish_hits) >= 2:
        findings.append({"id": "phishing_text", "kind": "phishing", "severity": "media",
                         "tecnico": "Lenguaje de urgencia/credenciales: " + ", ".join(phish_hits[:6]),
                         "claro": "El texto presiona para actuar con urgencia o pide datos personales o bancarios."})
    if ransom_hits:
        findings.append({"id": "ransom_note", "kind": "ransomware", "severity": "alta",
                         "tecnico": "Texto típico de nota de rescate: " + ", ".join(ransom_hits[:6]),
                         "claro": "El contenido se parece a una nota de secuestro de archivos (ransomware)."})

    mf, mfind = analyze_macros(data, real_type)
    feats.update(mf)
    findings += mfind

    if real_type == "pdf":
        pf, pfind = analyze_pdf(data)
        feats.update(pf)
        findings += pfind
    if real_type in ("docx", "xlsx", "pptx", "docm", "xlsm", "pptm"):
        of, ofind = analyze_ooxml(data)
        feats.update(of)
        findings += ofind

    b64 = B64_RE.findall(data[:5_000_000])
    feats["long_base64"] = len(b64)
    feats["js_obfuscation"] = len(JS_OBF_RE.findall(text or "")) + len(JS_OBF_RE.findall(data[:2_000_000].decode("latin-1", "ignore")))
    feats["powershell"] = len(PS_RE.findall(text or "")) + len(PS_RE.findall(data[:2_000_000].decode("latin-1", "ignore")))
    feats["entropy"] = round(shannon_entropy(data[:1_000_000]), 3)
    if feats["powershell"]:
        findings.append({"id": "powershell", "kind": "ransomware", "severity": "alta",
                         "tecnico": "Comandos PowerShell codificados o de descarga.",
                         "claro": "El archivo contiene instrucciones para ejecutar comandos en Windows."})
    if feats["js_obfuscation"] >= 2 or feats["long_base64"] >= 3:
        findings.append({"id": "obfuscated_script", "kind": "ransomware", "severity": "media",
                         "tecnico": f"Posible script ofuscado (patrones={feats['js_obfuscation']}, base64 largos={feats['long_base64']}).",
                         "claro": "El archivo contiene código escondido o disfrazado."})
    return {"features": feats, "findings": findings}
