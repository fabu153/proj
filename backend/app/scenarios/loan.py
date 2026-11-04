"""Deterministic loan & stress engine (Blueprint p.09 and p.13).

Order of operations — always the same, always visible:
  1. FX: convert the facility into the reporting currency (or block).
  2. Sources & uses: decide how proceeds move gross debt and cash.
  3. Pro forma interest: existing + new facility (- refinanced debt cost).
  4. Stress: shock EBITDA; reprice ONLY the floating portion of debt.
  5. Metrics + covenant headroom + risk flags.

Mechanical sensitivities only. Nothing here predicts how rates change revenue,
market access or default — that is deliberately out of scope (p.13).
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator

ENGINE_VERSION = "1.0.0"


class UseOfProceeds(str, Enum):
    CAPEX = "capex"                 # spent at close: debt up, cash flat
    ACQUISITION = "acquisition"     # spent at close: debt up, cash flat (no EBITDA credit)
    REFINANCING = "refinancing"     # repays existing debt: gross debt flat
    RETAINED_CASH = "retained_cash" # held on balance sheet: debt up AND cash up


class Baseline(BaseModel):
    """Reviewed historical figures, single currency & scale."""
    currency: str
    scale: str = "millions"
    ebitda: float
    gross_debt: float = Field(ge=0)
    cash: float = Field(ge=0)
    interest_expense: float = Field(ge=0)
    existing_floating_share: float = Field(0.0, ge=0, le=1,
        description="Share of EXISTING gross debt that reprices with rate shock.")


class Facility(BaseModel):
    amount: float = Field(gt=0)
    currency: str = "EUR"
    coupon: float = Field(0.06, ge=0, lt=1, description="All-in annual rate")
    floating: bool = True
    tenor_years: int = Field(5, ge=1, le=30)
    annual_amortization: float = Field(0.0, ge=0, description="Principal repaid per year; 0 = bullet")
    use_of_proceeds: UseOfProceeds = UseOfProceeds.CAPEX
    fx_rate_to_reporting: Optional[float] = Field(None, gt=0,
        description="Units of reporting currency per 1 unit of facility currency")
    fx_rate_date: Optional[str] = None
    refinanced_debt_rate: Optional[float] = Field(None, ge=0, lt=1,
        description="Rate on the debt being refinanced; defaults to baseline average cost")

    @model_validator(mode="after")
    def _amort_fits(self):
        if self.annual_amortization * self.tenor_years > self.amount + 1e-9:
            raise ValueError("annual_amortization x tenor exceeds facility amount")
        return self


class Shock(BaseModel):
    name: str = "base"
    ebitda_shock: float = Field(0.0, ge=-1.0, le=1.0, description="-0.20 = EBITDA -20%")
    rate_shock_bps: float = Field(0.0, ge=-500, le=1000)


class Covenants(BaseModel):
    max_net_leverage: Optional[float] = None
    min_ebitda_interest_cover: Optional[float] = None


class FXBlocked(ValueError):
    """Raised when a facility currency differs from reporting currency and no FX rate is given."""


class ScenarioResult(BaseModel):
    name: str
    engine_version: str = ENGINE_VERSION
    currency: str
    ebitda: float
    gross_debt: float
    cash: float
    net_debt: float
    interest_expense: float
    net_leverage: Optional[float]
    gross_leverage: Optional[float]
    ebitda_interest_cover: Optional[float]
    covenant_headroom: dict[str, Optional[float]] = {}
    flags: list[str] = []
    steps: list[str] = []          # human-readable audit trail of every adjustment


# --------------------------------------------------------------------------- core
def _facility_in_reporting_ccy(base: Baseline, fac: Facility) -> tuple[float, str]:
    if fac.currency.upper() == base.currency.upper():
        return fac.amount, f"Facility {fac.amount:,.2f} {fac.currency}; same currency as statements."
    if fac.fx_rate_to_reporting is None:
        raise FXBlocked(f"Facility in {fac.currency} but statements in {base.currency}: "
                        f"enter an FX rate and date; calculation blocked rather than mixing currencies.")
    amt = fac.amount * fac.fx_rate_to_reporting
    return amt, (f"Facility {fac.amount:,.2f} {fac.currency} x {fac.fx_rate_to_reporting} "
                 f"({fac.fx_rate_date or 'user-entered, undated'}) = {amt:,.2f} {base.currency}.")


def pro_forma(base: Baseline, fac: Facility) -> tuple[float, float, float, float, float, list[str]]:
    """Return (gross_debt, cash, existing_interest, new_interest, floating_debt, steps) at close."""
    steps: list[str] = []
    amt, fx_step = _facility_in_reporting_ccy(base, fac)
    steps.append(fx_step)

    gd, cash, existing_int = base.gross_debt, base.cash, base.interest_expense
    existing_floating = base.gross_debt * base.existing_floating_share
    use = fac.use_of_proceeds

    if use in (UseOfProceeds.CAPEX, UseOfProceeds.ACQUISITION):
        gd += amt
        steps.append(f"Uses: {amt:,.2f} spent on {use.value} at close -> gross debt +{amt:,.2f}, cash unchanged. "
                     f"No EBITDA benefit assumed.")
    elif use is UseOfProceeds.RETAINED_CASH:
        gd += amt
        cash += amt
        steps.append(f"Uses: {amt:,.2f} retained as cash -> gross debt +{amt:,.2f}, cash +{amt:,.2f}; "
                     f"net debt unchanged at close.")
    elif use is UseOfProceeds.REFINANCING:
        repaid = min(amt, base.gross_debt)
        rate = fac.refinanced_debt_rate
        if rate is None:
            rate = base.interest_expense / base.gross_debt if base.gross_debt > 0 else 0.0
        saved = repaid * rate
        existing_int -= saved
        # assume repaid debt comes pro rata from fixed/floating buckets
        if base.gross_debt > 0:
            existing_floating *= (base.gross_debt - repaid) / base.gross_debt
        gd = gd - repaid + amt
        cash += amt - repaid
        steps.append(f"Uses: refinance {repaid:,.2f} of existing debt at {rate:.2%} -> interest saved {saved:,.2f}; "
                     f"gross debt {base.gross_debt:,.2f} -> {gd:,.2f}.")
        if amt > repaid:
            steps.append(f"Excess proceeds {amt - repaid:,.2f} retained as cash.")

    new_int = amt * fac.coupon
    steps.append(f"New facility interest: {amt:,.2f} x {fac.coupon:.2%} = {new_int:,.2f} "
                 f"({'floating' if fac.floating else 'fixed'}, {fac.tenor_years}y "
                 f"{'bullet' if fac.annual_amortization == 0 else 'amortizing'}).")
    floating_debt = existing_floating + (amt if fac.floating else 0.0)
    return gd, cash, existing_int, new_int, floating_debt, steps


def run_scenario(base: Baseline, fac: Optional[Facility], shock: Shock,
                 covenants: Optional[Covenants] = None) -> ScenarioResult:
    if fac is not None:
        gd, cash, existing_int, new_int, floating_debt, steps = pro_forma(base, fac)
    else:
        gd, cash, existing_int, new_int = base.gross_debt, base.cash, base.interest_expense, 0.0
        floating_debt = base.gross_debt * base.existing_floating_share
        steps = ["No new facility (status quo)."]

    ebitda = base.ebitda * (1 + shock.ebitda_shock)
    if shock.ebitda_shock:
        steps.append(f"EBITDA shock {shock.ebitda_shock:+.0%}: {base.ebitda:,.2f} -> {ebitda:,.2f}.")
    delta_rate = shock.rate_shock_bps / 10_000
    rate_add = floating_debt * delta_rate
    if shock.rate_shock_bps:
        steps.append(f"Rate shock {shock.rate_shock_bps:+.0f} bps on floating debt {floating_debt:,.2f} "
                     f"-> interest {rate_add:+,.2f}. Fixed-rate debt not repriced.")
    interest = max(existing_int + new_int + rate_add, 0.0)
    nd = gd - cash

    lev_ok = ebitda > 0
    net_lev = nd / ebitda if lev_ok else None
    gross_lev = gd / ebitda if lev_ok else None
    cover = ebitda / interest if interest > 0 else None

    flags: list[str] = []
    if not lev_ok:
        flags.append("NON_POSITIVE_EBITDA: leverage undefined")
    if cover is not None and cover < 1.0:
        flags.append("INTEREST_COVER_BELOW_1X")
    if nd < 0:
        flags.append("NET_CASH_POSITION")

    headroom: dict[str, Optional[float]] = {}
    if covenants:
        if covenants.max_net_leverage is not None:
            h = None if net_lev is None else covenants.max_net_leverage - net_lev  # positive = room
            headroom["max_net_leverage"] = h
            if h is None or h < 0:
                flags.append("COVENANT_BREACH:max_net_leverage")
        if covenants.min_ebitda_interest_cover is not None:
            h = None if cover is None else cover - covenants.min_ebitda_interest_cover  # positive = room
            headroom["min_ebitda_interest_cover"] = h
            if h is None or h < 0:
                flags.append("COVENANT_BREACH:min_ebitda_interest_cover")

    return ScenarioResult(name=shock.name, currency=base.currency, ebitda=ebitda, gross_debt=gd, cash=cash,
                          net_debt=nd, interest_expense=interest, net_leverage=net_lev,
                          gross_leverage=gross_lev, ebitda_interest_cover=cover,
                          covenant_headroom=headroom, flags=flags, steps=steps)


def amortization_schedule(fac: Facility) -> list[dict]:
    """Year-by-year opening balance, repayment, interest (on opening balance), closing balance."""
    rows, bal = [], fac.amount
    for y in range(1, fac.tenor_years + 1):
        repay = bal if y == fac.tenor_years else min(fac.annual_amortization, bal)
        rows.append({"year": y, "opening": bal, "interest": bal * fac.coupon,
                     "repayment": repay, "closing": bal - repay})
        bal -= repay
    return rows


DEFAULT_CASES = [
    Shock(name="base", ebitda_shock=0.0, rate_shock_bps=0),
    Shock(name="downside", ebitda_shock=-0.20, rate_shock_bps=200),
    Shock(name="severe_downside", ebitda_shock=-0.35, rate_shock_bps=400),
]
