from food_copilot.evaluation.runner import evaluate, format_summary
from food_copilot.retrieval.rankers import BM25Retriever
from food_copilot.services.discovery import DiscoveryService
from tests.helpers import restaurant


def test_unlabeled_queries_are_not_scored():
    service = DiscoveryService(records=[restaurant("known")])
    queries = [
        {"query": "Old Klang Road under RM20", "relevant_restaurant_ids": []},
        {
            "query": "Old Klang Road under RM20",
            "relevant_restaurant_ids": ["priced"],
        },
    ]
    priced = restaurant("priced", name="Priced", price_range_myr={"max": 15, "status": "verified", "source_url": "https://example.local/menu"})
    service = DiscoveryService(records=[restaurant("known"), priced])
    result = evaluate(service, queries)
    assert result.unlabeled_count == 1
    assert result.metrics_computed is True
    assert len(result.labeled_queries) == 1
    assert result.labeled_queries[0].recall_at_5 == 1.0
    assert result.constraint_violations == {"budget": 0, "region": 0, "halal": 0}
    summary = format_summary(result)
    assert "Unlabeled queries: 1" in summary


def test_all_empty_labels_do_not_invent_scores():
    service = DiscoveryService(records=[restaurant("known")])
    result = evaluate(service, [{"query": "Old Klang Road RM20", "relevant_restaurant_ids": []}])
    assert result.metrics_computed is False
    assert result.labeled_queries == []
    assert "not computed" in result.note
    assert "Recall@5=" not in format_summary(result)


def test_bm25_orders_a_name_match_first_without_being_the_default():
    rows = [
        restaurant("other", name="Other Place"),
        restaurant("kopi", name="Kopitiam Corner"),
    ]
    ranked = BM25Retriever().rank(rows, "kopitiam")
    assert ranked[0]["restaurant_id"] == "kopi"
