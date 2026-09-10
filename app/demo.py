"""Synthetic product data for demo mode.

Demo mode exists so the dashboard is usable before a Keepa subscription is in
place. The products below are INVENTED — the ASINs are not real listings and
the numbers are not market data.

What is real: these fixtures are pushed through the exact same
`scoring.score_product` and `rfq.build_rfq` code paths that live Keepa results
use. So the scores, fee estimates, and sourcing ceilings on screen are genuine
outputs of the production model — only the inputs are fabricated.

Every response built from this module carries `demo_mode: true`, and the UI
renders a persistent banner. Nothing here should ever be mistaken for a lead.
"""

from __future__ import annotations

import math
import random

# (title, category, price, sales_rank, offer_count, amazon_on_listing, rating,
#  review_count, seasonality_shape)
#
# seasonality_shape drives the synthetic rank history:
#   "steady"   - flat year-round, the profile we actually want
#   "mild"     - gentle drift
#   "seasonal" - strong annual swing (holiday/summer dependent)
_FIXTURES = [
    ("Bamboo Drawer Organiser Set, 6-Piece Expandable", "Home & Kitchen", 34.99, 18400, 3, False, 4.6, 212, "steady"),
    ("Silicone Stretch Lids, 12-Pack Reusable", "Home & Kitchen", 18.95, 42100, 5, False, 4.4, 388, "steady"),
    ("Adjustable Laptop Stand, Aluminium Foldable", "Office Products", 42.50, 26700, 7, False, 4.5, 455, "mild"),
    ("Resistance Bands Set with Door Anchor", "Sports & Outdoors", 29.99, 31200, 9, False, 4.3, 476, "seasonal"),
    ("Ceramic Pour-Over Coffee Dripper", "Home & Kitchen", 26.00, 58900, 4, False, 4.7, 143, "steady"),
    ("Weighted Blanket 15lb, Cooling Cotton", "Home & Kitchen", 64.99, 12800, 14, True, 4.5, 492, "seasonal"),
    ("Cable Management Box, Fire-Resistant", "Electronics", 22.99, 47300, 6, False, 4.4, 267, "steady"),
    ("Collapsible Silicone Food Storage, 4-Pack", "Home & Kitchen", 31.75, 67400, 2, False, 4.6, 98, "steady"),
    ("Desk Cable Grommet, Brushed Steel 3-Pack", "Tools & Home Improvement", 16.50, 89200, 3, False, 4.2, 61, "steady"),
    ("Insulated Lunch Bag, Leakproof Adult", "Home & Kitchen", 27.99, 22100, 11, False, 4.3, 431, "mild"),
    ("Acacia Wood Serving Board with Handle", "Home & Kitchen", 38.00, 54600, 5, False, 4.8, 177, "seasonal"),
    ("Magnetic Knife Strip, 16-Inch Walnut", "Home & Kitchen", 44.95, 71300, 4, False, 4.7, 129, "steady"),
    ("Blue Light Blocking Glasses, Unisex Frame", "Health & Household", 24.99, 35800, 19, True, 4.1, 388, "steady"),
    ("Under-Sink Organiser, 2-Tier Pull-Out", "Home & Kitchen", 33.50, 28900, 8, False, 4.4, 302, "mild"),
    ("Travel Jewellery Case, Vegan Leather", "Clothing, Shoes & Jewelry", 21.99, 63700, 6, False, 4.5, 214, "seasonal"),
    ("Digital Kitchen Scale, 11lb Stainless", "Home & Kitchen", 19.99, 15600, 22, True, 4.5, 487, "mild"),
    ("Plant Mister Bottle, Amber Glass", "Patio, Lawn & Garden", 17.25, 94500, 3, False, 4.6, 88, "seasonal"),
    ("Monitor Light Bar, USB-C Powered", "Electronics", 58.00, 19700, 9, False, 4.4, 356, "mild"),
    ("Shoe Storage Bench, 3-Tier Fabric", "Home & Kitchen", 52.99, 41200, 7, False, 4.2, 268, "steady"),
    ("Ergonomic Wrist Rest Set, Memory Foam", "Office Products", 23.50, 37400, 12, False, 4.3, 391, "steady"),
    ("Spice Rack Organiser, 4-Tier Countertop", "Home & Kitchen", 36.99, 49800, 5, False, 4.5, 186, "steady"),
    ("Reusable Produce Bags, Mesh 9-Pack", "Grocery & Gourmet Food", 15.99, 76200, 4, False, 4.6, 141, "steady"),
    ("Car Trunk Organiser, Collapsible", "Automotive", 32.99, 33100, 10, False, 4.4, 412, "mild"),
    ("Pet Grooming Glove, Double-Sided", "Pet Supplies", 18.75, 44900, 16, False, 4.2, 468, "steady"),
    ("Yoga Wheel, Cork Surface 12-Inch", "Sports & Outdoors", 46.00, 82600, 3, False, 4.7, 104, "seasonal"),
    ("Standing Desk Anti-Fatigue Mat", "Office Products", 61.50, 24300, 8, False, 4.5, 329, "steady"),
    ("Charcuterie Board Set with Slate Markers", "Home & Kitchen", 49.99, 38700, 6, False, 4.6, 243, "seasonal"),
    ("Toothbrush Sanitiser, UV Wall-Mounted", "Health & Household", 39.99, 68400, 4, False, 4.3, 157, "steady"),
    ("Laundry Sorter Cart, 3-Bag Rolling", "Home & Kitchen", 57.99, 29500, 11, False, 4.3, 374, "steady"),
    ("Sourdough Proofing Basket Kit", "Home & Kitchen", 28.50, 59300, 5, False, 4.8, 196, "seasonal"),
]


def _synthetic_rank_history(base_rank: int, shape: str, rng: random.Random) -> list[float]:
    """Build a plausible 12-month weekly sales-rank series.

    Lower rank = better selling. A seasonal product's rank improves sharply in
    its peak weeks and decays the rest of the year; a steady product wobbles
    around its baseline with noise only.
    """
    amplitude = {"steady": 0.05, "mild": 0.18, "seasonal": 0.55}.get(shape, 0.15)
    noise_level = {"steady": 0.04, "mild": 0.07, "seasonal": 0.10}.get(shape, 0.06)

    # Peak somewhere in the back third of the year for seasonal items.
    peak_week = rng.randint(40, 50) if shape == "seasonal" else rng.randint(0, 51)

    series: list[float] = []
    for week in range(52):
        phase = 2 * math.pi * ((week - peak_week) / 52.0)
        # cos peaks at the peak week; invert so rank *drops* (improves) there.
        seasonal_factor = 1.0 - amplitude * math.cos(phase)
        noise = rng.gauss(1.0, noise_level)
        rank = base_rank * seasonal_factor * noise
        series.append(max(rank, 1.0))

    return series


def demo_products(limit: int, seed: int = 20260910) -> list[dict]:
    """Return normalised product dicts in the same shape as `normalise_product`."""
    rng = random.Random(seed)
    products: list[dict] = []

    for index, fixture in enumerate(_FIXTURES[:limit]):
        (
            title,
            category,
            price,
            sales_rank,
            offer_count,
            amazon,
            rating,
            reviews,
            shape,
        ) = fixture

        products.append(
            {
                # Clearly fake ASIN namespace — these are not real listings.
                "asin": f"B0DEMO{index:04d}",
                "title": title,
                "price": price,
                "sales_rank": sales_rank,
                "offer_count": offer_count,
                "amazon_on_listing": amazon,
                "rating": rating,
                "review_count": reviews,
                "category": category,
                "rank_history": _synthetic_rank_history(sales_rank, shape, rng),
            }
        )

    return products


def filter_demo_products(products: list[dict], criteria) -> list[dict]:
    """Apply the user's filters to demo data so the form visibly does something."""
    kept = []
    for product in products:
        price = product.get("price") or 0
        rank = product.get("sales_rank") or 0
        offers = product.get("offer_count") or 0
        rating = product.get("rating") or 0
        reviews = product.get("review_count") or 0

        if not (criteria.min_price <= price <= criteria.max_price):
            continue
        if not (criteria.min_sales_rank <= rank <= criteria.max_sales_rank):
            continue
        if offers > criteria.max_offer_count:
            continue
        if rating < criteria.min_rating:
            continue
        if reviews > criteria.max_review_count:
            continue
        if criteria.category:
            wanted = criteria.category.strip().lower()
            actual = (product.get("category") or "").lower()
            if wanted and not wanted.isdigit() and wanted not in actual:
                continue
        kept.append(product)

    return kept
