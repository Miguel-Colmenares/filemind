"""Orquestador de FileMind: detección → protocolo de 4 fases → cuarentena o clasificación.

Implementa el flujo de la Figura 1 de filemind_seguridad.pdf y el flujo de
6 pasos de la propuesta de IA (WhatsApp → detección y descarga →
procesamiento → análisis con IA → clasificación → organización), con
retroalimentación del usuario.
"""
from __future__ import annotations

import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from ..ai.classifier import TopicClassifier
from ..security.controls import attach_points, run_controls
from ..infrastructure.repository import AuditStore, now_iso
from ..config import Settings
from ..domain.models import LABELS, category_label
from ..infrastructure.bufete import BufeteFolder
from ..infrastructure.extract import extract
from ..infrastructure.notify import Notifier, build_message
from ..security.heuristic import DomainAgeLookup, run_heuristic
from ..security.risk import RiskModel, build_vector, score
from ..security.sandbox import run_sandbox, sandbox_features
from ..security.signatures import SignatureRepository
from ..security.static import run_static, sha256_bytes
from ..infrastructure.storage import Storage


class FileMind:
    def __init__(self, settings: Settings, notifier: Notifier | None = None):
        self.s = settings
        settings.ensure_dirs()
        self.audit = AuditStore(settings.db_path, settings.log_retention_days)
        if not self.audit.get_groups() and settings.monitored_groups:
            self.audit.set_groups(settings.monitored_groups)
        self.signatures = SignatureRepository(settings.signatures_path, settings.malwarebazaar_api_key,
                                              settings.virustotal_api_key, settings.external_lookup_timeout_s)
        self.domain_age = DomainAgeLookup(settings.data_dir / "rdap_cache.json",
                                          enabled=settings.rdap_lookup)
        self.storage = Storage(settings.library_dir, settings.quarantine_dir)
        self.bufete = BufeteFolder(self.audit)  # copia en la carpeta del bufete, por etiqueta
        self.notifier = notifier or Notifier(settings.notify_webhook)
        self.reload_models()
        self.pool = ThreadPoolExecutor(max_workers=settings.workers, thread_name_prefix="fm")

    def reload_models(self) -> None:
        self.topic = TopicClassifier.load(self.s.topic_model_path) or TopicClassifier()
        self.risk_model = RiskModel.load(self.s.models_dir / "riesgo.joblib")

    # ------------------------------------------------------------------- RF1
    @property
    def groups(self) -> list[str]:
        return self.audit.get_groups()

    def is_monitored(self, group: str | None) -> bool:
        return group is not None and group in set(self.groups)

    # ---------------------------------------------------------------- API
    def submit(self, data: bytes, filename: str, group: str | None, sender: str | None = None,
               message_ts: float | None = None) -> Future:
        return self.pool.submit(self.process, data, filename, group, sender, message_ts)

    def process(self, data: bytes, filename: str, group: str | None, sender: str | None = None,
                message_ts: float | None = None, explicit: bool = False) -> dict | None:
        """``explicit`` = el usuario pidió exportar ese chat a mano (RF9): no se exige que esté monitoreado."""
        detected = time.time()
        # RF1: archivos de grupos no seleccionados no se procesan ni se guardan
        if not explicit and not self.is_monitored(group):
            self.audit.log("ignorado_grupo_no_monitoreado", group=group)
            return None
        t0 = time.perf_counter()
        # RF3: hash SHA-256 antes de cualquier otro procesamiento
        digest = sha256_bytes(data)
        latency = round(detected - message_ts, 3) if message_ts else None
        self.audit.log("archivo_detectado", digest, group, name=filename, size=len(data), sender=sender,
                       latency_s=latency, rf2_ok=(latency is None or latency <= 10))
        self.audit.log("hash_calculado", digest, group, algorithm="SHA-256", value=digest)

        prev = self.audit.get_file(digest)
        if prev and prev["status"] in ("clasificado", "cuarentena"):
            self.audit.log("duplicado", digest, group, original=prev["original_name"], status=prev["status"])
            return {**prev, "duplicate": True}

        # Fase 1
        st = run_static(data, filename, self.signatures)
        self.audit.log("fase1_estatico", digest, group, real_type=st["real_type"],
                       declared_ext=st["declared_ext"], extension_mismatch=st["extension_mismatch"],
                       double_extension=st["double_extension"], signature_query=st["signature_lookup"])
        # Fase 2
        ex = extract(data, st["real_type"])
        heur = run_heuristic(data, st["real_type"], ex["text"], ex["urls"], self.domain_age)
        self.audit.log("fase2_heuristico", digest, group, features=heur["features"],
                       findings=[f["tecnico"] for f in heur["findings"]], urls=ex["urls"][:20])
        # Controles de ciberseguridad (tipo real, hashes, macros/OLE, PDF, comprimidos, YARA,
        # entropía, URL, HTML e ingeniería social): cada uno deja su resultado en el reporte
        ctl = run_controls(data, filename, st, ex, self.signatures)
        self.audit.log("controles_seguridad", digest, group,
                       controles=[{"id": c["id"], "estado": c["estado"], "resumen": c["resumen"]} for c in ctl["controls"]],
                       features=ctl["features"])
        # Fase 3 (se omite si ya es malware conocido: no aporta y ahorra tiempo)
        if st["known_malware"]:
            sbx = {"backend": None, "status": "omitido", "isolation": {}}
        else:
            sbx = run_sandbox(data, filename, self.s.sandbox_backend, self.s.sandbox_timeout_s,
                              self.s.sandbox_image)
        sfeat, sfind = sandbox_features(sbx)
        self.audit.log("fase3_sandbox", digest, group, status=sbx.get("status"), isolation=sbx.get("isolation"),
                       features=sfeat)
        # Fase 4
        vec = build_vector(st, heur["features"], sfeat, ctl["features"])
        risk = score(vec, self.risk_model)
        attach_points(ctl["controls"], risk["rule_contributions"])
        findings = list(heur["findings"]) + ctl["findings"] + sfind
        if st["known_malware"]:
            findings.insert(0, {"id": "known_malware", "kind": "ransomware", "severity": "alta",
                                "tecnico": f"Hash en repositorio de firmas ({st['signature_lookup'].get('family')}).",
                                "claro": "Este archivo ya está registrado como un virus conocido."})
        if st["executable_content"] or st["double_extension"] or st["bidi_override"]:
            findings.insert(0, {"id": "fake_extension", "kind": "ransomware", "severity": "alta",
                                "tecnico": f"Declarado .{st['declared_ext']} pero su contenido real es '{st['real_type']}'"
                                           f" (doble extensión={st['double_extension']}, bidi={st['bidi_override']}).",
                                "claro": "Parece un documento, pero en realidad es un programa disfrazado."})
        elif st["extension_mismatch"]:
            findings.insert(0, {"id": "ext_mismatch", "kind": "ransomware", "severity": "media",
                                "tecnico": f"Extensión .{st['declared_ext']} no coincide con la firma real '{st['real_type']}'.",
                                "claro": "El tipo de archivo no coincide con lo que dice su nombre."})
        self.audit.log("fase4_puntaje", digest, group, score=risk["score"], level=risk["level"],
                       rule_score=risk["rule_score"], contributions=risk["rule_contributions"],
                       ml=risk["ml_probabilities"], floors=risk["floors"])

        report = {"static": st, "heuristic": heur, "controls": ctl["controls"], "sandbox": sbx, "risk": risk,
                  "features": vec}
        rec = {"sha256": digest, "original_name": filename, "group_name": group, "sender": sender,
               "received_at": datetime.fromtimestamp(message_ts, timezone.utc).isoformat() if message_ts else None,
               "detected_at": now_iso(), "size": len(data), "real_type": st["real_type"],
               "risk_score": risk["score"], "risk_level": risk["level"],
               "reasons": [f["claro"] for f in findings]}

        # RF8: cuarentena si el puntaje supera 70
        if risk["score"] > self.s.quarantine_threshold:
            path = self.storage.quarantine_file(data, filename, digest, {"risk": risk, "reasons": rec["reasons"]})
            msg = build_message(filename, group, sender, risk, findings)
            rec.update(status="cuarentena", category=None, category_confidence=None, stored_path=str(path),
                       notification=msg)
            self.audit.log("cuarentena", digest, group, path=str(path), score=risk["score"])
        else:
            pred = self.topic.predict(ex["text"], st["real_type"], self.s.topic_min_confidence)
            path = self.storage.store(data, filename, pred["category"], digest)
            msg = build_message(filename, group, sender, risk, findings, category_label(pred["category"]))
            rec.update(status="clasificado", category=pred["category"], category_confidence=pred["confidence"],
                       stored_path=str(path), notification=msg)
            report["topic"] = pred
            report["text_excerpt"] = ex["text"][:5000]
            self.audit.log("clasificado", digest, group, category=pred["category"], top=pred["top"],
                           needs_review=pred["needs_review"], path=str(path))
        elapsed = round(time.perf_counter() - t0, 3)
        rec["protocol_seconds"] = elapsed
        rec["report"] = report
        self.audit.log("protocolo_completo", digest, group, seconds=elapsed,
                       rnf1_ok=elapsed <= self.s.max_protocol_seconds)
        self.audit.upsert_file(rec)
        if rec["status"] == "clasificado":
            self.bufete.on_classified(rec)
        # Cada archivo nuevo genera un aviso (también los seguros), para saber que llegó algo por WhatsApp
        self.notifier.send({"ts": now_iso(), "sha256": digest, "group": group, "level": risk["level"],
                            "message": msg})
        return rec

    # ------------------------------------------------------- retroalimentación
    def correct_category(self, sha256: str, category: str) -> dict:
        if category not in LABELS:
            raise ValueError(f"Categoría inválida: {category}")
        rec = self.audit.get_file(sha256)
        if not rec or rec["status"] != "clasificado":
            raise KeyError("Archivo no encontrado o no clasificado")
        new_path = self.storage.move(Path(rec["stored_path"]), category)
        text = (rec.get("report") or {}).get("text_excerpt", "")
        self.audit.add_feedback(sha256, rec["category"], category, f"__type={rec['real_type']}__\n{text}")
        self.audit.upsert_file({"sha256": sha256, "category": category, "stored_path": str(new_path)})
        self.audit.log("correccion_usuario", sha256, rec["group_name"], before=rec["category"], after=category)
        self.bufete.on_classified(self.audit.get_file(sha256))  # la copia del PC pasa a la subcarpeta nueva
        return {"sha256": sha256, "category": category, "path": str(new_path)}

    def release(self, sha256: str, category: str, reason: str, who: str = "admin") -> dict:
        rec = self.audit.get_file(sha256)
        if not rec or rec["status"] != "cuarentena":
            raise KeyError("Archivo no está en cuarentena")
        path = self.storage.release(sha256, category)
        self.audit.upsert_file({"sha256": sha256, "status": "clasificado", "category": category,
                                "stored_path": str(path)})
        self.audit.log("liberado_de_cuarentena", sha256, rec["group_name"], by=who, reason=reason,
                       category=category)
        self.bufete.on_classified(self.audit.get_file(sha256))
        return {"sha256": sha256, "path": str(path)}

    def shutdown(self):
        self.pool.shutdown(wait=True)
