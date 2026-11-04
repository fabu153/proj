"""Versioned analysis snapshot (Stage B2, test WF-02).

The loan lab, the memo and the memo PDF must describe the same case. A snapshot is the complete set of
deterministic inputs behind a scenario run — company, fiscal year, the credit baseline taken from the
filings, facility, covenants, floating share and every stress case including the analyst's own — plus the
engine version. Its id is the first 12 hex digits of the SHA-256 of the canonical JSON, so the same inputs
always give the same id and any change gives a new one. The UI compares the memo's id with the loan
lab's current id and marks the memo "Outdated — regenerate" when they differ.
"""
from __future__ import annotations

import hashlib
import json
from typing import Optional

from ..finance.metrics import compute_all
from .loan import ENGINE_VERSION, Baseline, Covenants, Facility, Shock

SNAPSHOT_VERSION = "1"
SCALE = 1_000_000
FIXED_CASES = [Shock(name="Base"), Shock(name="Downside", ebitda_shock=-0.20, rate_shock_bps=200),
               Shock(name="Severe", ebitda_shock=-0.35, rate_shock_bps=400)]
_KEYS = {"base": "base", "downside": "downside", "severe": "severe", "severe_downside": "severe",
         "your case": "custom", "custom": "custom"}


def case_key(name: str) -> str:
    """Package key for a case name: 'Base' -> 'base', 'Your case' -> 'custom'."""
    n = name.strip().lower()
    return _KEYS.get(n, "".join(ch if ch.isalnum() else "_" for ch in n)[:24] or "case")


def credit_baseline(cy, currency: str, floating_share: float) -> tuple[Optional[Baseline], list[str]]:
    """The one baseline both /scenarios and the memo package use: credit-basis values, in millions."""
    from ..documents.xbrl import engine_inputs
    v = {k: (x / SCALE if x is not None else None) for k, x in engine_inputs(cy).items()}
    m = compute_all(v, cash_basis=cy.cash_basis)
    needed = {"ebitda": m["ebitda"].value, "gross_debt": m["gross_debt"].value, "cash": v.get("cash"),
              "interest_expense": v.get("interest_expense")}
    missing = [k for k, x in needed.items() if x is None]
    if missing:
        return None, missing
    return Baseline(currency=currency, existing_floating_share=floating_share, **needed), []


def canonical(obj) -> str:
    def norm(x):
        if isinstance(x, float):
            return round(x, 10)            # 0.1 + 0.2 and 0.3 must not produce different ids
        if isinstance(x, dict):
            return {k: norm(v) for k, v in x.items()}
        if isinstance(x, list):
            return [norm(v) for v in x]
        return x
    return json.dumps(norm(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def make_snapshot(company_id: str, fiscal_year_end: str, baseline: Optional[Baseline], facility: Optional[Facility],
                  covenants: Optional[Covenants], shocks: list[Shock], cash_basis: str = "unrestricted") -> dict:
    inputs = {
        "snapshot_version": SNAPSHOT_VERSION, "engine_version": ENGINE_VERSION,
        "company_id": company_id, "fiscal_year_end": fiscal_year_end, "cash_basis": cash_basis,
        "baseline": baseline.model_dump(mode="json") if baseline else None,
        "facility": facility.model_dump(mode="json") if facility else None,
        "covenants": (covenants or Covenants()).model_dump(mode="json"),
        "cases": [s.model_dump(mode="json") for s in shocks],
    }
    return {"id": hashlib.sha256(canonical(inputs).encode()).hexdigest()[:12], "inputs": inputs}
