"""Source trail for the memo's headline figures (Stage E2, test OUT-02).

For EBITDA, net debt, net debt / EBITDA and EBITDA / interest, the trail runs
    filing (SEC accession or uploaded-report page) -> normalized fact (USD millions, with any rule applied)
    -> calculation (formula with the actual numbers) -> the memo sentence that cites it (added by the UI / PDF).
Every number in it comes from the same CompanyYear and compute_all() result the memo package used.
"""
from __future__ import annotations

import re
from typing import Optional

SCALE = 1_000_000
CHAINS = {
    "ebitda": ["ebitda"],
    "net_debt": ["gross_debt", "net_debt"],
    "net_leverage": ["ebitda", "gross_debt", "net_debt", "net_leverage"],
    "ebitda_interest_cover": ["ebitda", "ebitda_interest_cover"],
}
FACTS_FOR = {"ebitda": ["operating_income", "depreciation_amortization"],
             "gross_debt": ["short_term_borrowings", "current_maturities_ltd", "long_term_debt"],
             "net_debt": ["cash"], "net_leverage": [], "ebitda_interest_cover": ["interest_expense"]}
LABELS = {"operating_income": "Operating income", "depreciation_amortization": "Depreciation and amortization",
          "short_term_borrowings": "Short-term borrowings", "current_maturities_ltd": "Current portion of long-term debt",
          "long_term_debt": "Long-term debt (non-current)", "cash": "Cash and equivalents",
          "interest_expense": "Interest expense", "ebitda": "EBITDA", "gross_debt": "Gross debt",
          "net_debt": "Net debt", "net_leverage": "Net debt / EBITDA", "ebitda_interest_cover": "EBITDA / interest"}
HEADLINE = list(CHAINS)
FORMULA_NAMES = {"unrestricted_cash": "cash"}      # formula wording -> input key


def _num(v: Optional[float], unit: str) -> str:
    if v is None:
        return "n/a"
    return f"{v:.2f}x" if unit == "x" else f"{v:,.1f}"


def _source(cf: dict, f) -> dict:
    if f is None:
        return {"kind": "none"}
    if f.page:
        return {"kind": "upload", "page": f.page, "method": f.extraction_method, "filed": f.filed}
    cik = str(cf.get("cik", "")).lstrip("0") or "0"
    return {"kind": "sec", "tag": f.tag, "accession": f.accession, "form": f.form, "filed": f.filed,
            "period_end": f.period_end,
            "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{f.accession.replace('-', '')}/"}


def _main_filing(year):
    """The filing most of this year's facts come from (used to cite values derived by a rule)."""
    fs = [f for f in year.facts.values() if f is not None]
    if not fs:
        return None
    acc = max({f.accession for f in fs}, key=lambda a: sum(f.accession == a for f in fs))
    return next(f for f in fs if f.accession == acc)


def fact_step(cf: dict, year, field: str, used: Optional[float], ccy: str) -> dict:
    f = year.facts.get(field)
    rule = (year.credit.get(field) or year.derived.get(field) or (None, None))[1]
    note = next((w.split(":", 1)[1].strip() for w in year.warnings
                 if w.startswith(f"{field}:") and "credit basis uses" not in w), None)
    return {"field": field, "label": LABELS[field],
            "as_filed": None if f is None else {"value": f.value, "unit": f.unit},
            "normalized": used, "unit": f"{ccy} millions", "rule": rule, "note": note,
            "basis": "credit" if field in year.credit else "derived" if field in year.derived else "reported",
            "source": _source(cf, f) if f is not None else
            ({**_source(cf, _main_filing(year)), "tag": None, "derived": True} if rule and _main_filing(year) else {"kind": "none"})}


def calc_step(key: str, r) -> dict:
    def value(m):
        name = FORMULA_NAMES.get(m.group(0), m.group(0))
        if name not in r.inputs:
            return m.group(0)
        v = r.inputs[name]
        return "n/a" if v is None else f"{v:,.1f}"
    expr = re.sub(r"[A-Za-z_][A-Za-z0-9_]*", value, r.formula)
    unit = "x" if r.unit == "x" else "amount"
    return {"metric": key, "label": LABELS[key], "formula": r.formula, "version": r.formula_version,
            "expression": f"{expr} = {_num(r.value, unit)}", "value": r.value, "unit": r.unit,
            "status": r.status.value, "note": (r.reason or "").replace("_", " ") or None}


def build_trail(cf: dict, year, vals: dict, metrics: dict, key: str, ccy: str) -> dict:
    chain = CHAINS[key]
    fields = [f for k in chain for f in FACTS_FOR[k]]
    return {"metric": key, "facts": [fact_step(cf, year, f, vals.get(f), ccy) for f in fields],
            "steps": [calc_step(k, metrics[k]) for k in chain]}
