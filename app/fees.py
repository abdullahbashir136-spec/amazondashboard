"""Amazon fee estimation.

!!! PLACEHOLDER MATH — NOT AUTHORITATIVE !!!

Every number in this module is an approximation. Referral fee percentages are a
hand-maintained lookup table and the FBA fulfilment fee is a single flat guess
that ignores size tier, weight, and dimensional weight entirely.

The authoritative current referral fee table lives at:
    https://sell.amazon.com/pricing
Real per-ASIN fulfilment fees come from SP-API's Product Fees endpoint:
    https://developer-docs.amazon.com/sp-api/docs/product-fees-api-v0-reference

`estimate_fees()` is deliberately the ONLY place fees are computed anywhere in
this codebase. Swapping to real SP-API data is a one-function change: keep the
signature, replace the body with a Product Fees call, and every caller (scoring,
RFQ ceilings, the UI) picks it up automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

# Approximate US referral fee rates by Keepa root-category name.
# Source (approximate, subject to change): https://sell.amazon.com/pricing
# Keys are lowercased for case-insensitive matching.
REFERRAL_RATE_BY_CATEGORY: dict[str, float] = {
    "electronics": 0.08,
    "computers": 0.08,
    "camera & photo": 0.08,
    "cell phones & accessories": 0.08,
    "video games": 0.15,
    "home & kitchen": 0.15,
    "kitchen & dining": 0.15,
    "toys & games": 0.15,
    "sports & outdoors": 0.15,
    "tools & home improvement": 0.15,
    "office products": 0.15,
    "pet supplies": 0.15,
    "health & household": 0.15,
    "beauty & personal care": 0.15,
    "grocery & gourmet food": 0.15,
    "baby products": 0.15,
    "musical instruments": 0.15,
    "books": 0.15,
    "arts, crafts & sewing": 0.15,
    "patio, lawn & garden": 0.15,
    "clothing, shoes & jewelry": 0.17,
    "watches": 0.16,
    "jewelry": 0.20,
    "automotive": 0.12,
    "industrial & scientific": 0.12,
}

DEFAULT_REFERRAL_RATE = 0.15

# Flat stand-in for FBA fulfilment. Real fees run roughly $3.00-$8.00+ for
# standard-size units and scale hard with weight/dimensions. This single number
# is wrong for almost every specific product — it exists so the ROI maths has
# *something* to subtract until SP-API is wired up.
FLAT_FBA_FULFILMENT_FEE = 5.50

# Amazon's per-unit closing fee applies to media categories only.
MEDIA_CATEGORIES = {"books", "video games"}
MEDIA_CLOSING_FEE = 1.80


@dataclass(frozen=True)
class FeeBreakdown:
    """Itemised (estimated) Amazon fees for a single unit sale."""

    referral_fee: float
    fulfilment_fee: float
    closing_fee: float
    total: float
    referral_rate: float
    is_estimate: bool = True
    basis: str = "placeholder-lookup-table"

    def as_dict(self) -> dict:
        return asdict(self)


def referral_rate_for_category(category: str | None) -> float:
    """Look up the approximate referral rate for a category name."""
    if not category:
        return DEFAULT_REFERRAL_RATE
    return REFERRAL_RATE_BY_CATEGORY.get(category.strip().lower(), DEFAULT_REFERRAL_RATE)


def estimate_fees(sale_price: float, category: str | None = None) -> FeeBreakdown:
    """Estimate total Amazon fees on a single unit sold at `sale_price`.

    PLACEHOLDER — see module docstring. Replace the body with an SP-API Product
    Fees call to make this authoritative; the signature is the contract.
    """
    if sale_price is None or sale_price <= 0:
        return FeeBreakdown(0.0, 0.0, 0.0, 0.0, DEFAULT_REFERRAL_RATE)

    rate = referral_rate_for_category(category)
    referral = round(sale_price * rate, 2)

    normalised = (category or "").strip().lower()
    closing = MEDIA_CLOSING_FEE if normalised in MEDIA_CATEGORIES else 0.0

    total = round(referral + FLAT_FBA_FULFILMENT_FEE + closing, 2)
    return FeeBreakdown(
        referral_fee=referral,
        fulfilment_fee=FLAT_FBA_FULFILMENT_FEE,
        closing_fee=closing,
        total=total,
        referral_rate=rate,
    )
