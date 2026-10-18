import asyncio
import json

from food_copilot.agents.orchestrator import handle_message
from food_copilot.mcp.server import build_mcp_server
from food_copilot.mcp.tools import (
    conversation_summary,
    discover_restaurants,
    restaurant_details,
    restaurant_evidence,
    save_user_preference,
    user_preferences,
)
from food_copilot.services.discovery import DiscoveryService
from tests.helpers import restaurant

QUERY = "Find a family-friendly restaurant in Old Klang Road under RM20."
HALAL_QUERY = "Find a verified halal restaurant in Old Klang Road under RM20."


class MemoryDouble:
    def __init__(self, postgres=True, redis=True, fail=False):
        self.database_url = "configured" if postgres else ""
        self.redis_url = "configured" if redis else ""
        self.fail = fail
        self.preferences_by_user = {}
        self.sessions = {}

    def status(self):
        return {"postgres": bool(self.database_url), "redis": bool(self.redis_url)}

    def _check(self):
        if self.fail or not self.database_url or not self.redis_url:
            raise RuntimeError("memory store unavailable")

    def preferences(self, user_id):
        self._check()
        return list(self.preferences_by_user.get(user_id, []))

    def save_preference(self, user_id, key, value, confirmed=True):
        self._check()
        rows = [item for item in self.preferences_by_user.get(user_id, []) if item["key"] != key]
        rows.append({"key": key, "value": value, "confirmed": confirmed})
        self.preferences_by_user[user_id] = rows
        return {"user_id": user_id, "key": key, "confirmed": confirmed}

    def conversation_summary(self, session_id):
        self._check()
        messages = self.sessions.get(session_id)
        if not messages:
            return {"ok": False, "error": "not_found", "session_id": session_id}
        return {
            "ok": True,
            "session_id": session_id,
            "user_id": messages[0]["user_id"],
            "message_count": len(messages),
            "messages": messages,
        }

    def delete_user(self, user_id):
        self._check()
        self.preferences_by_user.pop(user_id, None)
        removed = [session_id for session_id, rows in self.sessions.items() if rows and rows[0]["user_id"] == user_id]
        for session_id in removed:
            self.sessions.pop(session_id, None)
        return {"user_id": user_id, "deleted_sessions": removed}


def _service():
    return DiscoveryService(records=[
        restaurant("priced", price_range_myr={"min": 8, "max": 12, "basis": "per_person", "status": "verified", "source_url": "https://example.local/menu"}),
        restaurant("unknown-price"),
        restaurant(
            "halal-branch",
            price_range_myr={"min": 10, "max": 18, "basis": "per_person", "status": "verified", "source_url": "https://example.local/menu"},
            halal_status={"status": "verified", "source_url": "https://example.local/halal"},
        ),
        restaurant(
            "halal-no-url",
            price_range_myr={"min": 10, "max": 18, "basis": "per_person", "status": "verified", "source_url": "https://example.local/menu"},
            halal_status={"status": "verified", "source_url": ""},
        ),
    ])


def test_tools_are_discoverable_by_an_mcp_client():
    service = _service()
    memory = MemoryDouble()
    server = build_mcp_server(service=service, memory=memory, repository=service.repository)

    async def run():
        from mcp.shared.memory import create_connected_server_and_client_session

        async with create_connected_server_and_client_session(server._mcp_server) as session:
            listed = await session.list_tools()
            names = sorted(tool.name for tool in listed.tools)
            called = await session.call_tool("discover_restaurants", {"query": QUERY})
            missing = await session.call_tool("get_restaurant_details", {"restaurant_id": "missing-id"})
            return names, called, missing

    names, called, missing = asyncio.run(run())
    assert names == [
        "discover_restaurants",
        "get_conversation_summary",
        "get_restaurant_details",
        "get_restaurant_evidence",
        "get_restaurant_reviews",
        "get_user_preferences",
        "save_user_preference",
        "search_restaurants",
    ]
    payload = called.structuredContent or json.loads(called.content[0].text)
    assert set(payload["eligible_restaurant_ids"]) == {"halal-branch", "halal-no-url", "priced", "unknown-price"}
    assert missing.isError is False
    missing_payload = missing.structuredContent or json.loads(missing.content[0].text)
    assert missing_payload["ok"] is False
    assert missing_payload["error"] == "not_found"


def test_each_tool_returns_a_structured_result():
    service = _service()
    memory = MemoryDouble()
    memory.sessions["session-1"] = [{"user_id": "user-1", "role": "user", "content": "quiet places"}]
    repository = service.repository
    discovered = discover_restaurants(QUERY, service=service)
    details = restaurant_details("priced", repository=repository)
    evidence = restaurant_evidence("priced", repository=repository)
    saved = save_user_preference("user-1", "ambience", "quiet", True, memory=memory)
    prefs = user_preferences("user-1", memory=memory)
    summary = conversation_summary("session-1", memory=memory)
    assert discovered["ok"] is True and "answer" in discovered and "constraints" in discovered
    assert details["ok"] is True and details["restaurant"]["restaurant_id"] == "priced"
    assert evidence["ok"] is True and evidence["price_status"] == "verified"
    assert saved["ok"] is True and saved["confirmed"] is True
    assert prefs["preferences"][0]["value"] == "quiet"
    assert "not a restaurant fact" in prefs["note"]
    assert summary["ok"] is True and summary["message_count"] == 1


def test_missing_and_blank_restaurant_ids():
    repository = _service().repository
    missing = restaurant_details("missing-id", repository=repository)
    evidence = restaurant_evidence("missing-id", repository=repository)
    blank = restaurant_details("  ", repository=repository)
    assert missing == {"ok": False, "error": "not_found", "restaurant_id": "missing-id"}
    assert evidence["error"] == "not_found"
    assert blank["error"] == "invalid_input"


def test_unverified_price_and_halal_stay_excluded():
    service = _service()
    budget = discover_restaurants(QUERY, service=service)
    halal = discover_restaurants(HALAL_QUERY, service=service)
    assert set(budget["eligible_restaurant_ids"]) == {"halal-branch", "halal-no-url", "priced", "unknown-price"}
    assert halal["eligible_restaurant_ids"] == ["halal-branch"]
    assert "halal-no-url" not in halal["eligible_restaurant_ids"]
    assert halal["exclusion_counts"]["halal_not_verified"] >= 1


def test_mcp_matches_existing_discovery_ids():
    service = _service()
    via_mcp = discover_restaurants(QUERY, service=service)
    via_orchestrator = handle_message(QUERY, service)
    assert via_mcp["eligible_restaurant_ids"] == [item["restaurant_id"] for item in via_orchestrator["results"]]
    assert via_mcp["needs_clarification"] == via_orchestrator["needs_clarification"]
    assert via_mcp["exclusion_counts"] == via_orchestrator["exclusion_counts"]


def test_preference_round_trip_requires_confirmation_and_delete_clears_it():
    memory = MemoryDouble()
    rejected = save_user_preference("user-1", "ambience", "quiet", False, memory=memory)
    assert rejected["ok"] is False
    assert rejected["error"] == "confirmation_required"
    assert memory.preferences_by_user == {}
    saved = save_user_preference("user-1", "ambience", "quiet", True, memory=memory)
    assert saved["ok"] is True
    assert user_preferences("user-1", memory=memory)["preferences"] == [
        {"key": "ambience", "value": "quiet", "confirmed": True}
    ]
    memory.sessions["session-1"] = [{"user_id": "user-1", "role": "user", "content": "quiet places"}]
    deleted = memory.delete_user("user-1")
    assert deleted["deleted_sessions"] == ["session-1"]
    assert user_preferences("user-1", memory=memory)["preferences"] == []
    assert conversation_summary("session-1", memory=memory)["error"] == "not_found"


def test_unavailable_memory_is_not_reported_as_success():
    empty = MemoryDouble(postgres=False, redis=False)
    failing = MemoryDouble(fail=True)
    for memory in (empty, failing):
        saved = save_user_preference("user-1", "ambience", "quiet", True, memory=memory)
        assert saved["ok"] is False
        assert saved["error"] == "memory_unavailable"
        assert user_preferences("user-1", memory=memory)["ok"] is False
        assert conversation_summary("session-1", memory=memory)["ok"] is False
    assert empty.preferences_by_user == {}
