from fastapi.testclient import TestClient

from app import allowed_origins, app
from food_copilot.config.settings import feature_flags

client = TestClient(app)


class MemoryDouble:
    def __init__(self):
        self.owner = "user-a"
        self.deleted = []
        self.saved = []

    def status(self):
        return {"postgres": True, "redis": True}

    def session_owner(self, session_id):
        return self.owner if session_id == "session-a" else None

    def recent_messages(self, session_id):
        return [{"role": "user", "content": "private note"}]

    def append_message(self, user_id, session_id, role, content):
        if self.session_owner(session_id) not in {None, user_id}:
            raise PermissionError("session_owner_mismatch")
        if "postgres://" in content or "sk-" in content:
            raise RuntimeError("connect postgres://user:secret@db/app failed sk-live")
        return {"message_id": 1, "session_id": session_id}

    def preferences(self, user_id):
        if user_id == "user-b":
            raise RuntimeError("postgres://user:secret@db/app")
        return [{"key": "diet", "value": "quiet", "confirmed": True}]

    def save_preference(self, user_id, key, value, confirmed=True):
        self.saved.append(user_id)
        return {"user_id": user_id, "key": key, "confirmed": confirmed}

    def delete_user(self, user_id):
        self.deleted.append(user_id)
        return {"user_id": user_id, "deleted_sessions": []}

    def _postgres(self):
        raise RuntimeError("postgres://user:secret@db/app")

    def _redis(self):
        raise RuntimeError("redis://:secret@cache")


def _patch_memory(monkeypatch, open_local=True):
    store = MemoryDouble()
    monkeypatch.setattr("food_copilot.api.routes.MemoryStore", lambda: store)
    monkeypatch.setattr("food_copilot.memory.store.load_local_env", lambda: None)
    if open_local:
        monkeypatch.setenv("ALLOW_UNAUTHENTICATED_MEMORY", "true")
    else:
        monkeypatch.delenv("ALLOW_UNAUTHENTICATED_MEMORY", raising=False)
    return store


def test_oversized_and_malformed_requests_are_rejected():
    too_long = client.post("/api/discover", json={"query": "x" * 1001})
    assert too_long.status_code == 422
    bad_id = client.post("/api/chat", json={"query": "Old Klang Road", "user_id": "../admin"})
    assert bad_id.status_code == 422
    assert "sk-" not in too_long.text


def test_memory_errors_do_not_include_credentials(monkeypatch):
    _patch_memory(monkeypatch)
    response = client.get("/api/memory/preferences/user-b")
    assert response.status_code == 503
    assert response.json()["detail"] == "Memory stores are unavailable."
    assert "postgres://" not in response.text
    assert "secret" not in response.text
    assert "sk-" not in response.text


def test_another_users_session_is_not_readable(monkeypatch):
    _patch_memory(monkeypatch)
    foreign = client.get("/api/memory/sessions/session-a", params={"user_id": "user-b"})
    assert foreign.status_code == 404
    assert "private note" not in foreign.text
    owner = client.get("/api/memory/sessions/session-a", params={"user_id": "user-a"})
    assert owner.status_code == 200
    assert owner.json()["messages"][0]["content"] == "private note"


def test_a_foreign_session_write_is_not_saved(monkeypatch):
    store = _patch_memory(monkeypatch)
    response = client.post("/api/memory/messages", json={
        "user_id": "user-b",
        "session_id": "session-a",
        "content": "take over",
    })
    assert response.status_code == 404
    assert store.saved == []


def test_memory_routes_are_closed_without_authenticated_identity(monkeypatch):
    store = _patch_memory(monkeypatch, open_local=False)
    response = client.delete("/api/memory/users/user-a")
    assert response.status_code == 403
    assert "not an account" in response.json()["detail"]
    assert store.deleted == []
    saved = client.post("/api/memory/preferences", json={
        "user_id": "user-b",
        "key": "diet",
        "value": "quiet",
        "confirmed": True,
    })
    assert saved.status_code == 403
    assert store.saved == []


def test_readiness_reports_dependencies_without_secrets(monkeypatch):
    class Up:
        def status(self):
            return {"postgres": True, "redis": True}

        def _postgres(self):
            class Conn:
                def execute(self, _query):
                    return None

                def close(self):
                    return None

            return Conn()

        def _redis(self):
            class Client:
                def ping(self):
                    return True

                def close(self):
                    return None

            return Client()

    monkeypatch.setattr("food_copilot.memory.store.MemoryStore", Up)
    monkeypatch.delenv("ENABLE_LLM_AGENT", raising=False)
    monkeypatch.delenv("ENABLE_LANGGRAPH", raising=False)
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["postgres"] is True
    assert body["redis"] is True
    assert body["llm_agent"] is False
    assert body["langgraph"] is False
    assert body["authentication"] == "not_configured"
    assert "postgres://" not in response.text


def test_readiness_does_not_claim_a_down_database_is_ready(monkeypatch):
    monkeypatch.delenv("ALLOW_UNAUTHENTICATED_MEMORY", raising=False)
    monkeypatch.setattr("food_copilot.memory.store.MemoryStore", MemoryDouble)
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["memory_required"] is False
    assert body["postgres"] is False
    assert body["postgres_state"] == "down"
    assert "postgres" in body["optional_unavailable"]
    assert "secret" not in response.text


def test_cors_allows_the_local_vue_origin_only():
    allowed = client.get("/health", headers={"Origin": "http://127.0.0.1:5173"})
    blocked = client.get("/health", headers={"Origin": "https://evil.example"})
    assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert "access-control-allow-origin" not in blocked.headers


def test_wildcard_origin_is_not_accepted(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "*")
    assert allowed_origins() == ["http://127.0.0.1:5173", "http://localhost:5173"]


def test_feature_flags_stay_off_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_LLM_AGENT", raising=False)
    monkeypatch.delenv("ENABLE_LANGGRAPH", raising=False)
    flags = feature_flags()
    assert flags["ENABLE_LLM_AGENT"] is False
    assert flags["ENABLE_LANGGRAPH"] is False
