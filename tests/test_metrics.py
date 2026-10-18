from food_copilot.retrieval.metrics import ndcg_at_k, recall_at_k


def test_recall_and_ndcg_reward_relevant_ids_only():
    retrieved = ["a", "b", "c", "d", "e"]
    assert recall_at_k(retrieved, ["b", "z"], k=5) == 0.5
    assert recall_at_k(["z"], ["a"], k=5) == 0.0
    perfect = ndcg_at_k(["a", "b"], ["a", "b"], k=5)
    worse = ndcg_at_k(["c", "a"], ["a", "b"], k=5)
    assert perfect == 1.0
    assert worse < perfect
