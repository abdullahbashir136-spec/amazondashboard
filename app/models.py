"""Request/response schemas for the search API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """Filter criteria for a sourcing run. Defaults are a reasonable starting
    point for private-label FBA: mid-rank, mid-price, thin competition."""

    min_sales_rank: int = Field(default=1_000, ge=1, le=5_000_000)
    max_sales_rank: int = Field(default=100_000, ge=1, le=5_000_000)
    min_price: float = Field(default=15.0, ge=0, le=10_000)
    max_price: float = Field(default=70.0, ge=0, le=10_000)
    max_offer_count: int = Field(default=10, ge=1, le=200)
    min_rating: float = Field(default=4.0, ge=0, le=5)
    max_review_count: int = Field(default=500, ge=0, le=1_000_000)
    category: str | None = Field(default=None, max_length=120)
    target_roi: float = Field(default=50.0, gt=0, le=1_000)
    target_quantity: int = Field(default=500, ge=1, le=1_000_000)
    limit: int = Field(default=25, ge=1, le=100)

    def normalised(self) -> "SearchRequest":
        """Swap any inverted min/max pairs rather than returning zero results."""
        data = self.model_dump()
        for lo, hi in (
            ("min_sales_rank", "max_sales_rank"),
            ("min_price", "max_price"),
        ):
            if data[lo] > data[hi]:
                data[lo], data[hi] = data[hi], data[lo]
        return SearchRequest(**data)


class SearchMeta(BaseModel):
    demo_mode: bool
    result_count: int
    candidates_found: int
    target_roi: float
    target_quantity: int
    tokens_left: int | None = None
    notice: str | None = None


class SearchResponse(BaseModel):
    meta: SearchMeta
    results: list[dict]


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
    hint: str | None = None
