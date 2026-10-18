"""Western, mood, and follow-up constraints. Fixtures only."""

from food_copilot.agents.context import next_session_context
from food_copilot.agents.discovery_graph import run_discovery_graph
from food_copilot.retrieval.web_search import source_is_restaurant
from food_copilot.services.discovery import DiscoveryService
from tests.helpers import restaurant


def _records():
    return [
        restaurant("japanese-1", name="Example Sushi", cuisine=["japanese"], latitude=3.08, longitude=101.65),
        restaurant("japanese-2", name="Second Sushi", cuisine=["japanese"], latitude=3.081, longitude=101.651),
        restaurant("western-1", name="The Grill Room", cuisine=["western"], latitude=3.09, longitude=101.66),
        restaurant("korean-1", name="Korean Place", cuisine=["korean"], latitude=3.07, longitude=101.64),
        restaurant(
            "moody-1",
            name="Lamp Room",
            cuisine=["western"],
            latitude=3.095,
            longitude=101.662,
            description="A moody dining room with dim lighting.",
            ambience=["moody"],
        ),
    ]


def _run(query, context=None, history=None):
    return run_discovery_graph(
        query,
        history=history,
        context=context,
        repository=DiscoveryService(records=_records()).repository,
        search=lambda query: {
            "ok": True,
            "query": query,
            "results": [
                {"title": "Japanese keyboard input", "url": "https://example.local/keyboard", "snippet": "hiragana dictionary"},
                {"title": "Learn Korean language course", "url": "https://example.local/learn", "snippet": "vocabulary"},
            ],
        },
    )


def test_western_does_not_return_japanese_after_a_japanese_search():
    first = _run("what about Japanese?", context={"region": "old_klang_road"})
    saved = next_session_context({}, first)
    result = _run("any western restaurant?", context=saved, history=[{"role": "user", "content": "what about Japanese?"}])
    assert result["constraints"]["region"] == "old_klang_road"
    assert result["constraints"]["cuisines"] == ["western"]
    names = [item["name"] for item in result["results"]]
    assert "The Grill Room" in names
    assert "Example Sushi" not in names
    assert "Second Sushi" not in names
    assert "learn korean" not in result["answer"].lower()
    assert "keyboard" not in result["answer"].lower()


def test_moody_does_not_repeat_the_previous_cuisine():
    first = _run("what about Japanese?", context={"region": "old_klang_road"})
    saved = next_session_context({}, first)
    result = _run(
        "any moody restaurant recommendation?",
        context=saved,
        history=[{"role": "user", "content": "what about Japanese?"}],
    )
    assert result["constraints"]["region"] == "old_klang_road"
    assert not result["constraints"].get("cuisines")
    assert result["constraints"]["ambience"] == "moody"
    assert [item["name"] for item in result["results"]] == ["Lamp Room"]
    assert "Example Sushi" not in result["answer"]


def test_moody_without_evidence_lists_the_local_restaurant_as_unverified():
    result = run_discovery_graph(
        "any moody restaurant recommendation?",
        context={"region": "old_klang_road", "cuisines": ["japanese"], "cuisine": "japanese"},
        repository=DiscoveryService(records=[
            restaurant("japanese-1", name="Example Sushi", cuisine=["japanese"]),
        ]).repository,
        search=lambda query: {"ok": True, "results": [], "query": query},
    )
    assert [item["name"] for item in result["results"]] == ["Example Sushi"]
    assert "not been verified" in result["answer"].lower()
    assert "cuisine alone is not treated as mood" in result["answer"].lower()
    assert "matches the requested atmosphere" not in result["results"][0]["match_reason"]


def test_korean_follow_up_keeps_the_area():
    result = _run(
        "how bout korean restaurant?",
        context={"region": "old_klang_road", "cuisines": ["japanese"], "cuisine": "japanese"},
        history=[{"role": "user", "content": "what about Japanese?"}],
    )
    assert result["constraints"]["region"] == "old_klang_road"
    assert result["constraints"]["cuisines"] == ["korean"]
    assert [item["name"] for item in result["results"]] == ["Korean Place"]


def test_besides_korean_excludes_korean_and_any_other_skips_shown_ids():
    excluded = _run(
        "any other cuisine besides Korean?",
        context={"region": "old_klang_road", "cuisines": ["korean"], "cuisine": "korean", "shown_ids": ["korean-1"], "shown_names": ["Korean Place"]},
    )
    assert "korean" in excluded["constraints"]["exclude_cuisines"]
    assert all(item["restaurant_id"] != "korean-1" for item in excluded["results"])
    saved = {
        "region": "old_klang_road",
        "cuisines": ["western"],
        "cuisine": "western",
        "shown_ids": ["western-1"],
        "shown_names": ["The Grill Room"],
    }
    more = _run("any other?", context=saved, history=[{"role": "user", "content": "any western restaurant in old klang road"}])
    assert more["constraints"]["cuisines"] == ["western"]
    assert all(item["restaurant_id"] != "western-1" for item in more["results"])


def test_language_pages_and_keyboards_are_not_restaurant_evidence():
    assert source_is_restaurant({"title": "Japanese keyboard", "snippet": "hiragana dictionary", "url": "https://example.local/ime"}) is False
    assert source_is_restaurant({"title": "Learn Korean language course", "snippet": "vocabulary", "url": "https://example.local/learn"}) is False


def test_both_requested_cuisines_are_covered_when_records_exist():
    result = _run("recommend korean and japanese restaurant", context={"region": "old_klang_road"})
    names = [item["name"] for item in result["results"]]
    assert "Korean Place" in names
    assert "Example Sushi" in names
    assert "korean:" in result["answer"].lower()
    assert "japanese:" in result["answer"].lower()
    result = _run("any other?")
    assert result["needs_clarification"] is True
    assert result["results"] == []
