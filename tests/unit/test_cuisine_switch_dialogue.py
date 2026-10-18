"""One session switches cuisine. Fixtures only; canonical JSON is not modified."""

from food_copilot.agents.context import next_session_context
from food_copilot.agents.discovery_graph import run_discovery_graph
from food_copilot.retrieval.web_search import source_is_restaurant
from food_copilot.services.discovery import DiscoveryService
from tests.helpers import restaurant


def _records():
    rows = [
        restaurant(f"korean-{index}", name=f"Korean Place {index}", cuisine=["korean"], latitude=3.09 + index / 1000, longitude=101.67)
        for index in range(9)
    ]
    rows.append(restaurant("japanese-1", name="Example Sushi", cuisine=["japanese"], latitude=3.08, longitude=101.65))
    rows.append(restaurant("japanese-2", name="Second Sushi", cuisine=["japanese"], latitude=3.081, longitude=101.651))
    rows.append(restaurant("chinese-1", name="How Ye Kee", cuisine=["chinese"], latitude=3.07, longitude=101.64))
    return rows


def _search(query):
    return {
        "ok": True,
        "query": query,
        "results": [
            {"title": "Learn Korean language course", "url": "https://example.local/learn", "snippet": "vocabulary lessons"},
            {"title": "Hanwoo restaurant", "url": "https://example.local/hanwoo", "snippet": "barbecue restaurant"},
        ],
    }


def _run(query, context=None, history=None):
    return run_discovery_graph(
        query,
        history=history,
        context=context,
        repository=DiscoveryService(records=_records()).repository,
        search=_search,
    )


def _saved(previous, result):
    return next_session_context(previous, result) or {}


def test_cuisine_switch_dialogue_keeps_area_and_changes_the_food():
    history = []
    saved = {}

    first = _run("I want Korean BBQ around Old Klang Road.")
    assert first["constraints"]["region"] == "old_klang_road"
    assert first["constraints"]["cuisines"] == ["korean"]
    first_ids = [item["restaurant_id"] for item in first["results"]]
    assert first_ids
    assert all(item.startswith("korean-") for item in first_ids)
    assert "learn korean" not in first["answer"].lower()
    history.append({"role": "user", "content": "I want Korean BBQ around Old Klang Road."})
    saved = _saved(saved, first)

    second = _run("how bout other", context=saved, history=history)
    assert second["constraints"]["region"] == "old_klang_road"
    assert "korean" in (second["constraints"].get("cuisines") or [])
    second_ids = [item["restaurant_id"] for item in second["results"]]
    assert second_ids
    assert not set(second_ids) & set(first_ids)
    assert all(item.startswith("korean-") for item in second_ids)
    history.append({"role": "user", "content": "how bout other"})
    saved = _saved(saved, second)

    third = _run("any other cuisine", context=saved, history=history)
    assert third["constraints"]["region"] == "old_klang_road"
    assert "korean" in (third["constraints"].get("exclude_cuisines") or [])
    assert "korean" not in (third["constraints"].get("cuisines") or [])
    third_ids = [item["restaurant_id"] for item in third["results"]]
    assert third_ids
    assert all(not item.startswith("korean-") for item in third_ids)
    assert "korean" not in third["answer"].lower() or "outside korean" in third["answer"].lower()
    history.append({"role": "user", "content": "any other cuisine"})
    saved = _saved(saved, third)

    fourth = _run("any other cuisine else than korean?", context=saved, history=history)
    assert fourth["constraints"]["region"] == "old_klang_road"
    assert "korean" in (fourth["constraints"].get("exclude_cuisines") or [])
    assert all(not item["restaurant_id"].startswith("korean-") for item in fourth["results"])
    assert not (set(item["restaurant_id"] for item in fourth["results"]) & set(third_ids))
    assert all("korean" not in (item.get("cuisine_label") or "") for item in fourth["results"])
    history.append({"role": "user", "content": "any other cuisine else than korean?"})
    saved = _saved(saved, fourth)

    shown = set(first_ids + second_ids + third_ids + [item["restaurant_id"] for item in fourth["results"]])
    fifth = _run("what about Japanese?", context=saved, history=history)
    assert fifth["constraints"]["region"] == "old_klang_road"
    assert fifth["constraints"]["cuisines"] == ["japanese"]
    fifth_ids = [item["restaurant_id"] for item in fifth["results"]]
    assert not (set(fifth_ids) & shown)
    assert set(fifth_ids) <= {"japanese-1", "japanese-2"}
    history.append({"role": "user", "content": "what about Japanese?"})
    saved = _saved(saved, fifth)

    sixth = _run("any other recommendations?", context=saved, history=history)
    assert sixth["constraints"]["region"] == "old_klang_road"
    assert "japanese" in (sixth["constraints"].get("cuisines") or [sixth["constraints"].get("cuisine")])
    assert all(item["restaurant_id"] != "japanese-1" for item in sixth["results"])
    assert all(not item["restaurant_id"].startswith("korean-") for item in sixth["results"])


def test_a_new_session_does_not_keep_the_cuisine_switch():
    result = _run("any other recommendations?")
    assert result["needs_clarification"] is True
    assert result["results"] == []


def test_language_pages_are_not_restaurant_sources():
    assert source_is_restaurant({"title": "Learn Korean language course", "snippet": "vocabulary", "url": "https://example.local/learn"}) is False
    assert source_is_restaurant({"title": "Hanwoo restaurant", "snippet": "barbecue restaurant", "url": "https://example.local/hanwoo"}) is True
