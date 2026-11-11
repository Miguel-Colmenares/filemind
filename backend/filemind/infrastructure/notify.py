"""Notificaciones en lenguaje claro y no técnico (RNF7).

Reglas de redacción: frases cortas, sin siglas técnicas (hash, macro VBA,
sandbox…), una acción concreta a seguir y el motivo principal primero.
Los detalles técnicos quedan en el reporte para el administrador.
"""
from __future__ import annotations

import json
import threading
import urllib.request

SEV_ORDER = {"alta": 0, "media": 1, "baja": 2}


def plain_reasons(findings: list[dict], limit: int = 3) -> list[str]:
    seen, out = set(), []
    for f in sorted(findings, key=lambda f: SEV_ORDER.get(f.get("severity"), 3)):
        msg = f.get("claro")
        if msg and msg not in seen:
            seen.add(msg)
            out.append(msg)
        if len(out) >= limit:
            break
    return out


def build_message(name: str, group: str | None, sender: str | None, risk: dict,
                  findings: list[dict], category: str | None = None) -> str:
    who = f" enviado por {sender}" if sender else ""
    where = f" en el grupo «{group}»" if group else ""
    reasons = plain_reasons(findings)
    if risk["level"] == "alto":
        lines = [f"FileMind bloqueó el archivo «{name}»{where}{who}.",
                 "Puede ser peligroso, por eso lo guardamos aparte y no se puede abrir."]
        if reasons:
            lines.append("¿Por qué? " + " ".join(reasons))
        lines += ["Qué hacer: no lo abras ni lo reenvíes.",
                  "Si esperabas este archivo, llama a quien lo envió (no le escribas por el mismo chat) "
                  "y confirma que es real. Luego pide al administrador que lo revise."]
    elif risk["level"] == "medio":
        lines = [f"El archivo «{name}»{where} se guardó en «{category}», pero tiene señales para revisar.",
                 *(["Detalle: " + " ".join(reasons)] if reasons else []),
                 "Ábrelo solo si conoces a quien lo envió y esperabas recibirlo. No actives macros ni contenido."]
    else:
        lines = [f"El archivo «{name}»{where} se revisó y se guardó en la carpeta «{category}»."]
    lines.append(f"Nivel de riesgo: {risk['level'].upper()} ({risk['score']} de 100).")
    return "\n".join(lines)


class Notifier:
    """Canales de notificación. Por defecto: registro + webhook opcional.

    El puente de WhatsApp puede consultar ``/api/notificaciones`` y enviar el
    mensaje por chat privado al usuario configurado.
    """

    def __init__(self, webhook_url: str = ""):
        self.webhook_url = webhook_url
        self._lock = threading.Lock()
        self.outbox: list[dict] = []
        self._seq = 0

    def send(self, payload: dict) -> None:
        with self._lock:
            self._seq += 1
            payload = dict(payload, id=self._seq)
            self.outbox.append(payload)
            self.outbox = self.outbox[-500:]
        if self.webhook_url:
            try:
                req = urllib.request.Request(self.webhook_url, data=json.dumps(payload).encode(),
                                             headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=3).close()
            except Exception:
                pass

    def pending(self, since: int = 0) -> list[dict]:
        with self._lock:
            return [p for p in self.outbox if p["id"] > since]
