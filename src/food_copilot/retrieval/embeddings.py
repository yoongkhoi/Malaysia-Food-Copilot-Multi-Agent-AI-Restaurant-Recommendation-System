"""Semantic embeddings. This module does not answer the user."""


class EmbeddingService:
    def __init__(self, model_name: str = "intfloat/multilingual-e5-base"):
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.model = SentenceTransformer(model_name)

    def embed_documents(self, texts: list[str]):
        passages = [f"passage: {text}" for text in texts]
        return self.model.encode(
            passages,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

    def embed_query(self, query: str):
        vector = self.model.encode(
            [f"query: {query}"],
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return vector[0]


def restaurant_to_document(restaurant: dict) -> str:
    cuisine = ", ".join(restaurant.get("cuisine") or []) or "Unknown"
    price = restaurant.get("price_range_myr") or {}
    if price.get("status") == "verified" and price.get("max") is not None:
        price_text = f"up to RM{price['max']} ({price.get('basis') or 'unspecified basis'})"
    else:
        price_text = "Unknown"
    return "\n".join([
        f"Name: {restaurant.get('name') or 'Unknown'}",
        f"Location: {restaurant.get('city') or 'Unknown'}, {restaurant.get('state') or 'Unknown'}",
        f"Cuisine: {cuisine}",
        f"Description: {restaurant.get('description') or ''}",
        f"Price: {price_text}",
        f"Family friendly: {restaurant.get('suitable_for_family') or 'unknown'}",
        f"Halal: {(restaurant.get('halal_status') or {}).get('status') or 'unknown'}",
    ])
