"""Capa de dominio: conceptos del negocio, sin dependencias de infraestructura.

Todo lo que el resto del sistema necesita saber sobre "qué es" un archivo
analizado vive aquí: categorías temáticas, estados, niveles de riesgo y la
forma de un hallazgo de seguridad.
"""
from __future__ import annotations

from enum import Enum
from typing import TypedDict

import json
import os
from pathlib import Path

# Perfiles de categorías. "general" son las definidas en el documento de IA
# (FILEMIND.pdf, pág. 9); "juridico" es el de un bufete de abogados.
PROFILES: dict[str, dict[str, str]] = {
    "general": {
        "Academico": "Tareas, trabajos, talleres, documentos de clases",
        "Informes": "Informes laborales o de proyectos",
        "Facturas": "Facturas y comprobantes",
        "Contratos": "Contratos y documentos legales",
        "Reuniones": "Actas y documentos relacionados con reuniones",
        "Presentaciones": "Presentaciones y diapositivas",
        "Financiero": "Presupuestos, reportes financieros",
        "Otros": "Documentos que no pertenecen a las categorías anteriores",
    },
    "juridico": {
        "Demandas": "Demandas y sus subsanaciones o reformas",
        "Contestaciones": "Contestaciones de demanda, excepciones y demandas de reconvención",
        "Tutelas": "Acciones de tutela, impugnaciones e incidentes de desacato",
        "Peticiones": "Derechos de petición y sus respuestas",
        "Recursos": "Recursos de reposición, apelación, queja, casación y alegatos",
        "Providencias": "Sentencias, autos y notificaciones del despacho judicial",
        "Poderes": "Poderes, sustituciones y revocatorias",
        "Contratos": "Contratos, otrosíes, acuerdos de confidencialidad y promesas",
        "Conciliaciones": "Solicitudes, actas y constancias de conciliación",
        "Pruebas": "Pruebas y anexos: certificados, dictámenes, declaraciones, historias",
        "Honorarios": "Facturas, cuentas de cobro y liquidaciones de honorarios",
        "Otros": "Documentos que no pertenecen a las categorías anteriores",
    },
    # Documentos REALES: sentencias de la Corte Constitucional (scripts/dataset_corte.py)
    "constitucional": {
        "Tutela": "Sentencias de revisión y unificación de acciones de tutela",
        "Inconstitucionalidad": "Sentencias sobre demandas de inconstitucionalidad contra leyes",
        "Tratados": "Revisión de tratados internacionales y sus leyes aprobatorias",
        "DecretosLegislativos": "Control de decretos legislativos de estados de excepción",
        "Objeciones": "Objeciones presidenciales o gubernamentales a proyectos de ley",
    },
}


def _active_profile() -> str:
    """``FILEMIND_PERFIL`` o la clave ``perfil`` de ``config.json`` (por defecto "general")."""
    name = os.environ.get("FILEMIND_PERFIL")
    if not name:
        cfg = Path(os.environ.get("FILEMIND_CONFIG", Path(__file__).resolve().parents[2] / "config.json"))
        try:
            name = json.loads(cfg.read_text(encoding="utf-8")).get("perfil")
        except (OSError, ValueError):
            name = None
    return name if name in PROFILES else "general"


PROFILE: str = _active_profile()
CATEGORY_DESCRIPTIONS: dict[str, str] = dict(PROFILES[PROFILE])
CATEGORIES: list[str] = list(CATEGORY_DESCRIPTIONS)   # clases del modelo de IA (no tocar)
# Etiquetas que se pueden asignar a un archivo: las del modelo más "Otros", que es lo que el
# clasificador devuelve cuando no está seguro (no es una clase del modelo en todos los perfiles).
LABEL_DESCRIPTIONS: dict[str, str] = {
    **CATEGORY_DESCRIPTIONS,
    "Otros": CATEGORY_DESCRIPTIONS.get("Otros", "Documentos que el sistema no pudo ubicar con seguridad en otra etiqueta"),
}
LABELS: list[str] = list(LABEL_DESCRIPTIONS)

# Nombre amigable de cada etiqueta (interfaz, PDF y nombre de la subcarpeta en el equipo)
CATEGORY_LABELS: dict[str, str] = {
    "Academico": "Académico", "Informes": "Informes", "Facturas": "Facturas", "Contratos": "Contratos",
    "Reuniones": "Reuniones", "Presentaciones": "Presentaciones", "Financiero": "Financiero", "Otros": "Otros",
    "Demandas": "Demandas", "Contestaciones": "Contestaciones", "Tutelas": "Tutelas",
    "Peticiones": "Derechos de petición", "Recursos": "Recursos", "Providencias": "Sentencias y autos",
    "Poderes": "Poderes", "Conciliaciones": "Conciliaciones", "Pruebas": "Pruebas y anexos",
    "Honorarios": "Honorarios", "Tutela": "Tutela", "Inconstitucionalidad": "Demandas de inconstitucionalidad",
    "Tratados": "Tratados internacionales", "DecretosLegislativos": "Decretos legislativos",
    "Objeciones": "Objeciones a proyectos de ley",
}


def category_label(category: str | None) -> str:
    return CATEGORY_LABELS.get(category or "Otros", category or "Otros")

# Umbral de cuarentena del documento de seguridad (RF8)
QUARANTINE_THRESHOLD = 70


class FileStatus(str, Enum):
    CLASSIFIED = "clasificado"
    QUARANTINED = "cuarentena"
    DUPLICATE = "duplicado"
    DELETED = "eliminado"


class RiskLevel(str, Enum):
    LOW = "bajo"
    MEDIUM = "medio"
    HIGH = "alto"

    @classmethod
    def from_score(cls, score: int) -> "RiskLevel":
        if score > QUARANTINE_THRESHOLD:
            return cls.HIGH
        return cls.MEDIUM if score >= 40 else cls.LOW


class Finding(TypedDict):
    """Hallazgo de una fase del protocolo, con explicación técnica y en lenguaje claro (RNF7)."""
    id: str
    kind: str        # "phishing" | "ransomware"
    severity: str    # "alta" | "media" | "baja"
    tecnico: str
    claro: str
