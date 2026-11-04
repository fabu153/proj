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
from pathlib import Path

from backend.app.features.panel import panel_rows  # noqa: F401  (re-exported for tests)


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
