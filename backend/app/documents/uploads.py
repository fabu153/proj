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


def effective_value(f: dict) -> Optional[float]:
    if f["status"] in ("auto_accepted", "accepted"):
        return f["value"]
    if f["status"] == "corrected":
        return f["reviewed_value"]
    return None   # rejected or still needs review


def blocking_reasons(doc: dict) -> list[str]:
    out = []
    for f in doc["facts"]:
        if f["period"] == "t" and f["field"] in CRITICAL and f["status"] == "needs_review":
            out.append(f"Review {f['field'].replace('_', ' ')} (page {f['page']}): {'; '.join(f['reasons'])}")
    if doc["fye_inferred"]:
        out.append("Confirm the fiscal year-end date (it was not stated on the statements)")
    if not doc["fiscal_year_end"]:
        out.append("Fiscal year-end missing")
    return out


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
            "facts": {"us-gaap": facts}, "currency": doc["currency"], "source": "Uploaded annual report"}


def cross_check_xbrl(extraction: dict, companyfacts: dict, tolerance: float = 0.005) -> int:
    """Compare latest-year candidates with SEC XBRL for the same fiscal year; mismatches need review."""
    years = {y.fiscal_year_end: y for y in build_company_years(companyfacts)}
    fye = extraction.get("fiscal_year_end")
    # allow a few days of slack for 52/53-week calendars
    match = next((y for k, y in years.items() if fye and abs((date.fromisoformat(k) - date.fromisoformat(fye)).days) <= 7), None)
    if match is None:
        extraction["issues"].append("No SEC XBRL year matches this fiscal year-end; cross-check skipped")
        return 0
    vals = match.values()
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
    return mismatches
