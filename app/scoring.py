"""Scoring model: competition, seasonality, and the sourcing-cost ceiling.

Both scores run 0..1 where LOWER IS BETTER, so a result list sorted ascending
puts the best opportunities on top.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, asdict

from .fees import estimate_fees, FeeBreakdown

# --- Tunables -------------------------------------------------------------
# Offer count at which competition is considered "saturated" (score maxes out
# on the offer component alone). Below this it scales linearly.
OFFER_COUNT_CEILING = 25.0

# How much of competition_score comes from raw offer count vs. Amazon presence.
OFFER_WEIGHT = 0.65
AMAZON_PENALTY = 0.35

# Coefficient of variation at which a product is considered fully seasonal.
# CV = stdev / mean of the sales-rank series. A steady year-round seller sits
# well under 0.3; a Christmas-only product blows past 1.0.
SEASONALITY_CV_CEILING = 0.80

# Minimum number of rank samples before a seasonality score means anything.
MIN_RANK_SAMPLES = 8


@dataclass
class ScoredProduct:
    asin: str
    title: str
    price: float | None
    sales_rank: int | None
    offer_count: int | None
    amazon_on_listing: bool
    rating: float | None
    review_count: int | None
    category: str | None
    competition_score: float
    seasonality_score: float
    opportunity_score: float
    max_sourcing_cost: float | None
    target_unit_price: float | None
    fees: dict
    seasonality_confidence: str
    rank_samples: int
    amazon_url: str
    rfq: dict | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def competition_score(offer_count: int | None, amazon_on_listing: bool) -> float:
    """0..1, lower is better.

    Two inputs: how many sellers are already on the listing, and whether Amazon
    itself is one of them. Amazon as a competitor is disproportionately bad —
    it wins the buy box more or less whenever it wants — so it carries a flat
    penalty on top of the offer-count component.
    """
    count = offer_count if offer_count is not None and offer_count >= 0 else int(OFFER_COUNT_CEILING)
    offer_component = min(count / OFFER_COUNT_CEILING, 1.0) * OFFER_WEIGHT
    penalty = AMAZON_PENALTY if amazon_on_listing else 0.0
    return round(min(offer_component + penalty, 1.0), 3)


def seasonality_score(rank_history: list[float] | None) -> tuple[float, str, int]:
    """Coefficient of variation of the trailing sales-rank series.

    Returns (score, confidence, sample_count). Steady rank all year = low CV =
    low score = good. Holiday-only products swing hard and score near 1.0.

    With too few samples we return the neutral midpoint 0.5 and flag low
    confidence rather than inventing precision we don't have.
    """
    samples = [float(r) for r in (rank_history or []) if r is not None and r > 0]
    n = len(samples)

    if n < MIN_RANK_SAMPLES:
        return 0.5, "low", n

    mean = statistics.fmean(samples)
    if mean <= 0:
        return 0.5, "low", n

    stdev = statistics.pstdev(samples)
    cv = stdev / mean
    score = round(min(cv / SEASONALITY_CV_CEILING, 1.0), 3)
    confidence = "high" if n >= 26 else "medium"
    return score, confidence, n


def max_sourcing_cost(
    sale_price: float | None,
    fees: FeeBreakdown,
    target_roi_pct: float,
) -> float | None:
    """Highest per-unit price payable to a supplier while still hitting target ROI.

        cost = (sale_price - fees) / (1 + target_roi/100)

    This is the number that actually matters when talking to suppliers — it
    becomes the hard ceiling in the RFQ. Returns None when the product can't
    clear fees at all (i.e. it's unsellable at any sourcing price).
    """
    if sale_price is None or sale_price <= 0:
        return None

    net = sale_price - fees.total
    if net <= 0:
        return None

    divisor = 1.0 + (target_roi_pct / 100.0)
    if divisor <= 0:
        return None

    return round(net / divisor, 2)


def opportunity_score(competition: float, seasonality: float) -> float:
    """Combined sort key. Lower is better. Competition weighted slightly higher
    because a crowded listing kills a lead faster than mild seasonality does."""
    return round(competition * 0.6 + seasonality * 0.4, 3)


def score_product(
    product: dict,
    target_roi_pct: float,
    negotiating_margin: float = 0.85,
) -> ScoredProduct:
    """Turn one normalised product dict into a fully scored lead.

    `product` is expected to come from `keepa_client.normalise_product()`, which
    already does the defensive field extraction. Everything here still uses
    `.get()` because Keepa's schema is sparse and category-dependent.
    """
    price = product.get("price")
    category = product.get("category")

    fees = estimate_fees(price or 0.0, category)
    comp = competition_score(product.get("offer_count"), bool(product.get("amazon_on_listing")))
    seas, confidence, samples = seasonality_score(product.get("rank_history"))
    ceiling = max_sourcing_cost(price, fees, target_roi_pct)

    # Open negotiations below the ceiling so there's room to move upward.
    target_price = round(ceiling * negotiating_margin, 2) if ceiling else None

    asin = product.get("asin", "")
    return ScoredProduct(
        asin=asin,
        title=product.get("title") or "(untitled)",
        price=price,
        sales_rank=product.get("sales_rank"),
        offer_count=product.get("offer_count"),
        amazon_on_listing=bool(product.get("amazon_on_listing")),
        rating=product.get("rating"),
        review_count=product.get("review_count"),
        category=category,
        competition_score=comp,
        seasonality_score=seas,
        opportunity_score=opportunity_score(comp, seas),
        max_sourcing_cost=ceiling,
        target_unit_price=target_price,
        fees=fees.as_dict(),
        seasonality_confidence=confidence,
        rank_samples=samples,
        amazon_url=f"https://www.amazon.com/dp/{asin}" if asin else "",
    )


def sort_leads(leads: list[ScoredProduct]) -> list[ScoredProduct]:
    """Best opportunities first: lowest competition + seasonality, then the most
    sourcing headroom as a tiebreak."""
    return sorted(
        leads,
        key=lambda x: (
            x.competition_score + x.seasonality_score,
            -(x.max_sourcing_cost or 0.0),
        ),
    )
