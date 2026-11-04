"""Typed API contracts (Blueprint p.15). The frontend codes against these shapes."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from ..scenarios.loan import Covenants, Facility, ScenarioResult, Shock


class CompanySummary(BaseModel):
    company_id: str
    name: str
    source: str
    fiscal_years: list[str]
    last_filed: Optional[str]
    synthetic: bool = False


class EvidenceRef(BaseModel):
    field: str
    value: float
    unit: str
    tag: str
    accession: str
    form: str
    filed: str
    period_end: str
    extraction_method: str


class MetricOut(BaseModel):
    metric: str
    value: Optional[float]
    status: str
    unit: str
    formula: str
    formula_version: str
    inputs: dict[str, Optional[float]]
    reason: Optional[str] = None


class AnalysisRequest(BaseModel):
    company_id: str
    fiscal_year_end: Optional[str] = Field(None, description="Defaults to latest available")
    as_of: Optional[str] = Field(None, description="Point-in-time cutoff for filings (YYYY-MM-DD)")


class AnalysisResponse(BaseModel):
    company_id: str
    company_name: str
    fiscal_year_end: str
    currency: str = "USD"
    scale: str = "millions"
    scorable: bool
    metrics: dict[str, MetricOut]
    evidence: dict[str, Optional[EvidenceRef]]
    warnings: list[str]
    hard_failures: list[str]
    derived: dict[str, dict] = Field(default_factory=dict, description="values filled by logged rules R1-R4")
    risk_model: dict = Field(default_factory=dict)
    review_required: bool = True


class PredictRequest(BaseModel):
    company_id: str
    fiscal_year_end: Optional[str] = None
    as_of: Optional[str] = None


class HistoryPoint(BaseModel):
    fiscal_year_end: str
    filed: Optional[str]
    scorable: bool
    values: dict[str, Optional[float]]
    metrics: dict[str, Optional[float]]


class ScenarioRequest(BaseModel):
    company_id: Optional[str] = None
    fiscal_year_end: Optional[str] = None
    baseline_override: Optional[dict] = Field(None, description="Use explicit Baseline fields instead of a company")
    existing_floating_share: float = Field(0.0, ge=0, le=1)
    facility: Optional[Facility] = Field(default_factory=lambda: Facility(amount=100.0))
    shocks: Optional[list[Shock]] = None
    covenants: Optional[Covenants] = None


class ScenarioResponse(BaseModel):
    baseline: dict
    results: list[ScenarioResult]
    facility_schedule: list[dict] = []
    disclaimer: str = ("Mechanical sensitivities only; not a forecast, rating or probability of default. "
                       "Analyst review required.")
