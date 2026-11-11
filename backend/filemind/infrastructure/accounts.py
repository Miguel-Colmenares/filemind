"""Usuarios, sesiones y espacios de trabajo (control de acceso de la versión web).

- Contraseñas: PBKDF2-HMAC-SHA256 con sal aleatoria de 16 bytes y 240.000 iteraciones
  (recomendación OWASP para PBKDF2-SHA256). Nunca se guarda la contraseña.
- Sesiones: token aleatorio de 256 bits que viaja en una cookie HttpOnly. En la base
  solo se guarda su SHA-256, así una copia de la base no permite suplantar a nadie.
- Bloqueo: 5 intentos fallidos seguidos bloquean la cuenta 5 minutos (fuerza bruta).
- Espacios de trabajo: agrupan personas, chats de WhatsApp y, opcionalmente, etiquetas
  (por ejemplo «Tutela»). Un miembro solo ve los archivos que llegaron por los chats de sus
  espacios y que tienen las etiquetas de esos espacios; el administrador ve todo.

Usa la misma conexión SQLite (y el mismo candado) que la auditoría.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

from .repository import AuditStore, Scope, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'miembro')),
    password_hash TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    created_at TEXT NOT NULL,
    last_login TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    ip TEXT,
    user_agent TEXT
);
CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS workspaces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    created_by INTEGER
);
CREATE TABLE IF NOT EXISTS workspace_members (
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    added_at TEXT NOT NULL,
    PRIMARY KEY (workspace_id, user_id)
);
CREATE TABLE IF NOT EXISTS workspace_chats (
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    chat_name TEXT NOT NULL,
    PRIMARY KEY (workspace_id, chat_name)
);
-- Etiquetas que filtra cada espacio (sin filas = todas las etiquetas)
CREATE TABLE IF NOT EXISTS workspace_categories (
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    PRIMARY KEY (workspace_id, category)
);
"""

ITERATIONS = 240_000
MAX_FAILS = 5
LOCK_MINUTES = 5
ROLES = ("admin", "miembro")
USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{3,32}$")


class AuthError(Exception):
    """Credenciales inválidas, cuenta bloqueada o inactiva (mensaje apto para mostrar)."""


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, it, salt, digest = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(it))
        return algo == "pbkdf2_sha256" and hmac.compare_digest(dk.hex(), digest)
    except (ValueError, TypeError):
        return False


def check_password_policy(password: str) -> None:
    if len(password) < 8:
        raise ValueError("La contraseña debe tener al menos 8 caracteres.")
    if password.isdigit() or password.isalpha():
        raise ValueError("La contraseña debe combinar letras y números o símbolos.")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Accounts:
    def __init__(self, audit: AuditStore, session_hours: int = 12):
        self.audit = audit
        self._conn, self._lock = audit._conn, audit._lock
        self.session_hours = session_hours
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # ------------------------------------------------------------------ usuarios
    @staticmethod
    def _public(r) -> dict:
        d = dict(r)
        d.pop("password_hash", None)
        d["active"] = bool(d.get("active"))
        return d

    def count_users(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def list_users(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM users ORDER BY role, name COLLATE NOCASE").fetchall()
            spaces = self._conn.execute(
                "SELECT m.user_id, w.id, w.name FROM workspace_members m JOIN workspaces w ON w.id = m.workspace_id"
            ).fetchall()
        by_user: dict[int, list] = {}
        for uid, wid, wname in spaces:
            by_user.setdefault(uid, []).append({"id": wid, "nombre": wname})
        return [self._public(r) | {"espacios": by_user.get(r["id"], [])} for r in rows]

    def get_user(self, user_id: int) -> dict | None:
        with self._lock:
            r = self._conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._public(r) if r else None

    def create_user(self, username: str, name: str, password: str, role: str = "miembro") -> dict:
        username = username.strip().lower()
        if not USERNAME_RE.match(username):
            raise ValueError("El usuario debe tener de 3 a 32 letras, números, punto, guion o guion bajo.")
        if role not in ROLES:
            raise ValueError("Rol inválido.")
        if not name.strip():
            raise ValueError("Escriba el nombre de la persona.")
        check_password_policy(password)
        with self._lock:
            try:
                cur = self._conn.execute(
                    "INSERT INTO users(username, name, role, password_hash, created_at) VALUES (?,?,?,?,?)",
                    (username, name.strip(), role, hash_password(password), now_iso()))
                self._conn.commit()
            except Exception as e:
                self._conn.rollback()
                if "UNIQUE" in str(e):
                    raise ValueError("Ya existe un usuario con ese nombre.") from e
                raise
        return self.get_user(cur.lastrowid)

    def _admins_active(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]

    def update_user(self, user_id: int, *, name: str | None = None, role: str | None = None,
                    active: bool | None = None, password: str | None = None) -> dict:
        user = self.get_user(user_id)
        if not user:
            raise KeyError("Usuario no encontrado")
        sets, args = [], []
        if name is not None and name.strip():
            sets.append("name = ?"); args.append(name.strip())
        if role is not None:
            if role not in ROLES:
                raise ValueError("Rol inválido.")
            sets.append("role = ?"); args.append(role)
        if active is not None:
            sets.append("active = ?"); args.append(int(active))
        if password is not None:
            check_password_policy(password)
            sets += ["password_hash = ?", "failed_attempts = 0", "locked_until = NULL"]
            args.append(hash_password(password))
        if not sets:
            return user
        with self._lock:
            self._conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", (*args, user_id))
            if self._admins_active() == 0:  # nunca dejar el sistema sin administrador
                self._conn.rollback()
                raise ValueError("Debe quedar al menos un administrador activo.")
            if active is False or password is not None or role is not None:
                self._conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            self._conn.commit()
        return self.get_user(user_id)

    def delete_user(self, user_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            if self._admins_active() == 0:
                self._conn.rollback()
                raise ValueError("Debe quedar al menos un administrador activo.")
            self._conn.commit()

    # ------------------------------------------------------------------ sesiones
    def authenticate(self, username: str, password: str) -> dict:
        """Devuelve el usuario o lanza AuthError. Aplica el bloqueo por intentos fallidos."""
        username = (username or "").strip().lower()
        with self._lock:
            r = self._conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not r:
            verify_password(password, hash_password("x"))  # mismo tiempo de respuesta exista o no el usuario
            raise AuthError("Usuario o contraseña incorrectos.")
        if r["locked_until"] and datetime.fromisoformat(r["locked_until"]) > _now():
            mins = max(1, round((datetime.fromisoformat(r["locked_until"]) - _now()).total_seconds() / 60))
            raise AuthError(f"Cuenta bloqueada por intentos fallidos. Intente de nuevo en {mins} min.")
        if not verify_password(password, r["password_hash"]):
            fails = r["failed_attempts"] + 1
            locked = (_now() + timedelta(minutes=LOCK_MINUTES)).isoformat() if fails >= MAX_FAILS else None
            with self._lock:
                self._conn.execute("UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
                                   (0 if locked else fails, locked, r["id"]))
                self._conn.commit()
            if locked:
                raise AuthError(f"Demasiados intentos fallidos. La cuenta quedó bloqueada {LOCK_MINUTES} minutos.")
            raise AuthError("Usuario o contraseña incorrectos.")
        if not r["active"]:
            raise AuthError("La cuenta está desactivada. Hable con el administrador.")
        with self._lock:
            self._conn.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL, last_login = ? WHERE id = ?",
                               (now_iso(), r["id"]))
            self._conn.commit()
        return self._public(r)

    def create_session(self, user_id: int, ip: str | None = None, user_agent: str | None = None) -> str:
        token = secrets.token_urlsafe(32)
        exp = (_now() + timedelta(hours=self.session_hours)).isoformat()
        with self._lock:
            self._conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_now().isoformat(),))
            self._conn.execute(
                "INSERT INTO sessions(token_hash, user_id, created_at, expires_at, ip, user_agent) VALUES (?,?,?,?,?,?)",
                (_token_hash(token), user_id, now_iso(), exp, ip, (user_agent or "")[:200]))
            self._conn.commit()
        return token

    def user_for_token(self, token: str | None) -> dict | None:
        if not token:
            return None
        with self._lock:
            r = self._conn.execute(
                "SELECT u.*, s.expires_at AS s_exp FROM sessions s JOIN users u ON u.id = s.user_id "
                "WHERE s.token_hash = ?", (_token_hash(token),)).fetchone()
        if not r or not r["active"] or datetime.fromisoformat(r["s_exp"]) < _now():
            return None
        user = self._public(r)
        user.pop("s_exp", None)
        return user

    def end_session(self, token: str | None) -> None:
        if token:
            with self._lock:
                self._conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))
                self._conn.commit()

    # --------------------------------------------------------- espacios de trabajo
    def list_workspaces(self, user: dict | None = None) -> list[dict]:
        """Todos (administrador) o solo los del usuario, con sus miembros y chats."""
        with self._lock:
            ws = self._conn.execute("SELECT * FROM workspaces ORDER BY name COLLATE NOCASE").fetchall()
            members = self._conn.execute(
                "SELECT m.workspace_id, u.id, u.name, u.username, u.role FROM workspace_members m "
                "JOIN users u ON u.id = m.user_id ORDER BY u.name COLLATE NOCASE").fetchall()
            chats = self._conn.execute("SELECT workspace_id, chat_name FROM workspace_chats ORDER BY chat_name").fetchall()
            cats = self._conn.execute("SELECT workspace_id, category FROM workspace_categories ORDER BY category").fetchall()
            counts = dict(self._conn.execute(
                "SELECT c.workspace_id, COUNT(DISTINCT f.sha256) FROM workspace_chats c JOIN files f ON f.group_name = c.chat_name "
                "WHERE f.status IN ('clasificado','cuarentena') AND (f.category IS NULL OR NOT EXISTS "
                "(SELECT 1 FROM workspace_categories k WHERE k.workspace_id = c.workspace_id) OR f.category IN "
                "(SELECT k.category FROM workspace_categories k WHERE k.workspace_id = c.workspace_id)) "
                "GROUP BY c.workspace_id").fetchall())
        out = []
        for w in ws:
            mem = [{"id": m[1], "nombre": m[2], "usuario": m[3], "rol": m[4]} for m in members if m[0] == w["id"]]
            if user and user.get("role") != "admin" and user["id"] not in {m["id"] for m in mem}:
                continue
            out.append({"id": w["id"], "nombre": w["name"], "descripcion": w["description"],
                        "creado": w["created_at"], "miembros": mem,
                        "chats": [c[1] for c in chats if c[0] == w["id"]],
                        "categorias": [k[1] for k in cats if k[0] == w["id"]], "archivos": counts.get(w["id"], 0)})
        return out

    def get_workspace(self, ws_id: int) -> dict | None:
        return next((w for w in self.list_workspaces() if w["id"] == ws_id), None)

    def save_workspace(self, ws_id: int | None, name: str, description: str, members: list[int],
                       chats: list[str], created_by: int | None = None, categories: list[str] | None = None) -> dict:
        name = name.strip()
        if len(name) < 2:
            raise ValueError("El espacio necesita un nombre de al menos 2 letras.")
        chats = list(dict.fromkeys(c.strip() for c in chats if c.strip()))
        with self._lock:
            try:
                if ws_id is None:
                    cur = self._conn.execute(
                        "INSERT INTO workspaces(name, description, created_at, created_by) VALUES (?,?,?,?)",
                        (name, description.strip(), now_iso(), created_by))
                    ws_id = cur.lastrowid
                else:
                    cur = self._conn.execute("UPDATE workspaces SET name = ?, description = ? WHERE id = ?",
                                             (name, description.strip(), ws_id))
                    if cur.rowcount == 0:
                        raise KeyError("Espacio no encontrado")
                self._conn.execute("DELETE FROM workspace_members WHERE workspace_id = ?", (ws_id,))
                self._conn.executemany("INSERT OR IGNORE INTO workspace_members(workspace_id, user_id, added_at) "
                                       "SELECT ?, id, ? FROM users WHERE id = ?",
                                       [(ws_id, now_iso(), int(u)) for u in members])
                self._conn.execute("DELETE FROM workspace_chats WHERE workspace_id = ?", (ws_id,))
                self._conn.executemany("INSERT INTO workspace_chats(workspace_id, chat_name) VALUES (?,?)",
                                       [(ws_id, c) for c in chats])
                if categories is not None:
                    self._conn.execute("DELETE FROM workspace_categories WHERE workspace_id = ?", (ws_id,))
                    self._conn.executemany("INSERT OR IGNORE INTO workspace_categories(workspace_id, category) VALUES (?,?)",
                                           [(ws_id, c) for c in dict.fromkeys(categories) if c])
                self._conn.commit()
            except Exception as e:
                self._conn.rollback()
                if "UNIQUE" in str(e):
                    raise ValueError("Ya existe un espacio con ese nombre.") from e
                raise
        return self.get_workspace(ws_id)

    def delete_workspace(self, ws_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM workspaces WHERE id = ?", (ws_id,))
            self._conn.commit()

    def visible_groups(self, user: dict, workspace_id: int | None = None) -> Scope | None:
        """Chats (y etiquetas) cuyos archivos puede ver el usuario. ``None`` = sin restricción.

        Un chat puede estar en varios espacios del usuario: si alguno no filtra etiquetas se ven
        todas; si no, se ve la unión de las etiquetas de esos espacios.
        """
        is_admin = user.get("role") == "admin"
        if workspace_id is None:
            if is_admin:
                return None
            with self._lock:
                ws_ids = [r[0] for r in self._conn.execute(
                    "SELECT workspace_id FROM workspace_members WHERE user_id = ?", (user["id"],))]
        else:
            if not is_admin:
                with self._lock:
                    ok = self._conn.execute("SELECT 1 FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
                                            (workspace_id, user["id"])).fetchone()
                if not ok:
                    raise PermissionError("No pertenece a ese espacio de trabajo.")
            ws_ids = [workspace_id]
        labels: dict[str, set[str] | None] = {}
        with self._lock:
            for wid in ws_ids:
                chats = [r[0] for r in self._conn.execute(
                    "SELECT chat_name FROM workspace_chats WHERE workspace_id = ?", (wid,))]
                cats = {r[0] for r in self._conn.execute(
                    "SELECT category FROM workspace_categories WHERE workspace_id = ?", (wid,))}
                for c in chats:
                    if not cats or (c in labels and labels[c] is None):
                        labels[c] = None
                    else:
                        labels[c] = (labels.get(c) or set()) | cats
        return Scope(labels.keys(), labels)
