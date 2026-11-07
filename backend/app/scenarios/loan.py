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

ENGINE_VERSION = "1.2.0"   # 1.2: EBITDA shocks scale |EBITDA| (losses deepen); explicit covenant states
# 1.1: refinancing/rate-floor validation, no interest clamp


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
    # Some loan agreements define non-positive EBITDA as an automatic leverage breach. That is a contractual
    # choice, so it is never assumed: by default an undefined ratio makes the covenant NOT TESTABLE.
    nonpositive_ebitda_breaches_leverage: bool = False


class CovenantState(str, Enum):
    PASS = "pass"                  # ratio valid and within the limit
    BREACH = "breach"              # ratio valid and outside the limit (or the contractual policy above applies)
    NOT_TESTABLE = "not_testable"  # a required figure is missing or the ratio is undefined


class CovenantAssessment(BaseModel):
    covenant: str
    limit: float
    value: Optional[float]         # the ratio tested; None when it cannot be calculated
    headroom: Optional[float]      # positive = room, negative = shortfall; None when not testable
    state: CovenantState
    reason: str


class FXBlocked(ValueError):
    """Raised when a facility currency differs from reporting currency and no FX rate is given."""


class ScenarioInputError(ValueError):
    """Assumptions that contradict the borrower's reported figures. The scenario is withheld, never patched."""


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
    covenant_status: dict[str, CovenantAssessment] = {}
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
        if repaid == 0:
            cash += amt
            gd += amt
            steps.append(f"Uses: refinancing selected but the borrower reports no existing debt; proceeds {amt:,.2f} "
                         f"held as cash -> gross debt +{amt:,.2f}, cash +{amt:,.2f}.")
        else:
            entered = fac.refinanced_debt_rate is not None
            rate = fac.refinanced_debt_rate if entered else base.interest_expense / base.gross_debt
            saved = repaid * rate
            # The retired debt's interest is part of the reported total, so it cannot exceed that total.
            if saved > base.interest_expense * 1.005 + 0.01:
                max_rate = base.interest_expense / repaid
                raise ScenarioInputError(
                    f"Refinancing assumption conflicts with the reported figures: retiring {repaid:,.2f} at "
                    f"{rate:.2%} would remove {saved:,.2f} of interest, but total reported interest expense is only "
                    f"{base.interest_expense:,.2f}. Use a rate of at most {max_rate:.2%} (or leave it blank to use the "
                    f"average cost of debt, {base.interest_expense / base.gross_debt:.2%}).")
            existing_int -= saved
            # repaid debt is assumed to come pro rata from the fixed and floating buckets
            existing_floating *= (base.gross_debt - repaid) / base.gross_debt
            gd = gd - repaid + amt
            cash += amt - repaid
            steps.append(f"Uses: refinance {repaid:,.2f} of existing debt at {rate:.2%} "
                         f"({'entered' if entered else 'average cost of debt = interest / gross debt'}) -> interest "
                         f"on retired debt {saved:,.2f} removed; existing interest {base.interest_expense:,.2f} -> "
                         f"{existing_int:,.2f}; gross debt {base.gross_debt:,.2f} -> {gd:,.2f}.")
            if amt > repaid:
                steps.append(f"Excess proceeds {amt - repaid:,.2f} retained as cash.")

    new_int = amt * fac.coupon
    steps.append(f"New facility interest: {amt:,.2f} x {fac.coupon:.2%} = {new_int:,.2f} "
                 f"({'floating' if fac.floating else 'fixed'}, {fac.tenor_years}y "
                 f"{'bullet' if fac.annual_amortization == 0 else 'amortizing'})"
                 + ("; first-year interest on the full opening balance, repayments lower it from year 2 "
                    "(see the repayment schedule)." if fac.annual_amortization else "."))
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

    # Fix 2: a shock moves EBITDA by a share of its SIZE, so a downside always deteriorates it. For positive
    # EBITDA this equals base x (1 + shock); for a loss, -100 at -20% becomes -120, not -80.
    ebitda = base.ebitda + abs(base.ebitda) * shock.ebitda_shock
    if shock.ebitda_shock:
        if base.ebitda == 0:
            steps.append(f"EBITDA shock {shock.ebitda_shock:+.0%}: EBITDA is zero, so a percentage shock has no "
                         "absolute effect; EBITDA stays 0.00 and no stressed value is invented.")
        elif base.ebitda < 0:
            steps.append(f"EBITDA shock {shock.ebitda_shock:+.0%} applied to the size of the loss: {base.ebitda:,.2f} "
                         f"{'-' if shock.ebitda_shock < 0 else '+'} {abs(base.ebitda * shock.ebitda_shock):,.2f} -> "
                         f"{ebitda:,.2f} (a downside deepens a loss, an upside narrows it).")
        else:
            steps.append(f"EBITDA shock {shock.ebitda_shock:+.0%}: {base.ebitda:,.2f} -> {ebitda:,.2f}.")
    delta_rate = shock.rate_shock_bps / 10_000
    if delta_rate < 0:   # a cut cannot take any floating rate below zero
        if fac is not None and fac.floating and fac.coupon + delta_rate < 0:
            raise ScenarioInputError(f"A {shock.rate_shock_bps:+.0f} bp shock would take the facility coupon "
                                     f"({fac.coupon:.2%}) below zero.")
        avg = base.interest_expense / base.gross_debt if base.gross_debt > 0 else 0.0
        if base.existing_floating_share > 0 and avg + delta_rate < 0:
            raise ScenarioInputError(f"A {shock.rate_shock_bps:+.0f} bp shock would take the existing floating debt "
                                     f"(average cost {avg:.2%}) below zero.")
    rate_add = floating_debt * delta_rate
    if shock.rate_shock_bps:
        steps.append(f"Rate shock {shock.rate_shock_bps:+.0f} bps on floating debt {floating_debt:,.2f} "
                     f"-> interest {rate_add:+,.2f}. Fixed-rate debt not repriced.")
    interest = existing_int + new_int + rate_add
    if interest < new_int + min(rate_add, 0.0) - 1e-9 or interest < 0:   # guarded above; never clamp silently
        raise ScenarioInputError(f"Inconsistent interest result ({interest:,.2f}); check the refinancing inputs.")
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
    status: dict[str, CovenantAssessment] = {}
    if base.ebitda == 0 and shock.ebitda_shock:
        flags.append("EBITDA_ZERO_SHOCK_NOT_APPLICABLE")
    if covenants:
        status = assess_covenants(covenants, net_lev, cover, ebitda, interest)
        for k, a in status.items():
            headroom[k] = a.headroom
            if a.state is CovenantState.BREACH:
                flags.append(f"COVENANT_BREACH:{k}")
            elif a.state is CovenantState.NOT_TESTABLE:
                flags.append(f"COVENANT_NOT_TESTABLE:{k}")

    return ScenarioResult(name=shock.name, currency=base.currency, ebitda=ebitda, gross_debt=gd, cash=cash,
                          net_debt=nd, interest_expense=interest, net_leverage=net_lev,
                          gross_leverage=gross_lev, ebitda_interest_cover=cover,
                          covenant_headroom=headroom, covenant_status=status, flags=flags, steps=steps)


def assess_covenants(cov: Covenants, net_lev: Optional[float], cover: Optional[float], ebitda: float,
                     interest: float) -> dict[str, CovenantAssessment]:
    """Fix 3: PASS / BREACH / NOT TESTABLE for every covenant set. Headroom stays numerically identical to v1.1
    for testable covenants; an undefined ratio is never counted as a breach unless the contractual policy says so."""
    out: dict[str, CovenantAssessment] = {}
    if cov.max_net_leverage is not None:
        lim = cov.max_net_leverage
        if net_lev is None:
            why = ("EBITDA is zero or negative, so net debt / EBITDA is undefined")
            if cov.nonpositive_ebitda_breaches_leverage:
                out["max_net_leverage"] = CovenantAssessment(covenant="max_net_leverage", limit=lim, value=None,
                                                             headroom=None, state=CovenantState.BREACH,
                                                             reason=why + "; the agreement treats this as a breach")
            else:
                out["max_net_leverage"] = CovenantAssessment(covenant="max_net_leverage", limit=lim, value=None,
                                                             headroom=None, state=CovenantState.NOT_TESTABLE, reason=why)
        else:
            h = lim - net_lev
            out["max_net_leverage"] = CovenantAssessment(
                covenant="max_net_leverage", limit=lim, value=net_lev, headroom=h,
                state=CovenantState.PASS if h >= 0 else CovenantState.BREACH,
                reason=f"net debt / EBITDA {net_lev:.2f}x against a maximum of {lim:.2f}x")
    if cov.min_ebitda_interest_cover is not None:
        lim = cov.min_ebitda_interest_cover
        if cover is None:
            out["min_ebitda_interest_cover"] = CovenantAssessment(
                covenant="min_ebitda_interest_cover", limit=lim, value=None, headroom=None,
                state=CovenantState.NOT_TESTABLE,
                reason="interest expense is zero or unavailable, so EBITDA / interest is undefined")
        else:
            h = cover - lim
            out["min_ebitda_interest_cover"] = CovenantAssessment(
                covenant="min_ebitda_interest_cover", limit=lim, value=cover, headroom=h,
                state=CovenantState.PASS if h >= 0 else CovenantState.BREACH,
                reason=f"EBITDA / interest {cover:.2f}x against a minimum of {lim:.2f}x")
    return out


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
