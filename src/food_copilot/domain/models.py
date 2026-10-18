"""Typed request and result models. Restaurant records stay in data.schema."""

from typing import Literal

from pydantic import BaseModel, Field

from food_copilot.data.schema import PriceStatus
from food_copilot.retrieval.constraints import QueryConstraints

EVIDENCE_STATUSES = ("verified", "not_verified", "unknown")
PRICE_STATUSES = ("verified", "not_verified", "unknown", "estimated", "price_range_only", "demo_example")
EvidenceLiteral = Literal["verified", "not_verified", "unknown"]


class EvidenceRecord(BaseModel):
    restaurant_id: str
    claim: str
    source_url: str
    source_name: str | None = None
    collected_at: str | None = None


class UserRequest(BaseModel):
    text: str
    constraints: QueryConstraints
    language: str = "en"
    unresolved: list[str] = Field(default_factory=list)
    clarification: str | None = None


class RestaurantCandidate(BaseModel):
    restaurant_id: str
    name: str | None = None
    stored_address: str | None = None
    location_verified: bool = False
    price_status: PriceStatus = "not_verified"
    price_min_myr: float | None = None
    price_max_myr: float | None = None
    halal_status: EvidenceLiteral = "not_verified"
    halal_demo_example: bool = False
    family_friendly: EvidenceLiteral = "not_verified"
    dataset_origin: Literal["canonical", "demo", "discovered"] = "canonical"
    evidence_urls: list[str] = Field(default_factory=list)
    match_reason: str = ""
    map_url: str | None = None
    photo_url: str | None = None
    cuisine_label: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class RecommendationResult(BaseModel):
    answer: str
    constraints: dict
    results: list[RestaurantCandidate] = Field(default_factory=list)
    exclusion_counts: dict[str, int] = Field(default_factory=dict)
    needs_clarification: bool = False
    sources_note: str = "Shown facts come from stored records. Unverified fields stay unverified."
    tools_called: list[str] = Field(default_factory=list)


class EvaluationQueryScore(BaseModel):
    query: str
    recall_at_5: float
    ndcg_at_5: float


class EvaluationResult(BaseModel):
    retriever: str
    dataset_records: int
    labeled_queries: list[EvaluationQueryScore] = Field(default_factory=list)
    unlabeled_queries: list[dict] = Field(default_factory=list)
    unlabeled_count: int = 0
    metrics_computed: bool = False
    constraint_violations: dict[str, int] = Field(default_factory=dict)
    empty_result_queries: int = 0
    clarification_queries: int = 0
    note: str = ""
