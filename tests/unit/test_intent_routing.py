from food_copilot.agents.context import next_session_context
from food_copilot.agents.discovery_graph import run_discovery_graph
from food_copilot.services.discovery import DiscoveryService
from tests.helpers import restaurant


def _records():
    return [
        restaurant("korean-1", name="Sae Ma Eul BBQ", cuisine=["korean"]),
        restaurant("korean-2", name="Other Grill", cuisine=["korean"]),
        restaurant("japanese-1", name="Example Sushi", cuisine=["japanese"]),
    ]


def _service():
    return DiscoveryService(records=_records())


def _patch_model(monkeypatch, answer="Food is anything people eat to get energy."):
    calls = []

    def complete(self, messages, tools=None, timeout=8, max_tokens=180, **_extra):
        calls.append({"messages": messages, "timeout": timeout, "max_tokens": max_tokens})
        system = messages[0]["content"]
        if "Classify the user message" in system:
            return {"content": "general_qa", "tool_calls": []}
        return {"content": answer, "tool_calls": []}

    monkeypatch.setattr("food_copilot.agents.model.openai_status", lambda: {"configured": True, "model": "gpt-4o-mini"})
    monkeypatch.setattr("food_copilot.agents.model.OpenAIChatModel.complete", complete)
    return calls


def test_what_is_food_calls_the_model_and_skips_restaurant_lookup(monkeypatch):
    calls = _patch_model(monkeypatch)
    searched = []
    result = run_discovery_graph("can i ask what is food", search=lambda query: searched.append(query))
    assert result["intent"] == "general_qa"
    assert result["needs_clarification"] is False
    assert result["results"] == []
    assert result["trace"]["llm_called"] is True
    assert result["model_name"] == "gpt-4o-mini"
    assert result["answer"] == "Food is anything people eat to get energy."
    assert "supported area" not in result["answer"].lower()
    assert "bm25" not in result["tools_called"]
    assert "web_search" not in result["tools_called"]
    assert "llm" in result["tools_called"]
    assert "retrieve" not in result["trace"]["nodes"]
    assert searched == []
    assert calls
    assert calls[0]["max_tokens"] == 400


def test_what_is_rag_does_not_retrieve(monkeypatch):
    _patch_model(monkeypatch, answer="RAG retrieves stored text and gives it to a model.")
    searched = []
    result = run_discovery_graph("What is RAG?", search=lambda query: searched.append(query))
    assert result["intent"] == "general_qa"
    assert result["trace"]["llm_called"] is True
    assert result["answer"].startswith("RAG retrieves")
    assert result["results"] == []
    assert searched == []
    assert "retrieve" not in result["trace"]["nodes"]


def test_a_failed_general_answer_is_not_replaced_with_a_canned_definition(monkeypatch):
    from food_copilot.agents.discovery_graph import _GENERAL_CACHE

    _GENERAL_CACHE.clear()
    def complete(self, messages, tools=None, timeout=8, max_tokens=180, **_extra):
        raise TimeoutError("slow")

    monkeypatch.setattr("food_copilot.agents.model.openai_status", lambda: {"configured": True, "model": "gpt-4o-mini"})
    monkeypatch.setattr("food_copilot.agents.model.OpenAIChatModel.complete", complete)
    result = run_discovery_graph("What is RAG?")
    assert result["trace"]["llm_called"] is False
    assert "TimeoutError" in result["model_note"]
    assert "not a model answer" in result["answer"]
    assert "supported area" not in result["answer"].lower()
    assert result["results"] == []


def test_korean_bbq_uses_the_restaurant_path():
    searched = []

    def search(query):
        searched.append(query)
        return {"ok": True, "results": [], "query": query}

    result = run_discovery_graph(
        "Recommend Korean BBQ around Old Klang Road",
        repository=_service().repository,
        search=search,
    )
    assert result["intent"] == "restaurant_search"
    assert result["needs_clarification"] is False
    assert result["constraints"]["region"] == "old_klang_road"
    assert result["constraints"]["cuisine"] == "korean"
    assert {item["name"] for item in result["results"]} == {"Sae Ma Eul BBQ", "Other Grill"}
    assert searched
    assert "retrieve" in result["trace"]["nodes"]
    assert "general" not in result["trace"]["nodes"]


def test_other_recommendations_keep_the_area_and_skip_shown_names():
    result = run_discovery_graph(
        "Any other recommendations?",
        repository=_service().repository,
        search=lambda query: {"ok": True, "results": [], "query": query},
        history=[{"role": "user", "content": "I want Korean BBQ around Old Klang Road."}],
        context={"region": "old_klang_road", "cuisine": "korean", "shown_names": ["Sae Ma Eul BBQ"]},
    )
    assert result["intent"] == "restaurant_followup"
    assert result["constraints"]["region"] == "old_klang_road"
    assert result["constraints"]["cuisine"] == "korean"
    assert [item["name"] for item in result["results"]] == ["Other Grill"]
    assert result["trace"]["stages"]["search_ms"] >= 0


def test_japanese_follow_up_keeps_old_klang_road():
    result = run_discovery_graph(
        "What about Japanese food?",
        repository=_service().repository,
        search=lambda query: {"ok": True, "results": [], "query": query},
        context={"region": "old_klang_road", "cuisine": "korean", "shown_names": ["Sae Ma Eul BBQ"]},
    )
    assert result["intent"] == "restaurant_followup"
    assert result["constraints"]["region"] == "old_klang_road"
    assert result["constraints"]["cuisine"] == "japanese"
    assert [item["name"] for item in result["results"]] == ["Example Sushi"]


def test_a_new_session_follow_up_does_not_inherit_another_search():
    searched = []
    result = run_discovery_graph("Any other recommendations?", search=lambda query: searched.append(query))
    assert result["needs_clarification"] is True
    assert result["intent"] == "clarify"
    assert result["results"] == []
    assert searched == []
    assert "does not name a supported area" not in result["answer"].lower()
    assert "kind of food" in result["answer"].lower()
    assert "retrieve" not in result["trace"]["nodes"]


def test_an_ambiguous_message_uses_the_model_router(monkeypatch):
    calls = _patch_model(monkeypatch, answer="Here is a direct answer.")
    result = run_discovery_graph("hmm ok", search=lambda query: (_ for _ in ()).throw(AssertionError("searched")))
    assert result["intent"] == "general_qa"
    assert result["trace"]["llm_called"] is True
    assert "intent_router" in result["tools_called"]
    assert "llm" in result["tools_called"]
    assert len(calls) == 2


def test_a_restaurant_request_without_an_area_uses_old_klang_road():
    from food_copilot.agents.context import next_session_context

    plain = run_discovery_graph(
        "recommend me a restaurant",
        repository=_service().repository,
        search=lambda query: {"ok": True, "results": [], "query": query},
    )
    korean = run_discovery_graph(
        "tell me a korean restaurant",
        repository=_service().repository,
        search=lambda query: {"ok": True, "results": [], "query": query},
    )
    assert plain["needs_clarification"] is False
    assert plain["constraints"]["region"] == "old_klang_road"
    assert "which area" not in plain["answer"].lower()
    assert korean["needs_clarification"] is False
    assert korean["constraints"]["cuisine"] == "korean"
    assert korean["constraints"]["region"] == "old_klang_road"
    saved = next_session_context({}, korean)
    assert saved["cuisine"] == "korean"
    assert saved["region"] == "old_klang_road"


def test_malay_and_bbq_follow_the_latest_request():
    malay = run_discovery_graph(
        "hello, bolehkah kamu recommend satu restaurant yang sesuai?",
        repository=_service().repository,
        search=lambda query: {"ok": True, "results": [], "query": query},
    )
    assert malay["needs_clarification"] is False
    assert malay["constraints"]["region"] == "old_klang_road"
    assert "kawasan mana" not in malay["answer"].lower()
    jepun = run_discovery_graph(
        "ada restaurant yang jepun punya tak?",
        repository=_service().repository,
        search=lambda query: {"ok": True, "results": [], "query": query},
    )
    assert jepun["constraints"]["region"] == "old_klang_road"
    assert jepun["constraints"]["cuisine"] == "japanese"
    bbq = run_discovery_graph(
        "bbq restaurant",
        repository=_service().repository,
        search=lambda query: {"ok": True, "results": [], "query": query},
        context={"region": None, "cuisine": "japanese"},
    )
    assert bbq["constraints"]["region"] == "old_klang_road"
    assert bbq["constraints"]["cuisine"] == "bbq"
    assert "japanese" not in bbq["answer"].lower()
    assert "bbq" in bbq["answer"].lower()


def test_repeat_general_question_reuses_the_exact_answer(monkeypatch):
    from food_copilot.agents.discovery_graph import _GENERAL_CACHE

    _GENERAL_CACHE.clear()
    calls = _patch_model(monkeypatch, answer="Plants make sugar from light.")
    first = run_discovery_graph("What is photosynthesis?")
    second = run_discovery_graph("what is   photosynthesis?")
    assert first["answer"] == "Plants make sugar from light."
    assert second["answer"] == first["answer"]
    assert second["trace"]["llm_called"] is False
    assert "answer_cache" in second["tools_called"]
    assert "not called again" in second["model_note"]
    assert len(calls) == 1
    assert "retrieve" not in second["trace"]["nodes"]
    previous = {"region": "old_klang_road", "cuisine": "korean", "shown_names": ["Sae Ma Eul BBQ"]}
    assert next_session_context(previous, {"intent": "general_qa", "context_update": "keep", "constraints": {}, "results": []}) is None
    updated = next_session_context(
        previous,
        {
            "context_update": "accumulate",
            "constraints": {"region": "old_klang_road", "cuisine": "korean"},
            "results": [{"name": "Other Grill"}],
        },
    )
    assert updated["shown_names"] == ["Sae Ma Eul BBQ", "Other Grill"]
    assert updated["cuisine"] == "korean"


def test_how_many_kfc_returns_only_kfc_branches_and_the_count():
    records = [
        restaurant("kfc-1", name="KFC", cuisine=["chicken"], latitude=3.09, longitude=101.67),
        restaurant("kfc-2", name="KFC", cuisine=["chicken"], latitude=3.10, longitude=101.68, address="Jalan Example"),
        restaurant("other", name="How Ye Kee", cuisine=["chinese"], latitude=3.08, longitude=101.66),
    ]
    result = run_discovery_graph(
        "how many kfc are there in old klang road",
        repository=DiscoveryService(records=records).repository,
        search=lambda query: {"ok": True, "results": [], "query": query},
    )
    assert [item["name"] for item in result["results"]] == ["KFC", "KFC"]
    assert result["constraints"]["name_contains"] == "kfc"
    assert "2 KFC in Old Klang Road." in result["answer"]
    assert "How Ye Kee" not in result["answer"]
    assert "MY-OSM" not in result["answer"]
    assert result["trace"]["llm_called"] is False


def test_korean_request_replaces_a_saved_kfc_search():
    records = [
        restaurant("kfc-1", name="KFC", cuisine=["chicken"], latitude=3.09, longitude=101.67),
        restaurant("korean-1", name="Sae Ma Eul BBQ", cuisine=["korean"], latitude=3.10, longitude=101.68),
    ]
    result = run_discovery_graph(
        "any recommendation for korean food?",
        history=[{"role": "user", "content": "how many kfc are there in old klang road"}],
        context={
            "region": "old_klang_road",
            "name_contains": "kfc",
            "shown_names": ["KFC"],
            "shown_ids": ["kfc-1"],
        },
        repository=DiscoveryService(records=records).repository,
        search=lambda query: {"ok": True, "results": [], "query": query},
    )
    assert result["constraints"]["cuisine"] == "korean"
    assert not result["constraints"].get("name_contains")
    assert [item["name"] for item in result["results"]] == ["Sae Ma Eul BBQ"]
    assert "kfc" not in result["answer"].lower()
    saved = next_session_context(
        {"region": "old_klang_road", "name_contains": "kfc", "shown_names": ["KFC"]},
        result,
    )
    assert saved["cuisine"] == "korean"
    assert not saved.get("name_contains")


def test_more_recommendations_keep_kfc_and_skip_the_shown_branch():
    records = [
        restaurant("kfc-1", name="KFC", cuisine=["chicken"], latitude=3.09, longitude=101.67),
        restaurant("kfc-2", name="KFC", cuisine=["chicken"], latitude=3.10, longitude=101.68),
        restaurant("other", name="How Ye Kee", cuisine=["chinese"], latitude=3.08, longitude=101.66),
    ]
    result = run_discovery_graph(
        "还有没有其他的推荐",
        history=[{"role": "user", "content": "how many kfc are there in old klang road"}],
        context={
            "region": "old_klang_road",
            "name_contains": "kfc",
            "shown_names": ["KFC"],
            "shown_ids": ["kfc-1"],
        },
        repository=DiscoveryService(records=records).repository,
        search=lambda query: {"ok": True, "results": [], "query": query},
    )
    assert [item["restaurant_id"] for item in result["results"]] == ["kfc-2"]
    assert "How Ye Kee" not in result["answer"]
