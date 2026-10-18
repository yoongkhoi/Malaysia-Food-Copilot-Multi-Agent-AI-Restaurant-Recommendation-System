from food_copilot.agents.orchestrator import (
    build_optional_graph,
    get_restaurant_details,
    handle_message,
    run_llm_agent,
)
from food_copilot.errors import FeatureDisabled, ToolError
from food_copilot.retrieval.rankers import build_ranker, reciprocal_rank_fusion
from food_copilot.services.discovery import DiscoveryService
from tests.helpers import restaurant


class _InjectingRanker:
    name = "evil"

    def rank(self, records, query_text):
        extra = restaurant(
            "injected",
            price_range_myr={"max": 80, "status": "verified", "source_url": "https://example.local/pricey"},
        )
        return records + [extra]


def test_second_validation_drops_a_ranked_ineligible_record():
    service = DiscoveryService(
        records=[restaurant("ok", price_range_myr={"max": 12, "status": "verified", "source_url": "https://example.local/menu"})],
        ranker=_InjectingRanker(),
    )
    outcome = handle_message("Old Klang Road under RM20", service)
    assert [item["restaurant_id"] for item in outcome["results"]] == ["ok"]
    assert "injected" not in outcome["answer"]


def test_unknown_id_and_blank_id_are_controlled():
    repository = DiscoveryService(records=[restaurant("known")]).repository
    missing = get_restaurant_details("missing-id", repository=repository)
    assert missing["ok"] is False
    assert missing["error"] == "not_found"
    try:
        get_restaurant_details("  ", repository=repository)
        raised = False
    except ToolError:
        raised = True
    assert raised


def test_details_do_not_change_stored_status():
    row = restaurant("known")
    repository = DiscoveryService(records=[row]).repository
    before = repository.get_by_id("known")["price_range_myr"]["status"]
    details = get_restaurant_details("known", repository=repository)
    assert details["ok"] is True
    assert repository.get_by_id("known")["price_range_myr"]["status"] == before == "not_verified"
    assert details["restaurant"]["halal_status"]["status"] == "not_verified"


def test_a_short_message_uses_old_klang_road_without_asking_for_an_area():
    outcome = handle_message("hello there", DiscoveryService(records=[restaurant("known")]))
    assert outcome["needs_clarification"] is False
    assert outcome["constraints"]["region"] == "old_klang_road"
    assert "which area" not in outcome["answer"].lower()
    assert "discover_restaurants" in outcome["tools_called"]


def test_optional_features_are_disabled_by_default():
    for name in ("bm25", "hybrid", "multilingual_embedding"):
        try:
            build_ranker(name)
            assert False, name
        except FeatureDisabled:
            pass
    try:
        run_llm_agent("Old Klang Road RM20")
        assert False
    except FeatureDisabled:
        pass
    try:
        build_optional_graph()
        assert False
    except FeatureDisabled as exc:
        assert "ENABLE_LANGGRAPH is false" in str(exc)


def test_rrf_is_deterministic():
    fused = reciprocal_rank_fusion([["b", "a"], ["a", "b"]])
    assert fused == ["a", "b"]
