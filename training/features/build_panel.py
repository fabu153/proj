"""Week 2 — SEC companyfacts -> leak-safe company-year panel with t+1 labels.

    python -m training.features.build_panel --universe training/data/universe_v1.csv \
        --out training/data/panel_v1.csv --report training/data/reports/coverage_v1.md

One row per (cik, fiscal_year_end). Year-t canonical facts (USD millions) and derived metrics
are usable from `as_of_date` (latest filing date among the chosen year-t facts). Labels come
ONLY from year t+1, in a separate pass; `label_available_date` is when that outcome became
public and drives the purge gap in chronological splits (Blueprint p.07, p.11).
"""
from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path
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


def panel_rows(companyfacts: dict, meta: Optional[dict] = None) -> list[dict]:
    meta = meta or {}
    years = build_company_years(companyfacts, vintage="original")
    comp = []
    for i, cy in enumerate(years):
        vals = {k: (v / SCALE if v is not None else None) for k, v in engine_inputs(cy).items()}
        prior = None
        if i > 0 and 330 <= (_d(cy.fiscal_year_end) - _d(years[i - 1].fiscal_year_end)).days <= 400:
            prior = {k: (v / SCALE if v is not None else None) for k, v in engine_inputs(years[i - 1]).items()}
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


def main():
    import pandas as pd

    from backend.app.documents.sec_client import SECClient
    from training.pipeline.coverage_report import write_report

    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--refresh", action="store_true", help="re-download companyfacts")
    args = ap.parse_args()

    client = SECClient()
    with open(args.universe) as fh:
        universe = list(csv.DictReader(fh))[: args.limit]
    rows, failures = [], []
    for n, u in enumerate(universe, 1):
        try:
            rows += panel_rows(client.company_facts(u["cik"], refresh=args.refresh), u)
        except Exception as e:  # noqa: BLE001 — keep going; failures go in the coverage report
            failures.append({"cik": u["cik"], "name": u["name"], "error": repr(e)[:200]})
        if n % 50 == 0:
            print(f"  {n}/{len(universe)} companies, {len(rows)} rows")
    df = pd.DataFrame(rows)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    write_report(df, universe, failures, args.report)
    print(f"rows={len(df)} companies_with_rows={df['cik'].nunique()} failures={len(failures)} -> {args.out}")


if __name__ == "__main__":
    main()
