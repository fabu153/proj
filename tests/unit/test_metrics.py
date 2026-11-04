"""F01 / F02 — metric dictionary golden cases and edge cases (Blueprint p.08, p.22)."""
import math

import pytest

from backend.app.finance.metrics import (Status, compute_all, current_ratio, debt_to_assets, ebitda, ebitda_margin,
                                         free_cash_flow, gross_debt, interest_cover, leverage, net_debt,
                                         revenue_growth)

GOLDEN = {  # illustrative company from Blueprint p.09 (EUR m), expanded into canonical facts
    "revenue": 500.0, "operating_income": 70.0, "depreciation_amortization": 30.0, "interest_expense": 20.0,
    "short_term_borrowings": 0.0, "current_maturities_ltd": 25.0, "long_term_debt": 275.0, "cash": 50.0,
    "operating_cash_flow": 80.0, "capital_expenditures": 35.0, "current_assets": 180.0,
    "current_liabilities": 120.0, "total_assets": 900.0,
}


def test_f01_golden_panel_matches_blueprint():
    m = compute_all(GOLDEN, {"revenue": 400.0})
    assert m["ebitda"].value == 100.0
    assert m["gross_debt"].value == 300.0
    assert m["net_debt"].value == 250.0
    assert m["net_leverage"].value == pytest.approx(2.5)
    assert m["gross_leverage"].value == pytest.approx(3.0)
    assert m["ebitda_interest_cover"].value == pytest.approx(5.0)
    assert m["ebit_interest_cover"].value == pytest.approx(3.5)
    assert m["ebitda_margin"].value == pytest.approx(0.20)
    assert m["revenue_growth"].value == pytest.approx(0.25)
    assert m["fcf_simple"].value == 45.0
    assert m["current_ratio"].value == pytest.approx(1.5)
    assert m["debt_to_assets"].value == pytest.approx(300 / 900)


def test_every_metric_carries_formula_and_version():
    for r in compute_all(GOLDEN).values():
        assert r.formula and r.formula_version == "1.0.0"


def test_ebitda_is_flagged_as_approximate():
    r = ebitda(70, 30)
    assert r.status is Status.WARNING and "approximate" in r.reason


@pytest.mark.parametrize("e", [0.0, -15.0])
def test_f02_non_positive_ebitda_makes_leverage_undefined(e):
    for net in (True, False):
        r = leverage(300.0, e, net=net)
        assert r.value is None and r.status is Status.UNDEFINED


def test_f02_zero_interest_does_not_crash_or_return_inf():
    r = interest_cover(100.0, 0.0, basis="ebitda")
    assert r.value is None and r.status is Status.UNDEFINED


def test_missing_interest_is_not_invented():
    r = interest_cover(100.0, None, basis="ebit")
    assert r.value is None and r.status is Status.NOT_AVAILABLE and "interest_expense" in r.reason


def test_no_metric_ever_returns_nan_or_inf_on_degenerate_inputs():
    degenerate = {k: 0.0 for k in GOLDEN}
    for r in compute_all(degenerate, {"revenue": 0.0}).values():
        assert r.value is None or math.isfinite(r.value)


def test_net_cash_position_flagged():
    nd = net_debt(40.0, 100.0)
    assert nd.value == -60.0 and nd.reason == "net_cash_position"
    lev = leverage(nd.value, 50.0, net=True)
    assert lev.status is Status.WARNING


def test_capex_sign_convention_flipped_and_flagged():
    r = free_cash_flow(80.0, -35.0)
    assert r.value == 45.0 and "capex_sign_flipped" in r.reason


def test_negative_debt_component_rejected():
    assert gross_debt(-1.0, 0.0, 100.0).status is Status.UNDEFINED


def test_ratio_denominator_guards():
    assert revenue_growth(100.0, 0.0).value is None
    assert ebitda_margin(10.0, 0.0).value is None
    assert current_ratio(10.0, 0.0).value is None
    assert debt_to_assets(10.0, 0.0).value is None
