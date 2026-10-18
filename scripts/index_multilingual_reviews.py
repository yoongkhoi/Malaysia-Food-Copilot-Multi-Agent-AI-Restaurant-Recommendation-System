"""Embed the existing pilot corpus with a small multilingual model. Does not touch the MiniLM index."""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from food_copilot.reviews.retrieve import load_jsonl

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
SOURCE = ROOT / "data" / "processed" / "reviews" / "pilot_corpus.jsonl"
TARGET = ROOT / "data" / "vector_store" / "restaurant_reviews_multilingual_minilm"


def main() -> int:
    import chromadb
    from fastembed import TextEmbedding

    docs = load_jsonl(SOURCE)
    TARGET.mkdir(parents=True, exist_ok=True)
    embedder = TextEmbedding(MODEL)
    client = chromadb.PersistentClient(path=str(TARGET))
    collection = client.get_or_create_collection(
        name="restaurant_reviews_multilingual",
        metadata={"hnsw:space": "cosine"},
    )
    batch = 64
    for start in range(0, len(docs), batch):
        chunk = docs[start:start + batch]
        vectors = [vector.tolist() for vector in embedder.embed([doc.get("review_text") or "" for doc in chunk])]
        collection.upsert(
            ids=[doc["review_id"] for doc in chunk],
            documents=[doc.get("review_text") or "" for doc in chunk],
            embeddings=vectors,
            metadatas=[{
                "restaurant_id": doc.get("restaurant_id") or "",
                "restaurant_name": doc.get("restaurant_name") or "",
                "source": doc.get("source") or "",
                "source_file": doc.get("source_file") or "",
                "rating": float(doc["rating"]) if doc.get("rating") is not None else -1.0,
                "language": doc.get("language") or "",
                "match_status": doc.get("match_status") or "",
                "source_city": doc.get("source_city") or "",
            } for doc in chunk],
        )
        print({"upserted_through": start + len(chunk), "total": len(docs)}, flush=True)
    (TARGET / "index_meta.json").write_text(json.dumps({
        "index_version": "reviews-multilingual-minilm-v1",
        "embedding_model": MODEL,
        "size_in_GB": 0.22,
        "documents": collection.count(),
        "replaces_existing_minilm_index": False,
    }, indent=2), encoding="utf-8")
    print({"indexed": collection.count(), "path": str(TARGET)})
    os._exit(0)


if __name__ == "__main__":
    raise SystemExit(main())
