"""Esquemas de entrada/salida de la API (Pydantic)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class GroupsIn(BaseModel):
    grupos: list[str] = Field(..., description="Nombres exactos de los grupos de WhatsApp a monitorear (RF1)")


class CategoryIn(BaseModel):
    categoria: str


class ReleaseIn(BaseModel):
    categoria: str
    motivo: str = Field(..., min_length=10)
    confirmar: bool = False


SUMMARY_FIELDS = ("sha256", "original_name", "group_name", "sender", "detected_at", "size", "real_type",
                  "risk_score", "risk_level", "status", "category", "category_confidence", "reasons",
                  "notification", "protocol_seconds", "duplicate")


def summary(rec: dict | None) -> dict:
    return {k: rec.get(k) for k in SUMMARY_FIELDS} if rec else {}
