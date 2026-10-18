"""Rankers. Only baseline is used unless a feature flag is on."""

import math
import re
from collections import Counter

from food_copilot.config.settings import embedding_model_name, feature_flags
from food_copilot.errors import FeatureDisabled

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "and", "for", "under", "near", "with", "food", "find",
    "restaurant", "restaurants", "bawah", "yang",
}


class BaselineRetriever:
    name = "baseline"

    def rank(self, records: list[dict], query_text: str) -> list[dict]:
        tokens = [token for token in _TOKEN.findall((query_text or "").lower()) if token not in _STOP and len(token) > 2]

        def score(row: dict) -> int:
            name = (row.get("name") or "").lower()
            return sum(1 for token in tokens if token in name)

        return sorted(records, key=lambda row: (-score(row), row.get("restaurant_id") or ""))


class BM25Retriever:
    name = "bm25"

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b

    def rank(self, records: list[dict], query_text: str) -> list[dict]:
        docs = [_TOKEN.findall(" ".join([
            row.get("name") or "",
            " ".join(row.get("cuisine") or []),
            row.get("description") or "",
        ]).lower()) for row in records]
        query = _TOKEN.findall((query_text or "").lower())
        if not query or not records:
            return sorted(records, key=lambda row: row.get("restaurant_id") or "")
        avg = sum(len(doc) for doc in docs) / len(docs) or 1.0
        df: Counter[str] = Counter()
        for doc in docs:
            df.update(set(doc))
        total = len(docs)
        scores = []
        for doc in docs:
            counts = Counter(doc)
            length = len(doc) or 1
            score = 0.0
            for term in query:
                if term not in counts:
                    continue
                idf = math.log(1 + (total - df[term] + 0.5) / (df[term] + 0.5))
                freq = counts[term]
                denom = freq + self.k1 * (1 - self.b + self.b * length / avg)
                score += idf * (freq * (self.k1 + 1)) / denom
            scores.append(score)
        order = sorted(range(len(records)), key=lambda index: (-scores[index], records[index].get("restaurant_id") or ""))
        return [records[index] for index in order]


class MultilingualEmbeddingRetriever:
    name = "multilingual_embedding"

    def __init__(self):
        if not feature_flags()["ENABLE_MULTILINGUAL_EMBEDDINGS"]:
            raise FeatureDisabled("ENABLE_MULTILINGUAL_EMBEDDINGS is false. The embedding model is not loaded.")
        try:
            from food_copilot.retrieval.embeddings import EmbeddingService, restaurant_to_document
        except ImportError as exc:
            raise FeatureDisabled("The embedding dependencies are not installed.") from exc
        self._to_document = restaurant_to_document
        self._service = EmbeddingService(embedding_model_name())

    def rank(self, records: list[dict], query_text: str) -> list[dict]:
        if not records:
            return []
        query_vector = self._service.embed_query(query_text or "")
        doc_matrix = self._service.embed_documents([self._to_document(row) for row in records])
        scores = doc_matrix @ query_vector
        order = sorted(
            range(len(records)),
            key=lambda index: (-float(scores[index]), records[index].get("restaurant_id") or ""),
        )
        return [records[index] for index in order]


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60) -> list[str]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for index, item_id in enumerate(ranking):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + index + 1)
    return sorted(scores, key=lambda item_id: (-scores[item_id], item_id))


class HybridRetriever:
    name = "hybrid"

    def __init__(self):
        flags = feature_flags()
        if not flags["ENABLE_HYBRID_RETRIEVAL"]:
            raise FeatureDisabled("ENABLE_HYBRID_RETRIEVAL is false. Hybrid RRF was not used.")
        if not flags["ENABLE_BM25"]:
            raise FeatureDisabled("Hybrid retrieval requires ENABLE_BM25=true. It was not run.")
        self.baseline = BaselineRetriever()
        self.bm25 = BM25Retriever()
        self.embedding = MultilingualEmbeddingRetriever() if flags["ENABLE_MULTILINGUAL_EMBEDDINGS"] else None

    def rank(self, records: list[dict], query_text: str) -> list[dict]:
        rankings = [
            [row.get("restaurant_id") or "" for row in self.baseline.rank(records, query_text)],
            [row.get("restaurant_id") or "" for row in self.bm25.rank(records, query_text)],
        ]
        if self.embedding is not None:
            rankings.append([row.get("restaurant_id") or "" for row in self.embedding.rank(records, query_text)])
        by_id = {row.get("restaurant_id"): row for row in records}
        return [by_id[item_id] for item_id in reciprocal_rank_fusion(rankings) if item_id in by_id]


def build_ranker(name: str = "baseline"):
    flags = feature_flags()
    if name == "baseline":
        return BaselineRetriever()
    if name == "bm25":
        if not flags["ENABLE_BM25"]:
            raise FeatureDisabled("ENABLE_BM25 is false. BM25 was not used.")
        return BM25Retriever()
    if name == "multilingual_embedding":
        return MultilingualEmbeddingRetriever()
    if name == "hybrid":
        return HybridRetriever()
    raise FeatureDisabled(f"Unknown retriever {name!r}.")
