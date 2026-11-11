#!/usr/bin/env python3
"""Importa una lista de huellas de malware conocido a ``data/firmas/``.

    python scripts/actualizar_firmas.py ruta/al/archivo.csv [--nombre malwarebazaar]
    python scripts/actualizar_firmas.py https://.../lista.txt  [--nombre abusech]

Acepta las exportaciones gratuitas de MalwareBazaar (CSV con columnas
``first_seen_utc, sha256_hash, md5_hash, sha1_hash, …, signature``, también
dentro de un .zip) y listas de texto con una huella por línea (``hash`` o
``hash;familia``; SHA-256, SHA-1 o MD5). El resultado queda normalizado como
``data/firmas/<nombre>.txt`` y el control «hashes» lo usa al reiniciar FileMind
(o al llamar ``SignatureRepository.reload()``). No requiere claves ni servicios
de pago; la descarga por URL es opcional y solo ocurre si se pasa una URL.
"""
from __future__ import annotations

import argparse
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from filemind.config import load_settings                 # noqa: E402
from filemind.security.signatures import _parse_line      # noqa: E402


def read_source(src: str) -> bytes:
    if src.startswith(("http://", "https://")):
        with urllib.request.urlopen(src, timeout=60) as r:
            return r.read()
    return Path(src).read_bytes()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("origen", help="archivo local o URL (.txt, .csv o .zip)")
    ap.add_argument("--nombre", default=None, help="nombre de la lista en data/firmas/ (por defecto, el del archivo)")
    a = ap.parse_args()
    raw = read_source(a.origen)
    texts = []
    if raw[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            texts = [z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.lower().endswith((".csv", ".txt"))]
    else:
        texts = [raw.decode("utf-8", "ignore")]
    seen: dict[str, str] = {}
    for t in texts:
        for line in t.splitlines():
            h, fam = _parse_line(line)
            if h and h not in seen:
                seen[h] = fam or ""
    if not seen:
        sys.exit("No se encontró ninguna huella válida en el origen.")
    s = load_settings()
    out_dir = s.data_dir / "firmas"
    out_dir.mkdir(parents=True, exist_ok=True)
    name = a.nombre or Path(a.origen.split("?")[0]).stem or "lista"
    out = out_dir / f"{name}.txt"
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(f"# importado de {a.origen}\n")
        for h, fam in seen.items():
            fh.write(f"{h};{fam}\n" if fam else f"{h}\n")
    print(f"{len(seen)} huellas guardadas en {out}. Reinicia FileMind para usarlas.")


if __name__ == "__main__":
    main()
