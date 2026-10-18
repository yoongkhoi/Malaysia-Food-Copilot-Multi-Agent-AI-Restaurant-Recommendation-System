from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["pilot"] == "Old Klang Road"
    assert response.json()["expansion"] == "Kuala Lumpur"


def test_missing_restaurant_is_not_invented():
    response = client.get("/api/restaurants/missing-id")
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "not_found"
    evidence = client.get("/api/restaurants/missing-id/evidence")
    assert evidence.status_code == 404


def test_chat_reuses_discovery_and_does_not_claim_a_model(monkeypatch):
    monkeypatch.delenv("ENABLE_LLM_AGENT", raising=False)
    monkeypatch.delenv("ENABLE_LANGGRAPH", raising=False)
    monkeypatch.delenv("ENABLE_WEB_SEARCH", raising=False)
    body = {"query": "Find a family-friendly restaurant in Old Klang Road under RM20."}
    chat = client.post("/api/chat", json=body)
    discover = client.post("/api/discover", json=body)
    assert chat.status_code == 200
    assert discover.status_code == 200
    assert chat.json()["results"] == discover.json()["results"]
    assert chat.json()["exclusion_counts"] == discover.json()["exclusion_counts"]
    assert chat.json()["retriever"] == "baseline"
    assert chat.json()["memory_saved"] is False
    assert chat.json()["agent_mode"] == "deterministic"
    assert "llm" not in " ".join(chat.json()["tools_called"]).lower()


def test_langgraph_route_without_a_key_still_retrieves(monkeypatch):
    monkeypatch.setenv("ENABLE_LANGGRAPH", "true")
    monkeypatch.delenv("ENABLE_LLM_AGENT", raising=False)
    monkeypatch.delenv("ENABLE_WEB_SEARCH", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("food_copilot.agents.model.load_local_env", lambda: None)
    response = client.post("/api/chat", json={"query": "Old Klang Road under RM20"})
    assert response.status_code == 200
    body = response.json()
    assert body["agent_mode"] == "langgraph"
    assert body["results"]
    assert "web_search" in body["tools_called"]
    assert "sk-" not in response.text


def test_langgraph_route_returns_the_graph_payload_without_the_key(monkeypatch):
    monkeypatch.setenv("ENABLE_LANGGRAPH", "true")
    monkeypatch.setenv("ENABLE_LLM_AGENT", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret")

    def fake_run(query, user_id=None, session_id=None, **kwargs):
        return {
            "answer": "No restaurants in the current dataset can be confirmed.",
            "constraints": {"region": "old_klang_road", "max_budget_myr": 20},
            "results": [],
            "exclusion_counts": {"price_unverified": 1},
            "needs_clarification": False,
            "sources_note": "Shown facts come from stored records. Unverified fields stay unverified.",
            "tools_called": ["discover_restaurants"],
            "language": "en",
            "retriever": "baseline",
            "memory_saved": False,
            "memory_note": "",
            "proposed_preferences": [],
            "saved_preferences": [],
            "temporary_preferences": [],
            "agent_mode": "langgraph",
        }

    monkeypatch.setattr("food_copilot.agents.graph.run_chat_graph", fake_run)
    response = client.post("/api/chat", json={"query": "Old Klang Road under RM20", "user_id": "user-1", "session_id": "session-1"})
    assert response.status_code == 200
    body = response.json()
    assert body["agent_mode"] == "langgraph"
    assert body["results"] == []
    assert "sk-test-secret" not in response.text


def test_agent_flag_without_a_key_is_a_config_error(monkeypatch):
    monkeypatch.setenv("ENABLE_LLM_AGENT", "true")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("food_copilot.agents.model.load_local_env", lambda: None)
    response = client.post("/api/chat", json={"query": "Old Klang Road under RM20"})
    assert response.status_code == 503
    assert response.json()["detail"] == "OPENAI_API_KEY is not set"
    assert "sk-" not in response.text


def test_accumulated_follow_up_ids_do_not_repeat_and_a_new_session_does_not_inherit(monkeypatch):
    monkeypatch.setenv("ENABLE_LANGGRAPH", "true")
    monkeypatch.setenv("ENABLE_BM25", "true")
    monkeypatch.delenv("ENABLE_LLM_AGENT", raising=False)
    monkeypatch.delenv("ENABLE_WEB_SEARCH", raising=False)
    monkeypatch.delenv("ALLOW_UNAUTHENTICATED_MEMORY", raising=False)
    monkeypatch.setattr("food_copilot.agents.model.load_local_env", lambda: None)
    first = client.post("/api/chat", json={
        "query": "Korean BBQ around Old Klang Road",
        "user_id": "user-follow",
        "session_id": "session-follow",
    })
    assert first.status_code == 200
    first_body = first.json()
    first_ids = [item["restaurant_id"] for item in first_body["results"]]
    assert first_ids
    assert first_body["constraints"]["region"] == "old_klang_road"
    context = {
        "region": "old_klang_road",
        "cuisine": "korean",
        "cuisines": ["korean"],
        "shown_ids": first_ids,
        "shown_names": [item["name"] for item in first_body["results"] if item.get("name")],
    }
    second = client.post("/api/chat", json={
        "query": "any other recommendations?",
        "user_id": "user-follow",
        "session_id": "session-follow",
        "context": context,
    })
    assert second.status_code == 200
    second_ids = [item["restaurant_id"] for item in second.json()["results"]]
    assert set(second_ids).isdisjoint(first_ids)
    third = client.post("/api/chat", json={
        "query": "any other recommendations?",
        "user_id": "user-follow",
        "session_id": "session-follow",
        "context": {**context, "shown_ids": first_ids + second_ids},
    })
    assert third.status_code == 200
    third_ids = [item["restaurant_id"] for item in third.json()["results"]]
    assert set(third_ids).isdisjoint(set(first_ids + second_ids))
    fresh = client.post("/api/chat", json={
        "query": "any other recommendations?",
        "user_id": "user-new",
        "session_id": "session-new",
    })
    assert fresh.status_code == 200
    assert fresh.json()["results"] == []
    assert fresh.json()["needs_clarification"] is True


def _graph(monkeypatch):
    monkeypatch.setenv("ENABLE_LANGGRAPH", "true")
    monkeypatch.setenv("ENABLE_BM25", "true")
    monkeypatch.delenv("ENABLE_LLM_AGENT", raising=False)
    monkeypatch.delenv("ENABLE_WEB_SEARCH", raising=False)
    monkeypatch.delenv("ALLOW_UNAUTHENTICATED_MEMORY", raising=False)
    monkeypatch.setattr("food_copilot.agents.model.load_local_env", lambda: None)


def test_cuisine_change_keeps_the_area_and_area_change_keeps_cuisine(monkeypatch):
    _graph(monkeypatch)
    korean = client.post("/api/chat", json={"query": "Korean BBQ around Old Klang Road"}).json()
    japanese = client.post("/api/chat", json={
        "query": "What about Japanese food?",
        "context": {"region": korean["constraints"]["region"], "cuisine": "korean"},
    }).json()
    assert japanese["constraints"]["region"] == "old_klang_road"
    assert japanese["constraints"]["cuisine"] == "japanese"
    moved = client.post("/api/chat", json={
        "query": "any japanese restaurant in kuala lumpur?",
        "context": {"region": "old_klang_road", "cuisine": "japanese", "cuisines": ["japanese"]},
    }).json()
    assert moved["constraints"]["region"] == "kuala_lumpur"
    assert moved["constraints"]["cuisine"] == "japanese"


def test_multiple_cuisines_and_a_fresh_session_do_not_share_state(monkeypatch):
    _graph(monkeypatch)
    both = client.post("/api/chat", json={
        "query": "recommend korean and japanese restaurants in old klang road",
    }).json()
    assert both["constraints"]["cuisines"] == ["korean", "japanese"]
    fresh = client.post("/api/chat", json={
        "query": "any other recommendations?",
        "session_id": "session-empty",
        "user_id": "user-empty",
    }).json()
    assert fresh["results"] == []
    assert fresh["needs_clarification"] is True
    assert fresh["constraints"].get("region") in {None, ""}


def test_restaurant_search_stays_usable_when_persistence_fails(monkeypatch):
    _graph(monkeypatch)
    monkeypatch.setenv("ALLOW_UNAUTHENTICATED_MEMORY", "true")

    class Store:
        def status(self):
            return {"postgres": True, "redis": True}

        def read_session(self, session_id):
            return {"owner": None, "messages": [], "context": {}}

        def stage_messages(self, *args, **kwargs):
            raise TimeoutError("slow")

    monkeypatch.setattr("food_copilot.api.routes.MemoryStore", Store)
    response = client.post("/api/chat", json={
        "query": "Korean BBQ around Old Klang Road",
        "user_id": "user-down",
        "session_id": "session-down",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["results"]
    assert body["memory_saved"] is False
    assert "not saved" in body["memory_note"]
    assert "secret" not in response.text
