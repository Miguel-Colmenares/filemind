#!/usr/bin/env python3
"""Trabajador de la Fase 3 (entorno aislado).

Se ejecuta DENTRO del sandbox (contenedor Docker sin red y de solo lectura, o
proceso con espacio de red propio y límites de recursos). Solo usa la
biblioteca estándar para que funcione en una imagen mínima.

Hace un "análisis dinámico" acotado al alcance del proyecto: desempaqueta y
decodifica el contenido real del archivo (flujos PDF comprimidos, entradas
ZIP/OOXML, blobs base64) y observa qué aparece una vez expandido, que es donde
el malware suele esconderse. También sondea el propio aislamiento (red y
escritura en disco) para evidenciar el RNF5.

Salida: un JSON en stdout.
"""
import base64
import io
import json
import signal
import re
import socket
import sys
import time
import zipfile
import zlib

MAX_EXPANDED = 200 * 1024 * 1024       # 200 MB descomprimidos como máximo
PE_RE = re.compile(rb"MZ.{58,300}?This program cannot be run", re.S)
URL_RE = re.compile(rb"https?://[^\s<>\"')\]]{4,200}")
JS_ACTIONS = [b"app.launchURL", b"this.exportDataObject", b"util.printf", b"getAnnots",
              b"eval(", b"unescape(", b"String.fromCharCode", b"app.openDoc", b"submitForm",
              b"/Launch", b"/JavaScript", b"WScript", b"ActiveXObject", b"cmd.exe", b"powershell"]
RANSOM = [b"vssadmin", b"delete shadows", b"bcdedit", b"cipher /w", b".encrypted", b"bitcoin",
          b"your files", b"sus archivos", b"CryptEncrypt", b"CryptoAPI", b"wbadmin"]
B64_RE = re.compile(rb"[A-Za-z0-9+/]{120,}={0,2}")


def probe_isolation():
    net_blocked = True
    try:
        s = socket.create_connection(("1.1.1.1", 53), timeout=1.0)
        s.close()
        net_blocked = False
    except OSError:
        pass
    fs_blocked = True
    for target in ("/filemind_probe", "/etc/filemind_probe", "filemind_probe_cwd"):
        try:
            with open(target, "wb") as fh:
                fh.write(b"x")
                fh.flush()
            fs_blocked = False
        except (OSError, ValueError):
            pass
    return {"network_blocked": net_blocked, "fs_write_blocked": fs_blocked}


def scan_blob(blob, obs):
    if PE_RE.search(blob):
        obs["embedded_executables"] += 1
    for k in JS_ACTIONS:
        if k.lower() in blob.lower():
            obs["active_content"].add(k.decode())
    for k in RANSOM:
        if k.lower() in blob.lower():
            obs["ransomware_markers"].add(k.decode())
    for u in URL_RE.findall(blob)[:50]:
        obs["urls"].add(u.decode("latin-1")[:200])
    for b in B64_RE.findall(blob)[:20]:
        try:
            dec = base64.b64decode(b + b"=" * (-len(b) % 4), validate=False)
        except Exception:
            continue
        obs["decoded_base64"] += 1
        if dec.startswith(b"MZ") or b"This program cannot be run" in dec:
            obs["embedded_executables"] += 1
        low = dec.lower()
        if b"powershell" in low or b"iex" in low or b"invoke-" in low or b"\x00i\x00e\x00x" in low:
            obs["hidden_scripts"] += 1


def expand_pdf(data, obs):
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        obs["streams"] += 1
        raw = m.group(1)
        try:
            dec = zlib.decompress(raw)
            obs["streams_decoded"] += 1
        except zlib.error:
            dec = raw
        obs["expanded_bytes"] += len(dec)
        if obs["expanded_bytes"] > MAX_EXPANDED:
            obs["expansion_limit_hit"] = True
            return
        scan_blob(dec, obs)
        if b"/Type" in dec and b"/ObjStm" not in dec and (b"/JavaScript" in dec or b"/Launch" in dec):
            obs["hidden_in_object_streams"] = True


def expand_zip(data, obs, depth=0):
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        obs["corrupt"] = True
        return
    for info in z.infolist():
        obs["entries"] += 1
        if obs["expanded_bytes"] + info.file_size > MAX_EXPANDED:
            obs["expansion_limit_hit"] = True
            return
        try:
            blob = z.read(info)
        except Exception:
            obs["corrupt"] = True
            continue
        obs["expanded_bytes"] += len(blob)
        scan_blob(blob, obs)
        if blob[:4] == b"PK\x03\x04" and depth < 2:
            obs["nested_archives"] += 1
            expand_zip(blob, obs, depth + 1)


def main():
    if hasattr(signal, "SIGXFSZ"):
        signal.signal(signal.SIGXFSZ, signal.SIG_IGN)   # escribir falla con error en vez de matar
    path = sys.argv[1]
    t0 = time.time()
    with open(path, "rb") as fh:
        data = fh.read()
    obs = {"streams": 0, "streams_decoded": 0, "entries": 0, "expanded_bytes": 0,
           "embedded_executables": 0, "decoded_base64": 0, "hidden_scripts": 0,
           "nested_archives": 0, "active_content": set(), "ransomware_markers": set(),
           "urls": set(), "hidden_in_object_streams": False, "expansion_limit_hit": False,
           "corrupt": False}
    if data.startswith(b"%PDF"):
        expand_pdf(data, obs)
    elif data.startswith(b"PK"):
        expand_zip(data, obs)
    scan_blob(data, obs)
    obs["isolation_probe"] = probe_isolation()
    obs["elapsed_s"] = round(time.time() - t0, 3)
    for k in ("active_content", "ransomware_markers", "urls"):
        obs[k] = sorted(obs[k])
    sys.stdout.write(json.dumps(obs))


if __name__ == "__main__":
    main()
