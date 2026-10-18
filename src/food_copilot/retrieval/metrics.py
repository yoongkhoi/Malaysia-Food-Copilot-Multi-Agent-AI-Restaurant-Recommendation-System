"""Retrieval metrics used to compare the hash baseline with a semantic index."""

import math


def recall_at_k(retrieved_ids: list[str], relevant_ids: list[str], k: int = 5) -> float:
    if not relevant_ids:
        return 0.0
    found = set(retrieved_ids[:k]) & set(relevant_ids)
    return len(found) / len(set(relevant_ids))


def ndcg_at_k(retrieved_ids: list[str], relevant_ids: list[str], k: int = 5) -> float:
    relevant = set(relevant_ids)
    if not relevant:
        return 0.0
    dcg = 0.0
    for index, item_id in enumerate(retrieved_ids[:k]):
        if item_id in relevant:
            dcg += 1.0 / math.log2(index + 2)
    ideal_hits = min(k, len(relevant))
    idcg = sum(1.0 / math.log2(index + 2) for index in range(ideal_hits))
    return dcg / idcg if idcg else 0.0
