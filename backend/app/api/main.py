"""CreditLens FastAPI app.

Run:  uvicorn backend.app.api.main:app --reload   (from repo root)
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .. import replay, store
from ..documents import pdf_extract, sec_search, uploads
from ..documents.sec_client import SECError
from ..features.universe_rules import excluded_sic
from ..finance import credit_extras
from ..finance import peers as peer_lib
from ..documents.xbrl import CompanyYear, build_company_years, engine_inputs
from ..finance.metrics import compute_all
from ..memos import service as memo_service
from ..memos.pdf import render_pdf
from ..memos.writer import llm_status
from ..models import risk as risk_service
from ..models.inference import ARTIFACT_DIR
from ..scenarios.snapshot import credit_baseline, make_snapshot
from ..scenarios.loan import (DEFAULT_CASES, ENGINE_VERSION, Baseline, Covenants, Facility, FXBlocked, ScenarioInputError, Shock,
                               amortization_schedule, run_scenario)
from ..schemas.api import (AnalysisRequest, AnalysisResponse, CompanySummary, DocumentMetaUpdate, EvidenceRef, FactEntry, GridRequest,
                           FactReview, HistoryPoint, MemoEdit, MemoRequest, MetricOut, PredictRequest, Resolution,
                           ResolveRequest, ScenarioRequest, ScenarioResponse)

REPO = Path(__file__).resolve().parents[3]
CURATED_DIR = Path(os.environ.get("CREDITLENS_CURATED", REPO / "backend" / "data" / "curated"))
CORS_ORIGINS = [o.strip() for o in os.environ.get("CREDITLENS_CORS_ORIGINS", "http://localhost:3000").split(",")]
# Vercel production and preview deployments (https://<project>-<hash>.vercel.app); override with "" to disable
CORS_ORIGIN_REGEX = os.environ.get("CREDITLENS_CORS_REGEX", r"https://(creditlens|proj)[a-z0-9-]*\.vercel\.app") or None
SCALE = 1_000_000  # display / scenario scale: millions
VERSION = "1.6.1"

log = logging.getLogger("creditlens")
logging.basicConfig(level=logging.INFO, format="%(message)s")

@asynccontextmanager
async def lifespan(_app):
    store.purge_expired()          # enforce the retention window on every start
    yield


app = FastAPI(title="CreditLens AI", version=VERSION, lifespan=lifespan,
              description="Decision-support credit analysis. Not a rating, not a PD, not a loan decision.")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_origin_regex=CORS_ORIGIN_REGEX,
                   allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["*"])

# ------------------------------------------------------------------ cross-cutting: logging, rate limits
RATE_LIMITS = {"/documents/upload": (int(os.environ.get("CREDITLENS_UPLOAD_LIMIT", "20")), 3600),
               "/memos": (int(os.environ.get("CREDITLENS_MEMO_LIMIT", "60")), 3600),
               "/companies/resolve": (int(os.environ.get("CREDITLENS_RESOLVE_LIMIT", "120")), 3600)}
_hits: dict[tuple[str, str], deque] = defaultdict(deque)


@app.middleware("http")
async def observe(request: Request, call_next):
    rid = uuid.uuid4().hex[:12]
    start = time.perf_counter()
    path = request.url.path
    if request.method == "POST" and path in RATE_LIMITS:
        limit, window = RATE_LIMITS[path]
        ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0]
        q, now = _hits[(path, ip)], time.time()
        while q and q[0] < now - window:
            q.popleft()
        if len(q) >= limit:
            return JSONResponse({"detail": f"Too many requests to {path}; try again later."}, status_code=429)
        q.append(now)
    try:
        response = await call_next(request)
    except Exception:  # noqa: BLE001 — log and return a generic error, never a stack trace
        log.exception(json.dumps({"rid": rid, "path": path, "event": "unhandled_error"}))
        return JSONResponse({"detail": f"Internal error (reference {rid})."}, status_code=500)
    response.headers["x-request-id"] = rid
    response.headers["x-content-type-options"] = "nosniff"
    response.headers["x-frame-options"] = "DENY"
    response.headers["referrer-policy"] = "no-referrer"
    # nothing is cached anywhere: uploads and memos are private, and the site's proxy (Vercel) must always ask
    # the live service
    response.headers["cache-control"] = "no-store"
    log.info(json.dumps({"rid": rid, "method": request.method, "path": path, "status": response.status_code,
                         "ms": round((time.perf_counter() - start) * 1000, 1)}))
    return response


# ------------------------------------------------------------------ company registry
@lru_cache
def _curated() -> dict[str, dict]:
    out = {}
    for p in sorted(CURATED_DIR.glob("*companyfacts*.json*")):
        opener = gzip.open if p.suffix == ".gz" else open
        with opener(p, "rt") as fh:
            data = json.load(fh)
        out[str(data.get("cik", p.stem)).zfill(10)] = data
    # v1.6 credit-only tags (debt maturities, retained earnings) for the frozen sample files, merged here so the
    # frozen files themselves stay byte-identical; only SUPPLEMENTAL_REGISTRY tags, never model inputs
    for p in sorted((CURATED_DIR / "supplement").glob("supplement_*.json.gz")):
        with gzip.open(p, "rt") as fh:
            sup = json.load(fh)
        cf = out.get(str(sup["cik"]).zfill(10))
        if cf is not None:
            ug = cf.setdefault("facts", {}).setdefault("us-gaap", {})
            for tag, v in sup["facts"]["us-gaap"].items():
                ug.setdefault(tag, v)
    return out


def _companyfacts() -> dict[str, dict]:
    """Curated SEC issuers plus finalized uploaded reports (rebuilt from reviewed facts on each call).

    A malformed upload is logged and skipped so it can never break other companies (DATA-01)."""
    out = {**sec_search.loaded(), **_curated()}          # companies fetched from SEC on request, then the samples
    for row in store.list_finalized():
        try:
            doc = store.get_document(row["id"])
            if doc:
                out[doc["company_id"]] = uploads.to_companyfacts(doc)
        except Exception:  # noqa: BLE001
            log.exception(json.dumps({"event": "skipped_malformed_upload", "document": row["id"]}))
    return out


def _sec_load(cik10: str) -> dict:
    """Fetch a filer from SEC through the server; SEC failures become clear, distinct HTTP errors."""
    try:
        return sec_search.load(cik10)
    except SECError as e:
        log.warning(json.dumps({"event": "sec_error", "kind": e.kind, "cik": cik10, "detail": str(e)}))
        if e.kind == "not_found":
            raise HTTPException(404, f"SEC EDGAR has no filer with CIK {cik10}.")
        if e.kind == "throttled":
            raise HTTPException(429, "SEC EDGAR is limiting requests right now (rate limit). Wait a minute and try again.")
        raise HTTPException(502, f"SEC EDGAR is unavailable right now, so this company's filings cannot be loaded. {e}")


def _cf(company_id: str) -> dict:
    cf = _companyfacts().get(company_id)
    if cf is None and sec_search.is_cik(company_id):
        cf = _sec_load(company_id)                        # e.g. a shared link after the server restarted
    if cf is None:
        raise HTTPException(404, f"Unknown company_id {company_id}")
    return cf


def _years(company_id: str, as_of: Optional[str] = None) -> list[CompanyYear]:
    return build_company_years(_cf(company_id), as_of=as_of)


def _pick(years: list[CompanyYear], fye: Optional[str]) -> tuple[CompanyYear, Optional[CompanyYear]]:
    if not years:
        raise HTTPException(422, "No annual filings available at this as-of date")
    idx = len(years) - 1 if fye is None else next((i for i, y in enumerate(years) if y.fiscal_year_end == fye), None)
    if idx is None:
        raise HTTPException(404, f"Fiscal year end {fye} not available")
    return years[idx], (years[idx - 1] if idx > 0 else None)


def _scaled(v: dict) -> dict:
    return {k: (x / SCALE if x is not None else None) for k, x in v.items()}


# ------------------------------------------------------------------ core analysis
@app.get("/health")
def health():
    return {"status": "ok", "version": VERSION, **llm_status()}


@app.get("/companies", response_model=list[CompanySummary])
def companies(include: Optional[str] = None):
    """The curated sample issuers. Uploaded reports are private to whoever holds their link, so they are listed
    only when that link's id is passed as `include` — never to every visitor."""
    out = []
    all_cf = _companyfacts()
    if include and include not in all_cf and sec_search.is_cik(include):
        all_cf[include] = _sec_load(include)
    for cid, cf in all_cf.items():
        if cid not in _curated() and cid != include:
            continue
        try:
            ys = build_company_years(cf)
        except Exception:  # noqa: BLE001 — isolate a malformed record
            log.exception(json.dumps({"event": "skipped_company", "company": cid}))
            continue
        out.append(CompanySummary(company_id=cid, name=cf.get("entityName", cid),
                                  source=cf.get("source", "SEC XBRL companyfacts"),
                                  fiscal_years=[y.fiscal_year_end for y in ys],
                                  last_filed=max((y.available_as_of for y in ys if y.available_as_of), default=None),
                                  synthetic="SYNTHETIC" in cf.get("entityName", ""), curated=cid in _curated(),
                                  tickers=(cf.get("sec_meta") or {}).get("tickers") or []))
    return out


# ------------------------------------------------------------------ any U.S. public company (search + load)
KEY_METRICS = {"ebitda": "EBITDA", "net_debt": "net debt", "net_leverage": "net debt / EBITDA",
               "ebitda_interest_cover": "EBITDA / interest", "ebit_interest_cover": "EBIT / interest",
               "fcf_simple": "free cash flow", "current_ratio": "current ratio", "ebitda_margin": "EBITDA margin"}


@app.get("/companies/search")
def company_search(q: str = "", limit: int = 10):
    """Name, ticker or CIK -> SEC registrants (name, tickers, CIK). Server side only: the browser never calls SEC."""
    q = q.strip()
    if not q:
        raise HTTPException(422, "Type a company name, ticker or CIK.")
    if len(q) > sec_search.MAX_QUERY:
        raise HTTPException(422, f"The search text is too long (at most {sec_search.MAX_QUERY} characters).")
    try:
        res = sec_search.search(q, max(1, min(limit, 20)))
    except SECError as e:
        log.warning(json.dumps({"event": "sec_error", "kind": e.kind, "where": "search", "detail": str(e)}))
        if e.kind == "throttled":
            raise HTTPException(429, "SEC EDGAR is limiting requests right now (rate limit). Wait a minute and try again.")
        raise HTTPException(502, "The SEC company list cannot be reached right now, so search is unavailable. "
                                 "The sample companies and upload still work.")
    cur = _curated()
    for r in res["results"]:
        r["curated"] = r["company_id"] in cur
    return res


@app.post("/companies/resolve", response_model=Resolution)
def company_resolve(req: ResolveRequest):
    """Load a searched filer and say plainly what CreditLens can do with it."""
    cik10 = req.cik.upper().replace("CIK", "").strip().zfill(10)
    cf = _curated().get(cik10) or _sec_load(cik10)
    source = cf.get("source", "SEC XBRL companyfacts")
    meta = cf.get("sec_meta") or {}
    common = {"sic": meta.get("sic") or None, "sic_description": meta.get("sicDescription") or None,
              "retrieved_at": cf.get("retrieved_at"), "source": source}
    name = cf.get("entityName") or meta.get("name") or cik10
    try:
        years = build_company_years(cf)
    except Exception:  # noqa: BLE001 — a record the pipeline cannot read is reported, never patched up
        log.exception(json.dumps({"event": "resolve_unreadable", "cik": cik10}))
        years = []
    if not years:
        return Resolution(company=None, outcome="no_supported_statements", **common,
                          message=f"{name} has no annual financial statements in SEC XBRL that CreditLens can read "
                                  "(U.S. GAAP 10-K data). This is typical of foreign issuers reporting under IFRS on "
                                  "Form 20-F or 40-F, funds and trusts, and shells. Nothing is estimated in their place; "
                                  "you can still upload a text-based annual report.")
    summary = next(c for c in companies(include=cik10) if c.company_id == cik10)
    cy, prior = years[-1], (years[-2] if len(years) > 1 else None)
    vals = _scaled(engine_inputs(cy))
    m = compute_all(vals, _scaled(engine_inputs(prior)) if prior else None, cash_basis=cy.cash_basis)
    unavailable = [label for k, label in KEY_METRICS.items() if m[k].status.value == "not_available"]
    risk = risk_service.score(cf, cy.fiscal_year_end)
    status = risk.get("status")
    lab = _lab_status(cf, cy)
    lab_missing = not lab["available"]
    lab_note = ("" if lab["available"] else FINANCIAL_LAB if (_industry(cf) or {}).get("financial")
                else "The loan lab and memo cannot run for this year. " + lab["reason"])
    gates = risk.get("gate_reasons", []) if status != "scored" else []
    if status != "scored":
        outcome = "score_withheld"
        msg = ("Financial statements loaded; the neural stress screen is withheld for this company: "
               + "; ".join(gates or [risk.get("message", "the model is unavailable")]) + "."
               + (" " + lab_note if lab_note else " Ratios, the loan lab and the memo still work."))
    elif unavailable or not cy.scorable or lab_missing:
        outcome = "partial"
        msg = ("Financial statements loaded; some figures are not reported in XBRL and are shown as unavailable, "
               "never estimated: " + ", ".join(unavailable or ["see the data checks"]) + "."
               + (" " + lab_note if lab_note else ""))
    else:
        outcome, msg = "full", "Financial statements loaded; all credit metrics and the stress screen are available."
    if unavailable and outcome == "score_withheld":
        msg += " Not reported in XBRL: " + ", ".join(unavailable) + "."
    return Resolution(company=summary, outcome=outcome, message=msg, fiscal_year_end=cy.fiscal_year_end,
                      loan_lab_available=not lab_missing,
                      metrics_unavailable=unavailable, score_status=status, gate_reasons=gates, **common)


@app.post("/analyses", response_model=AnalysisResponse)
def analyses(req: AnalysisRequest):
    cf = _cf(req.company_id)
    cy, prior = _pick(build_company_years(cf, as_of=req.as_of), req.fiscal_year_end)
    vals = _scaled(engine_inputs(cy))
    prior_vals = _scaled(engine_inputs(prior)) if prior else None
    metrics = compute_all(vals, prior_vals, cash_basis=cy.cash_basis)
    ccy = cf.get("currency", "USD")
    return AnalysisResponse(
        company_id=req.company_id, company_name=cy.company_name, fiscal_year_end=cy.fiscal_year_end, currency=ccy,
        scorable=cy.scorable, source=cf.get("source", "SEC XBRL companyfacts"),
        metrics={k: MetricOut(metric=m.metric, value=m.value, status=m.status.value, unit=m.unit, formula=m.formula,
                              formula_version=m.formula_version, inputs=dict(m.inputs), reason=m.reason)
                 for k, m in metrics.items()},
        evidence={k: (EvidenceRef(field=f.field, value=f.value / SCALE, unit=f"{ccy} millions", tag=f.tag,
                                  accession=f.accession, form=f.form, filed=f.filed, period_end=f.period_end,
                                  extraction_method=f.extraction_method, page=f.page) if f else None)
                  for k, f in cy.facts.items()},
        derived={**{k: {"value": v / SCALE, "rule": r, "basis": "model and credit"} for k, (v, r) in cy.derived.items()},
                 **{k: {"value": v / SCALE, "rule": r, "basis": "credit"} for k, (v, r) in cy.credit.items()}},
        supplemental={k: EvidenceRef(field=f.field, value=f.value / SCALE, unit=f"{ccy} millions", tag=f.tag,
                                     accession=f.accession, form=f.form, filed=f.filed, period_end=f.period_end,
                                     extraction_method=f.extraction_method, page=f.page)
                      for k, f in cy.supplemental.items()},
        cash_basis=cy.cash_basis, unavailable_inputs=cf.get("unavailable_critical", []),
        sec_check=cf.get("sec_check", "SEC XBRL is the source" if "unavailable_critical" not in cf else None),
        warnings=cy.warnings, hard_failures=cy.hard_failures,
        risk_model=risk_service.score(cf, cy.fiscal_year_end, req.as_of),
        industry=_industry(cf), loan_lab=_lab_status(cf, cy),
        credit_extras=(ex := _extras(cf, cy, prior, vals, prior_vals, metrics)),
        peers=_peers(cf, cy, prior, ex))


@app.post("/predict")
def predict(req: PredictRequest):
    cf = _cf(req.company_id)
    cy, _ = _pick(build_company_years(cf, as_of=req.as_of), req.fiscal_year_end)
    return {"company_id": req.company_id, "fiscal_year_end": cy.fiscal_year_end,
            **risk_service.score(cf, cy.fiscal_year_end, req.as_of)}


@app.get("/model")
def model_card():
    """Model X-Ray: metadata, evaluation exhibits and limitations of the deployed network."""
    out = {}
    for name in ("metadata", "xray"):
        p = ARTIFACT_DIR / f"{name}.json"
        out[name] = json.loads(p.read_text()) if p.exists() else None
    if out["metadata"] is None:
        raise HTTPException(404, "No model artifact deployed")
    from ..features.feature_set import FEATURE_DICTIONARY, FEATURE_GROUPS
    out["feature_groups"] = [{"group": g, "features": [{"name": f, "definition": FEATURE_DICTIONARY[f][0]} for f in fs]}
                             for g, fs in FEATURE_GROUPS.items()]
    try:
        out["held_out"] = replay.model_evidence()
    except FileNotFoundError:
        out["held_out"] = None
    # experiments and the canonical onset breakdown (not a model artifact; nothing here produces a score)
    rp = Path(__file__).resolve().parents[2] / "data" / "research" / "research_v1.json"
    out["research"] = json.loads(rp.read_text()) if rp.exists() else None
    return out


# ------------------------------------------------------------------ historical model replay (Stage D)
@app.get("/replay")
def replay_overview():
    """Held-out (2021-25) cases with their frozen forecasts. No outcome fields."""
    return replay.overview()


@app.get("/replay/cases/{case_id}")
def replay_forecast(case_id: str):
    """What was known when the year-t 10-K was filed, and the frozen forecast. No outcome fields."""
    try:
        return replay.forecast(case_id)
    except KeyError:
        raise HTTPException(404, "Unknown replay case")


@app.get("/replay/cases/{case_id}/outcome")
def replay_outcome(case_id: str):
    """The next-year accounting-stress label, its three conditions and the assessment of the forecast."""
    try:
        return replay.outcome(case_id)
    except KeyError:
        raise HTTPException(404, "Unknown replay case")


@app.get("/companies/{company_id}/history", response_model=list[HistoryPoint])
def history(company_id: str):
    years = _years(company_id)
    out, prev = [], None
    for cy in years:
        v = _scaled(engine_inputs(cy))
        m = compute_all(v, prev, cash_basis=cy.cash_basis)
        out.append(HistoryPoint(
            fiscal_year_end=cy.fiscal_year_end, filed=cy.available_as_of, scorable=cy.scorable,
            values={k: v.get(k) for k in ("revenue", "operating_income", "net_income", "interest_expense",
                                          "operating_cash_flow", "capital_expenditures", "cash", "total_assets")},
            metrics={k: m[k].value for k in ("ebitda", "gross_debt", "net_debt", "fcf_simple", "ebitda_margin",
                                             "net_leverage", "gross_leverage", "ebit_interest_cover",
                                             "ebitda_interest_cover", "current_ratio", "revenue_growth")}))
        prev = v
    return out


FINANCIAL_NOTE = ("This is a financial-sector filer (SEC SIC {sic}{desc}). The industrial credit metrics used here "
                  "(EBITDA, net debt / EBITDA, interest cover, free cash flow) do not describe a bank's or insurer's "
                  "credit: interest is its main revenue and expense, deposits are its funding and \"revenue\" tags "
                  "capture only part of its income. Bank credit is judged on capital, asset quality and liquidity, "
                  "which CreditLens does not model. The figures below are shown as reported, not as credit metrics.")


def _industry(cf: dict) -> Optional[dict]:
    """Industry of a company found by search (SEC SIC code); None for samples and uploads."""
    meta = cf.get("sec_meta")
    if not meta:
        return None
    sic = cf.get("sic") or meta.get("sic")
    financial = excluded_sic(sic) == "financial_sector"
    desc = meta.get("sicDescription")
    return {"sic": sic or None, "sic_description": desc, "financial": financial,
            "note": FINANCIAL_NOTE.format(sic=sic, desc=f", {desc}" if desc else "") if financial else None}


FINANCIAL_LAB = ("The loan lab and memo are not available for financial-sector filers: their leverage and coverage "
                 "tests are built for operating companies and would be misleading for a bank or insurer.")


def _extras(cf: dict, cy, prior, vals: dict, prior_vals: Optional[dict], metrics) -> dict:
    """Debt maturity wall and textbook scores (finance/credit_extras.py), all from this year's XBRL facts."""
    if (_industry(cf) or {}).get("financial"):
        return {"not_applicable": "Industrial credit measures do not apply to financial-sector filers."}
    re_fact = cy.supplemental.get("retained_earnings")
    v = {**vals, "retained_earnings": re_fact.value / SCALE if re_fact else None}
    z = credit_extras.altman_z2(v)
    if re_fact:
        z["retained_earnings_evidence"] = {"tag": re_fact.tag, "accession": re_fact.accession, "filed": re_fact.filed}
    wall = (credit_extras.maturity_wall(cy.supplemental, vals, metrics["fcf_simple"].value, SCALE)
            if cf.get("source") != "Uploaded annual report" else
            {"available": False, "version": credit_extras.EXTRAS_VERSION,
             "reason": "The debt maturity schedule is not extracted from uploaded PDFs; search the company to load it from SEC."})
    return {"maturities": wall,
            "altman_z2": z, "ohlson_o": credit_extras.ohlson_o(vals, prior_vals, cy.fiscal_year_end)}


def _peers(cf: dict, cy, prior, extras: dict) -> Optional[dict]:
    """Percentile bands against the training panel's lending population (finance/peers.py)."""
    if (_industry(cf) or {}).get("financial") or not cy.scorable:
        return None
    mv = _scaled(engine_inputs(cy, basis="model"))
    mp = _scaled(engine_inputs(prior, basis="model")) if prior else None
    m = compute_all(mv, mp, cash_basis=cy.cash_basis)
    values = {k: m[k].value for k in ("revenue_growth", "ebitda_margin", "gross_leverage", "net_leverage",
                                       "ebit_interest_cover", "ebitda_interest_cover", "current_ratio")}
    for k in ("altman_z2", "ohlson_o"):
        values[k] = extras.get(k, {}).get("value") if extras.get(k, {}).get("available") else None
    cik = str(cf.get("cik", "")).zfill(10)
    sic = cf.get("sic") or (cf.get("sec_meta") or {}).get("sic") or peer_lib.sic_of(cik)
    out = peer_lib.percentiles(values, cik, sic, cy.fiscal_year_end)
    out["sic"] = sic
    return out


def _lab_status(cf: dict, cy) -> dict:
    """Whether the loan lab, heatmap and memo can run for this year, decided once on the server."""
    ind = _industry(cf)
    if ind and ind["financial"]:
        return {"available": False, "reason": FINANCIAL_LAB, "missing": []}
    if not cy.scorable:
        return {"available": False, "reason": "Hard data checks failed for this year.", "missing": []}
    missing = credit_baseline(cy, cf.get("currency", "USD"), 0.0)[1]
    if missing:
        return {"available": False, "missing": missing,
                "reason": "Not reported in XBRL for this year: " + ", ".join(
                    m.replace("_", " ").replace("ebitda", "EBITDA") for m in missing) + ". Nothing is estimated in its place."}
    return {"available": True, "reason": None, "missing": []}


def _baseline(company_id: str, fye: Optional[str], floating_share: float) -> tuple[Baseline, CompanyYear]:
    cf = _cf(company_id)
    cy, _ = _pick(build_company_years(cf), fye)
    if (_industry(cf) or {}).get("financial"):
        raise HTTPException(422, FINANCIAL_LAB)
    if not cy.scorable:
        raise HTTPException(422, f"Hard data checks failed: {cy.hard_failures}")
    base, missing = credit_baseline(cy, cf.get("currency", "USD"), floating_share)
    if missing:
        raise HTTPException(422, f"Cannot run scenario; not available: {', '.join(missing)}. Review source facts.")
    return base, cy


@app.post("/scenarios", response_model=ScenarioResponse)
def scenarios(req: ScenarioRequest):
    snap = None
    shocks = req.shocks or DEFAULT_CASES
    if req.baseline_override:
        base = Baseline(**req.baseline_override)
    elif req.company_id:
        base, cy = _baseline(req.company_id, req.fiscal_year_end, req.existing_floating_share)
        snap = make_snapshot(req.company_id, cy.fiscal_year_end, base, req.facility, req.covenants, shocks,
                             cy.cash_basis)
    else:
        raise HTTPException(422, "Provide company_id or baseline_override")
    try:
        results = [run_scenario(base, req.facility, s, req.covenants) for s in shocks]
    except (FXBlocked, ScenarioInputError) as e:
        raise HTTPException(422, str(e))
    sched = amortization_schedule(req.facility) if req.facility else []
    return ScenarioResponse(baseline=base.model_dump(), results=results, facility_schedule=sched, snapshot=snap)


@app.post("/scenarios/grid")
def scenario_grid(req: GridRequest):
    """Stage F: every cell is one call of the same Python scenario engine as the loan lab (run_scenario).
    Nothing is interpolated or recomputed in the browser."""
    base, cy = _baseline(req.company_id, req.fiscal_year_end, req.existing_floating_share)
    if any(not -1.0 <= e <= 1.0 for e in req.ebitda_shocks) or any(not -500 <= r <= 1000 for r in req.rate_shocks_bps):
        raise HTTPException(422, "Shocks outside the engine's range (EBITDA -100% to +100%, rates -500 to +1,000 bp)")
    rows = []
    for r in req.rate_shocks_bps:
        row = []
        for e in req.ebitda_shocks:
            try:
                res = run_scenario(base, req.facility, Shock(name=f"grid {e:+.0%} / {r:+.0f}bp", ebitda_shock=e,
                                                             rate_shock_bps=r), req.covenants)
            except FXBlocked as err:
                raise HTTPException(422, str(err))
            except ScenarioInputError as err:
                row.append({"ebitda_shock": e, "rate_shock_bps": r, "error": str(err)})
                continue
            h = res.covenant_headroom
            st = {k: a.state.value for k, a in res.covenant_status.items()}
            row.append({"ebitda_shock": e, "rate_shock_bps": r, "ebitda": res.ebitda, "net_leverage": res.net_leverage,
                        "ebitda_interest_cover": res.ebitda_interest_cover,
                        "headroom_lev": h.get("max_net_leverage"), "headroom_cov": h.get("min_ebitda_interest_cover"),
                        "state_lev": st.get("max_net_leverage"), "state_cov": st.get("min_ebitda_interest_cover"),
                        # the engine's assessment is the only source of truth for colouring (Fix 3)
                        "breach": "breach" in st.values(), "not_testable": "not_testable" in st.values(),
                        "reasons": {k: a.reason for k, a in res.covenant_status.items()},
                        "flags": res.flags})
        rows.append(row)
    return {"company_id": req.company_id, "fiscal_year_end": cy.fiscal_year_end, "currency": base.currency,
            "engine_version": ENGINE_VERSION, "ebitda_shocks": req.ebitda_shocks, "rate_shocks_bps": req.rate_shocks_bps,
            "covenants": (req.covenants or Covenants()).model_dump(), "cells": rows}


# ------------------------------------------------------------------ documents (Week 6)
@app.post("/documents/upload")
async def upload_document(file: UploadFile = File(...), company_name: str = Form(""), cik: str = Form("")):
    data = await file.read(pdf_extract.MAX_BYTES + 1)
    try:
        extraction = pdf_extract.extract(data).to_dict()
    except pdf_extract.ExtractionError as e:
        store.audit("upload_rejected", file.filename or "?", reason=str(e))
        raise HTTPException(422, str(e))
    finally:
        del data  # the PDF is never persisted
    cik10 = cik.strip().zfill(10) if cik.strip().isdigit() else None
    if cik10 and cik10 in _curated():
        uploads.cross_check_xbrl(extraction, _curated()[cik10])
    elif cik10:
        extraction["sec_check"] = (f"Not checked against SEC: CIK {cik10.lstrip('0')} is not one of the "
                                   f"{len(_curated())} sample issuers held offline")
    else:
        extraction["sec_check"] = "Not checked against SEC: no CIK given"
    sha = hashlib.sha256((file.filename or "").encode() + str(extraction["candidates"]).encode()).hexdigest()
    doc_id = store.create_document(filename=file.filename or "upload.pdf", sha256=sha, extraction=extraction,
                                   company_name=company_name.strip() or (file.filename or "Uploaded company").rsplit(".", 1)[0])
    store.audit("document_uploaded", doc_id, filename=file.filename, pages=extraction["pages"],
                candidates=len(extraction["candidates"]), cross_checked_cik=cik10)
    return _document_view(doc_id)


def _document_view(doc_id: str) -> dict:
    doc = store.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found (it may have been deleted or expired)")
    doc["blocking"] = uploads.blocking_reasons(doc)
    doc["unavailable_critical"] = uploads.unavailable_critical(doc)
    doc["can_finalize"] = not doc["blocking"] and doc["status"] != "finalized"
    doc["currencies"], doc["scales"] = list(uploads.CURRENCIES), list(uploads.SCALES)
    return doc


@app.get("/documents/{doc_id}")
def get_document(doc_id: str):
    return _document_view(doc_id)


@app.patch("/documents/{doc_id}")
def update_document(doc_id: str, body: DocumentMetaUpdate):
    doc = _document_view(doc_id)
    try:
        store.set_document_meta(doc["id"], body.fiscal_year_end, body.company_name, body.currency, body.scale_label)
    except PermissionError as e:
        raise HTTPException(409, str(e))
    return _document_view(doc["id"])


@app.post("/documents/{doc_id}/facts")
def add_document_fact(doc_id: str, body: FactEntry):
    """Enter a figure the parser did not find, or record explicitly that it is not available."""
    doc = _document_view(doc_id)
    try:
        store.add_fact(doc["id"], body.field, body.period, body.value, body.page, body.note)
    except PermissionError as e:
        raise HTTPException(409, str(e))
    return _document_view(doc["id"])


@app.patch("/facts/{fact_id}/review")
def review_fact(fact_id: str, body: FactReview):
    if body.decision == "correct" and body.value is None:
        raise HTTPException(422, "A corrected value is required")
    try:
        return store.review_fact(fact_id, body.decision, body.value, body.note)
    except KeyError:
        raise HTTPException(404, "Fact not found")
    except PermissionError as e:
        raise HTTPException(409, str(e))


@app.post("/documents/{doc_id}/finalize")
def finalize_document(doc_id: str):
    doc = _document_view(doc_id)
    if doc["blocking"]:
        raise HTTPException(409, "Review required before analysis: " + "; ".join(doc["blocking"]))
    store.finalize(doc["id"])
    return {"company_id": doc["company_id"], **_document_view(doc["id"])}


@app.delete("/documents/{doc_id}")
def delete_document(doc_id: str):
    if not store.delete_document(doc_id):
        raise HTTPException(404, "Document not found")
    return {"deleted": doc_id}


# ------------------------------------------------------------------ memos (Week 6)
@app.get("/memos/config")
def memo_config():
    return llm_status()


@app.post("/memos")
def create_memo(req: MemoRequest):
    cf = _cf(req.company_id)
    if (_industry(cf) or {}).get("financial"):
        raise HTTPException(422, FINANCIAL_LAB)
    facility = req.facility or Facility(amount=100.0, currency=cf.get("currency", "USD"))
    try:
        return memo_service.generate(cf, req.company_id, req.fiscal_year_end, facility, req.covenants,
                                     req.existing_floating_share, prefer_llm=req.use_llm, shocks=req.shocks)
    except (FXBlocked, ScenarioInputError) as e:
        raise HTTPException(422, str(e))
    except (ValueError, StopIteration) as e:
        raise HTTPException(422, f"Memo could not be built: {e}")


def _memo(memo_id: str) -> dict:
    m = store.get_memo(memo_id)
    if not m:
        raise HTTPException(404, "Memo not found")
    return m


@app.get("/memos/{memo_id}")
def get_memo(memo_id: str):
    return _memo(memo_id)


@app.patch("/memos/{memo_id}/sentences/{sentence_id}")
def edit_memo_sentence(memo_id: str, sentence_id: str, body: MemoEdit):
    try:
        return memo_service.edit_sentence(_memo(memo_id), sentence_id, body.text)
    except KeyError:
        raise HTTPException(404, "Sentence not found")


@app.get("/memos/{memo_id}/pdf")
def memo_pdf(memo_id: str, snapshot: Optional[str] = None):
    """`snapshot` is the analysis snapshot the caller's loan table shows; a mismatch means the memo is outdated."""
    m = _memo(memo_id)
    memo_snap = (m.get("snapshot") or {}).get("id")
    if snapshot is not None and snapshot != memo_snap:
        raise HTTPException(409, f"This memo was built from snapshot {memo_snap}, but the loan lab shows {snapshot}. "
                                 "Regenerate the memo before exporting.")
    store.audit("memo_exported", memo_id, flagged=m["summary"]["flagged"])
    name = "".join(ch for ch in m["package"]["meta.company"]["display"] if ch.isalnum() or ch in " -")[:40].strip()
    return Response(render_pdf(m), media_type="application/pdf",
                    headers={"content-disposition": f'attachment; filename="CreditLens memo - {name}.pdf"'})


@app.get("/audit")
def audit(request: Request, subject: Optional[str] = None, limit: int = 100):
    """Operator-only: raw audit entries can reveal what was uploaded, so they need CREDITLENS_ADMIN_TOKEN."""
    token = os.environ.get("CREDITLENS_ADMIN_TOKEN")
    if not token or request.headers.get("x-admin-token") != token:
        raise HTTPException(404, "Not found")
    return store.audit_log(subject, min(max(limit, 1), 500))
