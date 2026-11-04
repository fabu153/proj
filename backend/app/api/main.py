"""CreditLens FastAPI app — Week 1 surface.

Run:  uvicorn backend.app.api.main:app --reload   (from repo root)
"""
from __future__ import annotations

import gzip
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from ..documents.xbrl import CompanyYear, build_company_years, engine_inputs
from ..finance.metrics import compute_all
from ..scenarios.loan import DEFAULT_CASES, Baseline, FXBlocked, run_scenario
from ..schemas.api import (AnalysisRequest, AnalysisResponse, CompanySummary, EvidenceRef, MetricOut,
                           ScenarioRequest, ScenarioResponse)

REPO = Path(__file__).resolve().parents[3]
CURATED_DIR = Path(os.environ.get("CREDITLENS_CURATED", REPO / "backend" / "data" / "curated"))
CORS_ORIGINS = [o.strip() for o in os.environ.get("CREDITLENS_CORS_ORIGINS", "http://localhost:3000").split(",")]
SCALE = 1_000_000  # display / scenario scale: millions

app = FastAPI(title="CreditLens AI", version="0.2.0",
              description="Decision-support credit analysis. Not a rating, not a PD, not a loan decision.")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])


@lru_cache
def _companyfacts() -> dict[str, dict]:
    out = {}
    for p in sorted(CURATED_DIR.glob("*companyfacts*.json*")):
        opener = gzip.open if p.suffix == ".gz" else open
        with opener(p, "rt") as fh:
            data = json.load(fh)
        out[str(data.get("cik", p.stem)).zfill(10)] = data
    return out


def _years(company_id: str, as_of: Optional[str] = None) -> list[CompanyYear]:
    cf = _companyfacts().get(company_id)
    if cf is None:
        raise HTTPException(404, f"Unknown company_id {company_id}")
    return build_company_years(cf, as_of=as_of)


def _pick(years: list[CompanyYear], fye: Optional[str]) -> tuple[CompanyYear, Optional[CompanyYear]]:
    if not years:
        raise HTTPException(422, "No annual filings available at this as-of date")
    idx = len(years) - 1 if fye is None else next((i for i, y in enumerate(years) if y.fiscal_year_end == fye), None)
    if idx is None:
        raise HTTPException(404, f"Fiscal year end {fye} not available")
    return years[idx], (years[idx - 1] if idx > 0 else None)


def _scaled(v: dict) -> dict:
    return {k: (x / SCALE if x is not None else None) for k, x in v.items()}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/companies", response_model=list[CompanySummary])
def companies():
    out = []
    for cid, cf in _companyfacts().items():
        ys = build_company_years(cf)
        out.append(CompanySummary(company_id=cid, name=cf.get("entityName", cid), source="SEC XBRL companyfacts",
                                  fiscal_years=[y.fiscal_year_end for y in ys],
                                  last_filed=max((y.available_as_of for y in ys if y.available_as_of), default=None),
                                  synthetic="SYNTHETIC" in cf.get("entityName", "")))
    return out


@app.post("/analyses", response_model=AnalysisResponse)
def analyses(req: AnalysisRequest):
    cy, prior = _pick(_years(req.company_id, req.as_of), req.fiscal_year_end)
    vals = _scaled(engine_inputs(cy))
    prior_vals = _scaled(engine_inputs(prior)) if prior else None
    metrics = compute_all(vals, prior_vals)
    return AnalysisResponse(
        company_id=req.company_id, company_name=cy.company_name, fiscal_year_end=cy.fiscal_year_end,
        scorable=cy.scorable,
        metrics={k: MetricOut(metric=m.metric, value=m.value, status=m.status.value, unit=m.unit, formula=m.formula,
                              formula_version=m.formula_version, inputs=dict(m.inputs), reason=m.reason)
                 for k, m in metrics.items()},
        evidence={k: (EvidenceRef(field=f.field, value=f.value / SCALE, unit="USD millions", tag=f.tag,
                                  accession=f.accession, form=f.form, filed=f.filed, period_end=f.period_end,
                                  extraction_method=f.extraction_method) if f else None)
                  for k, f in cy.facts.items()},
        warnings=cy.warnings, hard_failures=cy.hard_failures)


@app.post("/scenarios", response_model=ScenarioResponse)
def scenarios(req: ScenarioRequest):
    if req.baseline_override:
        base = Baseline(**req.baseline_override)
    elif req.company_id:
        cy, _ = _pick(_years(req.company_id), req.fiscal_year_end)
        if not cy.scorable:
            raise HTTPException(422, f"Hard data checks failed: {cy.hard_failures}")
        m = compute_all(_scaled(engine_inputs(cy)))
        needed = {"ebitda": m["ebitda"].value, "gross_debt": m["gross_debt"].value}
        v = _scaled(engine_inputs(cy))
        needed |= {"cash": v.get("cash"), "interest_expense": v.get("interest_expense")}
        missing = [k for k, x in needed.items() if x is None]
        if missing:
            raise HTTPException(422, f"Cannot run scenario; not available: {missing}. Review source facts.")
        base = Baseline(currency="USD", existing_floating_share=req.existing_floating_share, **needed)
    else:
        raise HTTPException(422, "Provide company_id or baseline_override")
    try:
        results = [run_scenario(base, req.facility, s, req.covenants) for s in (req.shocks or DEFAULT_CASES)]
    except FXBlocked as e:
        raise HTTPException(422, str(e))
    return ScenarioResponse(baseline=base.model_dump(), results=results)
