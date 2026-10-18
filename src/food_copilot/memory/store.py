"""Session memory. Redis holds the live thread. Neon holds durable messages and preferences."""

import json
import os
import re
import threading
from pathlib import Path

_REDIS_CLIENTS: dict[str, object] = {}
_REDIS_LOCK = threading.Lock()
_PG_LOCAL = threading.local()
ROOT = Path(__file__).resolve().parents[3]
SESSION_LIMIT = 10
SESSION_TTL_SECONDS = 60 * 60 * 24
_SESSION_KEY = re.compile(r"^session:[A-Za-z0-9][A-Za-z0-9_-]{0,79}:(messages|user)$")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS app_users (
    user_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES app_users(user_id) ON DELETE CASCADE,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS messages (
    id BIGSERIAL PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id TEXT NOT NULL REFERENCES app_users(user_id) ON DELETE CASCADE,
    preference_key TEXT NOT NULL,
    preference_value TEXT NOT NULL,
    confirmed BOOLEAN NOT NULL DEFAULT false,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, preference_key)
);
"""


def load_local_env() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def session_key(session_id: str) -> str:
    return f"session:{session_id}:messages"


def owner_key(session_id: str) -> str:
    return f"session:{session_id}:user"


def _bounded_int(name: str, default: int, low: int, high: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    return max(low, min(value, high))


def session_ttl_seconds() -> int:
    return _bounded_int("SESSION_TTL_SECONDS", SESSION_TTL_SECONDS, 60, 7 * 24 * 60 * 60)


def session_message_limit() -> int:
    return _bounded_int("SESSION_MESSAGE_LIMIT", SESSION_LIMIT, 1, 20)


def session_message_max_chars() -> int:
    return _bounded_int("SESSION_MESSAGE_MAX_CHARS", 2000, 200, 4000)


def preference_value_max_chars() -> int:
    return _bounded_int("PREFERENCE_VALUE_MAX_CHARS", 200, 20, 500)


def preference_limit() -> int:
    return _bounded_int("PREFERENCE_LIMIT", 20, 1, 50)


def startup_cleanup_enabled() -> bool:
    return os.environ.get("REDIS_STARTUP_CLEANUP", "false").strip().lower() in {"1", "true", "yes", "on"}


def clip_text(content: str, limit: int) -> str:
    text = str(content or "")
    if len(text) <= limit:
        return text
    return text[:limit]


def cleanup_session_keys(client) -> dict:
    """Trim this app's session lists and add a TTL where one is missing. Never flushes the database."""
    limit = session_message_limit()
    ttl = session_ttl_seconds()
    scanned = trimmed = ttl_set = skipped = 0
    cursor = 0
    while True:
        cursor, keys = client.scan(cursor=cursor, match="session:*", count=100)
        for key in keys:
            scanned += 1
            if not _SESSION_KEY.match(str(key)):
                skipped += 1
                continue
            if str(key).endswith(":messages") and client.llen(key) > limit:
                client.ltrim(key, -limit, -1)
                trimmed += 1
            if client.ttl(key) == -1:
                client.expire(key, ttl)
                ttl_set += 1
        if cursor in {0, "0"}:
            break
    return {"scanned": scanned, "trimmed": trimmed, "ttl_set": ttl_set, "skipped": skipped, "deleted": 0}


class _HeldConnection:
    """Keep a Neon connection for this store. The context manager must not close it."""

    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is not None or getattr(self.connection.info, "transaction_status", None) not in {0, None}:
                self.connection.rollback()
        except Exception:
            return False
        return False


class MemoryStore:
    def __init__(self, database_url: str | None = None, redis_url: str | None = None):
        load_local_env()
        self.database_url = database_url or os.environ.get("DATABASE_URL", "")
        self.redis_url = redis_url or os.environ.get("REDIS_URL", "")
        self._connection = None
        self._redis_client = None

    def status(self) -> dict:
        return {
            "postgres": bool(self.database_url),
            "redis": bool(self.redis_url),
        }

    def _postgres(self):
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is not set")
        import psycopg

        held = getattr(_PG_LOCAL, "conn", None)
        if held is None or getattr(_PG_LOCAL, "url", None) != self.database_url or held.closed:
            held = psycopg.connect(self.database_url, connect_timeout=3)
            _PG_LOCAL.conn = held
            _PG_LOCAL.url = self.database_url
        self._connection = held
        return _HeldConnection(held)

    def _redis(self):
        if not self.redis_url:
            raise RuntimeError("REDIS_URL is not set")
        import redis

        with _REDIS_LOCK:
            client = _REDIS_CLIENTS.get(self.redis_url)
            if client is None:
                client = redis.Redis.from_url(
                    self.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=3,
                    socket_timeout=3,
                )
                _REDIS_CLIENTS[self.redis_url] = client
        self._redis_client = client
        return client

    def ensure_schema(self) -> None:
        with self._postgres() as connection:
            connection.execute(SCHEMA_SQL)
            connection.commit()

    def session_owner(self, session_id: str, database: bool = True) -> str | None:
        if self.redis_url:
            owner = self._redis().get(f"session:{session_id}:user")
            if owner:
                return owner
        if database and self.database_url:
            with self._postgres() as connection:
                row = connection.execute(
                    "SELECT user_id FROM conversations WHERE conversation_id = %s",
                    (session_id,),
                ).fetchone()
            if row:
                return row[0]
        return None

    def _insert_postgres(self, user_id: str, session_id: str, role: str, content: str):
        with self._postgres() as connection:
            connection.execute(
                "INSERT INTO app_users (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING",
                (user_id,),
            )
            connection.execute(
                """
                INSERT INTO conversations (conversation_id, user_id)
                VALUES (%s, %s)
                ON CONFLICT (conversation_id) DO NOTHING
                """,
                (session_id, user_id),
            )
            row = connection.execute(
                """
                INSERT INTO messages (conversation_id, user_id, role, content)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (session_id, user_id, role, content),
            ).fetchone()
            connection.commit()
        return row[0]

    def read_session(self, session_id: str) -> dict:
        """Owner, transcript, and saved constraints in one Redis round trip."""
        client = self._redis()
        pipe = client.pipeline()
        pipe.get(owner_key(session_id))
        pipe.lrange(session_key(session_id), -session_message_limit(), -1)
        pipe.get(f"session:{session_id}:context")
        owner, raw_messages, raw_context = pipe.execute()
        messages = []
        for item in raw_messages or []:
            try:
                parsed = json.loads(item)
            except (TypeError, ValueError):
                continue
            if isinstance(parsed, dict):
                messages.append(parsed)
        context = {}
        if raw_context:
            try:
                parsed = json.loads(raw_context)
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, dict):
                context = parsed
        return {"owner": owner, "messages": messages, "context": context}

    def _remember_redis(
        self,
        user_id: str,
        session_id: str,
        messages: list[tuple[str, str]],
        context_body: dict | None = None,
    ) -> None:
        client = self._redis()
        key = session_key(session_id)
        limit = session_message_limit()
        ttl = session_ttl_seconds()
        pipe = client.pipeline()
        for role, content in messages:
            pipe.rpush(key, json.dumps({"role": role, "content": content}))
        pipe.ltrim(key, -limit, -1)
        pipe.expire(key, ttl)
        pipe.set(owner_key(session_id), user_id, ex=ttl)
        if context_body is not None:
            pipe.set(f"session:{session_id}:context", json.dumps(context_body), ex=ttl)
        pipe.execute()

    def _insert_postgres_many(self, user_id: str, session_id: str, messages: list[tuple[str, str]]) -> None:
        with self._postgres() as connection:
            connection.execute(
                "INSERT INTO app_users (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING",
                (user_id,),
            )
            connection.execute(
                """
                INSERT INTO conversations (conversation_id, user_id)
                VALUES (%s, %s)
                ON CONFLICT (conversation_id) DO NOTHING
                """,
                (session_id, user_id),
            )
            for role, content in messages:
                connection.execute(
                    """
                    INSERT INTO messages (conversation_id, user_id, role, content)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (session_id, user_id, role, content),
                )
            connection.commit()

    def stage_messages(
        self,
        user_id: str,
        session_id: str,
        messages: list[tuple[str, str]],
        context_body: dict | None = None,
        owner: str | None = None,
        owner_known: bool = False,
        durable_wait: float = 2.0,
    ) -> dict:
        """Write the session cache, then wait briefly for the database copy.

        ``stored_in`` lists only the stores that accepted the turn.
        ``durable`` is ``stored``, ``failed``, or ``timeout``.
        """
        if not owner_known:
            owner = self.session_owner(session_id, database=False)
        if owner and owner != user_id:
            raise PermissionError("session_owner_mismatch")
        prepared = []
        for role, content in messages:
            if role not in {"user", "assistant"}:
                raise ValueError("role must be user or assistant")
            prepared.append((role, clip_text(content, session_message_max_chars())))
        stored: list[str] = []
        redis_error = ""
        try:
            self._remember_redis(user_id, session_id, prepared, context_body)
            stored.append("redis")
        except Exception as exc:
            redis_error = exc.__class__.__name__
        outcome: dict[str, str] = {}

        def durable() -> None:
            try:
                self._insert_postgres_many(user_id, session_id, prepared)
                outcome["durable"] = "stored"
            except Exception as exc:
                outcome["durable"] = "failed"
                outcome["error"] = exc.__class__.__name__

        thread = threading.Thread(target=durable, name="session-durable", daemon=True)
        thread.start()
        if durable_wait > 0:
            thread.join(durable_wait)
        if outcome.get("durable") == "stored":
            stored.append("postgres")
            durable_state = "stored"
        elif outcome.get("durable") == "failed":
            durable_state = "failed"
        elif durable_wait >= 1:
            durable_state = "timeout"
        else:
            durable_state = "queued"
        return {
            "session_id": session_id,
            "stored_in": stored,
            "durable": durable_state,
            "redis_error": redis_error,
            "postgres_error": outcome.get("error", ""),
        }

    def append_message(self, user_id: str, session_id: str, role: str, content: str) -> dict:
        if role not in {"user", "assistant"}:
            raise ValueError("role must be user or assistant")
        owner = self.session_owner(session_id)
        if owner and owner != user_id:
            raise PermissionError("session_owner_mismatch")
        content = clip_text(content, session_message_max_chars())
        message_id = self._insert_postgres(user_id, session_id, role, content)
        self._remember_redis(user_id, session_id, [(role, content)])
        return {"message_id": message_id, "session_id": session_id, "stored_in": ["postgres", "redis"]}

    def recent_messages(self, session_id: str) -> list[dict]:
        raw = self._redis().lrange(session_key(session_id), -session_message_limit(), -1)
        return [json.loads(item) for item in raw]

    def conversation_summary(self, session_id: str) -> dict:
        """Return the stored transcript. This is not a model-written summary."""
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a non-empty string")
        session_id = session_id.strip()
        with self._postgres() as connection:
            rows = connection.execute(
                """
                SELECT user_id, role, content, created_at
                FROM messages
                WHERE conversation_id = %s
                ORDER BY id
                """,
                (session_id,),
            ).fetchall()
        if not rows:
            return {"ok": False, "error": "not_found", "session_id": session_id}
        messages = []
        for row in rows[-session_message_limit():]:
            created = row[3]
            messages.append({
                "role": row[1],
                "content": row[2],
                "created_at": created.isoformat() if hasattr(created, "isoformat") else str(created),
            })
        return {
            "ok": True,
            "session_id": session_id,
            "user_id": rows[0][0],
            "message_count": len(rows),
            "messages": messages,
        }

    def save_preference(self, user_id: str, key: str, value: str, confirmed: bool = True) -> dict:
        key = clip_text(str(key or "").strip(), 40)
        value = clip_text(str(value or "").strip(), preference_value_max_chars())
        if not key or not value:
            raise ValueError("preference key and value are required")
        with self._postgres() as connection:
            connection.execute(
                "INSERT INTO app_users (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING",
                (user_id,),
            )
            connection.execute(
                """
                INSERT INTO user_preferences (user_id, preference_key, preference_value, confirmed, updated_at)
                VALUES (%s, %s, %s, %s, now())
                ON CONFLICT (user_id, preference_key)
                DO UPDATE SET preference_value = EXCLUDED.preference_value,
                              confirmed = EXCLUDED.confirmed,
                              updated_at = now()
                """,
                (user_id, key, value, confirmed),
            )
            connection.commit()
        return {"user_id": user_id, "key": key, "confirmed": confirmed}

    def preferences(self, user_id: str) -> list[dict]:
        with self._postgres() as connection:
            rows = connection.execute(
                """
                SELECT preference_key, preference_value, confirmed
                FROM user_preferences
                WHERE user_id = %s
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (user_id, preference_limit()),
            ).fetchall()
        return [
            {"key": row[0], "value": row[1], "confirmed": row[2]}
            for row in rows
        ]

    def list_sessions(self, user_id: str, limit: int = 20) -> list[dict]:
        with self._postgres() as connection:
            rows = connection.execute(
                """
                SELECT c.conversation_id, c.started_at,
                       (
                         SELECT left(m.content, 120)
                         FROM messages m
                         WHERE m.conversation_id = c.conversation_id AND m.role = 'user'
                         ORDER BY m.id DESC
                         LIMIT 1
                       ) AS preview
                FROM conversations c
                WHERE c.user_id = %s
                ORDER BY c.started_at DESC
                LIMIT %s
                """,
                (user_id, limit),
            ).fetchall()
        sessions = []
        for row in rows:
            started = row[1]
            sessions.append({
                "session_id": row[0],
                "started_at": started.isoformat() if hasattr(started, "isoformat") else str(started),
                "preview": row[2] or "",
            })
        return sessions

    def ops_snapshot(self) -> dict:
        """Counts and recent rows. Connection strings are not included."""
        postgres = {"connected": False, "database_bytes": None, "quota": "无法从当前接口获取", "tables": [], "recent_messages": [], "error": None}
        redis_status = {"connected": False, "used_memory_bytes": None, "session_keys": 0, "sessions": [], "error": None}
        if self.database_url:
            try:
                with self._postgres() as connection:
                    counts = connection.execute(
                        """
                        SELECT
                          (SELECT count(*) FROM app_users),
                          (SELECT count(*) FROM conversations),
                          (SELECT count(*) FROM messages),
                          (SELECT count(*) FROM user_preferences),
                          pg_total_relation_size('app_users'),
                          pg_total_relation_size('conversations'),
                          pg_total_relation_size('messages'),
                          pg_total_relation_size('user_preferences'),
                          pg_database_size(current_database())
                        """
                    ).fetchone()
                    recent = connection.execute(
                        """
                        SELECT conversation_id, role, left(content, 160), created_at
                        FROM messages
                        ORDER BY id DESC
                        LIMIT 12
                        """
                    ).fetchall()
                names = ("app_users", "conversations", "messages", "user_preferences")
                for index, name in enumerate(names):
                    postgres["tables"].append({
                        "name": name,
                        "rows": int(counts[index]),
                        "bytes": int(counts[index + 4]),
                    })
                postgres["database_bytes"] = int(counts[8])
                postgres["connected"] = True
                for row in recent:
                    created = row[3]
                    postgres["recent_messages"].append({
                        "session_id": row[0],
                        "role": row[1],
                        "content": row[2],
                        "created_at": created.isoformat() if hasattr(created, "isoformat") else str(created),
                    })
            except Exception as exc:
                postgres["error"] = exc.__class__.__name__
        else:
            postgres["error"] = "not_configured"
        if self.redis_url:
            try:
                client = self._redis()
                info = client.info("memory")
                redis_status["connected"] = True
                redis_status["used_memory_bytes"] = int(info.get("used_memory") or 0)
                dataset = info.get("used_memory_dataset")
                redis_status["used_memory_dataset_bytes"] = int(dataset) if dataset is not None else None
                redis_status["db_keys"] = int(client.dbsize() or 0)
                redis_status["memory_note"] = (
                    "used_memory is the whole Redis process. "
                    "Clearing this app's session keys does not shrink it to zero: "
                    "Redis keeps allocator overhead, and keys outside this app remain."
                )
                cursor = 0
                found = []
                while len(found) < 30:
                    cursor, keys = client.scan(cursor=cursor, match="session:*:messages", count=50)
                    found.extend(keys)
                    if cursor in {0, "0"}:
                        break
                redis_status["session_keys"] = len(found)
                for key in found[:12]:
                    session_id = str(key).split(":")[1] if ":" in str(key) else str(key)
                    redis_status["sessions"].append({
                        "session_id": session_id,
                        "messages": int(client.llen(key) or 0),
                        "ttl_seconds": int(client.ttl(key) or -1),
                    })
            except Exception as exc:
                redis_status["error"] = exc.__class__.__name__
        else:
            redis_status["error"] = "not_configured"
        return {"postgres": postgres, "redis": redis_status}

    def clear_sessions(self) -> dict:
        """Delete chat sessions only. Restaurant rows and preferences stay."""
        removed_keys = 0
        if self.redis_url:
            client = self._redis()
            cursor = 0
            while True:
                cursor, keys = client.scan(cursor=cursor, match="session:*", count=100)
                for key in keys:
                    text = str(key)
                    if text.endswith(":messages") or text.endswith(":user") or text.endswith(":context"):
                        client.delete(key)
                        removed_keys += 1
                if cursor in {0, "0"}:
                    break
        messages = 0
        conversations = 0
        if self.database_url:
            with self._postgres() as connection:
                messages = connection.execute("DELETE FROM messages").rowcount or 0
                conversations = connection.execute("DELETE FROM conversations").rowcount or 0
                connection.commit()
        return {"redis_keys": removed_keys, "messages": messages, "conversations": conversations}

    def delete_user(self, user_id: str) -> dict:
        removed_sessions = []
        with self._postgres() as connection:
            sessions = connection.execute(
                "SELECT conversation_id FROM conversations WHERE user_id = %s",
                (user_id,),
            ).fetchall()
            removed_sessions = [row[0] for row in sessions]
            connection.execute("DELETE FROM app_users WHERE user_id = %s", (user_id,))
            connection.commit()
        client = self._redis()
        for session_id in removed_sessions:
            client.delete(session_key(session_id), owner_key(session_id))
        return {"user_id": user_id, "deleted_sessions": removed_sessions}

    def cleanup_sessions(self) -> dict:
        return cleanup_session_keys(self._redis())
