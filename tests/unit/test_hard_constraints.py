from food_copilot.agents.orchestrator import handle_message
from food_copilot.retrieval.constraints import apply_constraints, parse_constraints
from food_copilot.services.discovery import DiscoveryService
from tests.helpers import restaurant


def _service():
    priced = restaurant(
        "priced",
        name="Priced Place",
        price_range_myr={"min": 10, "max": 18, "basis": "per person", "status": "verified", "source_url": "https://example.local/menu"},
    )
    open_price = restaurant("open-price", name="Open Price")
    open_price["price_range_myr"] = {"min": 5, "max": None, "status": "verified"}
    over = restaurant(
        "over",
        name="Over Budget",
        price_range_myr={"min": 30, "max": 40, "basis": "per person", "status": "verified", "source_url": "https://example.local/pricey"},
    )
    kl_only = restaurant("kl-only", name="KL Only", regions=["kuala_lumpur"])
    kl_only["price_range_myr"] = {"max": 15, "status": "verified"}
    halal = restaurant(
        "halal-branch",
        name="Certified Branch",
        halal_status={"status": "verified", "source_url": "https://example.local/cert"},
        price_range_myr={"max": 19, "status": "verified", "source_url": "https://example.local/menu"},
    )
    halal_no_url = restaurant(
        "halal-no-url",
        name="Missing Cert URL",
        halal_status={"status": "verified", "source_url": None},
        price_range_myr={"max": 19, "status": "verified", "source_url": "https://example.local/menu"},
    )
    return DiscoveryService(records=[priced, open_price, over, kl_only, halal, halal_no_url])


def test_unverified_and_open_ended_prices_miss_rm20():
    outcome = handle_message("Find a family-friendly restaurant in Old Klang Road under RM20.", _service())
    ids = {item["restaurant_id"] for item in outcome["results"]}
    assert ids == {"halal-branch", "halal-no-url", "priced", "open-price"}
    assert "over" not in ids
    assert "kl-only" not in ids
    assert outcome["constraints"]["max_budget_myr"] == 20
    assert outcome["constraints"]["region"] == "old_klang_road"
    assert "verified price up to RM18" in outcome["answer"]


def test_similarity_cannot_make_an_unverified_price_eligible():
    row = restaurant("similar", name="Tasty")
    row["similarity"] = 0.99
    buckets = apply_constraints([row], parse_constraints("Old Klang Road RM20"))
    assert [item["restaurant_id"] for item in buckets.matching] == ["similar"]
    assert "price_unverified" not in buckets.exclusion_counts


def test_verified_halal_requires_a_source_url():
    outcome = handle_message("Cari restoran halal yang disahkan di Kuala Lumpur bawah RM25.", _service())
    ids = [item["restaurant_id"] for item in outcome["results"]]
    assert ids == ["halal-branch"]
    assert outcome["constraints"]["require_halal_verified"] is True
    assert outcome["constraints"]["region"] == "kuala_lumpur"
    assert outcome["language"] == "ms"


def test_empty_result_does_not_relax_the_budget():
    only_over = DiscoveryService(records=[restaurant(
        "over",
        price_range_myr={"max": 40, "status": "verified", "source_url": "https://example.local/menu"},
    )])
    outcome = handle_message("帮我找旧巴生路适合家庭聚餐、每人不超过 RM20 的餐厅。", only_over)
    assert outcome["results"] == []
    assert outcome["constraints"]["max_budget_myr"] == 20
    assert outcome["exclusion_counts"]["price_over_budget"] == 1


def test_cheap_without_a_number_does_not_guess_a_budget():
    outcome = handle_message(
        "kedai makan murah untuk keluarga di Old Klang Road",
        DiscoveryService(records=[restaurant("known")]),
    )
    assert outcome["needs_clarification"] is False
    assert [item["restaurant_id"] for item in outcome["results"]] == ["known"]
    assert outcome["constraints"]["max_budget_myr"] is None
    assert outcome["constraints"]["budget_mode"] == "flexible"
    assert "No budget number was guessed" in outcome["answer"]


def test_outside_region_is_excluded():
    buckets = apply_constraints(
        [restaurant("kl-only", regions=["kuala_lumpur"], price_range_myr={"max": 10, "status": "verified"})],
        parse_constraints("Old Klang Road RM20"),
    )
    assert buckets.matching == []
    assert buckets.exclusion_counts["region_mismatch"] == 1
