"""Company-year panel rows: year-t facts + metrics, and t+1 labels built in a separate pass.

Shared by the training pipeline (training/features/build_panel.py) and the API, so a prediction
is made from exactly the same row definition the model was trained on.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from backend.app.documents.xbrl import HELPER_FIELDS, TAG_REGISTRY, build_company_years, engine_inputs
from backend.app.finance.metrics import compute_all
from backend.app.labels.stress_label import LABEL_VERSION, onset_label, stress_label

SCALE = 1_000_000
CANONICAL = [k for k in TAG_REGISTRY if k not in HELPER_FIELDS]
METRICS = ["ebitda", "gross_debt", "net_debt", "fcf_simple", "ebitda_margin", "gross_leverage", "net_leverage",
           "ebit_interest_cover", "ebitda_interest_cover", "current_ratio", "debt_to_assets", "revenue_growth"]
CRITICAL = ["revenue", "operating_income", "interest_expense", "depreciation_amortization",
            "operating_cash_flow", "long_term_debt", "total_assets"]


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _label_inputs(vals: dict, m: dict) -> dict:
    return {**vals, "ebitda": m["ebitda"].value, "gross_debt": m["gross_debt"].value}


def panel_rows(companyfacts: dict, meta: Optional[dict] = None, as_of: Optional[str] = None) -> list[dict]:
    meta = meta or {}
    years = build_company_years(companyfacts, as_of=as_of, vintage="original")
    comp = []
    for i, cy in enumerate(years):
        vals = {k: (v / SCALE if v is not None else None) for k, v in engine_inputs(cy, basis="model").items()}
        prior = None
        if i > 0 and 330 <= (_d(cy.fiscal_year_end) - _d(years[i - 1].fiscal_year_end)).days <= 400:
            prior = {k: (v / SCALE if v is not None else None) for k, v in engine_inputs(years[i - 1], basis="model").items()}
        comp.append((cy, vals, compute_all(vals, prior)))

    rows = []
    for i, (cy, vals, m) in enumerate(comp):
        cur = stress_label(_label_inputs(vals, m))
        row = {"cik": cy.cik, "company_name": cy.company_name, "sic": meta.get("sic"),
               "size_quintile": meta.get("size_quintile"), "fiscal_year_end": cy.fiscal_year_end,
               "as_of_date": cy.available_as_of, "scorable": int(cy.scorable),
               "n_warnings": len(cy.warnings), "hard_failures": "|".join(cy.hard_failures),
               "critical_coverage": sum(vals.get(k) is not None for k in CRITICAL) / len(CRITICAL)}
        row.update({f"v_{k}": vals.get(k) for k in CANONICAL})
        row.update({f"m_{k}": m[k].value for k in METRICS})
        row.update(stress_t=cur.label, cond_cov_t=cur.coverage_weak, cond_lev_t=cur.leverage_high,
                   cond_cfo_t=cur.cash_flow_weak)
        nxt_ok = (i + 1 < len(comp) and
                  330 <= (_d(comp[i + 1][0].fiscal_year_end) - _d(cy.fiscal_year_end)).days <= 400)
        if nxt_ok and comp[i + 1][0].scorable:
            ncy, nvals, nm = comp[i + 1]
            nxt = stress_label(_label_inputs(nvals, nm))
            row.update(label_next_fy=nxt.label, label_onset=onset_label(cur, nxt),
                       label_available_date=ncy.available_as_of, label_reason=nxt.reason or "")
        else:
            row.update(label_next_fy=None, label_onset=None, label_available_date=None,
                       label_reason="no_consecutive_t+1" if not nxt_ok else "t+1_failed_hard_checks")
        row["label_version"] = LABEL_VERSION
        rows.append(row)
    return rows
