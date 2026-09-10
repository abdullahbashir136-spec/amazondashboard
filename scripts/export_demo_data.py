"""Generate `demo-data.json` for the static (backend-less) preview build.

Runs the demo fixtures through the real scoring and RFQ pipeline and writes the
result next to the frontend. This is what the Netlify preview serves when there
is no FastAPI backend behind it.

Usage:
    python scripts/export_demo_data.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import demo as demo_data  # noqa: E402
from app.main import DEMO_NOTICE, _build_leads  # noqa: E402
from app.models import SearchRequest  # noqa: E402

OUTPUT = ROOT / "app" / "static" / "demo-data.json"

# Wide-open criteria so every fixture makes it into the export; the frontend
# applies the user's actual filters on top of this.
EXPORT_CRITERIA = SearchRequest(
    min_sales_rank=1,
    max_sales_rank=5_000_000,
    min_price=0,
    max_price=10_000,
    max_offer_count=200,
    min_rating=0,
    max_review_count=1_000_000,
    target_roi=50.0,
    target_quantity=500,
    limit=100,
)


def main() -> int:
    products = demo_data.demo_products(limit=len(demo_data._FIXTURES))
    leads = _build_leads(products, EXPORT_CRITERIA)

    payload = {
        "generated_by": "scripts/export_demo_data.py",
        "demo_mode": True,
        "preview_mode": True,
        "notice": DEMO_NOTICE,
        "baseline_target_roi": EXPORT_CRITERIA.target_roi,
        "baseline_target_quantity": EXPORT_CRITERIA.target_quantity,
        "results": leads,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"Wrote {len(leads)} scored demo leads -> {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
