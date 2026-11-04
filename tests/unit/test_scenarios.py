"""F03 / F04 / S01 — EUR 100m loan case reproduced exactly (Blueprint p.09, p.13, p.22)."""
import pytest
from pydantic import ValidationError

from backend.app.scenarios.loan import (Baseline, Covenants, Facility, FXBlocked, Shock, UseOfProceeds,
                                        amortization_schedule, run_scenario)

BASE = Baseline(currency="EUR", ebitda=100, gross_debt=300, cash=50, interest_expense=20)
FAC = Facility(amount=100, currency="EUR", coupon=0.06, floating=True, use_of_proceeds=UseOfProceeds.CAPEX)


def test_status_quo_matches_blueprint():
    r = run_scenario(BASE, None, Shock())
    assert r.net_debt == 250 and r.net_leverage == pytest.approx(2.5) and r.ebitda_interest_cover == pytest.approx(5.0)


def test_golden_post_loan_base_case():
    r = run_scenario(BASE, FAC, Shock(name="base"))
    assert (r.gross_debt, r.cash, r.net_debt) == (400, 50, 350)
    assert r.net_leverage == pytest.approx(3.5)
    assert r.interest_expense == pytest.approx(26.0)
    assert r.ebitda_interest_cover == pytest.approx(100 / 26)     # 3.85x


def test_s01_downside_ebitda_minus20_rates_plus200():
    r = run_scenario(BASE, FAC, Shock(name="downside", ebitda_shock=-0.20, rate_shock_bps=200))
    assert r.ebitda == pytest.approx(80)
    assert r.interest_expense == pytest.approx(28.0)              # rate shock on new EUR 100m only
    assert r.net_leverage == pytest.approx(4.375)                 # 4.38x
    assert r.ebitda_interest_cover == pytest.approx(80 / 28)      # 2.86x


def test_f03_retained_cash_leaves_net_debt_unchanged():
    r = run_scenario(BASE, FAC.model_copy(update={"use_of_proceeds": UseOfProceeds.RETAINED_CASH}), Shock())
    assert r.gross_debt == 400 and r.cash == 150 and r.net_debt == 250


def test_f03_refinancing_keeps_gross_debt_and_swaps_interest():
    fac = FAC.model_copy(update={"use_of_proceeds": UseOfProceeds.REFINANCING, "refinanced_debt_rate": 0.05})
    r = run_scenario(BASE, fac, Shock())
    assert r.gross_debt == 300 and r.net_debt == 250
    assert r.interest_expense == pytest.approx(20 - 5 + 6)


def test_f04_currency_mismatch_blocks_calculation():
    usd_base = BASE.model_copy(update={"currency": "USD"})
    with pytest.raises(FXBlocked):
        run_scenario(usd_base, FAC, Shock())


def test_f04_explicit_fx_converts_facility():
    usd_base = BASE.model_copy(update={"currency": "USD"})
    fac = FAC.model_copy(update={"fx_rate_to_reporting": 1.10, "fx_rate_date": "2026-11-04"})
    r = run_scenario(usd_base, fac, Shock())
    assert r.gross_debt == pytest.approx(410) and r.interest_expense == pytest.approx(20 + 6.6)
    assert any("1.1" in s for s in r.steps)


def test_rate_shock_reprices_existing_floating_debt_only_when_declared():
    base = BASE.model_copy(update={"existing_floating_share": 0.5})
    r = run_scenario(base, FAC, Shock(rate_shock_bps=200))
    assert r.interest_expense == pytest.approx(20 + 6 + (150 + 100) * 0.02)


def test_fixed_rate_facility_not_repriced():
    r = run_scenario(BASE, FAC.model_copy(update={"floating": False}), Shock(rate_shock_bps=300))
    assert r.interest_expense == pytest.approx(26.0)


def test_covenant_headroom_direction_and_breach_flag():
    cov = Covenants(max_net_leverage=4.0, min_ebitda_interest_cover=3.0)
    base_case = run_scenario(BASE, FAC, Shock(), cov)
    assert base_case.covenant_headroom["max_net_leverage"] == pytest.approx(0.5)          # 4.0 - 3.5
    assert base_case.covenant_headroom["min_ebitda_interest_cover"] == pytest.approx(100 / 26 - 3.0)
    down = run_scenario(BASE, FAC, Shock(ebitda_shock=-0.2, rate_shock_bps=200), cov)
    assert "COVENANT_BREACH:max_net_leverage" in down.flags
    assert "COVENANT_BREACH:min_ebitda_interest_cover" in down.flags


def test_total_ebitda_wipeout_flags_not_crashes():
    r = run_scenario(BASE, FAC, Shock(ebitda_shock=-1.0))
    assert r.net_leverage is None and any("NON_POSITIVE_EBITDA" in f for f in r.flags)


def test_every_scenario_has_audit_steps():
    r = run_scenario(BASE, FAC, Shock(ebitda_shock=-0.2, rate_shock_bps=200))
    assert len(r.steps) >= 4


def test_amortization_schedule_sums_to_principal():
    fac = Facility(amount=100, annual_amortization=10, tenor_years=5)
    rows = amortization_schedule(fac)
    assert sum(r["repayment"] for r in rows) == pytest.approx(100)
    assert rows[-1]["closing"] == 0 and rows[0]["interest"] == pytest.approx(6.0)


def test_amortization_exceeding_principal_rejected():
    with pytest.raises(ValidationError):
        Facility(amount=100, annual_amortization=30, tenor_years=5)
