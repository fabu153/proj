"""Typed API contracts (Blueprint p.15). The frontend codes against these shapes."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from ..scenarios.loan import Covenants, Facility, ScenarioResult, Shock


class CompanySummary(BaseModel):
    company_id: str
    name: str
    source: str
    fiscal_years: list[str]
    last_filed: Optional[str]
    synthetic: bool = False
    curated: bool = False
    tickers: list[str] = []


class ResolveRequest(BaseModel):
    cik: str = Field(min_length=1, max_length=13, pattern=r"^\s*(?:CIK)?\s*\d{1,10}\s*$")


class Resolution(BaseModel):
    """What a searched company supports. outcome, most restrictive first: no_supported_statements,
    score_withheld, partial (some metrics unavailable), full. SEC failures are HTTP errors, not outcomes."""
    company: Optional[CompanySummary]
    outcome: Literal["full", "partial", "score_withheld", "no_supported_statements"]
    message: str
    fiscal_year_end: Optional[str] = None
    metrics_unavailable: list[str] = []
    loan_lab_available: bool = False
    score_status: Optional[str] = None
    gate_reasons: list[str] = []
    sic: Optional[str] = None
    sic_description: Optional[str] = None
    retrieved_at: Optional[str] = None
    source: str


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
    page: Optional[int] = None


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
    source: str = "SEC XBRL companyfacts"
    metrics: dict[str, MetricOut]
    evidence: dict[str, Optional[EvidenceRef]]
    warnings: list[str]
    hard_failures: list[str]
    derived: dict[str, dict] = Field(default_factory=dict, description="values set by logged rules R1-R7")
    supplemental: dict[str, EvidenceRef] = Field(default_factory=dict, description="credit-basis source facts")
    cash_basis: str = "unrestricted"
    unavailable_inputs: list[str] = Field(default_factory=list, description="critical figures marked unavailable")
    sec_check: Optional[str] = None
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


class GridRequest(BaseModel):
    """Stage F heatmap: the loan lab's facility and covenants, stressed over a grid of EBITDA and rate shocks."""
    company_id: str
    fiscal_year_end: Optional[str] = None
    existing_floating_share: float = Field(0.0, ge=0, le=1)
    facility: Optional[Facility] = None
    covenants: Optional[Covenants] = None
    ebitda_shocks: list[float] = Field(default_factory=lambda: [-0.5, -0.4, -0.3, -0.2, -0.1, 0.0, 0.1],
                                       min_length=1, max_length=13)
    rate_shocks_bps: list[float] = Field(default_factory=lambda: [0, 100, 200, 300, 400, 500], min_length=1, max_length=11)


class ScenarioResponse(BaseModel):
    baseline: dict
    results: list[ScenarioResult]
    facility_schedule: list[dict] = []
    snapshot: Optional[dict] = Field(None, description="id + complete inputs; shared with the memo and its PDF")
    disclaimer: str = ("Mechanical sensitivities only; not a forecast, rating or probability of default. "
                       "Analyst review required.")


class FactReview(BaseModel):
    decision: Literal["accept", "correct", "reject"]
    value: Optional[float] = Field(None, description="Corrected value in currency units (not millions)")
    note: Optional[str] = Field(None, max_length=500)


class DocumentMetaUpdate(BaseModel):
    fiscal_year_end: Optional[str] = Field(None, description="YYYY-MM-DD, a real calendar date")
    company_name: Optional[str] = Field(None, max_length=120)
    currency: Optional[Literal["USD", "EUR", "CHF", "GBP", "CAD", "JPY"]] = None
    scale_label: Optional[Literal["units", "thousands", "millions", "billions"]] = None

    @field_validator("fiscal_year_end")
    @classmethod
    def _real_date(cls, v):
        if v is None:
            return v
        try:
            d = date.fromisoformat(v)
        except ValueError:
            raise ValueError(f"{v!r} is not a calendar date (YYYY-MM-DD)")
        if not date(1990, 1, 1) <= d <= date.today() + timedelta(days=366):
            raise ValueError("fiscal year-end must be between 1990 and one year from today")
        return d.isoformat()


class FactEntry(BaseModel):
    field: Literal["revenue", "operating_income", "net_income", "interest_expense", "depreciation_amortization",
                   "operating_cash_flow", "capital_expenditures", "cash", "short_term_borrowings",
                   "current_maturities_ltd", "long_term_debt", "total_assets", "total_liabilities",
                   "stockholders_equity", "current_assets", "current_liabilities"]
    period: Literal["t", "t-1"] = "t"
    value: Optional[float] = Field(None, description="Base currency units (not millions); null = not available")
    page: Optional[int] = Field(None, ge=0, le=5000)
    note: Optional[str] = Field(None, max_length=500)


class MemoRequest(BaseModel):
    company_id: str
    fiscal_year_end: Optional[str] = None
    facility: Optional[Facility] = Field(None, description="Defaults to 100m in the reporting currency")
    covenants: Optional[Covenants] = None
    existing_floating_share: float = Field(0.0, ge=0, le=1)
    shocks: Optional[list[Shock]] = Field(None, description="The loan lab's cases, including 'Your case'")
    use_llm: bool = True


class MemoEdit(BaseModel):
    text: str = Field(..., max_length=1000, description="Rendered sentence text; empty removes the sentence")
