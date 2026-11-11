"""Configuración central de FileMind.

Los valores se leen de ``config.json`` (junto al proyecto) y pueden
sobrescribirse con variables de entorno ``FILEMIND_*``.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

from .domain.models import CATEGORIES, PROFILE  # noqa: F401  (re-exportado)


@dataclass
class Settings:
    data_dir: Path = ROOT / "data"
    # RF1: solo estos grupos se procesan. Vacío = ninguno (seguro por defecto).
    monitored_groups: list[str] = field(default_factory=list)
    # RF8: umbral de cuarentena (puntaje estrictamente mayor que este valor)
    quarantine_threshold: int = 70
    # RNF1: presupuesto de tiempo por archivo (s) y tamaño máximo (MB)
    max_protocol_seconds: float = 15.0
    max_file_mb: int = 20
    # RNF8: retención mínima de los registros de auditoría (días)
    log_retention_days: int = 183
    # Fase 3: backend de aislamiento: "auto" | "docker" | "namespace" | "subprocess"
    sandbox_backend: str = "auto"
    sandbox_timeout_s: float = 8.0
    sandbox_image: str = "python:3.11-slim"
    # RF5: APIs externas de firmas (opcionales; sin clave se usa solo la base local)
    malwarebazaar_api_key: str = ""
    virustotal_api_key: str = ""
    external_lookup_timeout_s: float = 3.0
    # RF6: consultar antigüedad de dominios vía RDAP (requiere red)
    rdap_lookup: bool = False
    # Webhook opcional para reenviar notificaciones (p.ej. el puente de WhatsApp)
    notify_webhook: str = ""
    # Clasificador temático: confianza mínima para no mandar a "Otros"
    topic_min_confidence: float = 0.35
    # Número de hilos de análisis (RNF6)
    workers: int = 4
    api_token: str = ""  # token del puente de WhatsApp (vacío = se genera en data/api_token.txt)
    # Horas que dura una sesión iniciada en la interfaz web
    session_hours: int = 12
    # Perfil de categorías ("general" | "juridico"); se lee al importar filemind.domain
    perfil: str = PROFILE
    # Encender el puente de WhatsApp junto con «python -m filemind serve» (si no hay uno encendido)
    whatsapp_autostart: bool = True

    @property
    def inbox_dir(self) -> Path:
        return self.data_dir / "inbox"

    @property
    def library_dir(self) -> Path:
        return self.data_dir / "biblioteca"

    @property
    def quarantine_dir(self) -> Path:
        return self.data_dir / "cuarentena"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "filemind.db"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "modelos"

    @property
    def topic_model_path(self) -> Path:
        return self.models_dir / ("tema.joblib" if PROFILE == "general" else f"tema_{PROFILE}.joblib")

    @property
    def signatures_path(self) -> Path:
        return self.data_dir / "firmas_malware.txt"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.inbox_dir, self.library_dir,
                  self.quarantine_dir, self.models_dir):
            d.mkdir(parents=True, exist_ok=True)
        for c in CATEGORIES:
            (self.library_dir / c).mkdir(exist_ok=True)
        os.chmod(self.quarantine_dir, 0o700)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["data_dir"] = str(self.data_dir)
        for k in ("malwarebazaar_api_key", "virustotal_api_key", "api_token"):
            d[k] = "***" if d[k] else ""
        return d


def load_settings(path: Path | None = None, **overrides) -> Settings:
    path = path or Path(os.environ.get("FILEMIND_CONFIG", ROOT / "config.json"))
    raw: dict = {}
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
    for key in Settings.__dataclass_fields__:
        env = os.environ.get("FILEMIND_" + key.upper())
        if env is not None:
            raw[key] = json.loads(env) if key == "monitored_groups" else env
    raw.update(overrides)
    s = Settings()
    for k, v in raw.items():
        if k not in Settings.__dataclass_fields__:
            continue
        default = getattr(s, k)
        if isinstance(default, bool):
            v = v in (True, "1", "true", "True")
        elif isinstance(default, Path):
            v = Path(v)
            if not v.is_absolute():
                v = ROOT / v
        elif isinstance(default, int):
            v = int(v)
        elif isinstance(default, float):
            v = float(v)
        setattr(s, k, v)
    # RNF8: nunca menos de 6 meses de retención
    s.log_retention_days = max(s.log_retention_days, 183)
    return s
