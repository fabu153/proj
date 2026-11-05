"""Week 3 — feature dictionary (Blueprint p.10-11): ratios, trends and missingness masks.

Every feature is a ratio or change of ratios (no raw size except one log-assets control).
All are computed from year-t facts (and t-1 for trends, only when fiscal years are
consecutive). Nothing from t+1 is ever touched here — labels live in the panel separately.

FEATURE_VERSION must be bumped whenever a definition changes.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FEATURE_VERSION = "features_v1"


def _div(a: pd.Series, b: pd.Series, positive_den: bool = True) -> pd.Series:
    den = b.where(b > 0) if positive_den else b.where(b != 0)
    return a / den


# name -> (description, unit). Order = model input order.
FEATURE_DICTIONARY: dict[str, tuple[str, str]] = {
    # profitability
    "ebitda_margin": ("(operating income + D&A) / revenue", "pct"),
    "operating_margin": ("operating income / revenue", "pct"),
    "net_margin": ("net income / revenue", "pct"),
    "roa": ("net income / total assets", "pct"),
    # cash generation
    "cfo_margin": ("operating cash flow / revenue", "pct"),
    "cfo_to_assets": ("operating cash flow / total assets", "pct"),
    "fcf_margin": ("(CFO - capex) / revenue", "pct"),
    "capex_intensity": ("capex / revenue", "pct"),
    # leverage & capital structure
    "gross_leverage": ("gross debt / EBITDA (undefined if EBITDA <= 0)", "x"),
    "net_leverage": ("net debt / EBITDA (undefined if EBITDA <= 0)", "x"),
    "debt_to_assets": ("gross debt / total assets", "pct"),
    "liabilities_to_assets": ("total liabilities / total assets", "pct"),
    "equity_to_assets": ("stockholders' equity / total assets", "pct"),
    "cfo_to_debt": ("operating cash flow / gross debt (undefined if no debt)", "x"),
    "fcf_to_debt": ("(CFO - capex) / gross debt (undefined if no debt)", "x"),
    # coverage & funding cost
    "ebit_interest_cover": ("operating income / interest expense", "x"),
    "ebitda_interest_cover": ("EBITDA / interest expense", "x"),
    "implied_cost_of_debt": ("interest expense / gross debt", "pct"),
    # liquidity
    "current_ratio": ("current assets / current liabilities", "x"),
    "cash_to_assets": ("cash / total assets", "pct"),
    "cash_to_current_liabilities": ("cash / current liabilities", "x"),
    "short_term_debt_share": ("(short-term borrowings + current LTD) / gross debt", "pct"),
    # size control
    "log_assets": ("ln(total assets, USD m)", "log"),
    # trends (t vs t-1, consecutive years only)
    "revenue_growth": ("revenue_t / revenue_t-1 - 1", "pct"),
    "d_ebitda_margin": ("change in EBITDA margin", "pp"),
    "d_debt_to_assets": ("change in debt / assets", "pp"),
    "debt_growth": ("gross debt_t / gross debt_t-1 - 1", "pct"),
    "d_cfo_to_assets": ("change in CFO / assets", "pp"),
    # current-state indicators (year t, label-rule logic applied to t only)
    "ebitda_nonpositive": ("1 if EBITDA <= 0", "flag"),
    "no_debt": ("1 if gross debt == 0", "flag"),
    "stress_conditions_t": ("number of the 3 stress conditions met in year t (unknown = 0, masked)", "count"),
}
FEATURES = list(FEATURE_DICTIONARY)

# Display grouping for the Model X-Ray (same order as the dictionary; not used by the model).
FEATURE_GROUPS: dict[str, list[str]] = {
    "Profitability": ["ebitda_margin", "operating_margin", "net_margin", "roa"],
    "Cash generation": ["cfo_margin", "cfo_to_assets", "fcf_margin", "capex_intensity"],
    "Leverage and capital structure": ["gross_leverage", "net_leverage", "debt_to_assets", "liabilities_to_assets",
                                       "equity_to_assets", "cfo_to_debt", "fcf_to_debt"],
    "Coverage and funding cost": ["ebit_interest_cover", "ebitda_interest_cover", "implied_cost_of_debt"],
    "Liquidity": ["current_ratio", "cash_to_assets", "cash_to_current_liabilities", "short_term_debt_share"],
    "Size": ["log_assets"],
    "Year-on-year trends": ["revenue_growth", "d_ebitda_margin", "d_debt_to_assets", "debt_growth", "d_cfo_to_assets"],
    "Current-state flags": ["ebitda_nonpositive", "no_debt", "stress_conditions_t"],
}
FLAG_FEATURES = {"ebitda_nonpositive", "no_debt", "stress_conditions_t"}


def build_features(panel: pd.DataFrame) -> pd.DataFrame:
    """Return panel identity/label columns + FEATURES (NaN where undefined)."""
    p = panel.sort_values(["cik", "fiscal_year_end"]).copy()
    v = lambda k: p[f"v_{k}"].astype(float)  # noqa: E731
    rev, oi, ni, ta = v("revenue"), v("operating_income"), v("net_income"), v("total_assets")
    cfo, capex = v("operating_cash_flow"), v("capital_expenditures").abs()
    ebitda, gd = p["m_ebitda"].astype(float), p["m_gross_debt"].astype(float)
    fcf = cfo - capex
    f = pd.DataFrame(index=p.index)
    f["ebitda_margin"] = _div(ebitda, rev)
    f["operating_margin"] = _div(oi, rev)
    f["net_margin"] = _div(ni, rev)
    f["roa"] = _div(ni, ta)
    f["cfo_margin"] = _div(cfo, rev)
    f["cfo_to_assets"] = _div(cfo, ta)
    f["fcf_margin"] = _div(fcf, rev)
    f["capex_intensity"] = _div(capex, rev)
    f["gross_leverage"] = p["m_gross_leverage"].astype(float)
    f["net_leverage"] = p["m_net_leverage"].astype(float)
    f["debt_to_assets"] = _div(gd, ta)
    f["liabilities_to_assets"] = _div(v("total_liabilities"), ta)
    f["equity_to_assets"] = _div(v("stockholders_equity"), ta)
    f["cfo_to_debt"] = _div(cfo, gd)
    f["fcf_to_debt"] = _div(fcf, gd)
    f["ebit_interest_cover"] = p["m_ebit_interest_cover"].astype(float)
    f["ebitda_interest_cover"] = p["m_ebitda_interest_cover"].astype(float)
    f["implied_cost_of_debt"] = _div(v("interest_expense"), gd)
    f["current_ratio"] = p["m_current_ratio"].astype(float)
    f["cash_to_assets"] = _div(v("cash"), ta)
    f["cash_to_current_liabilities"] = _div(v("cash"), v("current_liabilities"))
    f["short_term_debt_share"] = _div(v("short_term_borrowings").fillna(0) + v("current_maturities_ltd").fillna(0), gd)
    f["log_assets"] = np.log(ta.where(ta > 0))

    # trends: only when previous row is the same company AND the previous consecutive fiscal year
    fye = pd.to_datetime(p["fiscal_year_end"])
    consecutive = (p["cik"] == p["cik"].shift(1)) & ((fye - fye.shift(1)).dt.days.between(330, 400))
    prev = lambda s: s.shift(1).where(consecutive)  # noqa: E731
    f["revenue_growth"] = p["m_revenue_growth"].astype(float)
    f["d_ebitda_margin"] = f["ebitda_margin"] - prev(f["ebitda_margin"])
    f["d_debt_to_assets"] = f["debt_to_assets"] - prev(f["debt_to_assets"])
    f["debt_growth"] = _div(gd, prev(gd)) - 1
    f["d_cfo_to_assets"] = f["cfo_to_assets"] - prev(f["cfo_to_assets"])

    f["ebitda_nonpositive"] = (ebitda <= 0).astype(float).where(ebitda.notna())
    f["no_debt"] = (gd == 0).astype(float).where(gd.notna())
    conds = p[["cond_cov_t", "cond_lev_t", "cond_cfo_t"]]
    f["stress_conditions_t"] = conds.apply(lambda c: c.map({True: 1.0, False: 0.0, "True": 1.0, "False": 0.0}))\
        .sum(axis=1, min_count=1)

    f = f.replace([np.inf, -np.inf], np.nan)
    keep = ["cik", "company_name", "sic", "size_quintile", "fiscal_year_end", "as_of_date", "scorable",
            "critical_coverage", "stress_t", "label_next_fy", "label_onset", "label_available_date"]
    return pd.concat([p[keep], f[FEATURES]], axis=1)


# Plain-language names for memos and the UI (frontend/lib/labels.ts mirrors these).
FEATURE_LABELS: dict[str, str] = {
    "ebitda_margin": "EBITDA margin", "operating_margin": "operating margin", "net_margin": "net margin",
    "roa": "return on assets", "cfo_margin": "operating cash flow margin", "cfo_to_assets": "operating cash flow to assets",
    "fcf_margin": "free cash flow margin", "capex_intensity": "capex to revenue", "gross_leverage": "gross debt to EBITDA",
    "net_leverage": "net debt to EBITDA", "debt_to_assets": "debt to assets", "liabilities_to_assets": "liabilities to assets",
    "equity_to_assets": "equity to assets", "cfo_to_debt": "operating cash flow to debt", "fcf_to_debt": "free cash flow to debt",
    "ebit_interest_cover": "EBIT interest cover", "ebitda_interest_cover": "EBITDA interest cover",
    "implied_cost_of_debt": "interest cost of debt", "current_ratio": "current ratio", "cash_to_assets": "cash to assets",
    "cash_to_current_liabilities": "cash to current liabilities", "short_term_debt_share": "share of debt due within a year",
    "log_assets": "company size", "revenue_growth": "revenue growth", "d_ebitda_margin": "change in EBITDA margin",
    "d_debt_to_assets": "change in debt to assets", "debt_growth": "debt growth",
    "d_cfo_to_assets": "change in cash flow to assets", "ebitda_nonpositive": "zero or negative EBITDA",
    "no_debt": "having no debt", "stress_conditions_t": "stress tests already failed this year",
}
