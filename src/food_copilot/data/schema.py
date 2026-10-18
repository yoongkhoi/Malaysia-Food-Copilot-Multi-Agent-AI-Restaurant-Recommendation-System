"""Canonical restaurant record. Unknown is not the same as false."""

from typing import Literal

from pydantic import BaseModel, Field

# verified: a source confirms the claim.
# not_verified: not checked yet. This is not a negative finding.
# unknown: checked sources still do not establish the claim.
EvidenceStatus = Literal["verified", "not_verified", "unknown"]
PriceStatus = Literal["verified", "not_verified", "unknown", "estimated", "price_range_only", "demo_example"]
RecordStatus = Literal["needs_review", "verified"]
LocationEvidence = Literal["address", "area_query", "none"]


class Source(BaseModel):
    source_name: str
    source_url: str
    license: str | None = None
    collected_at: str
    fields: list[str] = Field(default_factory=list)


class PriceRange(BaseModel):
    min: float | None = None
    max: float | None = None
    basis: str = "unknown"
    status: PriceStatus = "not_verified"
    source_url: str | None = None
    checked_at: str | None = None
    notes: str | None = None


class HalalStatus(BaseModel):
    status: EvidenceStatus = "not_verified"
    verified_at: str | None = None
    source_url: str | None = None
    demo_example: bool = False


class Restaurant(BaseModel):
    restaurant_id: str
    name: str | None
    country_code: str = "MY"
    state: str | None = None
    city: str | None = None
    area_query: str | None = None
    regions: list[str] = Field(default_factory=list)
    location_evidence: LocationEvidence = "none"
    location_verified: bool = False
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    cuisine: list[str] = Field(default_factory=list)
    cuisine_raw: str | None = None
    diets: list[str] = Field(default_factory=list)
    ambience: list[str] = Field(default_factory=list)
    dataset_origin: Literal["canonical", "demo", "discovered"] = "canonical"
    price_range_myr: PriceRange = Field(default_factory=PriceRange)
    suitable_for_family: EvidenceStatus = "not_verified"
    halal_status: HalalStatus = Field(default_factory=HalalStatus)
    description: str | None = None
    sources: list[Source]
    record_status: RecordStatus = "needs_review"
