"""Continuous restaurant dialogue. Fixtures only; canonical JSON is not modified."""

from food_copilot.agents.context import next_session_context
from food_copilot.agents.discovery_graph import run_discovery_graph
from food_copilot.data.discoveries import consider_web_result
from food_copilot.services.discovery import DiscoveryService
from tests.helpers import restaurant


def _records():
    return [
        restaurant("kfc-1", name="KFC", cuisine=["chicken"], latitude=3.09, longitude=101.67, address=None),
        restaurant("kfc-2", name="KFC", cuisine=["chicken"], latitude=3.11, longitude=101.68, address="Jalan Example"),
        restaurant("korean-1", name="Sae Ma Eul", cuisine=["korean"], latitude=3.10, longitude=101.66),
        restaurant("japanese-1", name="Example Sushi", cuisine=["japanese"], latitude=3.08, longitude=101.65),
        restaurant("other-1", name="How Ye Kee", cuisine=["chinese"], latitude=3.07, longitude=101.64),
    ]


def _run(query, context=None, history=None):
    return run_discovery_graph(
        query,
        history=history,
        context=context,
        repository=DiscoveryService(records=_records()).repository,
        search=lambda query: {"ok": True, "results": [{"title": "Airline FAQ", "url": "https://example.local/faq", "snippet": "baggage"}], "query": query},
    )


def test_kfc_sell_chicken_is_general_and_does_not_retrieve(monkeypatch):
    monkeypatch.setattr(
        "food_copilot.agents.model.OpenAIChatModel.complete",
        lambda self, messages, tools=None, timeout=8, max_tokens=180, **_extra: {"content": "KFC sells fried chicken.", "tool_calls": []},
    )
    monkeypatch.setattr("food_copilot.agents.model.openai_status", lambda: {"configured": True, "model": "gpt-4o-mini"})
    result = _run("kfc sell chicken?")
    assert result["intent"] == "general_qa"
    assert result["results"] == []
    assert "retrieve" not in result["trace"]["nodes"]


def test_where_can_i_find_kfc_uses_old_klang_road():
    result = _run("where can i find kfc?")
    assert result["needs_clarification"] is False
    assert result["constraints"]["region"] == "old_klang_road"
    assert result["constraints"]["name_contains"] == "kfc"
    assert [item["name"] for item in result["results"]] == ["KFC", "KFC"]
    assert "which area" not in result["answer"].lower()


def test_old_klang_road_kfc_returns_only_matching_branches():
    result = _run("search for old klang road kfc")
    assert result["constraints"]["region"] == "old_klang_road"
    assert result["constraints"]["name_contains"] == "kfc"
    assert [item["name"] for item in result["results"]] == ["KFC", "KFC"]
    assert result["match_count"] == 2
    assert "How Ye Kee" not in result["answer"]
    assert "no street address on file" in result["answer"].lower()
    assert "3.09" not in result["answer"]


def test_other_than_kfc_keeps_the_area_and_drops_the_brand():
    first = _run("search for old klang road kfc")
    saved = next_session_context({}, first)
    result = _run(
        "can u recommend other type of restaurant else than kfc?",
        context=saved,
        history=[{"role": "user", "content": "search for old klang road kfc"}],
    )
    assert result["constraints"]["region"] == "old_klang_road"
    assert "kfc" in (result["constraints"].get("exclude_brands") or [])
    assert not result["constraints"].get("name_contains")
    assert all("kfc" not in (item["name"] or "").lower() for item in result["results"])
    assert result["results"]


def test_korean_and_japanese_are_both_retrieved():
    result = _run(
        "recommend korean and japanese restaurant",
        context={"region": "old_klang_road"},
    )
    assert result["constraints"]["cuisines"] == ["korean", "japanese"]
    names = [item["name"] for item in result["results"]]
    assert "Sae Ma Eul" in names
    assert "Example Sushi" in names
    assert "korean:" in result["answer"].lower()
    assert "japanese:" in result["answer"].lower()


def test_any_japanese_keeps_the_area_and_does_not_invent_names():
    result = _run(
        "any japanese restaurant?",
        context={"region": "old_klang_road", "cuisines": ["korean"], "cuisine": "korean"},
        history=[{"role": "user", "content": "recommend korean and japanese restaurant in old klang road"}],
    )
    assert result["constraints"]["region"] == "old_klang_road"
    assert result["constraints"]["cuisines"] == ["japanese"]
    assert [item["name"] for item in result["results"]] == ["Example Sushi"]
    assert result["results"][0]["dataset_origin"] == "canonical"
    assert "Sae Ma Eul" not in result["answer"]


def test_any_other_excludes_the_restaurant_already_shown():
    saved = {
        "region": "old_klang_road",
        "cuisine": "japanese",
        "cuisines": ["japanese"],
        "shown_names": ["Example Sushi"],
        "shown_ids": ["japanese-1"],
    }
    result = _run("any other recommendations?", context=saved, history=[{"role": "user", "content": "any japanese restaurant in old klang road"}])
    assert result["intent"] == "restaurant_followup"
    assert [item["restaurant_id"] for item in result["results"]] == []
    assert "no stored japanese" in result["answer"].lower()


def test_a_new_session_does_not_inherit_the_previous_search():
    result = _run("any other recommendations?")
    assert result["needs_clarification"] is True
    assert result["results"] == []
    assert "old klang road" not in (result["constraints"].get("region") or "")


def test_ordinary_recommendations_skip_the_rewrite_unless_requested(monkeypatch):
    calls = []

    def complete(self, messages, tools=None, timeout=8, max_tokens=180, **_extra):
        calls.append(messages[0]["content"])
        return {"content": "Try Imaginary Grill.", "tool_calls": []}

    monkeypatch.setattr("food_copilot.agents.model.OpenAIChatModel.complete", complete)
    monkeypatch.setattr("food_copilot.agents.model.openai_status", lambda: {"configured": True, "model": "gpt-4o-mini"})
    monkeypatch.delenv("ENABLE_PHRASE_LLM", raising=False)
    monkeypatch.delenv("ENABLE_WEB_SEARCH", raising=False)
    repository = DiscoveryService(records=_records()).repository
    skipped = run_discovery_graph("any japanese restaurant in old klang road", repository=repository)
    assert skipped["trace"]["llm_called"] is False
    assert skipped["trace"]["stages"]["phrase_llm_ms"] == 0
    assert "Example Sushi" in skipped["answer"]
    assert calls == []
    monkeypatch.setenv("ENABLE_PHRASE_LLM", "true")
    rewritten = run_discovery_graph("any japanese restaurant in old klang road", repository=repository)
    assert calls
    assert "Imaginary Grill" not in rewritten["answer"]
    assert "Example Sushi" in rewritten["answer"]


def test_empty_japanese_result_is_explicit(monkeypatch):
    called = []

    def complete(self, messages, tools=None, timeout=8, max_tokens=180, **_extra):
        called.append(messages)
        raise TimeoutError("model down")

    monkeypatch.setattr("food_copilot.agents.model.OpenAIChatModel.complete", complete)
    result = run_discovery_graph(
        "any japanese restaurant in old klang road",
        repository=DiscoveryService(records=[restaurant("other", name="How Ye Kee", cuisine=["chinese"])]).repository,
        search=lambda query: {"ok": True, "results": [], "query": query},
    )
    assert result["results"] == []
    assert "no stored japanese" in result["answer"].lower()
    assert called == []


def test_web_page_without_the_area_is_not_a_verified_restaurant():
    decision = consider_web_result(
        {"title": "Sushi Memory", "url": "https://example.local/sushi", "snippet": "Japanese food on Jalan Ampang."},
        {"region": "old_klang_road", "cuisines": ["japanese"]},
        [],
    )
    assert decision["action"] == "skipped"
    assert decision["reason"] == "region_not_in_source"


def test_lookup_failure_does_not_invent_restaurants():
    class Broken:
        def list_restaurants(self):
            raise TimeoutError("database timeout")

    result = run_discovery_graph(
        "search for old klang road kfc",
        repository=Broken(),
        search=lambda query: {"ok": True, "results": [], "query": query},
    )
    assert result["results"] == []
    assert "lookup failed" in result["answer"].lower()
    assert "timeout" in result["answer"].lower()
