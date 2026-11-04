"""CreditAnalysisPackage (Blueprint p.14): every value a memo may cite, each with an ID and a source.

The package is the ONLY source of numbers for the memo. Writers reference items by ID
(`{{metric.net_leverage.t}}`), the renderer substitutes the formatted value, and the evidence
appendix lists each cited item's provenance: filing/page, formula, model or scenario assumption.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

from ..documents.xbrl import build_company_years, engine_inputs
from ..finance.metrics import compute_all
from ..models import risk as risk_service
from ..scenarios.loan import Baseline, Covenants, Facility, Shock, UseOfProceeds, run_scenario

SCALE = 1_000_000
FACT_FIELDS = ["revenue", "operating_income", "net_income", "interest_expense", "depreciation_amortization",
               "operating_cash_flow", "capital_expenditures", "cash", "total_assets"]
FACT_LABELS = {"revenue": "Revenue", "operating_income": "Operating income", "net_income": "Net income",
               "interest_expense": "Interest expense", "depreciation_amortization": "Depreciation and amortization",
               "operating_cash_flow": "Operating cash flow", "capital_expenditures": "Capital expenditures",
               "cash": "Cash and equivalents", "total_assets": "Total assets"}
METRIC_LABELS = {"ebitda": ("EBITDA (approx.)", "amount"), "ebitda_margin": ("EBITDA margin", "pct"),
                 "revenue_growth": ("Revenue growth", "pct"), "gross_debt": ("Gross debt", "amount"),
                 "net_debt": ("Net debt", "amount"), "gross_leverage": ("Gross debt / EBITDA", "x"),
                 "net_leverage": ("Net debt / EBITDA", "x"), "ebit_interest_cover": ("EBIT / interest", "x"),
                 "ebitda_interest_cover": ("EBITDA / interest", "x"), "fcf_simple": ("Free cash flow (CFO − capex)", "amount"),
                 "current_ratio": ("Current ratio", "x")}
USE_TEXT = {"capex": "capital expenditure", "acquisition": "an acquisition", "refinancing": "refinancing existing debt",
            "retained_cash": "general liquidity (held as cash)"}
CASES = {"base": Shock(name="base"), "downside": Shock(name="downside", ebitda_shock=-0.20, rate_shock_bps=200),
         "severe": Shock(name="severe", ebitda_shock=-0.35, rate_shock_bps=400)}


def fmt(value: Any, unit: str, ccy: str = "USD") -> str:
    if value is None:
        return "not available"
    if unit == "text":
        return str(value)
    if unit == "amount":
        s = f"{abs(value):,.0f}m" if abs(value) >= 100 else f"{abs(value):,.1f}m"
        return f"{ccy} {'-' if value < 0 else ''}{s}"
    if unit == "pct":
        return f"{value * 100:.1f}%"
    if unit == "pp":
        return f"{value * 100:+.1f} percentage points"
    if unit == "x":
        return f"{value:.2f}x"
    if unit == "prob":
        return f"{value * 100:.1f}%"
    if unit == "bp":
        return f"{value:+.0f} bp"
    if unit == "ratio":
        return f"{value:.3f}"
    return f"{value:,.2f}"


class Package:
    def __init__(self, currency: str):
        self.ccy = currency
        self.items: dict[str, dict] = {}

    def add(self, item_id: str, label: str, value: Any, unit: str, source: dict) -> None:
        self.items[item_id] = {"id": item_id, "label": label, "value": value, "unit": unit,
                               "display": fmt(value, unit, self.ccy), "source": source}

    def has(self, item_id: str) -> bool:
        return item_id in self.items and self.items[item_id]["value"] is not None

    def val(self, item_id: str) -> Any:
        return self.items[item_id]["value"] if item_id in self.items else None

    def sha256(self) -> str:
        return hashlib.sha256(json.dumps(self.items, sort_keys=True, default=str).encode()).hexdigest()


def build_package(companyfacts: dict, company_id: str, fiscal_year_end: Optional[str], facility: Optional[Facility],
                  covenants: Optional[Covenants], existing_floating_share: float = 0.0) -> Package:
    years = build_company_years(companyfacts)
    if not years:
        raise ValueError("No annual data available")
    idx = len(years) - 1 if fiscal_year_end is None else next(
        i for i, y in enumerate(years) if y.fiscal_year_end == fiscal_year_end)
    cy = years[idx]
    prior = years[idx - 1] if idx > 0 else None
    ccy = companyfacts.get("currency", "USD")
    pk = Package(ccy)
    src_kind = companyfacts.get("source", "SEC XBRL companyfacts")
    pk.add("meta.company", "Borrower", companyfacts.get("entityName", company_id).replace(" (uploaded report)", ""),
           "text", {"kind": "identity", "detail": src_kind})
    pk.add("meta.fye", "Fiscal year end", cy.fiscal_year_end, "text", {"kind": "identity", "detail": src_kind})
    pk.add("meta.source", "Data source", "an uploaded annual report" if "Uploaded" in src_kind else "SEC 10-K XBRL filings",
           "text", {"kind": "identity", "detail": src_kind})

    def scaled(c):
        return {k: (v / SCALE if v is not None else None) for k, v in engine_inputs(c).items()}

    v_t = scaled(cy)
    v_p = scaled(prior) if prior else None
    for tag, vals, year in (("t", v_t, cy), ("t1", v_p, prior)):
        if vals is None:
            continue
        for f in FACT_FIELDS:
            fact = year.facts.get(f)
            src = {"kind": "filing", "fiscal_year_end": year.fiscal_year_end}
            if fact:
                src.update(tag=fact.tag, accession=fact.accession, filed=fact.filed, page=fact.page,
                           method=fact.extraction_method)
            pk.add(f"fact.{f}.{tag}", f"{FACT_LABELS[f]} ({year.fiscal_year_end[:4]})", vals.get(f), "amount", src)
        prior_vals = v_p if tag == "t" else None
        m = compute_all(vals, prior_vals)
        for k, (label, unit) in METRIC_LABELS.items():
            r = m[k]
            pk.add(f"metric.{k}.{tag}", f"{label} ({year.fiscal_year_end[:4]})", r.value, unit,
                   {"kind": "formula", "formula": r.formula, "version": r.formula_version, "status": r.status.value,
                    "note": r.reason, "fiscal_year_end": year.fiscal_year_end})
    if pk.has("metric.revenue_growth.t"):
        pk.add("metric.revenue_growth.abs", "Size of revenue change", abs(pk.val("metric.revenue_growth.t")), "pct",
               {"kind": "formula", "formula": "|revenue_t / revenue_t-1 - 1|", "version": "1.0.0"})
    if pk.has("metric.ebitda_margin.t") and pk.has("metric.ebitda_margin.t1"):
        pk.add("metric.ebitda_margin.change", "Change in EBITDA margin",
               pk.val("metric.ebitda_margin.t") - pk.val("metric.ebitda_margin.t1"), "pp",
               {"kind": "formula", "formula": "ebitda_margin_t - ebitda_margin_t-1", "version": "1.0.0"})
    pk.add("data.warning_count", "Data-quality warnings", len(cy.warnings), "text",
           {"kind": "data_checks", "warnings": cy.warnings, "derived": {k: r for k, (_, r) in cy.derived.items()}})

    # ---------------- neural screen
    r = risk_service.score(companyfacts, cy.fiscal_year_end)
    pk.add("risk.status", "Stress screen status", r.get("status"), "text", {"kind": "model"})
    if r.get("status") == "scored":
        model_src = {"kind": "model", **(r.get("model") or {}), "features_as_of": r.get("features_as_of"),
                     "sample_period": r.get("sample_period")}
        pk.add("risk.probability", "Next-FY accounting-stress probability", r["probability"], "prob", model_src)
        pk.add("risk.band", "Screening band", r["band"], "text", model_src)
        for i, d in enumerate(r.get("drivers", [])[:3], 1):
            from ..features.feature_set import FEATURE_LABELS  # local import avoids a cycle at module load
            direction = "raising" if d["logit_contribution"] > 0 else "lowering"
            pk.add(f"risk.driver.{i}", f"Model driver {i}",
                   f"{FEATURE_LABELS.get(d['feature'], d['feature'])} ({direction} the score)", "text",
                   {"kind": "model", "attribution": "occlusion, log-odds", "logit_contribution": d["logit_contribution"]})
        m = r.get("model") or {}
        pk.add("model.test_pr_auc", "Model held-out PR-AUC", m.get("test_pr_auc"), "ratio",
               {"kind": "model_evaluation", "ci95": m.get("test_pr_auc_ci95")})
        pk.add("model.xgb_pr_auc", "XGBoost benchmark PR-AUC", m.get("xgboost_benchmark_test_pr_auc"), "ratio",
               {"kind": "model_evaluation"})
    elif r.get("status") == "withheld":
        pk.add("risk.gate", "Reason the screen was withheld", "; ".join(r.get("gate_reasons", [])), "text",
               {"kind": "model"})

    # ---------------- facility and scenarios
    if facility is not None:
        amt_src = {"kind": "assumption", "detail": "entered in the loan lab"}
        pk.add("facility.amount", "Facility amount",
               f"{facility.currency} {facility.amount:,.0f}m", "text", amt_src)
        pk.add("facility.coupon", "All-in coupon", facility.coupon, "pct", amt_src)
        pk.add("facility.tenor", "Tenor", f"{facility.tenor_years}-year", "text", amt_src)
        pk.add("facility.structure", "Structure",
               ("floating-rate " if facility.floating else "fixed-rate ") +
               ("bullet" if facility.annual_amortization == 0 else "amortizing"), "text", amt_src)
        pk.add("facility.use", "Use of proceeds", USE_TEXT[UseOfProceeds(facility.use_of_proceeds).value], "text", amt_src)
        m_t = compute_all(v_t)
        needed = {"ebitda": m_t["ebitda"].value, "gross_debt": m_t["gross_debt"].value, "cash": v_t.get("cash"),
                  "interest_expense": v_t.get("interest_expense")}
        if all(x is not None for x in needed.values()):
            base = Baseline(currency=ccy, existing_floating_share=existing_floating_share, **needed)
            if covenants:
                if covenants.max_net_leverage is not None:
                    pk.add("covenant.max_net_leverage", "Covenant: maximum net leverage", covenants.max_net_leverage,
                           "x", amt_src)
                if covenants.min_ebitda_interest_cover is not None:
                    pk.add("covenant.min_cover", "Covenant: minimum EBITDA cover",
                           covenants.min_ebitda_interest_cover, "x", amt_src)
            for name, shock in CASES.items():
                res = run_scenario(base, facility, shock, covenants)
                src = {"kind": "scenario", "case": name, "ebitda_shock": shock.ebitda_shock,
                       "rate_shock_bps": shock.rate_shock_bps, "steps": res.steps, "engine_version": res.engine_version}
                pk.add(f"scen.{name}.assumptions", f"{name.title()} case assumptions",
                       f"EBITDA {shock.ebitda_shock:+.0%}, rates {shock.rate_shock_bps:+.0f} bp" if name != "base"
                       else "no EBITDA or rate shock", "text", src)
                for k, label, unit in (("gross_debt", "gross debt", "amount"), ("net_debt", "net debt", "amount"),
                                       ("ebitda", "EBITDA", "amount"), ("interest_expense", "interest", "amount"),
                                       ("net_leverage", "net debt / EBITDA", "x"),
                                       ("ebitda_interest_cover", "EBITDA / interest", "x")):
                    pk.add(f"scen.{name}.{k}", f"{name.title()} case {label}", getattr(res, k), unit, src)
                for cov_key, item in (("max_net_leverage", "headroom_lev"), ("min_ebitda_interest_cover", "headroom_cov")):
                    if cov_key in res.covenant_headroom:
                        h = res.covenant_headroom[cov_key]
                        pk.add(f"scen.{name}.{item}", f"{name.title()} case headroom ({cov_key.replace('_', ' ')})",
                               h, "x", src)
                        if h is not None and h < 0:   # shortfall as a positive magnitude, for readable breach wording
                            pk.add(f"scen.{name}.{item}_shortfall",
                                   f"{name.title()} case covenant shortfall ({cov_key.replace('_', ' ')})", -h, "x", src)
        else:
            pk.add("scen.unavailable", "Scenario inputs missing",
                   ", ".join(k for k, x in needed.items() if x is None), "text", {"kind": "data_checks"})
    pk.add("meta.generated_at", "Package built", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "text",
           {"kind": "identity"})
    return pk
