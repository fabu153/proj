"""Deterministic credit-metric engine (Blueprint p.08).

Every function is pure: inputs in, MetricResult out. No LLM ever computes a
number. Each result carries the formula id/version and the inputs used, so the
memo can link a sentence -> metric -> source facts.

Conventions
-----------
* All amounts must already be in ONE currency and ONE scale (validated upstream).
* Interest expense is a positive number (expense magnitude).
* Capex is a positive number (cash outflow magnitude); a negative input is
  flipped and flagged (XBRL often reports PaymentsToAcquire... as positive,
  but some filers / PDFs show it negative).
* Missing input -> value=None, status=NOT_AVAILABLE. Economically meaningless
  ratio (e.g. leverage on non-positive EBITDA) -> value=None, status=UNDEFINED.
  We never return inf, NaN or a fabricated number.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Optional

FORMULA_VERSION = "1.0.0"


class Status(str, Enum):
    OK = "ok"
    NOT_AVAILABLE = "not_available"   # an input is missing
    UNDEFINED = "undefined"           # inputs present, ratio economically meaningless
    WARNING = "ok_with_warning"       # value computed, but read with a caveat


@dataclass(frozen=True)
class MetricResult:
    metric: str
    value: Optional[float]
    status: Status
    formula: str
    inputs: Mapping[str, Optional[float]] = field(default_factory=dict)
    reason: Optional[str] = None
    unit: str = "ratio"
    formula_version: str = FORMULA_VERSION

    @property
    def available(self) -> bool:
        return self.value is not None


# --------------------------------------------------------------------------- helpers
def _missing(metric: str, formula: str, inputs: dict, unit: str = "ratio") -> Optional[MetricResult]:
    missing = [k for k, v in inputs.items() if v is None]
    if missing:
        return MetricResult(metric, None, Status.NOT_AVAILABLE, formula, inputs,
                            reason=f"missing_input:{','.join(missing)}", unit=unit)
    return None


# --------------------------------------------------------------------------- building blocks
def ebitda(operating_income: Optional[float], d_and_a: Optional[float]) -> MetricResult:
    f = "operating_income + depreciation_amortization"
    inputs = {"operating_income": operating_income, "depreciation_amortization": d_and_a}
    if (m := _missing("ebitda", f, inputs, "amount")):
        return m
    if d_and_a < 0:
        return MetricResult("ebitda", None, Status.UNDEFINED, f, inputs,
                            reason="negative_d_and_a_check_sign", unit="amount")
    return MetricResult("ebitda", operating_income + d_and_a, Status.WARNING, f, inputs,
                        reason="approximate_unadjusted_ebitda_non_gaap", unit="amount")


def gross_debt(short_term_borrowings: Optional[float], current_maturities_ltd: Optional[float],
               long_term_debt_noncurrent: Optional[float]) -> MetricResult:
    """Sum of debt buckets. Leases deliberately excluded (flagged separately).

    Short-term borrowings / current maturities may legitimately be absent (zero);
    the caller passes 0.0 only when the filing confirms none. Long-term debt is required.
    """
    f = "short_term_borrowings + current_maturities_ltd + long_term_debt_noncurrent"
    inputs = {"short_term_borrowings": short_term_borrowings,
              "current_maturities_ltd": current_maturities_ltd,
              "long_term_debt_noncurrent": long_term_debt_noncurrent}
    if (m := _missing("gross_debt", f, inputs, "amount")):
        return m
    parts = (short_term_borrowings, current_maturities_ltd, long_term_debt_noncurrent)
    if any(p < 0 for p in parts):
        return MetricResult("gross_debt", None, Status.UNDEFINED, f, inputs,
                            reason="negative_debt_component", unit="amount")
    return MetricResult("gross_debt", sum(parts), Status.OK, f, inputs,
                        reason="excludes_lease_liabilities", unit="amount")


def net_debt(gross_debt_value: Optional[float], cash: Optional[float]) -> MetricResult:
    f = "gross_debt - unrestricted_cash"
    inputs = {"gross_debt": gross_debt_value, "cash": cash}
    if (m := _missing("net_debt", f, inputs, "amount")):
        return m
    v = gross_debt_value - cash
    return MetricResult("net_debt", v, Status.WARNING if v < 0 else Status.OK, f, inputs,
                        reason="net_cash_position" if v < 0 else None, unit="amount")


# --------------------------------------------------------------------------- ratios
def revenue_growth(revenue_t: Optional[float], revenue_t_minus_1: Optional[float]) -> MetricResult:
    f = "revenue_t / revenue_t-1 - 1"
    inputs = {"revenue_t": revenue_t, "revenue_t-1": revenue_t_minus_1}
    if (m := _missing("revenue_growth", f, inputs, "pct")):
        return m
    if revenue_t_minus_1 <= 0:
        return MetricResult("revenue_growth", None, Status.UNDEFINED, f, inputs,
                            reason="non_positive_prior_revenue", unit="pct")
    return MetricResult("revenue_growth", revenue_t / revenue_t_minus_1 - 1, Status.OK, f, inputs, unit="pct")


def ebitda_margin(ebitda_value: Optional[float], revenue: Optional[float]) -> MetricResult:
    f = "ebitda / revenue"
    inputs = {"ebitda": ebitda_value, "revenue": revenue}
    if (m := _missing("ebitda_margin", f, inputs, "pct")):
        return m
    if revenue <= 0:
        return MetricResult("ebitda_margin", None, Status.UNDEFINED, f, inputs,
                            reason="non_positive_revenue", unit="pct")
    return MetricResult("ebitda_margin", ebitda_value / revenue, Status.OK, f, inputs, unit="pct")


def leverage(debt: Optional[float], ebitda_value: Optional[float], *, net: bool) -> MetricResult:
    name = "net_leverage" if net else "gross_leverage"
    f = ("net_debt / ebitda" if net else "gross_debt / ebitda")
    inputs = {"net_debt" if net else "gross_debt": debt, "ebitda": ebitda_value}
    if (m := _missing(name, f, inputs, "x")):
        return m
    if ebitda_value <= 0:
        return MetricResult(name, None, Status.UNDEFINED, f, inputs,
                            reason="non_positive_ebitda_leverage_undefined", unit="x")
    v = debt / ebitda_value
    if net and debt < 0:
        return MetricResult(name, v, Status.WARNING, f, inputs, reason="net_cash_negative_leverage", unit="x")
    return MetricResult(name, v, Status.OK, f, inputs, unit="x")


def interest_cover(earnings: Optional[float], interest_expense: Optional[float], *, basis: str) -> MetricResult:
    """basis = 'ebit' or 'ebitda'. EBITDA cover is NOT a DSCR."""
    assert basis in ("ebit", "ebitda")
    name = f"{basis}_interest_cover"
    f = f"{basis} / interest_expense"
    inputs = {basis: earnings, "interest_expense": interest_expense}
    if (m := _missing(name, f, inputs, "x")):
        return m
    if interest_expense <= 0:
        return MetricResult(name, None, Status.UNDEFINED, f, inputs,
                            reason="non_positive_interest_expense", unit="x")
    v = earnings / interest_expense
    if earnings <= 0:
        return MetricResult(name, v, Status.WARNING, f, inputs, reason="non_positive_earnings", unit="x")
    return MetricResult(name, v, Status.OK, f, inputs, unit="x")


def free_cash_flow(cfo: Optional[float], capex: Optional[float]) -> MetricResult:
    f = "cfo - capex"
    inputs = {"cfo": cfo, "capex": capex}
    if (m := _missing("fcf_simple", f, inputs, "amount")):
        return m
    reason = "simple_fcf_after_interest_paid_per_us_gaap_cfo"
    if capex < 0:   # sign-convention fix, flagged
        capex = -capex
        reason += ";capex_sign_flipped"
    return MetricResult("fcf_simple", cfo - capex, Status.OK, f, {"cfo": cfo, "capex": capex},
                        reason=reason, unit="amount")


def current_ratio(current_assets: Optional[float], current_liabilities: Optional[float]) -> MetricResult:
    f = "current_assets / current_liabilities"
    inputs = {"current_assets": current_assets, "current_liabilities": current_liabilities}
    if (m := _missing("current_ratio", f, inputs, "x")):
        return m
    if current_liabilities <= 0:
        return MetricResult("current_ratio", None, Status.UNDEFINED, f, inputs,
                            reason="non_positive_current_liabilities", unit="x")
    return MetricResult("current_ratio", current_assets / current_liabilities, Status.OK, f, inputs, unit="x")


def debt_to_assets(gross_debt_value: Optional[float], total_assets: Optional[float]) -> MetricResult:
    f = "gross_debt / total_assets"
    inputs = {"gross_debt": gross_debt_value, "total_assets": total_assets}
    if (m := _missing("debt_to_assets", f, inputs, "pct")):
        return m
    if total_assets <= 0:
        return MetricResult("debt_to_assets", None, Status.UNDEFINED, f, inputs,
                            reason="non_positive_total_assets", unit="pct")
    return MetricResult("debt_to_assets", gross_debt_value / total_assets, Status.OK, f, inputs, unit="pct")


# --------------------------------------------------------------------------- full panel
def compute_all(fy: Mapping[str, Optional[float]], prior: Optional[Mapping[str, Optional[float]]] = None
                ) -> dict[str, MetricResult]:
    """Compute the whole metric dictionary for one company-year of canonical facts."""
    g = fy.get
    out: dict[str, MetricResult] = {}
    out["ebitda"] = e = ebitda(g("operating_income"), g("depreciation_amortization"))
    out["gross_debt"] = gd = gross_debt(g("short_term_borrowings"), g("current_maturities_ltd"),
                                        g("long_term_debt"))
    out["net_debt"] = nd = net_debt(gd.value, g("cash"))
    out["revenue_growth"] = revenue_growth(g("revenue"), prior.get("revenue") if prior else None)
    out["ebitda_margin"] = ebitda_margin(e.value, g("revenue"))
    out["gross_leverage"] = leverage(gd.value, e.value, net=False)
    out["net_leverage"] = leverage(nd.value, e.value, net=True)
    out["ebit_interest_cover"] = interest_cover(g("operating_income"), g("interest_expense"), basis="ebit")
    out["ebitda_interest_cover"] = interest_cover(e.value, g("interest_expense"), basis="ebitda")
    out["fcf_simple"] = free_cash_flow(g("operating_cash_flow"), g("capital_expenditures"))
    out["current_ratio"] = current_ratio(g("current_assets"), g("current_liabilities"))
    out["debt_to_assets"] = debt_to_assets(gd.value, g("total_assets"))
    return out
