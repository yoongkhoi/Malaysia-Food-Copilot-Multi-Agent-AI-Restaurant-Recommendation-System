import json

from food_copilot.agents.mcp_client import mcp_call
from food_copilot.agents.model import OpenAIChatModel
from food_copilot.agents.preference import explicit_confirmation, review_preferences
from food_copilot.agents.recommendation import recommend
from food_copilot.agents.runtime import answer_with_agents
from food_copilot.errors import FeatureDisabled, ModelCallError, ModelConfigError
from food_copilot.mcp.server import build_mcp_server
from food_copilot.services.discovery import DiscoveryService
from tests.helpers import restaurant

QUERY = "Find a restaurant in Old Klang Road under RM20."


class ScriptedModel:
    def __init__(self, replies):
        self.replies = list(replies)

    def complete(self, messages, tools=None):
        return self.replies.pop(0)


class MemoryDouble:
    def __init__(self):
        self.saved = []
        self.database_url = "configured"
        self.redis_url = "configured"

    def status(self):
        return {"postgres": True, "redis": True}

    def preferences(self, user_id):
        return [item for item in self.saved if item["user_id"] == user_id]

    def save_preference(self, user_id, key, value, confirmed=True):
        self.saved.append({"user_id": user_id, "key": key, "value": value, "confirmed": confirmed})
        return {"user_id": user_id, "key": key, "confirmed": confirmed}


def _service():
    return DiscoveryService(records=[
        restaurant(
            "MY-OSM-node-priced",
            price_range_myr={"min": 8, "max": 12, "basis": "per_person", "status": "verified", "source_url": "https://example.local/menu"},
        ),
        restaurant("MY-OSM-node-unknown"),
        restaurant(
            "MY-OSM-node-halal",
            price_range_myr={"min": 10, "max": 18, "basis": "per_person", "status": "verified", "source_url": "https://example.local/menu"},
            halal_status={"status": "verified", "source_url": "https://example.local/halal"},
        ),
    ])


def test_missing_openai_configuration(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("food_copilot.agents.model.load_local_env", lambda: None)
    try:
        OpenAIChatModel().complete([{"role": "user", "content": "hello"}])
        assert False
    except ModelConfigError as exc:
        assert str(exc) == "OPENAI_API_KEY is not set"
        assert "sk-" not in str(exc)


def test_model_failure_does_not_reveal_a_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret")

    class Boom:
        def __init__(self, **kwargs):
            pass

        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    raise RuntimeError("unauthorized sk-test-secret")

    import openai

    monkeypatch.setattr(openai, "OpenAI", Boom)
    try:
        OpenAIChatModel().complete([{"role": "user", "content": "hello"}])
        assert False
    except ModelCallError as exc:
        assert str(exc) == "The model request failed."
        assert "sk-test-secret" not in str(exc)


def test_today_request_is_not_stored():
    memory = MemoryDouble()
    model = ScriptedModel([{
        "content": json.dumps({"temporary": ["spicy today"], "proposed": [{"key": "diet", "value": "spicy"}]}),
        "tool_calls": [],
    }])
    result = review_preferences("I want spicy food today", model, memory=memory, user_id="user-1")
    assert result["temporary"] == ["spicy today"]
    assert result["saved_preferences"] == []
    assert memory.saved == []
    assert not explicit_confirmation("I want spicy food today")


def test_preference_is_saved_only_after_explicit_confirmation():
    memory = MemoryDouble()
    model = ScriptedModel([{
        "content": json.dumps({"temporary": [], "proposed": [{"key": "ambience", "value": "quiet"}]}),
        "tool_calls": [],
    }])
    result = review_preferences(
        "Please remember that I prefer quiet restaurants",
        model,
        memory=memory,
        user_id="user-1",
    )
    assert result["saved_preferences"] == [{"key": "ambience", "value": "quiet"}]
    assert memory.saved[0]["confirmed"] is True


def test_empty_tool_result_keeps_the_reported_exclusion_counts():
    service = _service()

    def empty(name, arguments):
        return {"ok": True, "eligible_restaurant_ids": [], "exclusion_counts": {"price_unverified": 2}, "needs_clarification": False}

    result = recommend(
        QUERY,
        ScriptedModel([{"content": "Nothing qualified.", "tool_calls": []}]),
        empty,
        repository=service.repository,
    )
    assert result["results"] == []
    assert result["exclusion_counts"]["price_unverified"] == 2


def test_tool_failure_does_not_invent_a_restaurant():
    service = _service()

    def fail(name, arguments):
        raise RuntimeError("mcp down")

    model = ScriptedModel([{"content": "Visit MY-OSM-node-999 tonight.", "tool_calls": []}])
    result = recommend(QUERY, model, fail, repository=service.repository)
    assert result["results"] == []
    assert "999" not in result["answer"]
    assert "tool failed" in result["answer"].lower()


def test_unverified_price_and_halal_stay_out_of_agent_results():
    service = _service()

    def leaky(name, arguments):
        return {
            "ok": True,
            "eligible_restaurant_ids": ["MY-OSM-node-priced", "MY-OSM-node-unknown", "MY-OSM-node-halal"],
            "needs_clarification": False,
            "exclusion_counts": {},
        }

    budget = recommend(
        QUERY,
        ScriptedModel([{"content": "Try MY-OSM-node-unknown.", "tool_calls": []}]),
        leaky,
        repository=service.repository,
    )
    assert [item["restaurant_id"] for item in budget["results"]] == ["MY-OSM-node-priced", "MY-OSM-node-unknown", "MY-OSM-node-halal"]

    halal = recommend(
        "Find a certified halal restaurant in Old Klang Road under RM20.",
        ScriptedModel([{"content": "MY-OSM-node-priced is fine.", "tool_calls": []}]),
        leaky,
        repository=service.repository,
    )
    assert [item["restaurant_id"] for item in halal["results"]] == ["MY-OSM-node-halal"]


def test_follow_up_tool_message_uses_the_provider_shape():
    seen = []

    class Capture(ScriptedModel):
        def complete(self, messages, tools=None):
            seen.append(messages)
            return super().complete(messages, tools)

    service = _service()
    model = Capture([
        {
            "content": "",
            "tool_calls": [{"id": "call-1", "name": "discover_restaurants", "arguments": {"query": QUERY}}],
        },
        {"content": "No extra restaurant.", "tool_calls": []},
    ])
    recommend(QUERY, model, lambda name, args: {"ok": True, "eligible_restaurant_ids": ["MY-OSM-node-priced"]}, repository=service.repository)
    assistant = next(item for item in seen[1] if item["role"] == "assistant")
    call = assistant["tool_calls"][0]
    assert call["type"] == "function"
    assert call["id"] == "call-1"
    assert call["function"]["name"] == "discover_restaurants"
    assert json.loads(call["function"]["arguments"]) == {"query": QUERY}


def test_recommendation_uses_the_mcp_tool_result():
    service = _service()
    server = build_mcp_server(service=service, repository=service.repository)
    model = ScriptedModel([
        {
            "content": "",
            "tool_calls": [{"id": "call-1", "name": "discover_restaurants", "arguments": {"query": QUERY}}],
        },
        {"content": "The only place I can confirm is outside the tool result: MY-OSM-node-999.", "tool_calls": []},
    ])
    result = recommend(QUERY, model, lambda name, args: mcp_call(name, args, server=server), repository=service.repository)
    assert result["tools_called"][0] == "discover_restaurants"
    assert "MY-OSM-node-999" not in result["answer"]
    assert "MY-OSM-node-999" not in [item["restaurant_id"] for item in result["results"]]


def test_agent_runtime_stays_off_without_the_flag(monkeypatch):
    monkeypatch.delenv("ENABLE_LLM_AGENT", raising=False)
    try:
        answer_with_agents(QUERY, model=ScriptedModel([]))
        assert False
    except FeatureDisabled:
        pass
