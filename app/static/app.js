/* FBA Lead Finder — frontend.
 *
 * The browser never sees the Keepa API key. It only ever calls our own backend.
 *
 * Two runtime modes:
 *   1. Backend mode  — POST /api/search against the FastAPI service (normal).
 *   2. Preview mode  — when there's no backend (e.g. the static Netlify build),
 *      fall back to the pre-generated demo-data.json so the dashboard is still
 *      browsable. Clearly labelled; never presented as real data.
 */

// Point this at your deployed backend (e.g. "https://fba-lead-finder.onrender.com")
// to drive a hosted API from a static frontend. Empty string = same origin.
const API_BASE = "";

const form = document.getElementById("searchForm");
const runBtn = document.getElementById("runBtn");
const resetBtn = document.getElementById("resetBtn");
const resultsEl = document.getElementById("results");
const statusEl = document.getElementById("status");
const summaryEl = document.getElementById("summary");
const bannerEl = document.getElementById("banner");
const modePill = document.getElementById("modePill");
const filtersToggle = document.getElementById("filtersToggle");

let previewCache = null;

// Resolves to true/false once the health probe finishes. Search awaits it so a
// fast click can't race the probe. When false we skip the API entirely rather
// than trying to infer "no backend" from assorted 404/405/501 responses that
// different static hosts return for a POST.
let backendReady;

/* --- Filters collapse (saves vertical space on a phone) ----------------- */

filtersToggle.addEventListener("click", () => {
  const open = filtersToggle.getAttribute("aria-expanded") === "true";
  filtersToggle.setAttribute("aria-expanded", String(!open));
  form.hidden = open;
});

resetBtn.addEventListener("click", () => {
  form.reset();
  statusEl.hidden = true;
  summaryEl.hidden = true;
  resultsEl.innerHTML = "";
});

/* --- Search ------------------------------------------------------------ */

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  // Native validation failure blocks submit silently, which reads as a dead
  // button. Surface the reason instead.
  if (!form.checkValidity()) {
    form.reportValidity();
    const bad = [...form.elements].find((el) => el.willValidate && !el.checkValidity());
    if (bad) {
      showError(new AppError(
        `"${bad.name.replace(/_/g, " ")}" is not a valid value.`,
        bad.validationMessage,
      ));
    }
    return;
  }
  await runSearch();
});

function readCriteria() {
  const data = new FormData(form);
  const numeric = [
    "min_sales_rank", "max_sales_rank", "min_price", "max_price",
    "max_offer_count", "min_rating", "max_review_count",
    "target_roi", "target_quantity", "limit",
  ];

  const criteria = {};
  for (const key of numeric) {
    const raw = data.get(key);
    criteria[key] = raw === "" || raw === null ? 0 : Number(raw);
  }

  const category = (data.get("category") || "").toString().trim();
  criteria.category = category || null;
  return criteria;
}

async function runSearch() {
  const criteria = readCriteria();

  runBtn.disabled = true;
  runBtn.textContent = "Searching…";
  showStatus("Querying product data…");
  summaryEl.hidden = true;
  resultsEl.innerHTML = "";

  try {
    const payload = await fetchLeads(criteria);
    render(payload, criteria);
  } catch (err) {
    showError(err);
  } finally {
    runBtn.disabled = false;
    runBtn.textContent = "Run Search";
  }
}

async function fetchLeads(criteria) {
  // No backend behind this frontend (e.g. the static Netlify build).
  if ((await backendReady) === false) {
    return previewFallback(criteria);
  }

  let response;
  try {
    response = await fetch(`${API_BASE}/api/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(criteria),
    });
  } catch {
    // Network-level failure => backend went away since the health probe.
    return previewFallback(criteria);
  }

  let body;
  try {
    body = await response.json();
  } catch {
    throw new AppError("The server returned a response we couldn't read.", null,
      `HTTP ${response.status}`);
  }

  if (!response.ok) {
    // FastAPI/Pydantic validation errors come back as {detail: [{loc, msg}, ...]},
    // which doesn't match our own {error, hint} error shape.
    if (response.status === 422 && Array.isArray(body.detail)) {
      const issues = body.detail
        .map((d) => `${(d.loc || []).filter((p) => p !== "body").join(".")}: ${d.msg}`)
        .join("; ");
      throw new AppError("Some filter values were rejected by the server.", issues);
    }
    throw new AppError(body.error || "The search failed.", body.hint, body.detail);
  }

  return body;
}

class AppError extends Error {
  constructor(message, hint, detail) {
    super(message);
    this.hint = hint;
    this.detail = detail;
  }
}

/* --- Preview mode ------------------------------------------------------ */
/* Loads pre-scored demo data generated by the Python pipeline. ROI-dependent
 * figures are recomputed here because the user can change target ROI after the
 * export was generated — the formula below is identical to
 * scoring.max_sourcing_cost(). Keep the two in sync if either changes. */

async function previewFallback(criteria) {
  if (!previewCache) {
    const res = await fetch("/static/demo-data.json", { cache: "no-store" }).catch(() => null);
    if (!res || !res.ok) {
      throw new AppError(
        "No backend is reachable and no preview data is available.",
        "Run the FastAPI server locally with: uvicorn app.main:app --reload",
      );
    }
    previewCache = await res.json();
  }

  const matched = previewCache.results.filter((lead) => {
    const price = lead.price ?? 0;
    const rank = lead.sales_rank ?? 0;
    const offers = lead.offer_count ?? 0;
    const rating = lead.rating ?? 0;
    const reviews = lead.review_count ?? 0;

    if (price < criteria.min_price || price > criteria.max_price) return false;
    if (rank < criteria.min_sales_rank || rank > criteria.max_sales_rank) return false;
    if (offers > criteria.max_offer_count) return false;
    if (rating < criteria.min_rating) return false;
    if (reviews > criteria.max_review_count) return false;
    if (criteria.category) {
      const want = criteria.category.toLowerCase();
      if (!(lead.category || "").toLowerCase().includes(want)) return false;
    }
    return true;
  }).slice(0, criteria.limit);

  const results = matched.map((lead) => recomputeForRoi(lead, criteria));

  return {
    meta: {
      demo_mode: true,
      preview_mode: true,
      result_count: results.length,
      candidates_found: matched.length,
      target_roi: criteria.target_roi,
      target_quantity: criteria.target_quantity,
      notice: previewCache.notice,
    },
    results,
  };
}

function recomputeForRoi(lead, criteria) {
  const copy = structuredClone(lead);
  const price = copy.price;
  const feeTotal = copy.fees?.total ?? 0;

  // Mirrors scoring.max_sourcing_cost() — fees don't depend on ROI, so this is
  // an exact recomputation rather than an approximation.
  let ceiling = null;
  const net = (price ?? 0) - feeTotal;
  if (price && net > 0 && criteria.target_roi > 0) {
    ceiling = round2(net / (1 + criteria.target_roi / 100));
  }

  copy.max_sourcing_cost = ceiling;
  copy.target_unit_price = ceiling === null ? null : round2(ceiling * 0.85);

  if (copy.rfq) {
    copy.rfq = rebuildRfq(copy, criteria.target_quantity);
  }
  return copy;
}

/* Mirrors rfq.build_rfq()'s variable sections. The prose lives in rfq.py — this
 * only substitutes the quantity and the two ROI-dependent price figures. */
function rebuildRfq(lead, quantity) {
  const rfq = lead.rfq;
  let body = rfq.body;

  body = body.replace(/Opening order: [\d,]+ units/,
    `Opening order: ${quantity.toLocaleString()} units`);

  if (lead.target_unit_price !== null && lead.max_sourcing_cost !== null) {
    body = body.replace(/Target unit price: \$[\d.]+ USD/,
      `Target unit price: $${lead.target_unit_price.toFixed(2)} USD`);
    body = body.replace(/Maximum unit price we can work with: \$[\d.]+ USD/,
      `Maximum unit price we can work with: $${lead.max_sourcing_cost.toFixed(2)} USD`);
    body = body.replace(/\(Above \$[\d.]+ the numbers/,
      `(Above $${lead.max_sourcing_cost.toFixed(2)} the numbers`);
    body = body.replace(/so please quote with that ceiling in mind\.\)/,
      "so please quote with that ceiling in mind.)");
  }

  const subject = rfq.subject.replace(/— [\d,]+ units/, `— ${quantity.toLocaleString()} units`);

  return {
    ...rfq,
    subject,
    body,
    target_quantity: quantity,
    target_unit_price: lead.target_unit_price,
    ceiling_unit_price: lead.max_sourcing_cost,
  };
}

const round2 = (n) => Math.round(n * 100) / 100;

/* --- Rendering --------------------------------------------------------- */

function render(payload, criteria) {
  const { meta, results } = payload;

  statusEl.hidden = true;
  setMode(meta);

  if (!results.length) {
    summaryEl.hidden = true;
    resultsEl.innerHTML = `<div class="empty">
      <p><strong>No products matched these filters.</strong></p>
      <p>Try widening the price or sales-rank range, or raising the max offer count.</p>
    </div>`;
    return;
  }

  summaryEl.hidden = false;
  summaryEl.innerHTML = [
    chip("Leads", results.length),
    chip("Candidates", meta.candidates_found),
    chip("Target ROI", `${meta.target_roi}%`),
    chip("Order qty", meta.target_quantity.toLocaleString()),
    meta.tokens_left != null ? chip("Keepa tokens left", meta.tokens_left) : "",
  ].join("");

  resultsEl.innerHTML = results.map((lead, i) => card(lead, i)).join("");
  wireCards();
}

function chip(label, value) {
  return `<span class="chip">${label} <b>${value}</b></span>`;
}

function setMode(meta) {
  modePill.hidden = false;
  if (meta.demo_mode) {
    modePill.textContent = meta.preview_mode ? "Preview" : "Demo";
    modePill.className = "mode-pill demo";
  } else {
    modePill.textContent = "Live";
    modePill.className = "mode-pill live";
  }

  if (meta.notice) {
    bannerEl.hidden = false;
    bannerEl.innerHTML = `<strong>⚠️ Sample data.</strong> ${escapeHtml(meta.notice)}`;
  } else {
    bannerEl.hidden = true;
  }
}

function scoreClass(score) {
  if (score <= 0.33) return "good";
  if (score <= 0.66) return "warn";
  return "bad";
}

function card(lead, index) {
  const price = lead.price != null ? `$${lead.price.toFixed(2)}` : "—";
  const ceiling = lead.max_sourcing_cost != null
    ? `$${lead.max_sourcing_cost.toFixed(2)}`
    : "—";
  const target = lead.target_unit_price != null
    ? `$${lead.target_unit_price.toFixed(2)}`
    : "—";

  const amazonFlag = lead.amazon_on_listing
    ? `<span class="flag amazon">Amazon on listing</span>` : "";
  const confFlag = lead.seasonality_confidence === "low"
    ? `<span class="flag lowconf">low confidence</span>` : "";

  return `
<article class="card" data-index="${index}">
  <div class="card-head">
    <span class="rank-badge">#${index + 1}</span>
    <h3><a href="${escapeAttr(lead.amazon_url)}" target="_blank" rel="noopener">${escapeHtml(lead.title)}</a></h3>
    <p class="asin-line">${escapeHtml(lead.asin)}${amazonFlag}</p>
  </div>

  <div class="metrics">
    <div class="metric"><span class="k">Price</span><span class="v">${price}</span></div>
    <div class="metric"><span class="k">Sales rank</span><span class="v">${lead.sales_rank != null ? lead.sales_rank.toLocaleString() : "—"}</span></div>
    <div class="metric"><span class="k">Offers</span><span class="v ${lead.offer_count > 15 ? "bad" : ""}">${lead.offer_count ?? "—"}</span></div>
    <div class="metric"><span class="k">Competition</span><span class="v ${scoreClass(lead.competition_score)}">${lead.competition_score.toFixed(2)}</span></div>
    <div class="metric"><span class="k">Seasonality</span><span class="v ${scoreClass(lead.seasonality_score)}">${lead.seasonality_score.toFixed(2)}${confFlag}</span></div>
    <div class="metric ceiling"><span class="k">Max cost</span><span class="v good">${ceiling} <small>/unit</small></span></div>
  </div>

  <div class="card-foot">
    <button class="rfq-toggle" type="button" aria-expanded="false">
      Show supplier RFQ draft — target ${target}/unit
    </button>
    <div class="rfq-body" hidden>
      <p class="rfq-subject">Subject: <b>${escapeHtml(lead.rfq?.subject || "")}</b></p>
      <textarea readonly>${escapeHtml(lead.rfq?.body || "")}</textarea>
      <div class="copy-row">
        <button class="copy-btn" type="button">Copy</button>
        <span class="copy-note">Review before sending — nothing is sent for you.</span>
      </div>
    </div>
  </div>
</article>`;
}

function wireCards() {
  resultsEl.querySelectorAll(".rfq-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      const body = btn.nextElementSibling;
      const open = !body.hidden;
      body.hidden = open;
      btn.setAttribute("aria-expanded", String(!open));
      btn.textContent = open
        ? btn.textContent.replace("Hide", "Show")
        : btn.textContent.replace("Show", "Hide");
    });
  });

  resultsEl.querySelectorAll(".copy-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const textarea = btn.closest(".rfq-body").querySelector("textarea");
      try {
        await navigator.clipboard.writeText(textarea.value);
        flash(btn, "Copied ✓");
      } catch {
        // Clipboard API needs a secure context; select the text instead.
        textarea.select();
        flash(btn, "Select + copy");
      }
    });
  });
}

function flash(btn, message) {
  const original = btn.textContent;
  btn.textContent = message;
  setTimeout(() => { btn.textContent = original; }, 1600);
}

/* --- Status / errors --------------------------------------------------- */

function showStatus(message) {
  statusEl.hidden = false;
  statusEl.className = "status";
  statusEl.textContent = message;
}

function showError(err) {
  statusEl.hidden = false;
  statusEl.className = "status error";
  const hint = err.hint ? `<div class="hint-line">${escapeHtml(err.hint)}</div>` : "";
  const detail = err.detail ? `<div class="hint-line">${escapeHtml(err.detail)}</div>` : "";
  statusEl.innerHTML = `<strong>${escapeHtml(err.message)}</strong>${hint}${detail}`;
}

/* --- Escaping ---------------------------------------------------------- */

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

const escapeAttr = escapeHtml;

/* --- Boot -------------------------------------------------------------- */

backendReady = (async function init() {
  try {
    const res = await fetch(`${API_BASE}/api/health`);
    if (res.ok) {
      // A static host may answer /api/health with its 200 HTML fallback, so
      // only trust a response that actually parses as our health payload.
      const health = await res.json();
      if (health && health.status === "ok") {
        setMode({ demo_mode: health.demo_mode, notice: null });
        if (health.demo_mode) {
          bannerEl.hidden = false;
          bannerEl.innerHTML = `<strong>⚠️ Demo mode.</strong> No Keepa API key is
            configured, so searches return invented sample products. Set
            <code>KEEPA_API_KEY</code> to switch to live data.`;
        }
        return true;
      }
    }
  } catch {
    /* fall through to preview */
  }

  setMode({ demo_mode: true, preview_mode: true, notice: null });
  bannerEl.hidden = false;
  bannerEl.innerHTML = `<strong>⚠️ Preview mode.</strong> This is the static
    frontend with no backend attached — results come from a bundled sample file.
    Deploy the FastAPI service and set a Keepa API key for live data.`;
  return false;
})();
