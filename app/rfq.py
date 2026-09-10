"""Alibaba RFQ draft generation.

IMPORTANT — this module produces TEXT ONLY. It never contacts a supplier, never
posts to Alibaba, and never takes any action with financial or contractual
consequences. Every draft is something the user copies, reviews, edits, and
sends themselves.

Alibaba has no public product-search API for outside buyers, and scraping their
web app violates their ToS — so RFQ support in v1 is deliberately limited to
generating text for manual use.
"""

from __future__ import annotations

from .scoring import ScoredProduct

# The ASIN goes in as a spec reference, not a shareable link — you generally do
# not want to hand a supplier the exact listing you intend to compete on.
SUPPLIER_ASKS = [
    "Unit price at the quantity above, plus your price breaks at higher volumes",
    "Sample cost and sample lead time",
    "Production lead time for a full order",
    "Business license / verification status (Gold Supplier, Trade Assurance, audit reports)",
    "Any relevant certifications for this product type (CE / FCC / RoHS / FDA as applicable)",
    "Private-label and customisation options — logo, packaging, colourways, MOQ for each",
    "Packaging dimensions and unit weight (needed for freight and FBA fee calculation)",
    "FOB port and whether you can quote DDP to a US Amazon FBA warehouse",
]


def build_rfq(lead: ScoredProduct, target_quantity: int) -> dict:
    """Build a subject line + body for a supplier inquiry about this product type."""
    subject = f"RFQ: {_product_descriptor(lead)} — {target_quantity:,} units, private label"

    if lead.target_unit_price is not None and lead.max_sourcing_cost is not None:
        pricing_block = (
            f"Target unit price: ${lead.target_unit_price:.2f} USD\n"
            f"Maximum unit price we can work with: ${lead.max_sourcing_cost:.2f} USD\n"
            f"(Above ${lead.max_sourcing_cost:.2f} the numbers stop working for us, "
            f"so please quote with that ceiling in mind.)"
        )
    else:
        pricing_block = (
            "Target unit price: to be confirmed — please quote your best price at "
            "this volume.\n"
            "(Our internal ceiling could not be calculated for this product; treat "
            "pricing as open.)"
        )

    asks = "\n".join(f"{i}. {ask}" for i, ask in enumerate(SUPPLIER_ASKS, start=1))

    body = f"""Hello,

We are a US-based Amazon seller sourcing for an upcoming private-label launch and
would like a quotation.

PRODUCT
{_product_descriptor(lead)}
Internal spec reference: {lead.asin}
(Reference only — we are looking for an equivalent product to your own
specification, not this exact branded item.)

QUANTITY
Opening order: {target_quantity:,} units
We expect to reorder on a regular cycle if the first run goes well.

PRICING
{pricing_block}

PLEASE INCLUDE IN YOUR REPLY
{asks}

If you can meet the target price at this volume we would like to move to samples
quickly. Please also let us know your standard payment terms.

Thank you,
"""

    return {
        "subject": subject,
        "body": body.strip(),
        "target_quantity": target_quantity,
        "target_unit_price": lead.target_unit_price,
        "ceiling_unit_price": lead.max_sourcing_cost,
        "disclaimer": (
            "Draft only — review and send manually. Pricing is based on estimated "
            "Amazon fees, not authoritative fee data."
        ),
    }


def _product_descriptor(lead: ScoredProduct) -> str:
    """Trim the Amazon title down to something usable as a product description.

    Amazon titles are keyword-stuffed; sending one verbatim to a supplier reads
    badly and leaks the exact listing. Take the leading clause only.
    """
    title = (lead.title or "").strip()
    if not title or title == "(untitled)":
        return lead.category or "Product"

    for separator in (" - ", " | ", ", "):
        if separator in title:
            title = title.split(separator)[0]
            break

    words = title.split()
    if len(words) > 12:
        title = " ".join(words[:12])

    return title.strip(" -|,")
