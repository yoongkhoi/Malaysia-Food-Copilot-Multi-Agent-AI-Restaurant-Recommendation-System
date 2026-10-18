import json

import pytest

from food_copilot.agents.graph import run_chat_graph
from food_copilot.agents.orchestrator import build_optional_graph
from food_copilot.errors import FeatureDisabled, ModelCallError
from food_copilot.services.discovery import DiscoveryService
from tests.helpers import restaurant

QUERY = "Find a restaurant in Old Klang Road under RM20."


class ScriptedModel:
    def __init__(self, replies):
        self.replies = list(replies)

    def complete(self, messages, tools=None):
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class MemoryDouble:
    def __init__(self, fail_write=False):
        self.fail_write = fail_write
        self.messages = []
        self.preferences = []

    def status(self):
        return {"postgres": True, "redis": True}

    def preferences(self, user_id):
        return [item for item in self.preferences if item["user_id"] == user_id]

    def recent_messages(self, session_id):
        return [item for item in self.messages if item["session_id"] == session_id]

    def save_preference(self, user_id, key, value, confirmed=True):
        self.preferences.append({
            "user_id": user_id,
            "key": key,
            "value": value,
            "confirmed": confirmed,
        })
        return {"user_id": user_id, "key": key, "confirmed": confirmed}

    def append_message(self, user_id, session_id, role, content):
        if self.fail_write:
            raise RuntimeError("memory down")
        self.messages.append({
            "user_id": user_id,
            "session_id": session_id,
            "role": role,
            "content": content,
        })
        return {"message_id": len(self.messages), "session_id": session_id}


def _service():
    return DiscoveryService(records=[
        restaurant(
            "MY-OSM-node-priced",
            price_range_myr={"min": 8, "max": 12, "basis": "per_person", "status": "verified", "source_url": "https://example.local/menu"},
        ),
        restaurant("MY-OSM-node-unknown"),
    ])


def _tools(name, arguments):
    return {
        "ok": True,
        "eligible_restaurant_ids": ["MY-OSM-node-priced", "MY-OSM-node-unknown"],
        "needs_clarification": False,
        "exclusion_counts": {},
    }


def _replies(preference, recommendation):
    return [
        {"content": json.dumps(preference), "tool_calls": []},
        {"content": recommendation, "tool_calls": []},
    ]


def test_langgraph_flag_stays_off_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_LANGGRAPH", raising=False)
    with pytest.raises(FeatureDisabled, match="ENABLE_LANGGRAPH is false"):
        build_optional_graph()


def test_graph_keeps_only_validated_restaurants_and_saves_the_turn():
    service = _service()
    memory = MemoryDouble()
    model = ScriptedModel(_replies(
        {"temporary": ["spicy today"], "proposed": [{"key": "diet", "value": "spicy"}]},
        "Please visit MY-OSM-node-unknown.",
    ))
    result = run_chat_graph(
        "I want spicy food today in Old Klang Road under RM20.",
        user_id="user-1",
        session_id="session-1",
        model=model,
        call_tool=_tools,
        memory=memory,
        repository=service.repository,
    )
    assert result["agent_mode"] == "langgraph"
    assert set(item["restaurant_id"] for item in result["results"]) == {"MY-OSM-node-priced", "MY-OSM-node-unknown"}
    assert result["saved_preferences"] == []
    assert memory.preferences == []
    assert result["memory_saved"] is True
    assert [item["role"] for item in memory.messages] == ["user", "assistant"]


def test_graph_saves_a_preference_only_after_explicit_confirmation():
    service = _service()
    memory = MemoryDouble()
    model = ScriptedModel(_replies(
        {"temporary": [], "proposed": [{"key": "ambience", "value": "quiet"}]},
        "No invented restaurant.",
    ))
    result = run_chat_graph(
        "Please remember that I prefer quiet restaurants in Old Klang Road under RM20.",
        user_id="user-1",
        session_id="session-1",
        model=model,
        call_tool=_tools,
        memory=memory,
        repository=service.repository,
    )
    assert result["saved_preferences"] == [{"key": "ambience", "value": "quiet"}]
    assert memory.preferences[0]["confirmed"] is True


def test_validator_removes_ids_the_agent_tried_to_include(monkeypatch):
    service = _service()

    def leaky(query, model, call_tool, repository=None, history=None):
        return {
            "answer": "Visit MY-OSM-node-unknown and MY-OSM-node-999.",
            "results": [
                {"restaurant_id": "MY-OSM-node-priced"},
                {"restaurant_id": "MY-OSM-node-unknown"},
                {"restaurant_id": "MY-OSM-node-999"},
            ],
            "exclusion_counts": {},
            "needs_clarification": False,
            "sources_note": "Shown facts come from stored records. Unverified fields stay unverified.",
            "tools_called": ["discover_restaurants"],
            "language": "en",
            "retriever": "baseline",
        }

    monkeypatch.setattr("food_copilot.agents.graph.recommend", leaky)
    model = ScriptedModel([{"content": json.dumps({"temporary": [], "proposed": []}), "tool_calls": []}])
    result = run_chat_graph(QUERY, model=model, call_tool=_tools, repository=service.repository)
    assert set(item["restaurant_id"] for item in result["results"]) == {"MY-OSM-node-priced", "MY-OSM-node-unknown"}
    assert "999" not in result["answer"]
    assert "passed every requested hard constraint" in result["answer"]


def test_graph_keeps_exclusion_counts_when_no_row_can_be_rechecked(monkeypatch):
    def empty(query, model, call_tool, repository=None, history=None):
        return {
            "answer": "No restaurants in the current dataset can be confirmed to satisfy all requested constraints.",
            "results": [],
            "exclusion_counts": {"price_unverified": 4},
            "needs_clarification": False,
            "sources_note": "Shown facts come from stored records. Unverified fields stay unverified.",
            "tools_called": ["discover_restaurants"],
            "language": "en",
            "retriever": "baseline",
        }

    monkeypatch.setattr("food_copilot.agents.graph.recommend", empty)
    model = ScriptedModel([{"content": json.dumps({"temporary": [], "proposed": []}), "tool_calls": []}])
    result = run_chat_graph(QUERY, model=model, call_tool=_tools, repository=_service().repository)
    assert result["results"] == []
    assert result["exclusion_counts"]["price_unverified"] == 4


def test_empty_result_explains_the_missing_price_evidence():
    service = _service()

    def only_unknown(name, arguments):
        return {"ok": True, "eligible_restaurant_ids": ["MY-OSM-node-unknown"], "needs_clarification": False}

    model = ScriptedModel(_replies({"temporary": [], "proposed": []}, "Try MY-OSM-node-unknown."))
    result = run_chat_graph(QUERY, model=model, call_tool=only_unknown, repository=service.repository)
    assert [item["restaurant_id"] for item in result["results"]] == ["MY-OSM-node-unknown"]
    assert result["results"][0]["price_max_myr"] is None


def test_one_identifier_does_not_save_the_turn():
    service = _service()
    memory = MemoryDouble()
    model = ScriptedModel(_replies({"temporary": [], "proposed": []}, "No restaurant was invented."))
    result = run_chat_graph(
        QUERY,
        user_id="user-1",
        model=model,
        call_tool=_tools,
        memory=memory,
        repository=service.repository,
    )
    assert result["memory_saved"] is False
    assert "Both user_id and session_id" in result["memory_note"]
    assert memory.messages == []


def test_graph_explains_a_tool_failure_without_inventing_a_restaurant():
    service = _service()

    def fail(name, arguments):
        raise RuntimeError("mcp down")

    model = ScriptedModel(_replies({"temporary": [], "proposed": []}, "Go to MY-OSM-node-999."))
    result = run_chat_graph(
        QUERY,
        model=model,
        call_tool=fail,
        memory=MemoryDouble(),
        repository=service.repository,
    )
    assert result["results"] == []
    assert "999" not in result["answer"]
    assert "tool failed" in result["answer"].lower()


def test_graph_model_error_is_not_a_recommendation():
    model = ScriptedModel([ModelCallError("The model request failed.")])
    with pytest.raises(ModelCallError, match="The model request failed"):
        run_chat_graph(QUERY, model=model, call_tool=_tools, repository=_service().repository)


def test_nodes_load_memory_before_the_model_and_save_after_validation():
    service = _service()
    order: list[str] = []

    class TrackingMemory(MemoryDouble):
        def preferences(self, user_id):
            order.append("preferences")
            return super().preferences(user_id)

        def recent_messages(self, session_id):
            order.append("recent")
            return super().recent_messages(session_id)

        def append_message(self, user_id, session_id, role, content):
            order.append(f"append:{role}")
            return super().append_message(user_id, session_id, role, content)

    class TrackingModel(ScriptedModel):
        def complete(self, messages, tools=None):
            order.append("model")
            return super().complete(messages, tools)

    memory = TrackingMemory()
    model = TrackingModel(_replies({"temporary": [], "proposed": []}, "No restaurant was invented."))
    result = run_chat_graph(
        QUERY,
        user_id="user-1",
        session_id="session-1",
        model=model,
        call_tool=_tools,
        memory=memory,
        repository=service.repository,
    )
    assert result["memory_saved"] is True
    assert order.index("recent") < order.index("model")
    assert order.index("model") < order.index("append:user")
    assert order[-2:] == ["append:user", "append:assistant"]


def test_malformed_preference_json_is_not_saved_and_fake_ids_are_removed():
    service = _service()
    memory = MemoryDouble()
    model = ScriptedModel([
        {"content": "remember this as a permanent diet", "tool_calls": []},
        {"content": "Visit MY-OSM-node-999.", "tool_calls": []},
    ])
    result = run_chat_graph(
        "Please remember that I prefer quiet restaurants in Old Klang Road under RM20.",
        user_id="user-1",
        session_id="session-1",
        model=model,
        call_tool=_tools,
        memory=memory,
        repository=service.repository,
    )
    assert result["saved_preferences"] == []
    assert memory.preferences == []
    assert "999" not in result["answer"]
    assert "MY-OSM-node-priced" in [item["restaurant_id"] for item in result["results"]]
    assert "MY-OSM-node-unknown" in [item["restaurant_id"] for item in result["results"]]


def test_unverified_halal_and_outside_region_stay_out_of_the_graph_result():
    service = DiscoveryService(records=[
        restaurant(
            "MY-OSM-node-priced",
            price_range_myr={"min": 8, "max": 12, "basis": "per_person", "status": "verified", "source_url": "https://example.local/menu"},
        ),
        restaurant(
            "MY-OSM-node-halal",
            price_range_myr={"min": 10, "max": 18, "basis": "per_person", "status": "verified", "source_url": "https://example.local/menu"},
            halal_status={"status": "verified", "source_url": "https://example.local/halal"},
        ),
        restaurant(
            "MY-OSM-node-other-city",
            regions=["kuala_lumpur"],
            price_range_myr={"min": 8, "max": 10, "basis": "per_person", "status": "verified", "source_url": "https://example.local/menu"},
            halal_status={"status": "verified", "source_url": "https://example.local/other"},
        ),
    ])

    def leaky(name, arguments):
        return {
            "ok": True,
            "eligible_restaurant_ids": [
                "MY-OSM-node-priced",
                "MY-OSM-node-halal",
                "MY-OSM-node-other-city",
            ],
            "needs_clarification": False,
        }

    model = ScriptedModel(_replies(
        {"temporary": [], "proposed": []},
        "Try MY-OSM-node-priced and MY-OSM-node-other-city.",
    ))
    result = run_chat_graph(
        "Find a verified halal restaurant in Old Klang Road under RM20.",
        model=model,
        call_tool=leaky,
        repository=service.repository,
    )
    assert [item["restaurant_id"] for item in result["results"]] == ["MY-OSM-node-halal"]
    assert "MY-OSM-node-priced" not in result["answer"]
    assert "MY-OSM-node-other-city" not in result["answer"]


def test_memory_write_failure_is_reported():
    service = _service()
    memory = MemoryDouble(fail_write=True)
    model = ScriptedModel(_replies({"temporary": [], "proposed": []}, "No restaurant was invented."))
    result = run_chat_graph(
        QUERY,
        user_id="user-1",
        session_id="session-1",
        model=model,
        call_tool=_tools,
        memory=memory,
        repository=service.repository,
    )
    assert result["memory_saved"] is False
    assert "not saved" in result["memory_note"]
    assert memory.messages == []
