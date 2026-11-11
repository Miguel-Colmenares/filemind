"""RF5 — Repositorio de firmas de malware conocidas.

Orden de consulta:
1. Base local ``data/firmas_malware.txt`` (una línea ``hash[;familia]``) y
   cualquier lista ``.txt``/``.csv`` dentro de ``data/firmas/`` (por ejemplo
   las exportaciones gratuitas de MalwareBazaar, ver
   ``scripts/actualizar_firmas.py``). Se aceptan SHA-256, SHA-1 y MD5.
2. Caché de respuestas previas de APIs externas.
3. MalwareBazaar y/o VirusTotal, solo si hay clave configurada (limitación
   documentada: depende de la disponibilidad de APIs externas).

Cada consulta devuelve un registro con la fuente y la respuesta, que el
pipeline guarda en la auditoría.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Archivo de prueba estándar EICAR (inofensivo, reconocido por todos los antivirus)
EICAR_SHA256 = "275a021bbfb6489e54d471899f7db9d1663fc695ec2fe2a2c4538aabf651fd0f"


HASH_LEN = {32: "MD5", 40: "SHA-1", 64: "SHA-256"}
_HEX = set("0123456789abcdef")


def _parse_line(line: str) -> tuple[str | None, str | None]:
    """Admite ``hash;familia``, ``hash`` suelto y filas CSV de MalwareBazaar
    (``"fecha","sha256","md5","sha1",...,"signature",...``)."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None, None
    if '","' in line:   # CSV de MalwareBazaar: se toma el SHA-256 (2.ª columna) y la familia
        cols = [c.strip().strip('"') for c in line.split('","')]
        h = cols[1].lower() if len(cols) > 1 else ""
        fam = cols[8] if len(cols) > 8 and cols[8] not in ("", "n/a") else None
        return (h, fam) if len(h) == 64 and set(h) <= _HEX else (None, None)
    h, _, fam = line.partition(";")
    h = h.strip().lower()
    if len(h) in HASH_LEN and set(h) <= _HEX:
        return h, (fam.strip() or None)
    return None, None


class SignatureRepository:
    def __init__(self, local_path: Path, mb_key: str = "", vt_key: str = "",
                 timeout: float = 3.0):
        self.local_path = Path(local_path)
        self.cache_path = self.local_path.with_name("firmas_cache.json")
        self.mb_key, self.vt_key, self.timeout = mb_key, vt_key, timeout
        self._lock = threading.Lock()
        self._local: dict[str, str] = {}
        self._cache: dict[str, dict] = {}
        self.reload()

    def reload(self) -> None:
        if not self.local_path.exists():
            self.local_path.parent.mkdir(parents=True, exist_ok=True)
            self.local_path.write_text(
                "# sha256;familia  (una firma por línea)\n"
                f"{EICAR_SHA256};EICAR-Test-File\n", encoding="utf-8")
        local: dict[str, str] = {}
        sources = [self.local_path]
        extra_dir = self.local_path.parent / "firmas"
        if extra_dir.is_dir():
            sources += sorted(p for p in extra_dir.iterdir() if p.suffix.lower() in (".txt", ".csv"))
        for src in sources:
            for line in src.read_text(encoding="utf-8", errors="ignore").splitlines():
                h, fam = _parse_line(line)
                if h:
                    local.setdefault(h, fam or src.stem)
        self._local = local
        if self.cache_path.exists():
            try:
                self._cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except ValueError:
                self._cache = {}

    def add(self, sha256: str, family: str) -> None:
        with self._lock, open(self.local_path, "a", encoding="utf-8") as fh:
            fh.write(f"{sha256.lower()};{family}\n")
            self._local[sha256.lower()] = family

    def __len__(self) -> int:
        return len(self._local)

    def lookup_local(self, *hashes: str) -> dict | None:
        """Busca MD5/SHA-1/SHA-256 en las listas locales (sin red). ``None`` si no hay coincidencia."""
        for h in hashes:
            fam = self._local.get((h or "").lower())
            if fam:
                return {"hash": h.lower(), "algoritmo": HASH_LEN.get(len(h), "?"), "family": fam}
        return None

    # ----------------------------------------------------------------- consulta
    def lookup(self, sha256: str) -> dict:
        h = sha256.lower()
        t0 = time.perf_counter()
        if h in self._local:
            return {"malicious": True, "source": "local", "family": self._local[h],
                    "queried": ["local"], "ms": 0.0}
        if h in self._cache:
            return {**self._cache[h], "source": self._cache[h]["source"] + "(cache)"}
        queried, result = ["local"], None
        if self.mb_key:
            queried.append("malwarebazaar")
            result = self._malwarebazaar(h)
        if (result is None or not result.get("malicious")) and self.vt_key:
            queried.append("virustotal")
            vt = self._virustotal(h)
            result = vt if vt is not None else result
        if result is None:
            result = {"malicious": False, "source": "local", "family": None}
        result.update(queried=queried, ms=round((time.perf_counter() - t0) * 1000, 1))
        if len(queried) > 1 and not result.get("error"):
            with self._lock:
                self._cache[h] = result
                self.cache_path.write_text(json.dumps(self._cache), encoding="utf-8")
        return result

    def _malwarebazaar(self, h: str) -> dict | None:
        try:
            body = urllib.parse.urlencode({"query": "get_info", "hash": h}).encode()
            req = urllib.request.Request("https://mb-api.abuse.ch/api/v1/", data=body,
                                         headers={"Auth-Key": self.mb_key})
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read())
            if data.get("query_status") == "ok":
                fam = (data.get("data") or [{}])[0].get("signature") or "desconocida"
                return {"malicious": True, "source": "malwarebazaar", "family": fam}
            return {"malicious": False, "source": "malwarebazaar", "family": None,
                    "response": data.get("query_status")}
        except Exception as e:
            return {"malicious": False, "source": "malwarebazaar", "family": None,
                    "error": f"{type(e).__name__}: {e}"}

    def _virustotal(self, h: str) -> dict | None:
        try:
            req = urllib.request.Request(f"https://www.virustotal.com/api/v3/files/{h}",
                                         headers={"x-apikey": self.vt_key})
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                stats = json.loads(r.read())["data"]["attributes"]["last_analysis_stats"]
            mal = stats.get("malicious", 0)
            return {"malicious": mal >= 3, "source": "virustotal", "family": None,
                    "response": stats}
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"malicious": False, "source": "virustotal", "family": None,
                        "response": "no encontrado"}
            return {"malicious": False, "source": "virustotal", "family": None,
                    "error": f"HTTP {e.code}"}
        except Exception as e:
            return {"malicious": False, "source": "virustotal", "family": None,
                    "error": f"{type(e).__name__}: {e}"}
