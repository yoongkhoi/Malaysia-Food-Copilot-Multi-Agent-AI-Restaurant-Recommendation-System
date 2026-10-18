from food_copilot.agents.orchestrator import handle_message
from food_copilot.ingestion.candidate_audit import audit_records
from food_copilot.retrieval.constraints import apply_constraints, parse_constraints
from food_copilot.services.discovery import DiscoveryService
from tests.helpers import restaurant


def _estimated():
    return restaurant(
        "estimated-place",
        name="Estimated Place",
        price_range_myr={
            "min": 12,
            "max": 18,
            "basis": "delivery platform",
            "status": "estimated",
            "source_url": "https://www.foodpanda.my/restaurant/example",
        },
    )


def test_search_url_does_not_make_a_verified_price_usable():
    row = restaurant(
        "search-price",
        price_range_myr={
            "max": 20,
            "status": "verified",
            "source_url": "https://www.google.com/search?q=menu+price",
        },
    )
    buckets = apply_constraints([row], parse_constraints("Old Klang Road under RM20"))
    assert [item["restaurant_id"] for item in buckets.matching] == ["search-price"]
    outcome = handle_message("Old Klang Road under RM20", DiscoveryService(records=[row]))
    assert outcome["results"][0]["price_status"] == "unknown"
    assert outcome["results"][0]["price_max_myr"] is None


def test_hard_budget_excludes_an_estimate_above_the_cap():
    row = _estimated()
    row["price_range_myr"]["max"] = 40
    buckets = apply_constraints([row], parse_constraints("must not exceed RM20 in Old Klang Road"))
    assert buckets.matching == []
    assert buckets.exclusion_counts["price_over_budget"] == 1


def test_flexible_budget_labels_an_estimate_and_does_not_guarantee_it():
    outcome = handle_message(
        "Find a restaurant around RM20 in Old Klang Road",
        DiscoveryService(records=[_estimated()]),
    )
    assert outcome["constraints"]["budget_mode"] == "flexible"
    assert [item["restaurant_id"] for item in outcome["results"]] == ["estimated-place"]
    assert "estimated price" in outcome["answer"]
    assert "not a confirmed current price" in outcome["answer"]
    assert "restaurants_final" not in outcome["answer"]


def test_price_range_only_cannot_guarantee_a_numeric_budget():
    row = restaurant(
        "band-only",
        price_range_myr={"status": "price_range_only", "basis": "recent customer evidence", "max": None},
    )
    hard = apply_constraints([row], parse_constraints("strictly under RM20 in Old Klang Road"))
    flexible = apply_constraints([row], parse_constraints("around RM20 in Old Klang Road"))
    assert [item["restaurant_id"] for item in hard.matching] == ["band-only"]
    assert [item["restaurant_id"] for item in flexible.matching] == ["band-only"]


def test_cheap_does_not_guess_a_number_and_can_show_a_labelled_band():
    row = restaurant(
        "band-only",
        price_range_myr={"status": "price_range_only", "basis": "recent customer evidence"},
    )
    outcome = handle_message(
        "kedai makan murah untuk keluarga di Old Klang Road",
        DiscoveryService(records=[row, restaurant("unknown-price")]),
    )
    assert outcome["needs_clarification"] is False
    assert outcome["constraints"]["max_budget_myr"] is None
    assert "not guessed" in outcome["answer"].lower() or "No budget number was guessed" in outcome["answer"]
    assert {item["restaurant_id"] for item in outcome["results"]} == {"band-only", "unknown-price"}
    assert "exact price unknown" in outcome["answer"]


def test_unknown_price_is_not_turned_into_an_amount():
    outcome = handle_message(
        "Old Klang Road under RM20",
        DiscoveryService(records=[restaurant("unknown-price")]),
    )
    assert [item["restaurant_id"] for item in outcome["results"]] == ["unknown-price"]
    assert outcome["results"][0]["price_max_myr"] is None


def test_chat_answer_does_not_expose_the_candidate_filename():
    outcome = handle_message("Old Klang Road under RM20", DiscoveryService(records=[restaurant("known")]))
    assert "restaurants_final_verified_full.json" not in outcome["answer"]
    assert "data/processed" not in outcome["answer"]


def test_candidate_audit_flags_a_verified_price_with_only_a_search_url():
    rows = [
        restaurant("one", name="One"),
        restaurant("one", name="One Again"),
        restaurant(
            "two",
            name="Two",
            price_range_myr={"max": 30, "status": "verified", "source_url": "https://www.google.com/search?q=price"},
        ),
    ]
    report = audit_records(rows, {"one", "canonical-only"})
    assert report["duplicate_ids"] == ["one"]
    assert report["verified_price_without_supporting_source"] == 1
    assert report["missing_from_candidate"] == 1
