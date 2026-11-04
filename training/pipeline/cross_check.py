"""Week 2 cross-check: panel values vs SEC's own calendar-year frames (independent period selection).

SEC `frames` aggregate one value per filer per calendar period. For December fiscal year-ends,
our annual-period selection must agree with CY<year> (duration) / CY<year>Q4I (instant) frames.
Original-vintage values can legitimately differ from frames when a later filing restated them,
so mismatches are listed with that caveat rather than silently counted as errors.

Also writes docs/manual_cross_check.md — 5 companies with filing links to verify by hand in the 10-K.

    python -m training.pipeline.cross_check
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from backend.app.documents.sec_client import SECClient
from backend.app.documents.xbrl import build_company_years

CHECKS = [("revenue", "Revenues", "duration"), ("revenue", "RevenueFromContractWithCustomerExcludingAssessedTax",
                                                 "duration"),
          ("operating_income", "OperatingIncomeLoss", "duration"), ("total_assets", "Assets", "instant"),
          ("cash", "CashAndCashEquivalentsAtCarryingValue", "instant")]
YEARS = [2014, 2018, 2022]


def main():
    client = SECClient()
    panel = pd.read_csv("training/data/panel_v1.csv", dtype={"cik": str})
    dec = panel[panel["fiscal_year_end"].str[5:] == "12-31"].copy()
    dec["fy"] = dec["fiscal_year_end"].str[:4].astype(int)
    # Frames carry the LATEST value per period; the panel stores the ORIGINAL vintage by design.
    # To test period selection in isolation, rebuild each company with vintage="latest" and compare
    # only where our chosen tag equals the frame's tag.
    latest: dict[tuple[str, str], dict] = {}
    for cik in dec["cik"].unique():
        for cy in build_company_years(client.company_facts(cik), vintage="latest"):
            latest[(cik, cy.fiscal_year_end)] = cy.facts
    rows = []
    for field, tag, ptype in CHECKS:
        for y in YEARS:
            frame = client.frame(tag, f"CY{y}" if ptype == "duration" else f"CY{y}Q4I")
            fv = {str(d["cik"]).zfill(10): d["val"] / 1e6 for d in frame["data"]}
            for _, r in dec[dec["fy"] == y].iterrows():
                f = latest.get((r["cik"], r["fiscal_year_end"]), {}).get(field)
                if f is None or f.tag != tag or r["cik"] not in fv:
                    continue
                ours, theirs = f.value / 1e6, fv[r["cik"]]
                rows.append({"field": field, "tag": tag, "fy": y, "cik": r["cik"], "company": r["company_name"],
                             "pipeline_latest": ours, "panel_original": r[f"v_{field}"], "sec_frame": theirs,
                             "match": abs(ours - theirs) <= max(0.5, 0.005 * abs(theirs))})
    df = pd.DataFrame(rows)
    summary = df.groupby("field")["match"].agg(["size", "mean"]).rename(columns={"size": "comparisons",
                                                                                 "mean": "match_rate"})
    print(summary.to_string())
    restated = (df["pipeline_latest"] - df["panel_original"]).abs() > 0.5
    print(f"share of compared values where original vintage differs from latest (restated): {restated.mean():.1%}")
    out = Path("training/data/reports/cross_check_frames_v1.csv")
    df.to_csv(out, index=False)

    # manual verification sheet: 5 well-covered large December filers, latest fiscal year
    full = panel[(panel["critical_coverage"] == 1) & (panel["fiscal_year_end"] == "2024-12-31") &
                 (panel["size_quintile"] >= 4)].sample(5, random_state=3)
    L = ["# Manual cross-check — verify against the 10-K (FY2024)", "",
         "Open each filing index, find the income statement, balance sheet and cash-flow statement, and tick "
         "each value (USD millions). Record any difference and its cause in the last column.", "",
         "| company | CIK | revenue | operating income | interest expense | D&A | CFO | total assets | "
         "gross debt (engine) | filing index | verified? |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in full.iterrows():
        link = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={r['cik']}&type=10-K"
        L.append(f"| {r['company_name']} | {r['cik']} | {r['v_revenue']:,.1f} | {r['v_operating_income']:,.1f} | "
                 f"{r['v_interest_expense']:,.1f} | {r['v_depreciation_amortization']:,.1f} | "
                 f"{r['v_operating_cash_flow']:,.1f} | {r['v_total_assets']:,.1f} | {r['m_gross_debt']:,.1f} | "
                 f"[10-K list]({link}) | ☐ |")
    Path("docs/manual_cross_check.md").write_text("\n".join(L) + "\n")
    mism = df[~df["match"]]
    print(f"mismatches: {len(mism)} of {len(df)} (see {out})")


if __name__ == "__main__":
    main()
