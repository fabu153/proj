"""Pre-registered next-fiscal-year financial-stress label (Blueprint p.07).

stress(t+1) = 1 if at least 2 of 3 conditions hold in fiscal year t+1:
  A. Coverage weakness : EBIT / gross interest expense < 1.5x (valid positive interest)
  B. High leverage     : gross debt / EBITDA > 5.0x, OR positive debt with non-positive EBITDA
  C. Cash-flow weakness: operating cash flow < 0

This is an ACCOUNTING-STRESS PROXY, not a probability of default. Thresholds are
declared research assumptions (configs/assumptions.yaml), frozen before training.

Leakage rule: labels are built ONLY from year t+1 facts, in a separate step from
features, and a label is None (right-censored / unlabelable) unless every condition
can be evaluated — we never guess a 0 from missing data.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

LABEL_VERSION = "stress_v1"
EBIT_COVER_MAX = 1.5
LEVERAGE_MAX = 5.0
CFO_MIN = 0.0
MIN_CONDITIONS = 2


@dataclass(frozen=True)
class StressLabel:
    label: Optional[int]                # 1, 0, or None if not determinable
    coverage_weak: Optional[bool]
    leverage_high: Optional[bool]
    cash_flow_weak: Optional[bool]
    reason: Optional[str] = None
    version: str = LABEL_VERSION


def _cond_coverage(ebit, interest) -> Optional[bool]:
    if ebit is None or interest is None:
        return None
    if interest <= 0:
        return False      # no valid positive interest -> condition cannot fire (debt-free firms)
    return ebit / interest < EBIT_COVER_MAX


def _cond_leverage(gross_debt, ebitda) -> Optional[bool]:
    if gross_debt is None or ebitda is None:
        return None
    if ebitda <= 0:
        return gross_debt > 0
    return gross_debt / ebitda > LEVERAGE_MAX


def _cond_cfo(cfo) -> Optional[bool]:
    return None if cfo is None else cfo < CFO_MIN


def stress_label(next_year: Mapping[str, Optional[float]]) -> StressLabel:
    """`next_year` holds canonical t+1 values incl. derived 'ebitda' and 'gross_debt'."""
    a = _cond_coverage(next_year.get("operating_income"), next_year.get("interest_expense"))
    b = _cond_leverage(next_year.get("gross_debt"), next_year.get("ebitda"))
    c = _cond_cfo(next_year.get("operating_cash_flow"))
    conds = [a, b, c]
    hits = sum(1 for x in conds if x is True)
    unknown = sum(1 for x in conds if x is None)
    if hits >= MIN_CONDITIONS:
        return StressLabel(1, a, b, c)                    # determinable even with one unknown
    if hits + unknown < MIN_CONDITIONS:
        return StressLabel(0, a, b, c)                    # cannot reach 2 even if unknowns fire
    return StressLabel(None, a, b, c, reason="insufficient_t+1_data")


def onset_label(current: StressLabel, nxt: StressLabel) -> Optional[int]:
    """Secondary target: not stressed in t, stressed in t+1. None if undeterminable or already stressed."""
    if current.label is None or nxt.label is None:
        return None
    if current.label == 1:
        return None   # excluded from onset population
    return nxt.label
