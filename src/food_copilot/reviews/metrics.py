"""Labeled retrieval metrics. Empty relevance sets are not scored as zero recall."""

from __future__ import annotations

import math


def _dcg(gains: list[int]) -> float:
    return sum(gain / math.log2(index + 2) for index, gain in enumerate(gains))


def recall_at(ranked_ids: list[str], relevant: set[str], k: int) -> float | None:
    if not relevant:
        return None
    return len(set(ranked_ids[:k]) & relevant) / len(relevant)


def precision_at(ranked_ids: list[str], relevant: set[str], k: int) -> float | None:
    """Precision@K uses K as the denominator. A short list does not raise the score."""
    if k <= 0 or not relevant:
        return None
    return len(set(ranked_ids[:k]) & relevant) / k


def mrr(ranked_ids: list[str], relevant: set[str]) -> float | None:
    if not relevant:
        return None
    for index, item_id in enumerate(ranked_ids, start=1):
        if item_id in relevant:
            return 1.0 / index
    return 0.0


def ndcg_at(ranked_ids: list[str], relevant: set[str], k: int) -> float | None:
    if not relevant:
        return None
    gains = [1 if item_id in relevant else 0 for item_id in ranked_ids[:k]]
    ideal = [1] * min(k, len(relevant))
    ideal += [0] * (k - len(ideal))
    ideal_score = _dcg(ideal[:k])
    if ideal_score == 0:
        return None
    return _dcg(gains) / ideal_score


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]
