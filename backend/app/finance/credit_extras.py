"""v1.6 deterministic credit extras: debt maturity wall + liquidity runway, Altman Z'' and Ohlson O.

Every figure comes from XBRL facts (or the documented proxies below) and a versioned formula. Nothing missing is
estimated: a missing input makes the figure unavailable, with the reason.

Textbook scores are shown as references beside the neural screen, not as CreditLens predictions:
* Altman Z'' (Altman 1995, the four-ratio version for non-manufacturers and emerging markets, no constant):
      Z'' = 6.56 X1 + 3.26 X2 + 6.72 X3 + 1.05 X4
      X1 = working capital / total assets, X2 = retained earnings / total assets, X3 = EBIT / total assets,
      X4 = book equity / total liabilities.   Zones: safe > 2.60, grey 1.10-2.60, distress < 1.10.
* Ohlson O (Ohlson 1980, model 1, one-year horizon):
      O = -1.32 - 0.407 SIZE + 6.03 TLTA - 1.43 WCTA + 0.0757 CLCA - 1.72 OENEG - 2.37 NITA - 1.83 FUTL
          + 0.285 INTWO - 0.521 CHIN,     P = 1 / (1 + exp(-O))
      SIZE = ln(total assets in USD millions / GNP price-level index, 1968 = 100) — the U.S. GDP implicit price
      deflator (BEA, via FRED) stands in for the GNP index; FUTL uses operating cash flow for "funds provided by
      operations"; CHIN = (NI_t - NI_t-1) / (|NI_t| + |NI_t-1|); INTWO = 1 if net income < 0 in both years;
      OENEG = 1 if total liabilities > total assets.
  The original coefficients were estimated on 1970-76 industrial bankruptcies: the probability is a historical
  calibration for bankruptcy, not for CreditLens's accounting-stress label.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Optional

EXTRAS_VERSION = "1.0.0"
DEFLATOR = Path(__file__).resolve().parents[2] / "data" / "macro" / "gdp_deflator.json"
MATURITIES = [("debt_maturity_y1", "Next 12 months"), ("debt_maturity_y2", "Year 2"), ("debt_maturity_y3", "Year 3"),
              ("debt_maturity_y4", "Year 4"), ("debt_maturity_y5", "Year 5"), ("debt_maturity_after5", "After year 5")]
Z_ZONES = ((2.60, "safe"), (1.10, "grey"))


def _ev(f) -> dict:
    return {"tag": f.tag, "accession": f.accession, "form": f.form, "filed": f.filed, "period_end": f.period_end}


def maturity_wall(supplemental: dict, vals: dict, fcf: Optional[float], scale: float = 1e6) -> dict:
    """Debt principal by year (long-term debt maturity schedule) and how far liquidity reaches.

    supplemental: CompanyYear.supplemental (SourcedFact per field); vals: credit-basis engine inputs in millions.
    """
    buckets = []
    for key, label in MATURITIES:
        f = supplemental.get(key)
        buckets.append({"key": key, "label": label, "value": (f.value / scale) if f else None,
                        "evidence": _ev(f) if f else None})
    reported = [b for b in buckets if b["value"] is not None]
    if not reported:
        return {"available": False, "version": EXTRAS_VERSION,
                "reason": "No debt maturity schedule is tagged in this year's XBRL "
                          "(LongTermDebtMaturitiesRepaymentsOfPrincipal…); nothing is estimated."}
    cash, stb = vals.get("cash"), vals.get("short_term_borrowings")
    y1 = buckets[0]["value"]
    total = sum(b["value"] for b in reported)
    out = {"available": True, "version": EXTRAS_VERSION, "buckets": buckets, "schedule_total": total,
           "long_term_debt_balance": None, "short_term_borrowings": stb, "cash": cash, "fcf": fcf,
           "within_two_years_share": None, "coverage_12m": None, "runway_through": None, "notes": []}
    ltd = sum(v for v in (vals.get("long_term_debt"), vals.get("current_maturities_ltd")) if v is not None) or None
    out["long_term_debt_balance"] = ltd
    if buckets[1]["value"] is not None and y1 is not None and total > 0:
        out["within_two_years_share"] = (y1 + buckets[1]["value"]) / total
    if buckets[5]["value"] is None:
        out["notes"].append("The amount due after year 5 is not tagged, so the schedule total understates long-term debt.")
    if cash is None or y1 is None:
        out["notes"].append("Cash or the next-12-month maturity is not reported, so liquidity coverage is unavailable.")
        return out
    due12 = y1 + (stb or 0.0)
    inflow = max(fcf, 0.0) if fcf is not None else 0.0
    out["due_12m"] = due12
    out["liquidity"] = cash + inflow
    out["coverage_12m"] = (cash + inflow) / due12 if due12 > 0 else None
    out["formula"] = "(cash + max(free cash flow, 0)) / (maturities in the next 12 months + short-term borrowings)"
    if fcf is None:
        out["notes"].append("Free cash flow is not available, so only cash counts as a source of repayment.")
    # how many scheduled years can cash plus FCF at the latest level repay (cumulatively)?
    need, through = (stb or 0.0), 0
    for i, b in enumerate(buckets[:5], start=1):
        if b["value"] is None:
            break
        need += b["value"]
        if cash + inflow * i >= need:
            through = i
        else:
            break
    out["runway_through"] = through
    out["runway_formula"] = ("largest n <= 5 with cash + n x max(FCF, 0) >= short-term borrowings + maturities in "
                             "years 1..n, assuming free cash flow stays at the latest level and nothing is refinanced")
    return out


@lru_cache(maxsize=1)
def deflator() -> dict:
    return json.loads(DEFLATOR.read_text())


def price_index(fiscal_year_end: str) -> tuple[Optional[float], str]:
    idx = deflator()["index_1968_100"]
    y = fiscal_year_end[:4]
    if y in idx:
        return idx[y], y
    latest = max(idx, key=int)
    if int(y) > int(latest):                     # the year's deflator is not complete yet: latest full year
        return idx[latest], latest
    return None, y


def altman_z2(v: dict) -> dict:
    """v: credit-basis inputs in millions plus retained_earnings."""
    need = {"total_assets": v.get("total_assets"), "current_assets": v.get("current_assets"),
            "current_liabilities": v.get("current_liabilities"), "retained_earnings": v.get("retained_earnings"),
            "operating_income": v.get("operating_income"), "stockholders_equity": v.get("stockholders_equity"),
            "total_liabilities": v.get("total_liabilities")}
    missing = [k for k, x in need.items() if x is None]
    if missing:
        return {"available": False, "missing": missing, "version": EXTRAS_VERSION}
    ta, tl = need["total_assets"], need["total_liabilities"]
    if ta <= 0 or tl <= 0:
        return {"available": False, "missing": [], "reason": "total assets or liabilities not positive",
                "version": EXTRAS_VERSION}
    x = {"x1_wc_ta": (need["current_assets"] - need["current_liabilities"]) / ta,
         "x2_re_ta": need["retained_earnings"] / ta, "x3_ebit_ta": need["operating_income"] / ta,
         "x4_equity_tl": need["stockholders_equity"] / tl}
    z = 6.56 * x["x1_wc_ta"] + 3.26 * x["x2_re_ta"] + 6.72 * x["x3_ebit_ta"] + 1.05 * x["x4_equity_tl"]
    zone = next((name for cut, name in Z_ZONES if z > cut), "distress")
    return {"available": True, "value": z, "zone": zone, "components": x, "inputs": need, "version": EXTRAS_VERSION,
            "formula": "6.56 X1 + 3.26 X2 + 6.72 X3 + 1.05 X4 (Altman 1995); safe > 2.60, distress < 1.10"}


def ohlson_o(v: dict, prior: Optional[dict], fiscal_year_end: str) -> dict:
    ni_prev = prior.get("net_income") if prior else None
    need = {"total_assets": v.get("total_assets"), "total_liabilities": v.get("total_liabilities"),
            "current_assets": v.get("current_assets"), "current_liabilities": v.get("current_liabilities"),
            "net_income": v.get("net_income"), "net_income_prior_year": ni_prev,
            "operating_cash_flow": v.get("operating_cash_flow")}
    missing = [k for k, x in need.items() if x is None]
    if missing:
        return {"available": False, "missing": missing, "version": EXTRAS_VERSION}
    ta, tl, ca, cl = need["total_assets"], need["total_liabilities"], need["current_assets"], need["current_liabilities"]
    ni, ni0, ffo = need["net_income"], need["net_income_prior_year"], need["operating_cash_flow"]
    if ta <= 0 or tl <= 0 or ca <= 0:
        return {"available": False, "missing": [], "reason": "total assets, liabilities or current assets not positive",
                "version": EXTRAS_VERSION}
    idx, idx_year = price_index(fiscal_year_end)
    if idx is None:
        return {"available": False, "missing": ["price index"], "version": EXTRAS_VERSION}
    t = {"size": math.log(ta / idx), "tlta": tl / ta, "wcta": (ca - cl) / ta, "clca": cl / ca,
         "oeneg": 1.0 if tl > ta else 0.0, "nita": ni / ta, "futl": ffo / tl,
         "intwo": 1.0 if (ni < 0 and ni0 < 0) else 0.0,
         "chin": (ni - ni0) / (abs(ni) + abs(ni0)) if (abs(ni) + abs(ni0)) > 0 else 0.0}
    o = (-1.32 - 0.407 * t["size"] + 6.03 * t["tlta"] - 1.43 * t["wcta"] + 0.0757 * t["clca"] - 1.72 * t["oeneg"]
         - 2.37 * t["nita"] - 1.83 * t["futl"] + 0.285 * t["intwo"] - 0.521 * t["chin"])
    return {"available": True, "value": o, "probability": (1 / (1 + math.exp(-o)) if o > -700 else 0.0) if o < 700 else 1.0, "terms": t, "inputs": need,
            "price_index": {"value": idx, "year": idx_year}, "version": EXTRAS_VERSION,
            "formula": "Ohlson (1980) model 1; P = 1 / (1 + e^-O); FFO proxied by operating cash flow"}
