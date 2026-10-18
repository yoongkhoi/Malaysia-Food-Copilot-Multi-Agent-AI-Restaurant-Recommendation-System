"""Round-trip the configured Neon and Redis memory stores, then delete the probe user."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from food_copilot.memory.store import MemoryStore


def main() -> int:
    store = MemoryStore()
    status = store.status()
    print(f"postgres_configured={status['postgres']} redis_configured={status['redis']}")
    if not status["postgres"] or not status["redis"]:
        print("missing configuration")
        return 1
    user_id = "memory-probe-user"
    session_id = "memory-probe-session"
    store.ensure_schema()
    store.delete_user(user_id)
    saved = store.append_message(user_id, session_id, "user", "I prefer quiet vegetarian places under RM40.")
    recent = store.recent_messages(session_id)
    preference = store.save_preference(user_id, "dietary_preference", "vegetarian", confirmed=True)
    loaded = store.preferences(user_id)
    deleted = store.delete_user(user_id)
    after = store.preferences(user_id)
    redis_after = store.recent_messages(session_id)
    ok = (
        saved["stored_in"] == ["postgres", "redis"]
        and recent[-1]["content"].startswith("I prefer quiet")
        and preference["confirmed"] is True
        and loaded == [{"key": "dietary_preference", "value": "vegetarian", "confirmed": True}]
        and session_id in deleted["deleted_sessions"]
        and after == []
        and redis_after == []
    )
    print(f"round_trip_ok={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
