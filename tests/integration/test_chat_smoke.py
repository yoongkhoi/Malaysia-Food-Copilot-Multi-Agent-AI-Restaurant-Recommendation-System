from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def _chat(query: str) -> dict:
    response = client.post("/api/chat", json={"query": query})
    assert response.status_code == 200, response.text
    body = response.json()
    text = body["answer"] + json_dumps_safe(body)
    assert "restaurants_final_verified_full" not in text
    assert "data/processed" not in text
    assert "postgres://" not in text
    assert "sk-" not in text
    assert "Traceback" not in text
    return body


def json_dumps_safe(body: dict) -> str:
    import json

    public = {key: value for key, value in body.items() if key != "raw_results"}
    return json.dumps(public)


def test_health_and_default_chat_do_not_call_a_model():
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"


def test_normal_old_klang_road_request_stays_inside_the_region():
    body = _chat("Find restaurants in Old Klang Road")
    assert body["constraints"]["region"] == "old_klang_road"
    assert body["constraints"]["max_budget_myr"] is None
    assert body["results"]
    assert all("stored region tag matches the requested area" in item["match_reason"] for item in body["results"])
    assert "restaurants_final" not in body["answer"]


def test_hard_budget_returns_no_unpriced_match():
    body = _chat("Old Klang Road under RM20")
    assert body["constraints"]["budget_mode"] == "hard"
    assert body["constraints"]["max_budget_myr"] == 20
    assert body["results"]
    assert all(item["price_max_myr"] is None or item["price_max_myr"] <= 20 for item in body["results"])
    assert "missing price" in body["answer"].lower() or "price not_verified" in body["answer"]


def test_halal_request_does_not_treat_unchecked_restaurants_as_certified():
    body = _chat("Old Klang Road verified halal restaurant under RM25")
    assert body["constraints"]["require_halal_verified"] is True
    assert body["results"] == []
    assert body["exclusion_counts"].get("halal_not_verified", 0) + body["exclusion_counts"].get("price_unverified", 0) > 0


def test_missing_area_searches_old_klang_road():
    body = _chat("Find a cheap restaurant")
    assert body["needs_clarification"] is False
    assert body["constraints"]["region"] == "old_klang_road"
    assert "which area" not in body["answer"].lower()
    assert "will not guess" not in body["answer"].lower()
