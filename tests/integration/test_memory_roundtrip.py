"""Real Redis and Postgres round trip. Skips when the stores are not configured."""

import uuid

import pytest

from food_copilot.memory.store import MemoryStore, load_local_env


@pytest.fixture(scope="module")
def configured_store():
    load_local_env()
    store = MemoryStore()
    status = store.status()
    if not status["postgres"] or not status["redis"]:
        pytest.skip("Redis or Postgres URL is not configured")
    return store


def test_configured_stores_can_write_and_read_a_probe_session(configured_store):
    store = configured_store
    session_id = "probe" + uuid.uuid4().hex[:12]
    user_id = "probe" + uuid.uuid4().hex[:12]
    text = "probe-only-turn"
    try:
        try:
            saved = store.stage_messages(
                user_id,
                session_id,
                [("user", text), ("assistant", text)],
                durable_wait=20,
            )
        except Exception as exc:
            pytest.fail(exc.__class__.__name__)
        assert "redis" in saved["stored_in"]
        loaded = store.read_session(session_id)
        assert [item["content"] for item in loaded["messages"]] == [text, text]
        if saved["durable"] != "stored":
            pytest.fail("postgres " + saved["durable"] + " " + (saved.get("postgres_error") or ""))
        summary = store.conversation_summary(session_id)
        assert summary["ok"] is True
        assert [item["content"] for item in summary["messages"]] == [text, text]
    finally:
        try:
            client = store._redis()
            client.delete(
                f"session:{session_id}:messages",
                f"session:{session_id}:user",
                f"session:{session_id}:context",
            )
        except Exception:
            pass
        try:
            with store._postgres() as connection:
                connection.execute("DELETE FROM messages WHERE conversation_id = %s", (session_id,))
                connection.execute("DELETE FROM conversations WHERE conversation_id = %s", (session_id,))
                connection.execute(
                    "DELETE FROM app_users WHERE user_id = %s AND NOT EXISTS (SELECT 1 FROM conversations WHERE user_id = %s)",
                    (user_id, user_id),
                )
                connection.commit()
        except Exception:
            pass
