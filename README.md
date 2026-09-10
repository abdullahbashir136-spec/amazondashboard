# FBA Lead Finder

A small self-hosted dashboard for Amazon FBA product research. Set your filters,
hit one button, and get back scored sourcing leads with a drafted supplier
inquiry for each one. Built mobile-first — it's meant to be opened from a phone.

For every candidate product it computes:

- **Competition score** (0–1, lower is better) — active offer count, with a flat
  penalty when Amazon itself is on the listing.
- **Seasonality score** (0–1, lower is better) — coefficient of variation of the
  trailing 12-month sales rank. Steady year-round = low = good.
- **Max sourcing cost** — the highest per-unit price you could pay a supplier and
  still hit your target ROI. This is the number that actually matters when
  negotiating, and it becomes the ceiling in the RFQ draft.

Results sort best-opportunity-first.

---

## Why Keepa's API and not SellerAmp

SellerAmp, Keepa's website, Amazon's retail site, and Alibaba all prohibit
automated access in their Terms of Service, and Amazon actively blocks and bans
scrapers. Getting your seller account banned to save a subscription fee is a bad
trade.

The [Keepa API](https://keepa.com/#!api) is the official, documented, paid REST
API for exactly this data — it's the legitimate equivalent of what SellerAmp
surfaces. **This project only talks to official APIs.** There is no scraping code
here and none should be added.

The `keepa` PyPI package used here is a community-maintained client for that
official API, not a scraper.

---

## Safety properties

These are deliberate design constraints, not incidental:

- **Your API key never reaches the browser.** All Keepa calls are server-side.
  The frontend only ever calls this app's own backend.
- **Nothing is ever sent or spent automatically.** The app surfaces leads and
  drafts text. It never places an order, contacts a supplier, or takes any
  action with financial or contractual consequences. Every RFQ is a draft you
  copy, review, edit, and send yourself.
- **Fee figures are estimates and labelled as such.** See below.

### ⚠️ About the fee numbers

Referral fees come from a hand-maintained lookup table and the FBA fulfilment fee
is a single flat `$5.50` placeholder that ignores size tier and weight entirely.
**Every sourcing ceiling in this app inherits that approximation.** Verify against
[Amazon's fee schedule](https://sell.amazon.com/pricing) before committing money.

All of it lives in one function — `estimate_fees()` in [`app/fees.py`](app/fees.py)
— so swapping in real SP-API data later is a single-file change.

---

## Running locally

Requires Python 3.11+.

```bash
python -m venv .venv
```

```bash
.venv\Scripts\activate
```

```bash
pip install -r requirements.txt
```

Copy the example config and add your key:

```bash
copy .env.example .env
```

Then edit `.env` and set `KEEPA_API_KEY` to your key from
<https://keepa.com/#!api>. Start the server:

```bash
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>.

### Demo mode

**With no `KEEPA_API_KEY` set, the app runs in demo mode** and returns invented
sample products instead of failing. The ASINs are fake and the market data is
fabricated — but the scores, fee estimates, and sourcing ceilings are produced by
the real scoring model running on those fabricated inputs, so the pipeline is
genuinely exercised. A persistent banner makes this obvious on screen.

This is how you develop the UI without burning Keepa tokens. Force it on with a
real key present by setting `DEMO_MODE=1`.

---

## Deploying

### Backend (Render) — needed for live Keepa data

1. Push this repo to GitHub.
2. On [Render](https://render.com): **New → Web Service**, connect the repo.
3. Settings:
   - **Runtime:** Python 3
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
     (or leave blank — the included `Procfile` declares this.)
4. **Environment → Add Environment Variable:** `KEEPA_API_KEY` = your key.
   Set it in Render's dashboard, never in the repo.
5. Deploy. The dashboard is served at the service root.

Render's free tier sleeps after inactivity, so the first request after a quiet
spell takes ~30 seconds to wake.

### Frontend (Netlify) — static preview only

Netlify can't run the Python backend. A Netlify deploy serves the dashboard in
**preview mode**: it falls back to the bundled `demo-data.json` and shows a
banner saying so. Useful for looking at the UI on your phone; not useful for real
sourcing.

`netlify.toml` is already configured — connect the repo in the Netlify dashboard
and it builds automatically.

To point the Netlify frontend at a live Render backend instead, set `API_BASE` at
the top of [`app/static/app.js`](app/static/app.js) to your Render URL, and add a
CORS middleware to `app/main.py` allowing that origin.

Regenerate the preview data after changing the scoring model:

```bash
python scripts/export_demo_data.py
```

---

## Project layout

```
app/
  main.py          FastAPI app, routes, demo-mode switch
  keepa_client.py  Keepa API access + defensive response normalisation
  scoring.py       competition / seasonality / ROI ceiling
  fees.py          fee estimation — THE ONLY PLACE FEES ARE COMPUTED
  rfq.py           supplier inquiry drafting (text only, never sends)
  models.py        request/response schemas
  demo.py          synthetic fixtures for demo mode
  static/          frontend (no build step)
scripts/
  export_demo_data.py   regenerates static/demo-data.json
```

### API

`GET /api/health` — liveness, plus which mode the service is in.

`POST /api/search` — body:

```json
{
  "min_sales_rank": 1000, "max_sales_rank": 100000,
  "min_price": 15, "max_price": 70,
  "max_offer_count": 10, "min_rating": 4.0, "max_review_count": 500,
  "category": null, "target_roi": 50, "target_quantity": 500, "limit": 25
}
```

Discovery uses Keepa's Product Finder (one bulk call), then product history is
fetched in batches of 100 ASINs to conserve tokens.

---

## Roadmap

Explicitly **not** built yet:

- **Real SP-API fee data.** Replace `estimate_fees()` with Amazon's Product Fees
  endpoint for authoritative per-ASIN numbers. Requires a registered seller
  account and a developer app. This is the highest-value next step — every
  sourcing ceiling currently rests on a placeholder.
- **Persistence.** v1 is stateless; every search is a fresh query. A small
  database would enable saved leads, search history, and caching Keepa responses
  to cut token spend on repeat queries.
- **Alibaba supplier-side automation.** Alibaba has no public product-search API
  for outside buyers, and scraping it violates their ToS. Any integration here is
  a deliberate later decision, not a default — v1 generates RFQ text you paste in
  yourself.
- **Better seasonality modelling.** Coefficient of variation catches "swings a
  lot" but can't distinguish a Christmas spike from a product that's simply
  volatile. Detecting an annual period would be a real improvement.
