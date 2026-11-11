"""Fase 3 — Análisis en entorno aislado (RNF5).

Backends, de más a menos aislado (``sandbox_backend = "auto"`` elige el
primero disponible):

``docker``
    ``docker run --rm --network none --read-only --tmpfs /tmp --cap-drop ALL
    --security-opt no-new-privileges --pids-limit --memory``. Sin red, sin
    escritura fuera de /tmp (tmpfs) y sin persistencia: el contenedor se
    destruye al terminar (``--rm``). Cumple el RNF5 completo.
``namespace``
    ``unshare --net`` (espacio de red vacío) + límites ``setrlimit``
    (CPU, memoria, tamaño de archivo = 0, descriptores) en un directorio
    temporal que se borra al final.
``subprocess``
    Solo límites de recursos y directorio temporal efímero (aislamiento
    parcial; se informa como tal en el reporte).

El trabajador sondea red y disco desde adentro y el resultado se guarda como
evidencia (``isolation``).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WORKER = Path(__file__).resolve().parents[2] / "sandbox" / "worker.py"


def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=5).returncode == 0
    except Exception:
        return False


def _unshare_available() -> bool:
    if not shutil.which("unshare"):
        return False
    try:
        return subprocess.run(["unshare", "--net", "true"], capture_output=True, timeout=5).returncode == 0
    except Exception:
        return False


_BACKEND_CACHE: dict[str, str] = {}


def _drop_privs_prefix() -> list[str]:
    """Si corremos como root, el análisis se ejecuta como 'nobody' (uid 65534)."""
    if hasattr(os, "geteuid") and os.geteuid() == 0 and shutil.which("setpriv"):
        return ["setpriv", "--reuid=65534", "--regid=65534", "--clear-groups", "--"]
    return []


def pick_backend(preferred: str = "auto") -> str:
    if preferred != "auto":
        return preferred
    if "auto" not in _BACKEND_CACHE:
        if _docker_available():
            _BACKEND_CACHE["auto"] = "docker"
        elif _unshare_available():
            _BACKEND_CACHE["auto"] = "namespace"
        else:
            _BACKEND_CACHE["auto"] = "subprocess"
    return _BACKEND_CACHE["auto"]


def _limits(cpu_s: int, mem_mb: int):
    def apply():  # se ejecuta en el hijo antes de exec
        import resource
        for lim, val in ((resource.RLIMIT_CPU, cpu_s), (resource.RLIMIT_AS, mem_mb << 20),
                         (resource.RLIMIT_FSIZE, 0),      # no puede escribir archivos
                         (resource.RLIMIT_NOFILE, 32), (resource.RLIMIT_CORE, 0)):
            try:
                resource.setrlimit(lim, (val, val))
            except (ValueError, OSError):   # macOS no admite algunos límites (p. ej. RLIMIT_AS)
                pass
        os.setsid()
    # Windows no admite preexec_fn: ahí se recomienda Docker Desktop para cumplir RNF5.
    return None if os.name == "nt" else apply


def run_sandbox(data: bytes, filename_hint: str, backend: str = "auto",
                timeout: float = 8.0, image: str = "python:3.11-slim") -> dict:
    backend = pick_backend(backend)
    workdir = Path(tempfile.mkdtemp(prefix="fm_sbx_"))
    sample = workdir / "sample.bin"
    sample.write_bytes(data)
    os.chmod(sample, 0o444)
    # Copia del trabajador junto a la muestra: el usuario sin privilegios (y Docker-en-Docker)
    # puede leerla aunque el proyecto esté en una carpeta privada.
    worker = workdir / "worker.py"
    shutil.copy(WORKER, worker)
    os.chmod(worker, 0o444)
    os.chmod(workdir, 0o755)   # legible pero no escribible por el usuario sin privilegios
    before = set(os.listdir(workdir))
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
    if os.name == "nt":  # Python necesita SYSTEMROOT para arrancar en Windows
        env = {**env, "PATH": os.environ.get("PATH", ""), "SYSTEMROOT": os.environ.get("SYSTEMROOT", r"C:\Windows")}
    if backend == "docker":
        cmd = ["docker", "run", "--rm", "--network", "none", "--read-only",
               "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges", "--pids-limit", "64",
               "--memory", "256m", "--cpus", "1", "--user", "65534:65534",
               "-v", f"{sample}:/sample:ro", "-v", f"{worker}:/worker.py:ro",
               image, "python", "-B", "/worker.py", "/sample"]
        preexec = None
    elif backend == "namespace":
        cmd = ["unshare", "--net"] + _drop_privs_prefix() + [sys.executable, "-B", "-I", str(worker), str(sample)]
        preexec = _limits(int(timeout) + 1, 512)
    else:
        cmd = _drop_privs_prefix() + [sys.executable, "-B", "-I", str(worker), str(sample)]
        preexec = _limits(int(timeout) + 1, 512)
    result: dict = {"backend": backend}
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, cwd=workdir,
                              env=env, preexec_fn=preexec)
        if proc.returncode == 0 and proc.stdout:
            result["observations"] = json.loads(proc.stdout)
            result["status"] = "ok"
        else:
            result["status"] = "error"
            result["stderr"] = proc.stderr.decode("utf-8", "ignore")[-500:]
            result["returncode"] = proc.returncode
    except subprocess.TimeoutExpired:
        result["status"] = "timeout"
    finally:
        leftover = sorted(set(os.listdir(workdir)) - before)
        shutil.rmtree(workdir, ignore_errors=True)
    probe = (result.get("observations") or {}).get("isolation_probe", {})
    result["isolation"] = {
        "backend": backend,
        "network_blocked": probe.get("network_blocked"),
        "fs_write_blocked": probe.get("fs_write_blocked"),
        "files_written_in_workdir": leftover,
        "ephemeral": not workdir.exists(),
        "rnf5_ok": bool(probe.get("network_blocked") and probe.get("fs_write_blocked") and not leftover),
    }
    return result


def sandbox_features(res: dict) -> tuple[dict, list[dict]]:
    obs = res.get("observations") or {}
    feats = {
        "sbx_embedded_exe": obs.get("embedded_executables", 0),
        "sbx_hidden_scripts": obs.get("hidden_scripts", 0),
        "sbx_active_content": len(obs.get("active_content", [])),
        "sbx_ransom_markers": len(obs.get("ransomware_markers", [])),
        "sbx_hidden_objstm": int(bool(obs.get("hidden_in_object_streams"))),
        "sbx_expansion_limit": int(bool(obs.get("expansion_limit_hit"))),
        "sbx_nested": obs.get("nested_archives", 0),
        "sbx_urls": len(obs.get("urls", [])),
        "sbx_failed": int(res.get("status") != "ok"),
    }
    findings = []
    if feats["sbx_embedded_exe"]:
        findings.append({"id": "sbx_exe", "kind": "ransomware", "severity": "alta",
                         "tecnico": "Al desempaquetar se encontró un ejecutable de Windows escondido.",
                         "claro": "Dentro del archivo hay un programa escondido."})
    if feats["sbx_hidden_scripts"]:
        findings.append({"id": "sbx_scripts", "kind": "ransomware", "severity": "alta",
                         "tecnico": "Scripts (PowerShell) ocultos en bloques base64.",
                         "claro": "El archivo esconde instrucciones para ejecutar comandos."})
    if feats["sbx_ransom_markers"]:
        findings.append({"id": "sbx_ransom", "kind": "ransomware", "severity": "alta",
                         "tecnico": "Marcadores de ransomware: " + ", ".join(obs.get("ransomware_markers", [])[:6]),
                         "claro": "El contenido muestra señales de programas que secuestran archivos."})
    if feats["sbx_hidden_objstm"]:
        findings.append({"id": "sbx_objstm", "kind": "ransomware", "severity": "alta",
                         "tecnico": "Acciones /JavaScript o /Launch escondidas en flujos comprimidos.",
                         "claro": "El PDF esconde código en partes comprimidas para evitar ser detectado."})
    if feats["sbx_expansion_limit"]:
        findings.append({"id": "sbx_bomb", "kind": "ransomware", "severity": "media",
                         "tecnico": "Se superó el límite de expansión (posible bomba de descompresión).",
                         "claro": "El archivo crece de forma anormal al abrirse y podría bloquear el equipo."})
    if res.get("status") == "timeout":
        findings.append({"id": "sbx_timeout", "kind": "ransomware", "severity": "media",
                         "tecnico": "El análisis aislado excedió el tiempo límite.",
                         "claro": "El archivo no se pudo revisar a tiempo; por precaución se trata como sospechoso."})
    return feats, findings
