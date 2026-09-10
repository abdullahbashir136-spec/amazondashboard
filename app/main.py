"""FBA Lead Finder — FastAPI backend.

The frontend only ever talks to this service. The Keepa API key is read from the
environment here and never serialised into any response, so it cannot reach the
browser.

This service surfaces leads and drafts text. It never places an order, contacts
a supplier, or takes any action with financial or contractual consequences.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import demo as demo_data
from .keepa_client import KeepaClient, KeepaError, normalise_product
from .models import SearchMeta, SearchRequest, SearchResponse
from .rfq import build_rfq
from .scoring import score_product, sort_leads

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("fba-lead-finder")

STATIC_DIR = Path(__file__).parent / "static"

DOMAIN_BY_ID = {
    "1": "US", "2": "GB", "3": "DE", "4": "FR",
    "5": "JP", "6": "CA", "8": "IT", "9": "ES", "10": "IN",
}

DEMO_NOTICE = (
    "Demo mode — no Keepa API key configured. These products are invented and "
    "the ASINs are not real listings. Scores, fee estimates, and sourcing "
    "ceilings are produced by the real scoring model running on fabricated "
    "inputs. Do not treat anything on this screen as a sourcing decision."
)

app = FastAPI(
    title="FBA Lead Finder",
    version="0.1.0",
    description="Keepa-powered sourcing dashboard. Official APIs only — no scraping.",
)


def _keepa_key() -> str | None:
    key = (os.getenv("KEEPA_API_KEY") or "").strip()
    # Guard against the .env.example placeholder being copied across verbatim.
    if not key or key == "your_keepa_api_key_here":
        return None
    return key


def _demo_forced() -> bool:
    return (os.getenv("DEMO_MODE") or "").strip().lower() in {"1", "true", "yes", "on"}


def _is_demo_mode() -> bool:
    return _demo_forced() or _keepa_key() is None


def _domain() -> str:
    return DOMAIN_BY_ID.get((os.getenv("KEEPA_DOMAIN") or "1").strip(), "US")


@app.get("/api/health")
def health() -> dict:
    """Cheap liveness probe that also reports which mode the service is in."""
    return {
        "status": "ok",
        "version": app.version,
        "demo_mode": _is_demo_mode(),
        "keepa_key_configured": _keepa_key() is not None,
        "domain": _domain(),
    }


@app.post("/api/search", response_model=SearchResponse)
def search(request: SearchRequest) -> JSONResponse:
    """Find candidate products, score them, and draft an RFQ for each."""
    criteria = request.normalised()

    if _is_demo_mode():
        return _demo_response(criteria)

    try:
        client = KeepaClient(_keepa_key(), domain=_domain())
        asins = client.find_candidates(criteria, criteria.limit)

        if not asins:
            return JSONResponse(
                status_code=200,
                content=SearchResponse(
                    meta=SearchMeta(
                        demo_mode=False,
                        result_count=0,
                        candidates_found=0,
                        target_roi=criteria.target_roi,
                        target_quantity=criteria.target_quantity,
                        tokens_left=client.tokens_left,
                        notice="No products matched these filters. Try widening the "
                        "price or sales-rank range, or raising the max offer count.",
                    ),
                    results=[],
                ).model_dump(),
            )

        raw_products = client.fetch_products(asins)
        leads = _build_leads(
            [normalise_product(p) for p in raw_products],
            criteria,
        )

        return JSONResponse(
            status_code=200,
            content=SearchResponse(
                meta=SearchMeta(
                    demo_mode=False,
                    result_count=len(leads),
                    candidates_found=len(asins),
                    target_roi=criteria.target_roi,
                    target_quantity=criteria.target_quantity,
                    tokens_left=client.tokens_left,
                ),
                results=leads,
            ).model_dump(),
        )

    except KeepaError as exc:
        log.warning("Keepa error: %s", exc)
        return JSONResponse(
            status_code=502,
            content={"error": str(exc), "hint": exc.hint},
        )
    except Exception as exc:  # noqa: BLE001 - surface anything unexpected to the UI
        log.exception("Unexpected error during search")
        return JSONResponse(
            status_code=500,
            content={
                "error": "Unexpected error while running the search.",
                "detail": str(exc),
                "hint": "Check the server logs for a full traceback.",
            },
        )


def _demo_response(criteria: SearchRequest) -> JSONResponse:
    products = demo_data.demo_products(limit=len(demo_data._FIXTURES))
    matched = demo_data.filter_demo_products(products, criteria)
    leads = _build_leads(matched[: criteria.limit], criteria)

    notice = DEMO_NOTICE
    if not leads:
        notice = (
            "Demo mode — no products in the sample set matched these filters. "
            "Try widening the price or sales-rank range. " + DEMO_NOTICE
        )

    return JSONResponse(
        status_code=200,
        content=SearchResponse(
            meta=SearchMeta(
                demo_mode=True,
                result_count=len(leads),
                candidates_found=len(matched),
                target_roi=criteria.target_roi,
                target_quantity=criteria.target_quantity,
                notice=notice,
            ),
            results=leads,
        ).model_dump(),
    )


def _build_leads(normalised: list[dict], criteria: SearchRequest) -> list[dict]:
    """Score, sort, and attach an RFQ draft to every product."""
    scored = [score_product(p, criteria.target_roi) for p in normalised]
    ordered = sort_leads(scored)

    payload = []
    for lead in ordered:
        lead.rfq = build_rfq(lead, criteria.target_quantity)
        payload.append(lead.as_dict())
    return payload


# --- Static frontend ------------------------------------------------------
# Mounted last so /api routes take precedence.

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")
