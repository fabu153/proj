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
from ..documents import pdf_extract, uploads
from ..documents.xbrl import CompanyYear, build_company_years, engine_inputs
from ..finance.metrics import compute_all
from ..memos import service as memo_service
from ..memos.pdf import render_pdf
from ..memos.writer import llm_status
from ..models import risk as risk_service
from ..models.inference import ARTIFACT_DIR
from ..scenarios.snapshot import credit_baseline, make_snapshot
from ..scenarios.loan import DEFAULT_CASES, Baseline, Facility, FXBlocked, ScenarioInputError, amortization_schedule, run_scenario
from ..schemas.api import (AnalysisRequest, AnalysisResponse, CompanySummary, DocumentMetaUpdate, EvidenceRef, FactEntry,
                           FactReview, HistoryPoint, MemoEdit, MemoRequest, MetricOut, PredictRequest, ScenarioRequest,
                           ScenarioResponse)

REPO = Path(__file__).resolve().parents[3]
CURATED_DIR = Path(os.environ.get("CREDITLENS_CURATED", REPO / "backend" / "data" / "curated"))
CORS_ORIGINS = [o.strip() for o in os.environ.get("CREDITLENS_CORS_ORIGINS", "http://localhost:3000").split(",")]
# Vercel production and preview deployments (https://<project>-<hash>.vercel.app); override with "" to disable
CORS_ORIGIN_REGEX = os.environ.get("CREDITLENS_CORS_REGEX", r"https://(creditlens|proj)[a-z0-9-]*\.vercel\.app") or None
SCALE = 1_000_000  # display / scenario scale: millions
VERSION = "1.2.0"

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
               "/memos": (int(os.environ.get("CREDITLENS_MEMO_LIMIT", "60")), 3600)}
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
    if path.startswith(("/documents", "/facts", "/memos", "/audit", "/companies", "/analyses", "/scenarios")):
        response.headers["cache-control"] = "no-store"     # uploaded figures and memos are never cached
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
    return out


def _companyfacts() -> dict[str, dict]:
    """Curated SEC issuers plus finalized uploaded reports (rebuilt from reviewed facts on each call).

    A malformed upload is logged and skipped so it can never break other companies (DATA-01)."""
    out = dict(_curated())
    for row in store.list_finalized():
        try:
            doc = store.get_document(row["id"])
            if doc:
                out[doc["company_id"]] = uploads.to_companyfacts(doc)
        except Exception:  # noqa: BLE001
            log.exception(json.dumps({"event": "skipped_malformed_upload", "document": row["id"]}))
    return out


def _cf(company_id: str) -> dict:
    cf = _companyfacts().get(company_id)
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
    for cid, cf in _companyfacts().items():
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
                                  synthetic="SYNTHETIC" in cf.get("entityName", "")))
    return out


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
        risk_model=risk_service.score(cf, cy.fiscal_year_end, req.as_of))


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


def _baseline(company_id: str, fye: Optional[str], floating_share: float) -> tuple[Baseline, CompanyYear]:
    cf = _cf(company_id)
    cy, _ = _pick(build_company_years(cf), fye)
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
def memo_pdf(memo_id: str):
    m = _memo(memo_id)
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
