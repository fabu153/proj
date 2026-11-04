"""Reviewed upload -> SEC-shaped companyfacts, so every engine runs unchanged on an annual report.

Gate (Week 6 exit criterion): a document can only be analysed when no CRITICAL fact for the
latest year is still awaiting review and the fiscal year-end has been confirmed. High-confidence
facts are accepted automatically but remain visible and correctable until finalization.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from .pdf_extract import CRITICAL
from .xbrl import TAG_REGISTRY, build_company_years

DURATION = {k for k, (ptype, _) in TAG_REGISTRY.items() if ptype == "duration"}


SCALES = {"units": 1.0, "thousands": 1e3, "millions": 1e6, "billions": 1e9}
CURRENCIES = ("USD", "EUR", "CHF", "GBP", "CAD", "JPY")
FIELD_NAMES = {"revenue": "revenue", "operating_income": "operating income", "interest_expense": "interest expense",
               "depreciation_amortization": "depreciation and amortization",
               "operating_cash_flow": "operating cash flow", "long_term_debt": "long-term debt",
               "total_assets": "total assets"}


def effective_value(f: dict) -> Optional[float]:
    if f["status"] in ("auto_accepted", "accepted", "manual"):
        return f["value"]
    if f["status"] == "corrected":
        return f["reviewed_value"]
    return None   # rejected, marked unavailable, or still needs review


def valid_fiscal_year_end(s: Optional[str]) -> bool:
    try:
        d = date.fromisoformat(s or "")
    except ValueError:
        return False
    return date(1990, 1, 1) <= d <= date.today() + timedelta(days=366)


def blocking_reasons(doc: dict) -> list[str]:
    """Everything that must be resolved before the reviewed figures can be analysed (test DATA-01)."""
    out = []
    if not doc.get("currency"):
        out.append("Confirm the reporting currency (not stated on the statements)")
    if not doc.get("scale_label"):
        out.append("Confirm the unit scale: units, thousands, millions or billions (not stated on the statements)")
    if doc["fye_inferred"] or not valid_fiscal_year_end(doc["fiscal_year_end"]):
        out.append("Confirm the fiscal year-end date (not stated on the statements, or not a valid date)")
    present = {f["field"] for f in doc["facts"] if f["period"] == "t"}
    for fld in CRITICAL:
        if fld not in present:
            out.append(f"Not found: {FIELD_NAMES[fld]}. Enter it from the report or mark it unavailable")
    for f in doc["facts"]:
        if f["period"] == "t" and f["field"] in CRITICAL and f["status"] == "needs_review":
            out.append(f"Review {FIELD_NAMES[f['field']]} (page {f['page']}): {'; '.join(f['reasons'])}")
    return out


def unavailable_critical(doc: dict) -> list[str]:
    """Critical figures the analysis will run without (rejected or marked unavailable): shown, never zero-filled."""
    return [FIELD_NAMES[f["field"]] for f in doc["facts"]
            if f["period"] == "t" and f["field"] in CRITICAL and f["status"] in ("rejected", "unavailable")]


def to_companyfacts(doc: dict) -> dict:
    fye_t = date.fromisoformat(doc["fiscal_year_end"])
    ends = {"t": fye_t, "t-1": fye_t - timedelta(days=364)}
    filed = (doc["finalized_at"] or doc["created_at"])[:10]
    facts: dict = {}
    for f in doc["facts"]:
        v = effective_value(f)
        if v is None or f["field"] not in TAG_REGISTRY:
            continue
        end = ends[f["period"]]
        e = {"end": end.isoformat(), "val": v, "accn": f"upload-{doc['id'][:8]}", "form": "10-K", "filed": filed,
             "fy": end.year, "fp": "FY", "page": f["page"], "extraction_method": f"PDF ({f['status'].replace('_', ' ')})"}
        if f["field"] in DURATION:
            e["start"] = (end - timedelta(days=364)).isoformat()
        tag = TAG_REGISTRY[f["field"]][1][0]
        facts.setdefault(tag, {"units": {"USD": []}})["units"]["USD"].append(e)
    return {"cik": doc["company_id"], "entityName": f"{doc['company_name']} (uploaded report)",
            "facts": {"us-gaap": facts}, "currency": doc["currency"], "source": "Uploaded annual report",
            "unavailable_critical": unavailable_critical(doc), "sec_check": doc.get("sec_check")}


def cross_check_xbrl(extraction: dict, companyfacts: dict, tolerance: float = 0.005) -> int:
    """Compare latest-year candidates with SEC XBRL for the same fiscal year; mismatches need review."""
    years = {y.fiscal_year_end: y for y in build_company_years(companyfacts)}
    fye = extraction.get("fiscal_year_end")
    # allow a few days of slack for 52/53-week calendars
    match = next((y for k, y in years.items() if fye and abs((date.fromisoformat(k) - date.fromisoformat(fye)).days) <= 7), None)
    if match is None:
        extraction["issues"].append("No SEC XBRL year matches this fiscal year-end; cross-check skipped")
        extraction["sec_check"] = "Not checked against SEC: no SEC fiscal year matches this report's year-end"
        return 0
    vals = match.credit_values()
    mismatches = 0
    for c in extraction["candidates"]:
        if c["period"] != "t" or vals.get(c["field"]) is None:
            continue
        x = vals[c["field"]]
        if any("includes short-term borrowings" in r for r in c["reasons"]):   # combined current-debt line
            x = x + (vals.get("short_term_borrowings") or 0.0)
        if abs(c["value"] - x) > max(tolerance * abs(x), 1.0):
            c["confidence"], c["needs_review"] = "low", True
            c["reasons"].append(f"differs from SEC XBRL ({x / 1e6:,.1f}m)")
            mismatches += 1
        else:
            c["reasons"].append("matches SEC XBRL")
    extraction["sec_check"] = (f"Checked against SEC XBRL for fiscal year {match.fiscal_year_end}: "
                               f"{mismatches} figure{'s' if mismatches != 1 else ''} differ")
    return mismatches
