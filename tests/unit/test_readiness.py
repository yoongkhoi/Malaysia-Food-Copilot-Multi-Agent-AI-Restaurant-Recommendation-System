from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


class Probe:
    def __init__(self, postgres="up", redis="up", postgres_configured=True, redis_configured=True):
        self.postgres_mode = postgres
        self.redis_mode = redis
        self.postgres_configured = postgres_configured
        self.redis_configured = redis_configured
        self.closed = []

    def status(self):
        return {"postgres": self.postgres_configured, "redis": self.redis_configured}

    def _postgres(self):
        mode = self.postgres_mode
        closed = self.closed

        class Wrapper:
            def __enter__(self):
                if mode == "down":
                    raise RuntimeError("postgres://user:secret@db/app")
                if mode == "timeout":
                    raise TimeoutError("connect timed out")
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, _query):
                return None

            def close(self):
                closed.append("postgres")

        inner = Wrapper()

        class Held:
            def __enter__(self):
                return inner.__enter__()

            def __exit__(self, exc_type, exc, tb):
                return inner.__exit__(exc_type, exc, tb)

            def close(self):
                closed.append("held")

        return Held()

    def _redis(self):
        mode = self.redis_mode
        closed = self.closed

        class Client:
            def ping(self):
                if mode == "down":
                    raise RuntimeError("redis://:secret@cache")
                if mode == "timeout":
                    raise TimeoutError("socket timeout")
                return True

            def close(self):
                closed.append("redis")

        return Client()


def test_healthy_dependencies_are_ready_and_clients_stay_open(monkeypatch):
    probe = Probe()
    monkeypatch.setattr("food_copilot.memory.store.MemoryStore", lambda: probe)
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["postgres"] is True
    assert body["redis"] is True
    assert body["postgres_state"] == "up"
    assert body["redis_state"] == "up"
    assert probe.closed == []
    assert "secret" not in response.text


def test_required_memory_stays_unready_when_postgres_fails(monkeypatch):
    probe = Probe(postgres="down")
    monkeypatch.setenv("ALLOW_UNAUTHENTICATED_MEMORY", "true")
    monkeypatch.setattr("food_copilot.memory.store.MemoryStore", lambda: probe)
    response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["memory_required"] is True
    assert body["postgres"] is False
    assert body["redis"] is True
    assert probe.closed == []
    assert "postgres://" not in response.text


def test_timeout_is_not_reported_as_healthy(monkeypatch):
    probe = Probe(redis="timeout")
    monkeypatch.setenv("ALLOW_UNAUTHENTICATED_MEMORY", "true")
    monkeypatch.setattr("food_copilot.memory.store.MemoryStore", lambda: probe)
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["redis_state"] == "timeout"
    assert response.json()["redis"] is False


def test_disabled_memory_does_not_make_search_unready(monkeypatch):
    probe = Probe(postgres_configured=False, redis_configured=False)
    monkeypatch.delenv("ALLOW_UNAUTHENTICATED_MEMORY", raising=False)
    monkeypatch.setattr("food_copilot.memory.store.MemoryStore", lambda: probe)
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["memory_required"] is False
    assert body["postgres_state"] == "disabled"
    assert body["redis_state"] == "disabled"
    assert body["postgres"] is False
    assert body["redis"] is False


def test_partial_dependency_failure_keeps_optional_memory_separate(monkeypatch):
    probe = Probe(postgres="down", redis="up")
    monkeypatch.delenv("ALLOW_UNAUTHENTICATED_MEMORY", raising=False)
    monkeypatch.setattr("food_copilot.memory.store.MemoryStore", lambda: probe)
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["postgres"] is False
    assert body["redis"] is True
    assert body["optional_unavailable"] == ["postgres"]
