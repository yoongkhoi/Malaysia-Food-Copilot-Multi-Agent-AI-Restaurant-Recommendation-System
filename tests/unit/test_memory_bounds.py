import json

from food_copilot.memory.store import (
    MemoryStore,
    cleanup_session_keys,
    clip_text,
    owner_key,
    session_key,
    session_message_limit,
    session_message_max_chars,
    session_ttl_seconds,
)


class _Redis:
    def __init__(self):
        self.lists = {}
        self.values = {}
        self.expires = {}
        self.flushed = False

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

    def ltrim(self, key, start, end):
        items = self.lists.get(key, [])
        if start < 0:
            start = max(len(items) + start, 0)
        if end < 0:
            end = len(items) + end
        self.lists[key] = items[start:end + 1]

    def lrange(self, key, start, end):
        items = self.lists.get(key, [])
        if start < 0:
            start = max(len(items) + start, 0)
        if end == -1:
            return items[start:]
        return items[start:end + 1]

    def llen(self, key):
        return len(self.lists.get(key, []))

    def expire(self, key, ttl):
        self.expires[key] = ttl

    def ttl(self, key):
        return self.expires.get(key, -1)

    def set(self, key, value, ex=None):
        self.values[key] = value
        if ex is not None:
            self.expires[key] = ex

    def get(self, key):
        return self.values.get(key)

    def scan(self, cursor=0, match=None, count=100):
        keys = list(self.lists) + [key for key in self.values if key not in self.lists]
        return 0, keys

    def flushdb(self):
        self.flushed = True

    def flushall(self):
        self.flushed = True

    def pipeline(self):
        redis = self

        class Pipe:
            def __init__(self):
                self.ops = []

            def rpush(self, key, value):
                self.ops.append(("rpush", key, value))
                return self

            def ltrim(self, key, start, end):
                self.ops.append(("ltrim", key, start, end))
                return self

            def expire(self, key, ttl):
                self.ops.append(("expire", key, ttl))
                return self

            def set(self, key, value, ex=None):
                self.ops.append(("set", key, value, ex))
                return self

            def execute(self):
                for name, *args in self.ops:
                    getattr(redis, name)(*args)
                return []

        return Pipe()


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, *_args, **_kwargs):
        return self

    def fetchone(self):
        return (1,)

    def commit(self):
        return None


def test_session_bounds_are_configurable(monkeypatch):
    monkeypatch.setenv("SESSION_TTL_SECONDS", "120")
    monkeypatch.setenv("SESSION_MESSAGE_LIMIT", "3")
    monkeypatch.setenv("SESSION_MESSAGE_MAX_CHARS", "250")
    assert session_ttl_seconds() == 120
    assert session_message_limit() == 3
    assert session_message_max_chars() == 250
    assert clip_text("x" * 300, session_message_max_chars()) == "x" * 250


def test_append_keeps_only_the_new_session_and_sets_ttl(monkeypatch):
    monkeypatch.setenv("SESSION_MESSAGE_LIMIT", "2")
    monkeypatch.setenv("SESSION_TTL_SECONDS", "90")
    monkeypatch.setenv("SESSION_MESSAGE_MAX_CHARS", "220")
    redis = _Redis()
    redis.rpush(session_key("old-session"), json.dumps({"role": "user", "content": "keep me"}))
    store = MemoryStore(database_url="postgres://example", redis_url="redis://example")
    store._postgres = lambda: _Connection()
    store._redis = lambda: redis
    store.session_owner = lambda _session_id: None
    store.append_message("user-1", "new-session", "user", "m" * 400)
    assert redis.values[owner_key("new-session")] == "user-1"
    assert redis.expires[session_key("new-session")] == 90
    stored = json.loads(redis.lists[session_key("new-session")][0])
    assert stored["content"] == "m" * 220
    assert session_key("old-session") in redis.lists
    assert "keep me" in redis.lists[session_key("old-session")][0]


def test_cleanup_trims_only_prefixed_session_keys():
    redis = _Redis()
    redis.lists[session_key("abc")] = ["1", "2", "3", "4"]
    redis.lists["other-app:session"] = ["secret"]
    redis.values["session:not a valid key:messages"] = "skip"
    monkey_limit = 2
    import food_copilot.memory.store as store

    original = store.session_message_limit
    store.session_message_limit = lambda: monkey_limit
    try:
        report = cleanup_session_keys(redis)
    finally:
        store.session_message_limit = original
    assert redis.lists[session_key("abc")] == ["3", "4"]
    assert redis.lists["other-app:session"] == ["secret"]
    assert redis.expires[session_key("abc")] > 0
    assert "other-app:session" not in redis.expires
    assert report["deleted"] == 0
    assert report["skipped"] >= 1
    assert redis.flushed is False


def test_cleanup_refuses_database_flush_commands():
    source = open("src/food_copilot/memory/store.py", encoding="utf-8").read().lower()
    assert "flushdb" not in source
    assert "flushall" not in source


def test_preference_value_is_clipped(monkeypatch):
    monkeypatch.setenv("PREFERENCE_VALUE_MAX_CHARS", "20")
    captured = {}

    class _Conn(_Connection):
        def execute(self, sql, params=None):
            if params and "user_preferences" in sql:
                captured["params"] = params
            return self

    store = MemoryStore(database_url="postgres://example", redis_url="")
    store._postgres = lambda: _Conn()
    saved = store.save_preference("user-1", "spice", "x" * 50, True)
    assert saved["key"] == "spice"
    assert captured["params"][2] == "x" * 20
