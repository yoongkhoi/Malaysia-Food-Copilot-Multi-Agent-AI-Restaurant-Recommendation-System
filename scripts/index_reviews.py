"""Build or rebuild the Chroma review index. A rebuild renames the old directory."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from food_copilot.reviews.chroma_store import open_collection, upsert_documents
from food_copilot.reviews.retrieve import load_jsonl


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--corpus", default="pilot")
    args = parser.parse_args()
    name = "pilot_corpus.jsonl" if args.corpus == "pilot" else "reviews.jsonl"
    source = ROOT / "data" / "processed" / "reviews" / name
    if not source.exists():
        print(f"Missing {source}. Run scripts/prepare_reviews.py first.")
        return 1
    docs = load_jsonl(source)
    path = ROOT / "data" / "vector_store" / "restaurant_reviews"
    collection = open_collection(path, rebuild=args.rebuild)[1]
    written = upsert_documents(collection, docs)
    print({"indexed": written, "collection_count": collection.count(), "path": str(path), "corpus": name})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
