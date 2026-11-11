"""Trazabilidad (RNF8) y persistencia.

Cada evento de análisis se guarda con marca de tiempo UTC en SQLite y, en
paralelo, en un archivo JSONL de solo anexado (``data/audit.jsonl``) que sirve
como evidencia para auditoría. La purga nunca borra eventos con menos de
``log_retention_days`` (mínimo 183 días = 6 meses).
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    event TEXT NOT NULL,
    sha256 TEXT,
    group_name TEXT,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS ix_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS ix_events_sha ON events(sha256);

CREATE TABLE IF NOT EXISTS files (
    sha256 TEXT PRIMARY KEY,
    original_name TEXT,
    group_name TEXT,
    sender TEXT,
    received_at TEXT,
    detected_at TEXT,
    size INTEGER,
    real_type TEXT,
    risk_score INTEGER,
    risk_level TEXT,
    status TEXT,              -- clasificado | cuarentena | duplicado | error
    category TEXT,
    category_confidence REAL,
    stored_path TEXT,
    reasons TEXT,             -- JSON
    notification TEXT,
    protocol_seconds REAL,
    report TEXT               -- JSON completo del protocolo
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    predicted TEXT,
    corrected TEXT NOT NULL,
    text_excerpt TEXT
);

CREATE TABLE IF NOT EXISTS groups (
    name TEXT PRIMARY KEY,
    added_at TEXT
);

-- Búsqueda por contenido: texto normalizado (minúsculas, sin tildes) de cada archivo
CREATE TABLE IF NOT EXISTS file_search (
    sha256 TEXT PRIMARY KEY,
    text TEXT NOT NULL
);

-- Importación incremental: mensajes de cada chat que ya pasaron por el protocolo
CREATE TABLE IF NOT EXISTS imported (
    chat_id TEXT NOT NULL,
    msg_id TEXT NOT NULL,
    sha256 TEXT,
    ts TEXT,
    PRIMARY KEY (chat_id, msg_id)
);
"""


def norm_text(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip()


class Scope(set):
    """Chats visibles para un usuario y, por chat, las etiquetas permitidas.

    Se comporta como el ``set`` de chats de siempre; ``labels`` dice, para cada chat, qué
    etiquetas se ven (``None`` = todas). Lo arman los espacios de trabajo que filtran por
    etiquetas. Los archivos en cuarentena (sin etiqueta) se ven siempre para que el equipo
    sepa que llegó algo peligroso por su chat.
    """

    def __init__(self, chats=(), labels: dict[str, set[str] | None] | None = None):
        super().__init__(chats)
        self.labels = {c: (labels or {}).get(c) for c in self}

    def allows(self, rec: dict | None) -> bool:
        if not rec or rec.get("group_name") not in self:
            return False
        allowed = self.labels.get(rec["group_name"])
        return allowed is None or rec.get("category") is None or rec.get("category") in allowed


def _in(groups) -> tuple[str, tuple]:
    """Filtro SQL por chats visibles (``None`` = sin filtro) y, si aplica, por etiquetas."""
    if groups is None:
        return "", ()
    labels = getattr(groups, "labels", {})
    groups = sorted(groups)
    if not groups:
        return " AND 0", ()
    free = [g for g in groups if labels.get(g) is None]
    parts, args = [], []
    if free:
        parts.append(f"group_name IN ({','.join('?' * len(free))})")
        args += free
    for g in groups:
        cats = sorted(labels.get(g) or ())
        if labels.get(g) is None:
            continue
        cond = f"category IN ({','.join('?' * len(cats))})" if cats else "0"
        parts.append(f"(group_name = ? AND (category IS NULL OR {cond}))")
        args += [g, *cats]
    return f" AND ({' OR '.join(parts)})", tuple(args)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class AuditStore:
    def __init__(self, db_path: Path, retention_days: int = 183):
        self.db_path = Path(db_path)
        self.jsonl_path = self.db_path.with_name("audit.jsonl")
        self.retention_days = max(retention_days, 183)
        self._lock = threading.Lock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._backfill_search()

    def _backfill_search(self) -> None:
        """Indexa el texto de los archivos analizados antes de que existiera la búsqueda."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT f.sha256, f.original_name, f.report FROM files f LEFT JOIN file_search s "
                "ON s.sha256 = f.sha256 WHERE s.sha256 IS NULL").fetchall()
            for sha, name, report in rows:
                self._conn.execute("INSERT OR REPLACE INTO file_search(sha256, text) VALUES (?,?)",
                                   (sha, self._search_text(name, report)))
            self._conn.commit()

    @staticmethod
    def _search_text(name, report) -> str:
        if isinstance(report, str):
            try:
                report = json.loads(report)
            except ValueError:
                report = {}
        excerpt = (report or {}).get("text_excerpt", "") if isinstance(report, dict) else ""
        return norm_text(f"{name or ''} {excerpt}")

    # ---------------------------------------------------------------- eventos
    def log(self, event: str, sha256: str | None = None,
            group: str | None = None, **detail) -> dict:
        rec = {"ts": now_iso(), "event": event, "sha256": sha256,
               "group": group, "detail": detail}
        payload = json.dumps(detail, ensure_ascii=False, default=str)
        with self._lock:
            self._conn.execute(
                "INSERT INTO events(ts, event, sha256, group_name, detail) VALUES (?,?,?,?,?)",
                (rec["ts"], event, sha256, group, payload))
            self._conn.commit()
            with open(self.jsonl_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        return rec

    def events(self, sha256: str | None = None, limit: int = 200) -> list[dict]:
        q = "SELECT * FROM events"
        args: tuple = ()
        if sha256:
            q += " WHERE sha256 = ?"
            args = (sha256,)
        q += " ORDER BY id DESC LIMIT ?"
        with self._lock:
            rows = self._conn.execute(q, args + (limit,)).fetchall()
        return [dict(r) | {"detail": json.loads(r["detail"] or "{}")} for r in rows]

    def purge_expired(self, now: datetime | None = None) -> int:
        """Borra solo eventos más antiguos que la retención configurada."""
        now = now or datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=self.retention_days)).isoformat()
        with self._lock:
            cur = self._conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
            self._conn.commit()
        return cur.rowcount

    def retention_report(self) -> dict:
        with self._lock:
            row = self._conn.execute(
                "SELECT MIN(ts) AS oldest, MAX(ts) AS newest, COUNT(*) AS n FROM events").fetchone()
        return {"retention_days": self.retention_days, **dict(row)}

    # --------------------------------------------------------------- archivos
    def get_file(self, sha256: str) -> dict | None:
        with self._lock:
            r = self._conn.execute("SELECT * FROM files WHERE sha256 = ?", (sha256,)).fetchone()
        return self._file_row(r) if r else None

    def upsert_file(self, rec: dict) -> None:
        rec = dict(rec)
        for k in ("reasons", "report"):
            if k in rec and not isinstance(rec[k], str):
                rec[k] = json.dumps(rec[k], ensure_ascii=False, default=str)
        cols = ",".join(rec)
        marks = ",".join("?" * len(rec))
        updates = ",".join(f"{c}=excluded.{c}" for c in rec if c != "sha256")
        with self._lock:
            self._conn.execute(
                f"INSERT INTO files({cols}) VALUES ({marks}) "
                f"ON CONFLICT(sha256) DO UPDATE SET {updates}", tuple(rec.values()))
            if "report" in rec:
                self._conn.execute("INSERT OR REPLACE INTO file_search(sha256, text) VALUES (?,?)",
                                   (rec["sha256"], self._search_text(rec.get("original_name"), rec["report"])))
            self._conn.commit()

    def list_files(self, status: str | None = None, limit: int = 500, groups=None) -> list[dict]:
        q = "SELECT * FROM files WHERE 1"
        args: tuple = ()
        if status:
            q += " AND status = ?"
            args = (status,)
        g, gargs = _in(groups)
        q += g
        args += gargs
        q += " ORDER BY detected_at DESC LIMIT ?"
        with self._lock:
            rows = self._conn.execute(q, args + (limit,)).fetchall()
        return [self._file_row(r) for r in rows]

    @staticmethod
    def _file_row(r) -> dict:
        d = dict(r)
        for k in ("reasons", "report"):
            if d.get(k):
                try:
                    d[k] = json.loads(d[k])
                except ValueError:
                    pass
        return d

    def search(self, query: str, groups=None, limit: int = 200) -> list[tuple[str, str]]:
        """Archivos cuyo nombre o texto contiene todas las palabras (sin importar tildes ni mayúsculas).

        Devuelve ``(sha256, fragmento)`` con el pedazo de texto donde aparece la primera palabra.
        """
        terms = [t for t in norm_text(query).split(" ") if len(t) >= 2][:8]
        if not terms:
            return []
        g, gargs = _in(groups)
        cond = " AND ".join("s.text LIKE ? ESCAPE '\\'" for _ in terms)
        likes = tuple("%" + t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%" for t in terms)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT s.sha256, s.text FROM file_search s JOIN files f ON f.sha256 = s.sha256 "
                f"WHERE {cond}{g.replace('group_name', 'f.group_name')} ORDER BY f.detected_at DESC LIMIT ?",
                likes + gargs + (limit,)).fetchall()
        out = []
        for sha, text in rows:
            i = text.find(terms[0])
            a, b = max(0, i - 70), min(len(text), i + len(terms[0]) + 110)
            out.append((sha, ("…" if a else "") + text[a:b] + ("…" if b < len(text) else "")))
        return out

    def series(self, days: int = 30, groups=None) -> list[dict]:
        """Archivos por día (UTC) de los últimos ``days`` días: estado, nivel de riesgo y categoría."""
        since = (datetime.now(timezone.utc) - timedelta(days=days - 1)).date().isoformat()
        g, gargs = _in(groups)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT substr(detected_at, 1, 10) AS d, status, risk_level, category FROM files "
                f"WHERE detected_at >= ?{g}", (since,) + gargs).fetchall()
        start = datetime.fromisoformat(since).date()
        out = {(start + timedelta(days=i)).isoformat(): {"fecha": (start + timedelta(days=i)).isoformat(), "total": 0,
               "estado": {}, "riesgo": {}, "categoria": {}} for i in range(days)}
        for d, status, level, cat in rows:
            day = out.get(d)
            if not day:
                continue
            day["total"] += 1
            day["estado"][status] = day["estado"].get(status, 0) + 1
            if level:
                day["riesgo"][level] = day["riesgo"].get(level, 0) + 1
            if cat and status == "clasificado":
                day["categoria"][cat] = day["categoria"].get(cat, 0) + 1
        return list(out.values())

    def counts_by_group(self) -> dict[str, int]:
        """Archivos analizados (clasificados o en cuarentena) por chat."""
        with self._lock:
            return dict(self._conn.execute(
                "SELECT group_name, COUNT(*) FROM files WHERE status IN ('clasificado','cuarentena') "
                "AND group_name IS NOT NULL GROUP BY group_name").fetchall())

    def stats(self, groups=None) -> dict:
        g, gargs = _in(groups)
        with self._lock:
            by_status = dict(self._conn.execute(
                f"SELECT status, COUNT(*) FROM files WHERE 1{g} GROUP BY status", gargs).fetchall())
            by_cat = dict(self._conn.execute(
                f"SELECT category, COUNT(*) FROM files WHERE status='clasificado'{g} GROUP BY category", gargs).fetchall())
            avg = self._conn.execute(
                f"SELECT AVG(protocol_seconds), MAX(protocol_seconds) FROM files WHERE 1{g}", gargs).fetchone()
        return {"por_estado": by_status, "por_categoria": by_cat,
                "tiempo_promedio_s": avg[0], "tiempo_maximo_s": avg[1]}

    # --------------------------------------------------------- retroalimentación
    def add_feedback(self, sha256: str, predicted: str | None, corrected: str, text: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO feedback(ts, sha256, predicted, corrected, text_excerpt) VALUES (?,?,?,?,?)",
                (now_iso(), sha256, predicted, corrected, text[:20000]))
            self._conn.commit()

    def feedback_rows(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute("SELECT * FROM feedback").fetchall()]

    # ---------------------------------------------------- importación incremental
    def mark_imported(self, chat_id: str, msg_id: str, sha256: str | None) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO imported(chat_id, msg_id, sha256, ts) VALUES (?,?,?,?)",
                               (chat_id, msg_id, sha256, now_iso()))
            self._conn.commit()

    def imported_ids(self, chat_id: str) -> dict[str, str | None]:
        """msg_id -> sha256 de los mensajes del chat que ya se importaron."""
        with self._lock:
            rows = self._conn.execute("SELECT msg_id, sha256 FROM imported WHERE chat_id = ?", (chat_id,)).fetchall()
        return {r[0]: r[1] for r in rows}

    def forget_imported(self, chat_id: str) -> int:
        with self._lock:
            cur = self._conn.execute("DELETE FROM imported WHERE chat_id = ?", (chat_id,))
            self._conn.commit()
        return cur.rowcount

    def known_hashes(self, hashes: list[str]) -> set[str]:
        """Huellas que FileMind ya analizó (clasificadas o en cuarentena)."""
        hashes = [h for h in hashes if h]
        if not hashes:
            return set()
        marks = ",".join("?" * len(hashes))
        with self._lock:
            rows = self._conn.execute(f"SELECT sha256 FROM files WHERE status IN ('clasificado','cuarentena') "
                                      f"AND sha256 IN ({marks})", hashes).fetchall()
        return {r[0] for r in rows}

    # ------------------------------------------------------------------ grupos
    def set_groups(self, names: list[str]) -> None:
        # Varios chats de WhatsApp pueden llamarse igual: se guarda cada nombre una sola vez
        unique = list(dict.fromkeys(n.strip() for n in names if n.strip()))
        with self._lock:
            try:
                self._conn.execute("DELETE FROM groups")
                self._conn.executemany("INSERT INTO groups(name, added_at) VALUES (?,?)",
                                       [(n, now_iso()) for n in unique])
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def get_groups(self) -> list[str]:
        with self._lock:
            return [r[0] for r in self._conn.execute("SELECT name FROM groups ORDER BY name")]
