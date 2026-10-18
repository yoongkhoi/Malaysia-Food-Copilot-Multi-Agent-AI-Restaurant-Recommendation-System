"""Persistent Chroma index. Importing this module requires the project virtualenv."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from food_copilot.reviews.retrieve import INDEX_VERSION, VECTOR_MODEL


def _metadata(doc: dict) -> dict:
    rating = doc.get("rating")
    return {
        "restaurant_id": doc.get("restaurant_id") or "",
        "restaurant_name": doc.get("restaurant_name") or "",
        "source": doc.get("source") or "",
        "source_file": doc.get("source_file") or "",
        "rating": float(rating) if rating is not None else -1.0,
        "language": doc.get("language") or "",
        "match_status": doc.get("match_status") or "",
        "source_city": doc.get("source_city") or "",
    }


def open_collection(path: Path, rebuild: bool = False):
    import chromadb
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

    path = Path(path)
    if rebuild and path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = path.parent / f"{path.name}.backup-{stamp}"
        if backup.exists():
            raise FileExistsError(f"Backup already exists: {backup}")
        shutil.move(str(path), str(backup))
    path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(path))
    collection = client.get_or_create_collection(
        name="restaurant_reviews",
        embedding_function=DefaultEmbeddingFunction(),
        metadata={"hnsw:space": "cosine"},
    )
    meta = {
        "index_version": INDEX_VERSION,
        "embedding_model": VECTOR_MODEL,
        "embedding_provider": "chromadb.utils.embedding_functions.DefaultEmbeddingFunction",
        "space": "cosine",
        "rebuild": rebuild,
    }
    (path / "index_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return client, collection


def upsert_documents(collection, docs: list[dict], batch_size: int = 128) -> int:
    written = 0
    for start in range(0, len(docs), batch_size):
        batch = docs[start:start + batch_size]
        collection.upsert(
            ids=[doc["review_id"] for doc in batch],
            documents=[doc.get("review_text") or "" for doc in batch],
            metadatas=[_metadata(doc) for doc in batch],
        )
        written += len(batch)
    return written


def query_documents(collection, query: str, limit: int, where: dict | None = None) -> list[dict]:
    count = collection.count()
    if count == 0:
        return []
    result = collection.query(
        query_texts=[query],
        n_results=min(limit, count),
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    docs = []
    ids = (result.get("ids") or [[]])[0]
    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    for review_id, text, meta in zip(ids, documents, metadatas):
        meta = meta or {}
        rating = meta.get("rating")
        docs.append({
            "review_id": review_id,
            "review_text": text or "",
            "restaurant_id": meta.get("restaurant_id") or None,
            "restaurant_name": meta.get("restaurant_name") or None,
            "source": meta.get("source") or None,
            "source_file": meta.get("source_file") or None,
            "rating": None if rating in (-1, -1.0, None) else rating,
            "language": meta.get("language") or None,
            "match_status": meta.get("match_status") or None,
            "source_city": meta.get("source_city") or None,
            "aspects": [],
        })
    return docs
