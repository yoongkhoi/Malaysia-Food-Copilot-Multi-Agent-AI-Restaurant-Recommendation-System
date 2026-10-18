"""Date atmosphere and review-backed recommendations. Fixtures only."""

from food_copilot.agents.discovery_graph import run_discovery_graph
from food_copilot.config.settings import feature_flags
from food_copilot.retrieval.constraints import parse_constraints
from food_copilot.retrieval.web_search import parse_bing_page
from food_copilot.reviews.recommend import recommend_from_reviews
from food_copilot.services.discovery import DiscoveryService
from tests.helpers import restaurant

_BING_BLOCK = """
<li class="b_algo"><h2><a href="https://example.local/place">Old Klang Road romantic dinner</a></h2>
<p class="b_caption"><p>A restaurant on Old Klang Road.</p></p></li>
"""


def _records():
    return [
        restaurant("plain-1", name="Plain Room", cuisine=["western"], latitude=3.09, longitude=101.66),
        restaurant("date-1", name="Lamp Room", cuisine=["western"], latitude=3.091, longitude=101.661, description="A romantic dinner room."),
        restaurant("cafe-1", name="Quiet Cafe", cuisine=["coffee_shop"], latitude=3.092, longitude=101.662),
        restaurant("unnamed-1", name=None, cuisine=["western"], latitude=3.093, longitude=101.663),
        restaurant("japanese-1", name="Example Sushi", cuisine=["japanese"], latitude=3.08, longitude=101.65),
    ]


def _run(query, context=None, search=None, records=None):
    def default_search(text):
        return {"ok": False, "error": "no_results", "results": [], "query": text}

    return run_discovery_graph(
        query,
        context=context,
        repository=DiscoveryService(records=records or _records()).repository,
        search=search or default_search,
    )


def test_a_date_request_in_old_klang_road_does_not_pretend_atmosphere_is_known():
    result = _run("I want a restaurant for a date", context={"region": "old_klang_road"})
    assert result["constraints"]["ambience"] == "date"
    assert result["constraints"]["region"] == "old_klang_road"
    assert result["atmosphere"] == "supported"
    assert [item["name"] for item in result["results"]] == ["Lamp Room"]
    assert "cuisine alone is not treated as mood" not in result["answer"].lower() or "atmosphere evidence" in result["answer"].lower()
    assert result["trace"]["llm_called"] is False


def test_romantic_dinner_keeps_the_area_and_cosy_cafe_keeps_both():
    romantic = _run("I want a romantic dinner", context={"region": "old_klang_road"})
    assert romantic["constraints"]["region"] == "old_klang_road"
    assert romantic["constraints"]["ambience"] == "date"
    cosy = _run("Any cosy café for a date?", context={"region": "old_klang_road", "cuisine": "japanese", "cuisines": ["japanese"]})
    assert cosy["constraints"]["region"] == "old_klang_road"
    assert cosy["constraints"]["cuisine"] == "cafe"
    assert cosy["constraints"]["ambience"] == "date"
    assert [item["name"] for item in cosy["results"]] == ["Quiet Cafe"]


def test_atmosphere_evidence_ranks_ahead_of_a_comparable_restaurant():
    result = _run("I want a restaurant for a date in old klang road")
    assert [item["name"] for item in result["results"]] == ["Lamp Room"]
    assert "Plain Room" not in result["answer"]


def test_cuisine_alone_does_not_prove_a_date_atmosphere():
    result = _run(
        "I want a restaurant for a date",
        context={"region": "old_klang_road"},
        records=[restaurant("japanese-1", name="Example Sushi", cuisine=["japanese"])],
    )
    assert result["atmosphere"] == "unverified"
    assert "Example Sushi" in result["answer"]
    assert "not been verified" in result["answer"].lower()
    assert "matches the requested atmosphere" not in result["results"][0]["match_reason"]


def test_web_page_parser_keeps_a_restaurant_result_and_names_empty_and_broken_pages():
    found = parse_bing_page(_BING_BLOCK, "romantic dinner restaurant Old Klang Road")
    assert found["ok"] is True
    assert found["results"][0]["title"] == "Old Klang Road romantic dinner"
    empty = parse_bing_page("<html><title>Search</title></html>", "romantic dinner")
    assert empty["error"] == "parse_failed"
    unrelated = parse_bing_page(
        '<li class="b_algo"><h2><a href="https://example.local/cal">Today Date Calculator</a></h2></li>',
        "date restaurant",
    )
    assert unrelated["error"] == "no_results"
    assert unrelated["parsed_blocks"] == 1


def test_disabled_web_search_still_returns_local_date_candidates(monkeypatch):
    monkeypatch.delenv("ENABLE_WEB_SEARCH", raising=False)
    result = run_discovery_graph(
        "I want a restaurant for a date in old klang road",
        repository=DiscoveryService(records=[restaurant("plain-1", name="Plain Room", cuisine=["western"])]).repository,
    )
    assert result["results"]
    assert "disabled" in result["answer"]
    assert "Plain Room" in result["answer"]


def test_outside_area_web_results_are_not_verified_canonical_cards():
    result = _run(
        "I want a restaurant for a date in old klang road",
        records=[restaurant("plain-1", name="Plain Room", cuisine=["western"])],
        search=lambda query: {
            "ok": True,
            "results": [{
                "title": "Penang Date Restaurant",
                "url": "https://example.local/penang",
                "snippet": "A restaurant in Penang.",
            }],
            "query": query,
        },
    )
    assert all(item["dataset_origin"] == "canonical" for item in result["results"])
    assert all(not str(item["restaurant_id"]).startswith("WEB-") for item in result["results"])
    assert "was verified as a canonical restaurant" in result["answer"]
    assert "Penang Date Restaurant" not in result["answer"]


def test_any_other_skips_shown_ids_and_a_new_session_does_not_inherit():
    first = _run("I want a restaurant for a date in old klang road")
    shown = [item["restaurant_id"] for item in first["results"]]
    more = _run(
        "any other recommendations?",
        context={"region": "old_klang_road", "ambience": "date", "shown_ids": shown, "shown_names": ["Lamp Room"]},
    )
    assert all(item["restaurant_id"] not in shown for item in more["results"])
    fresh = _run("any other recommendations?")
    assert fresh["needs_clarification"] is True
    assert fresh["results"] == []


def test_review_request_uses_only_confirmed_identity_and_keeps_a_complaint():
    canonical = [
        restaurant("ike", name="Iketeru", regions=["kuala_lumpur"]),
        restaurant("dark", name="Dining in the Dark KL", regions=["kuala_lumpur"], address="Jalan Example"),
        restaurant("plain", name="Plain Room", regions=["old_klang_road"]),
    ]
    docs = [
        {"review_id": "rv-good", "restaurant_id": "ike", "restaurant_name": "Iketeru", "match_status": "unique_name_in_area", "rating": 5, "review_text": "The cod was excellent.", "source": "google", "source_file": "pilot"},
        {"review_id": "rv-mixed", "restaurant_id": "ike", "restaurant_name": "Iketeru", "match_status": "unique_name_in_area", "rating": 2, "review_text": "The fish was salty and the wait was long.", "source": "google", "source_file": "pilot"},
        {"review_id": "rv-ambiguous", "restaurant_id": "plain", "restaurant_name": "Plain Room", "match_status": "ambiguous_branch", "rating": 5, "review_text": "Best ever.", "source": "google"},
        {"review_id": "rv-unmatched", "restaurant_id": None, "restaurant_name": "Somewhere", "match_status": "unmatched", "rating": 5, "review_text": "Lovely.", "source": "google"},
    ]
    found = recommend_from_reviews(docs, {"region": "kuala_lumpur"}, canonical)
    assert [item["name"] for item in found["restaurants"]] == ["Iketeru"]
    assert "salty" in found["answer"]
    assert "Best ever" not in found["answer"]
    assert "Somewhere" not in found["answer"]
    empty = recommend_from_reviews(
        [item for item in docs if item["match_status"] == "unmatched"],
        {"region": "old_klang_road"},
        canonical,
    )
    assert empty["ok"] is False
    assert "not applied" in empty["note"]
    ambiguous = recommend_from_reviews(
        [item for item in docs if item["match_status"] == "ambiguous_branch"],
        {"region": "old_klang_road"},
        canonical,
    )
    assert ambiguous["ok"] is False
    assert "one canonical branch" in ambiguous["note"]


def test_review_rag_stays_off_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_REVIEW_RAG", raising=False)
    assert feature_flags()["ENABLE_REVIEW_RAG"] is False
    result = _run("Korean BBQ around Old Klang Road", records=[restaurant("korean-1", name="Sae Ma Eul", cuisine=["korean"])])
    assert result.get("review_evidence") in (None, [])
    assert "pilot corpus" not in result["answer"].lower()


def test_the_live_graph_uses_confirmed_reviews_when_the_user_asks(monkeypatch):
    docs = [
        {"review_id": "rv-good", "restaurant_id": "ike", "restaurant_name": "Iketeru", "match_status": "unique_name_in_area", "rating": 5, "review_text": "The cod was excellent.", "source": "google", "source_file": "pilot"},
        {"review_id": "rv-mixed", "restaurant_id": "ike", "restaurant_name": "Iketeru", "match_status": "unique_name_in_area", "rating": 2, "review_text": "The fish was salty.", "source": "google", "source_file": "pilot"},
    ]
    monkeypatch.setattr("food_copilot.reviews.recommend.load_jsonl", lambda path: docs)
    monkeypatch.setattr("food_copilot.reviews.recommend._PILOT", type("Pilot", (), {"exists": lambda self: True})())
    result = _run(
        "I don't know what to eat, can you recommend based on review?",
        context={"region": "kuala_lumpur"},
        records=[restaurant("ike", name="Iketeru", regions=["kuala_lumpur"]), restaurant("unnamed-1", name=None, regions=["kuala_lumpur"])],
        search=lambda query: {"ok": False, "error": "disabled", "results": [], "query": query},
    )
    assert [item["name"] for item in result["results"]] == ["Iketeru"]
    assert "salty" in result["answer"]
    assert result["review_evidence"]
    assert result["review_evidence"][0]["opinion_not_verified_fact"] is True
    assert all(item.get("name") for item in result["results"])


def test_an_explicit_review_request_returns_evidence_fields():
    docs = [{
        "review_id": "rv-1",
        "restaurant_id": "ike",
        "restaurant_name": "Iketeru",
        "match_status": "unique_name_in_area",
        "rating": 4,
        "review_text": "The set lunch was the part I liked.",
        "source": "google",
        "source_file": "pilot",
    }]
    result = _run(
        "I don't know what to eat, can you recommend based on review?",
        context={"region": "kuala_lumpur"},
        records=[restaurant("ike", name="Iketeru", regions=["kuala_lumpur"])],
        search=lambda query: {"ok": False, "error": "disabled", "results": [], "query": query},
    )
    # The live loader is not used when the graph has no injected docs.
    # This checks the intent still reaches restaurant search and does not invent a dish.
    assert result["intent"] == "restaurant_search"
    assert parse_constraints("I don't know what to eat, can you recommend based on review?").cuisine is None
    found = recommend_from_reviews(docs, {"region": "kuala_lumpur"}, [restaurant("ike", name="Iketeru", regions=["kuala_lumpur"])])
    assert found["evidence"][0]["opinion_not_verified_fact"] is True
    assert "set lunch" in found["evidence"][0]["span"]
