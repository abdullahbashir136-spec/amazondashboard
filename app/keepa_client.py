"""Keepa API access.

Keepa's official REST API (https://keepa.com/#!api) is the ONLY Amazon data
source in this project. The `keepa` PyPI package is a community-maintained
client for that documented API — it is not a scraper, and nothing here touches
Amazon's, Keepa's, SellerAmp's, or Alibaba's web front-ends.

All calls run server-side. The API key never leaves this process.

Keepa's response schema is sparse and varies by product and category, so every
field read below goes through defensive `.get()` access with explicit fallbacks.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

# Keepa encodes "no value" as -1 across price, rank, rating, and count fields.
KEEPA_NULL = -1

# Keepa returns prices as integer cents.
CENTS = 100.0

# Product data endpoint accepts up to 100 ASINs per call. Batching matters —
# tokens are the scarce resource on a Keepa subscription.
BATCH_SIZE = 100

# Keepa's CSV index for the Amazon-direct offer series. A non-null value in the
# recent tail means Amazon itself is/was selling the item.
CSV_AMAZON_INDEX = 0
CSV_SALES_RANK_INDEX = 3


class KeepaError(RuntimeError):
    """Raised for any Keepa-side failure we want surfaced to the user."""

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.hint = hint


class KeepaClient:
    """Thin wrapper over the `keepa` package with defensive normalisation."""

    def __init__(self, api_key: str, domain: str = "US"):
        if not api_key:
            raise KeepaError(
                "No Keepa API key configured.",
                hint="Set KEEPA_API_KEY in your environment or .env file. "
                "Get a key at https://keepa.com/#!api",
            )
        self.domain = domain
        try:
            import keepa  # imported lazily so demo mode works without the dep
        except ImportError as exc:  # pragma: no cover
            raise KeepaError(
                "The `keepa` package is not installed.",
                hint="Run: pip install -r requirements.txt",
            ) from exc

        try:
            self._api = keepa.Keepa(api_key)
        except Exception as exc:
            raise KeepaError(
                f"Could not authenticate with Keepa: {exc}",
                hint="Check that KEEPA_API_KEY is a valid, active key.",
            ) from exc

    @property
    def tokens_left(self) -> int | None:
        return getattr(self._api, "tokens_left", None)

    # --- Discovery --------------------------------------------------------

    def find_candidates(self, criteria, limit: int) -> list[str]:
        """Run a Keepa Product Finder query and return matching ASINs.

        This is the bulk discovery call — one request returns many ASINs, which
        is far cheaper in tokens than probing products individually.
        """
        params = build_finder_params(criteria, limit)
        log.info("Keepa product_finder params: %s", params)
        try:
            asins = self._api.product_finder(params, domain=self.domain)
        except Exception as exc:
            raise KeepaError(
                f"Keepa Product Finder request failed: {exc}",
                hint="This often means the filter combination is invalid or your "
                "token balance is exhausted. Try widening the filters.",
            ) from exc

        return list(asins or [])[:limit]

    # --- Product detail ---------------------------------------------------

    def fetch_products(self, asins: list[str]) -> list[dict]:
        """Pull full price/rank/offer history for ASINs, batched to save tokens."""
        if not asins:
            return []

        products: list[dict] = []
        for start in range(0, len(asins), BATCH_SIZE):
            batch = asins[start : start + BATCH_SIZE]
            try:
                result = self._api.query(
                    batch,
                    domain=self.domain,
                    history=True,
                    stats=90,
                    offers=None,
                )
            except Exception as exc:
                raise KeepaError(
                    f"Keepa product lookup failed: {exc}",
                    hint="If this mentions tokens, wait for your balance to refill.",
                ) from exc
            products.extend(result or [])

        return products


# --- Query building -------------------------------------------------------


def build_finder_params(criteria, limit: int) -> dict:
    """Translate our filter criteria into Keepa Product Finder parameters.

    Keepa expects prices in cents and ratings on a 0-50 scale (4.3 stars -> 43).
    Parameter names follow Keepa's `current_<CSV_NAME>_gte/_lte` convention.
    """
    params: dict = {
        "current_SALES_gte": int(criteria.min_sales_rank),
        "current_SALES_lte": int(criteria.max_sales_rank),
        "current_NEW_gte": int(round(criteria.min_price * CENTS)),
        "current_NEW_lte": int(round(criteria.max_price * CENTS)),
        "current_COUNT_NEW_lte": int(criteria.max_offer_count),
        "current_COUNT_REVIEWS_lte": int(criteria.max_review_count),
        "perPage": int(limit),
        "page": 0,
    }

    if criteria.min_rating and criteria.min_rating > 0:
        params["current_RATING_gte"] = int(round(criteria.min_rating * 10))

    if criteria.category:
        category = str(criteria.category).strip()
        if category.isdigit():
            params["rootCategory"] = int(category)
        else:
            # Free-text category falls back to a title match; Keepa's numeric
            # rootCategory ids are more reliable when you know them.
            params["title"] = category

    return params


# --- Normalisation --------------------------------------------------------


def _clean(value, scale: float = 1.0):
    """Keepa uses -1 for 'unknown'. Convert to None, optionally rescaling."""
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric <= KEEPA_NULL:
        return None
    return numeric / scale if scale != 1.0 else numeric


def _last_valid(series) -> float | None:
    """Last non-null entry in a Keepa CSV series."""
    if series is None:
        return None
    try:
        values = list(series)
    except TypeError:
        return None
    for value in reversed(values):
        cleaned = _clean(value)
        if cleaned is not None:
            return cleaned
    return None


def extract_rank_history(product: dict, months: int = 12) -> list[float]:
    """Pull the trailing sales-rank series used for the seasonality score.

    The `keepa` package parses history into `product["data"]` with paired
    `<KEY>` value arrays and `<KEY>_time` datetime arrays when `history=True`.
    Key naming has varied across versions, so try the known variants and fall
    back to the raw `csv` block.
    """
    data = product.get("data") or {}

    for value_key, time_key in (
        ("SALES", "SALES_time"),
        ("salesRank", "salesRank_time"),
        ("SALES_RANK", "SALES_RANK_time"),
    ):
        values = data.get(value_key)
        if values is None:
            continue

        times = data.get(time_key)
        cutoff = datetime.now(timezone.utc) - timedelta(days=30 * months)

        series: list[float] = []
        try:
            paired = list(zip(times, values)) if times is not None else []
        except TypeError:
            paired = []

        if paired:
            for timestamp, rank in paired:
                cleaned = _clean(rank)
                if cleaned is None:
                    continue
                moment = _as_utc(timestamp)
                if moment is None or moment >= cutoff:
                    series.append(cleaned)
        else:
            series = [c for c in (_clean(v) for v in values) if c is not None]

        if series:
            # Cap the sample count — a multi-year daily series is far more
            # resolution than a coefficient of variation needs.
            return series[-400:]

    # Fallback: raw csv block, index 3 is the sales-rank series as
    # [time, value, time, value, ...].
    csv = product.get("csv")
    if isinstance(csv, (list, tuple)) and len(csv) > CSV_SALES_RANK_INDEX:
        raw = csv[CSV_SALES_RANK_INDEX]
        if raw:
            values = [_clean(v) for v in list(raw)[1::2]]
            return [v for v in values if v is not None][-400:]

    return []


def _as_utc(timestamp) -> datetime | None:
    """Coerce whatever the keepa package hands back into an aware datetime."""
    if timestamp is None:
        return None
    if isinstance(timestamp, datetime):
        return timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)
    # numpy.datetime64 and friends expose .astype / .item()
    for attr in ("to_pydatetime", "item"):
        converter = getattr(timestamp, attr, None)
        if callable(converter):
            try:
                candidate = converter()
            except Exception:
                continue
            if isinstance(candidate, datetime):
                return candidate if candidate.tzinfo else candidate.replace(tzinfo=timezone.utc)
    return None


def detect_amazon_on_listing(product: dict) -> bool:
    """True when Amazon itself appears to be selling this item.

    Prefer the parsed AMAZON history; fall back to raw csv index 0. A recent
    non-null Amazon price means Amazon is (or very recently was) on the listing.
    """
    data = product.get("data") or {}
    for key in ("AMAZON", "amazon"):
        series = data.get(key)
        if series is not None:
            recent = list(series)[-30:]
            if any(_clean(v) is not None for v in recent):
                return True
            return False

    csv = product.get("csv")
    if isinstance(csv, (list, tuple)) and len(csv) > CSV_AMAZON_INDEX:
        raw = csv[CSV_AMAZON_INDEX]
        if raw:
            recent_values = list(raw)[1::2][-30:]
            return any(_clean(v) is not None for v in recent_values)

    return False


def normalise_product(product: dict) -> dict:
    """Flatten a raw Keepa product into the shape `scoring.score_product` wants.

    Keepa omits fields freely depending on product and category, so this is all
    best-effort with explicit None fallbacks.
    """
    stats = product.get("stats") or {}

    price = _first_present(
        _clean(_index(stats.get("current"), 1), CENTS),   # NEW price
        _clean(_index(stats.get("current"), 0), CENTS),   # AMAZON price
        _clean(_index(stats.get("current"), 18), CENTS),  # BUY_BOX_SHIPPING
        _last_valid((product.get("data") or {}).get("NEW")),
    )

    sales_rank = _first_present(
        _clean(_index(stats.get("current"), CSV_SALES_RANK_INDEX)),
        _clean(product.get("salesRankReference")),
    )

    offer_count = _first_present(
        _clean(product.get("offerCountNew")),
        _clean(_index(stats.get("current"), 11)),  # COUNT_NEW
        _clean(stats.get("offerCountNew")),
    )

    rating = _clean(_index(stats.get("current"), 16), 10.0)  # RATING, 0-50 scale
    review_count = _clean(_index(stats.get("current"), 17))  # COUNT_REVIEWS

    category = product.get("categoryTree")
    if isinstance(category, list) and category:
        first = category[0]
        category = first.get("name") if isinstance(first, dict) else str(first)
    elif not isinstance(category, str):
        category = product.get("productGroup") or product.get("rootCategory")
        category = str(category) if category is not None else None

    return {
        "asin": product.get("asin") or "",
        "title": product.get("title") or "(untitled)",
        "price": round(price, 2) if price is not None else None,
        "sales_rank": int(sales_rank) if sales_rank is not None else None,
        "offer_count": int(offer_count) if offer_count is not None else None,
        "amazon_on_listing": detect_amazon_on_listing(product),
        "rating": round(rating, 1) if rating is not None else None,
        "review_count": int(review_count) if review_count is not None else None,
        "category": category,
        "rank_history": extract_rank_history(product),
    }


def _index(sequence, position: int):
    """Safely index into a possibly-missing, possibly-short sequence."""
    if sequence is None:
        return None
    try:
        return sequence[position]
    except (IndexError, KeyError, TypeError):
        return None


def _first_present(*values):
    for value in values:
        if value is not None:
            return value
    return None
