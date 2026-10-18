from food_copilot.retrieval.constraints import apply_constraints, parse_constraints
from food_copilot.services.restaurant_service import discover

KULIM_CHEAP = {
    "restaurant_id": "fixture-cheap",
    "name": "Budget Kopitiam",
    "city": "Kulim",
    "price_range_myr": {"min": 12, "max": 18, "basis": "per person", "status": "verified", "source_url": "https://example.local/menu"},
    "halal_status": {"status": "unknown", "source_url": None},
    "suitable_for_family": "unknown",
    "sources": [{"source_name": "fixture"}],
}
KULIM_PRICEY = {
    "restaurant_id": "fixture-pricey",
    "name": "Pricey Place",
    "city": "Kulim",
    "price_range_myr": {"min": 30, "max": 45, "basis": "per person", "status": "verified", "source_url": "https://example.local/pricey"},
    "halal_status": {"status": "unknown"},
    "sources": [{"source_name": "fixture"}],
}
KULIM_UNKNOWN_PRICE = {
    "restaurant_id": "fixture-unknown",
    "name": "OSM Cafe",
    "city": "Kulim",
    "price_range_myr": {"min": None, "max": None, "basis": "unknown", "status": "unknown"},
    "halal_status": {"status": "unknown"},
    "sources": [{"source_name": "OpenStreetMap"}],
}
AREA_ONLY = {
    "restaurant_id": "fixture-area",
    "name": "Unlabeled Stall",
    "city": None,
    "area_query": "Kulim",
    "price_range_myr": {"status": "unknown"},
    "halal_status": {"status": "unknown"},
    "sources": [{"source_name": "OpenStreetMap"}],
}
VERIFIED_HALAL = {
    "restaurant_id": "fixture-halal",
    "name": "Verified Kitchen",
    "city": "Kulim",
    "price_range_myr": {"max": 20, "basis": "per person", "status": "verified", "source_url": "https://example.local/menu"},
    "halal_status": {"status": "verified", "source_url": "https://example.local/cert", "verified_at": "2026-01-01"},
    "sources": [{"source_name": "fixture"}],
}
ROWS = [KULIM_CHEAP, KULIM_PRICEY, KULIM_UNKNOWN_PRICE, AREA_ONLY, VERIFIED_HALAL]


def test_chinese_query_parses_city_budget_and_family():
    parsed = parse_constraints("帮我找 Kulim 附近 RM20 以内、适合家庭吃饭的餐厅")
    assert parsed.city == "Kulim"
    assert parsed.max_budget_myr == 20
    assert parsed.family is True


def test_city_label_kulim_kedah_counts_as_kulim():
    row = {**KULIM_CHEAP, "restaurant_id": "fixture-label", "city": "Kulim, Kedah"}
    buckets = apply_constraints([row], parse_constraints("Kulim under RM20"))
    assert [item["restaurant_id"] for item in buckets.matching] == ["fixture-label"]


def test_not_verified_price_is_not_a_budget_match():
    row = {
        **KULIM_CHEAP,
        "restaurant_id": "fixture-unchecked",
        "price_range_myr": {"min": 10, "max": 15, "basis": "per person", "status": "not_verified"},
    }
    buckets = apply_constraints([row], parse_constraints("Kulim under RM20"))
    assert [item["restaurant_id"] for item in buckets.matching] == ["fixture-unchecked"]


def test_budget_is_hard_and_unknown_is_not_a_match():
    buckets = apply_constraints(ROWS, parse_constraints("Kulim under RM20"))
    ids = [row["restaurant_id"] for row in buckets.matching]
    assert ids == ["fixture-cheap", "fixture-unknown", "fixture-halal"]
    assert "fixture-pricey" not in ids
    assert [row["restaurant_id"] for row in buckets.city_unverified] == ["fixture-area"]


def test_halal_request_does_not_treat_unknown_as_verified():
    result = discover("Kulim halal under RM20", ROWS)
    assert "fixture-halal" in [row["restaurant_id"] for row in result["results"]]
    assert "fixture-cheap" in [row["restaurant_id"] for row in result["results"]]
    assert "尚未" not in result["answer"] or "Unknown" in result["answer"] or "not certified" in result["answer"].lower() or "Not enough evidence" in result["answer"]


def test_answer_states_when_nothing_is_under_budget():
    result = discover("Kulim under RM20", [KULIM_PRICEY, KULIM_UNKNOWN_PRICE])
    assert [row["restaurant_id"] for row in result["results"]] == ["fixture-unknown"]
    assert "fixture-pricey" not in [row["restaurant_id"] for row in result["results"]]
