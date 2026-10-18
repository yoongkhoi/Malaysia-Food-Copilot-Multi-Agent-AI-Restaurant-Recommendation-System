import json

from food_copilot.memory.store import MemoryStore


class FakePipe:
    def __init__(self, client):
        self.client = client
        self.ops = []

    def get(self, key):
        self.ops.append(("get", key))
        return self

    def lrange(self, key, start, end):
        self.ops.append(("lrange", key, start, end))
        return self

    def rpush(self, key, value):
        self.ops.append(("rpush", key, value))
        return self

    def ltrim(self, key, start, end):
        self.ops.append(("ltrim", key))
        return self

    def expire(self, key, ttl):
        self.ops.append(("expire", key))
        return self

    def set(self, key, value, ex=None):
        self.ops.append(("set", key, value))
        return self

    def execute(self):
        results = []
        for op in self.ops:
            if op[0] == "get":
                results.append(self.client.store.get(op[1]))
            elif op[0] == "lrange":
                results.append(list(self.client.store.get(op[1], [])))
            elif op[0] == "rpush":
                self.client.store.setdefault(op[1], []).append(op[2])
            elif op[0] == "set":
                self.client.store[op[1]] = op[2]
        self.ops = []
        return results


class FakeRedis:
    def __init__(self):
        self.store = {}

    def pipeline(self):
        return FakePipe(self)


class FakeConnection:
    def __init__(self, fail=False, delay=0):
        self.fail = fail
        self.delay = delay
        self.rows = []
        self.committed = False

    def __enter__(self):
        if self.delay:
            import time
            time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("postgres://user:secret@db/app")
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.rows.append((query, params))
        return self

    def commit(self):
        self.committed = True


def _store(redis, connection):
    store = MemoryStore.__new__(MemoryStore)
    store._redis = lambda: redis
    store._postgres = lambda: connection
    store.session_owner = lambda session_id, database=True: None
    return store


def test_write_and_read_back_one_session():
    redis = FakeRedis()
    connection = FakeConnection()
    store = _store(redis, connection)
    saved = store.stage_messages("user-a", "session-a", [("user", "Korean BBQ"), ("assistant", "Sae Ma Eul")])
    assert saved["stored_in"] == ["redis", "postgres"]
    assert saved["durable"] == "stored"
    loaded = store.read_session("session-a")
    assert [item["content"] for item in loaded["messages"]] == ["Korean BBQ", "Sae Ma Eul"]
    assert connection.committed is True
    assert "secret" not in json.dumps(saved)


def test_two_sessions_stay_isolated():
    redis = FakeRedis()
    store = _store(redis, FakeConnection())
    store.stage_messages("user-a", "session-a", [("user", "Old Klang Road")])
    store.stage_messages("user-b", "session-b", [("user", "Kuala Lumpur")])
    assert store.read_session("session-a")["messages"][0]["content"] == "Old Klang Road"
    assert store.read_session("session-b")["messages"][0]["content"] == "Kuala Lumpur"


def test_redis_failure_can_still_store_postgres():
    class BrokenRedis(FakeRedis):
        def pipeline(self):
            raise ConnectionError("redis down")

    connection = FakeConnection()
    store = _store(BrokenRedis(), connection)
    saved = store.stage_messages("user-a", "session-a", [("user", "Korean BBQ")])
    assert saved["stored_in"] == ["postgres"]
    assert saved["durable"] == "stored"
    assert saved["redis_error"] == "ConnectionError"
    assert connection.committed is True


def test_postgres_failure_keeps_the_redis_copy():
    redis = FakeRedis()
    store = _store(redis, FakeConnection(fail=True))
    saved = store.stage_messages("user-a", "session-a", [("user", "Korean BBQ")])
    assert saved["stored_in"] == ["redis"]
    assert saved["durable"] == "failed"
    assert saved["postgres_error"] == "RuntimeError"
    assert store.read_session("session-a")["messages"][0]["content"] == "Korean BBQ"
    assert "postgres://" not in json.dumps(saved)


def test_postgres_timeout_does_not_claim_the_database_copy():
    redis = FakeRedis()
    store = _store(redis, FakeConnection(delay=2.2))
    saved = store.stage_messages("user-a", "session-a", [("user", "Korean BBQ")])
    assert saved["stored_in"] == ["redis"]
    assert saved["durable"] == "timeout"
    assert store.read_session("session-a")["messages"]


def test_a_new_session_has_no_inherited_transcript():
    redis = FakeRedis()
    store = _store(redis, FakeConnection())
    store.stage_messages("user-a", "session-a", [("user", "Korean BBQ")])
    assert store.read_session("session-new")["messages"] == []
    assert store.read_session("session-new")["context"] == {}
