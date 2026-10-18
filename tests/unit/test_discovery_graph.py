import json

from food_copilot.agents.discovery_graph import run_discovery_graph
from food_copilot.data.discoveries import consider_web_result
from food_copilot.services.discovery import DiscoveryService
from tests.helpers import restaurant


def test_missing_area_uses_old_klang_road():
    calls = []

    def search(query):
        calls.append(query)
        return {"ok": True, "results": [], "error": None}

    result = run_discovery_graph(
        "cheap food",
        repository=DiscoveryService(records=[restaurant("known", name="Known Rice")]).repository,
        search=search,
    )
    assert result["needs_clarification"] is False
    assert result["constraints"]["region"] == "old_klang_road"
    assert "will not guess" not in result["answer"].lower()
    assert "which area" not in result["answer"].lower()
    assert calls


def test_search_failure_is_reported_and_local_rows_remain():
    service = DiscoveryService(records=[restaurant("known", name="Known Rice")])

    def search(query):
        return {"ok": False, "error": "TimeoutError", "results": [], "query": query}

    result = run_discovery_graph(
        "Find rice in Old Klang Road",
        repository=service.repository,
        search=search,
    )
    assert result["agent_mode"] == "langgraph"
    assert [item["restaurant_id"] for item in result["results"]] == ["known"]
    assert "Web search failed (TimeoutError)" in result["answer"]
    assert "web_search" in result["tools_called"]


def test_a_specific_web_place_is_stored_once_and_a_listicle_is_not(monkeypatch, tmp_path):
    monkeypatch.setenv("DISCOVERED_RESTAURANTS_PATH", str(tmp_path / "discovered.json"))
    monkeypatch.setenv("MERGE_CANDIDATES_PATH", str(tmp_path / "queue.json"))
    constraints = {"region": "old_klang_road", "cuisine": "korean"}
    skipped = consider_web_result(
        {"title": "Best Korean BBQ in Kuala Lumpur", "url": "https://example.local/list", "snippet": "Old Klang Road"},
        constraints,
        [],
    )
    inserted = consider_web_result(
        {
            "title": "Hanwoo Table",
            "url": "https://example.local/hanwoo",
            "snippet": "Korean barbecue on Jalan Klang Lama.",
        },
        constraints,
        [],
    )
    again = consider_web_result(
        {
            "title": "Hanwoo Table",
            "url": "https://example.local/hanwoo",
            "snippet": "Korean barbecue on Jalan Klang Lama.",
        },
        constraints,
        [],
    )
    rows = json.loads((tmp_path / "discovered.json").read_text(encoding="utf-8"))
    assert skipped["action"] == "skipped"
    assert inserted["action"] == "inserted"
    assert again["action"] == "already_stored"
    assert len(rows) == 1
    assert rows[0]["address"] is None
    assert rows[0]["latitude"] is None
    assert rows[0]["price_range_myr"]["status"] == "unknown"
    assert rows[0]["halal_status"]["status"] == "unknown"
    assert rows[0]["sources"][0]["source_url"] == "https://example.local/hanwoo"
