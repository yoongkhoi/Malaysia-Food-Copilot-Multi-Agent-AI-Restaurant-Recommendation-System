"""Preference agent. Python decides whether a proposal may be stored."""

import json
import re

from food_copilot.errors import ModelCallError

_CONFIRM = re.compile(
    r"remember (that|this)|save (this|that|my) preference|from now on|always prefer|"
    r"请记住|以后都|下次还是|长期偏好",
    re.I,
)


def with_saved_preferences(query: str, preferences: list | None) -> str:
    """Add confirmed diet or ambience preferences to the constraint text. They are not restaurant facts."""
    extra = []
    for item in preferences or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip().lower()
        value = str(item.get("value") or "").strip()
        if key in {"diet", "dietary", "ambience"} and value:
            extra.append(value)
    if not extra:
        return query
    return f"{query} {' '.join(extra)}"


def explicit_confirmation(text: str) -> bool:
    return bool(_CONFIRM.search(text or ""))


def review_preferences(query: str, model, memory=None, user_id: str | None = None, session_id: str | None = None) -> dict:
    saved = []
    if memory is not None and user_id and memory.status().get("postgres") and memory.status().get("redis"):
        try:
            saved = memory.preferences(user_id)
        except Exception:
            saved = []
    messages = [
        {
            "role": "system",
            "content": (
                "You extract food preferences. Return JSON with keys temporary and proposed. "
                "proposed is a list of objects with key and value. "
                "A request for today is temporary, not proposed. "
                "A user preference is not a restaurant price, address, or halal fact."
            ),
        },
        {
            "role": "user",
            "content": json.dumps({"query": query, "saved_preferences": saved, "session_id": session_id}, ensure_ascii=False),
        },
    ]
    reply = model.complete(messages)
    try:
        parsed = json.loads(reply.get("content") or "{}")
    except json.JSONDecodeError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    temporary = parsed.get("temporary") if isinstance(parsed.get("temporary"), list) else []
    proposed = []
    for item in parsed.get("proposed") or []:
        if isinstance(item, dict) and str(item.get("key") or "").strip() and str(item.get("value") or "").strip():
            proposed.append({"key": str(item["key"]).strip(), "value": str(item["value"]).strip()})
    stored = []
    if explicit_confirmation(query) and proposed and memory is not None and user_id:
        for item in proposed:
            try:
                memory.save_preference(user_id, item["key"], item["value"], True)
            except Exception as exc:
                raise ModelCallError("The preference was not saved.") from exc
            stored.append(item)
        proposed = []
    return {
        "temporary": [str(item) for item in temporary],
        "proposed_preferences": proposed,
        "saved_preferences": stored,
    }
