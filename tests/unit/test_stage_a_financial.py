"""Stage A (v1.1) — FIN-01 refinancing, FIN-02 restricted cash, R6/R7 credit basis, model basis frozen."""
import gzip
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.api.main import app
from backend.app.documents.xbrl import build_company_years, engine_inputs
from backend.app.finance.metrics import Status, compute_all
from backend.app.models import risk
from backend.app.scenarios.loan import (Baseline, Facility, ScenarioInputError, Shock, UseOfProceeds,
                                        run_scenario)

CURATED = Path(__file__).parents[2] / "backend" / "data" / "curated"
SMALL = Baseline(currency="EUR", ebitda=40, gross_debt=100, cash=10, interest_expense=5)


def _cf(cik):
    with gzip.open(CURATED / f"companyfacts_{cik}.json.gz", "rt") as fh:
        return json.load(fh)


# ------------------------------------------------------------------ FIN-01 refinancing
def test_fin01_retired_interest_above_reported_interest_is_refused():
    fac = Facility(amount=100, currency="EUR", coupon=0.06, use_of_proceeds=UseOfProceeds.REFINANCING,
                   refinanced_debt_rate=0.15)
    with pytest.raises(ScenarioInputError, match="at most 5.00%"):
        run_scenario(SMALL, fac, Shock())


def test_fin01_new_loan_interest_never_erased():
    fac = Facility(amount=100, currency="EUR", coupon=0.06, use_of_proceeds=UseOfProceeds.REFINANCING)
    r = run_scenario(SMALL, fac, Shock())        # default: retire at the average cost of debt (5 / 100 = 5%)
    assert r.interest_expense == pytest.approx(6.0)
    assert any("average cost of debt" in s for s in r.steps)


def test_fin01_capex_versus_refinancing_net_debt():
    capex = run_scenario(SMALL, Facility(amount=100, currency="EUR", use_of_proceeds=UseOfProceeds.CAPEX), Shock())
    refi = run_scenario(SMALL, Facility(amount=100, currency="EUR", use_of_proceeds=UseOfProceeds.REFINANCING), Shock())
    assert capex.net_debt == pytest.approx(SMALL.gross_debt - SMALL.cash + 100)
    assert refi.net_debt == pytest.approx(SMALL.gross_debt - SMALL.cash)
    assert capex.interest_expense == pytest.approx(11.0) and refi.interest_expense == pytest.approx(6.0)


def test_fin01_refinancing_without_existing_debt_holds_cash():
    base = SMALL.model_copy(update={"gross_debt": 0, "interest_expense": 0})
    r = run_scenario(base, Facility(amount=50, currency="EUR", use_of_proceeds=UseOfProceeds.REFINANCING), Shock())
    assert r.cash == pytest.approx(60) and r.interest_expense == pytest.approx(3.0)


def test_rate_cut_cannot_push_floating_rate_below_zero():
    fac = Facility(amount=100, currency="EUR", coupon=0.03, floating=True)
    with pytest.raises(ScenarioInputError, match="below zero"):
        run_scenario(SMALL, fac, Shock(rate_shock_bps=-400))
    assert run_scenario(SMALL, fac, Shock(rate_shock_bps=-200)).interest_expense == pytest.approx(5 + 3 - 2)


def test_amortizing_facility_explains_first_year_interest():
    r = run_scenario(SMALL, Facility(amount=100, currency="EUR", annual_amortization=20), Shock())
    assert any("first-year interest on the full opening balance" in s for s in r.steps)


def test_fin01_api_returns_clear_422():
    c = TestClient(app)
    r = c.post("/scenarios", json={"baseline_override": SMALL.model_dump(),
                                   "facility": {"amount": 100, "currency": "EUR", "use_of_proceeds": "refinancing",
                                                "refinanced_debt_rate": 0.15}})
    assert r.status_code == 422 and "conflicts with the reported figures" in r.json()["detail"]


# ------------------------------------------------------------------ FIN-02 restricted cash (R5)
def _synthetic(restricted=None):
    def fact(v, instant=True):
        e = {"end": "2025-12-31", "val": v, "accn": "a", "form": "10-K", "filed": "2026-02-01"}
        if not instant:
            e["start"] = "2025-01-01"
        return {"units": {"USD": [e]}}
    g = {"Revenues": fact(1000e6, False), "OperatingIncomeLoss": fact(100e6, False),
         "DepreciationDepletionAndAmortization": fact(50e6, False), "LongTermDebtNoncurrent": fact(400e6),
         "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents": fact(120e6)}
    if restricted is not None:
        g["RestrictedCash"] = fact(restricted)
    return {"cik": 9, "entityName": "T", "facts": {"us-gaap": g}}


def test_fin02_tagged_restricted_cash_is_removed_for_credit_only():
    y = build_company_years(_synthetic(restricted=30e6))[0]
    assert y.cash_basis == "unrestricted_derived"
    assert engine_inputs(y)["cash"] == 90e6                       # credit: unrestricted
    assert engine_inputs(y, basis="model")["cash"] == 120e6       # model: exactly as trained


def test_fin02_inseparable_restricted_cash_qualifies_net_debt():
    y = build_company_years(_synthetic())[0]
    assert y.cash_basis == "combined_not_separable"
    v = {k: (x / 1e6 if x is not None else None) for k, x in engine_inputs(y).items()}
    m = compute_all(v, cash_basis=y.cash_basis)
    for k in ("net_debt", "net_leverage"):
        assert m[k].status is Status.WARNING and "restricted" in m[k].reason
    assert compute_all(v)["net_debt"].status is Status.OK          # without the flag it would look clean


def test_fin02_pg_cash_is_combined_and_qualified():
    # P&G tags only cash incl. restricted cash; the 10-K shows no restricted balance, but the data cannot prove it
    y = build_company_years(_cf("0000080424"))[-1]
    assert y.cash_basis == "combined_not_separable"
    assert any("cannot be separated" in w for w in y.warnings)


# ------------------------------------------------------------------ R6 / R7 from the 10-K reconciliation
def test_r6_united_rentals_total_da_matches_10k():
    y = build_company_years(_cf("0001067701"))[-1]
    assert y.fiscal_year_end == "2025-12-31"
    assert engine_inputs(y)["depreciation_amortization"] == pytest.approx(3108e6)        # 10-K cash-flow line
    assert engine_inputs(y, basis="model")["depreciation_amortization"] == pytest.approx(438e6)
    v = {k: (x / 1e6 if x is not None else None) for k, x in engine_inputs(y).items()}
    assert compute_all(v)["ebitda"].value == pytest.approx(3973 + 3108)


def test_r7_income_statement_interest_preferred_to_cash_paid():
    uri = build_company_years(_cf("0001067701"))[-1]
    bg = build_company_years(_cf("0001278027"))[-1]
    assert engine_inputs(uri)["interest_expense"] == pytest.approx(716e6)                # 10-K "Interest expense, net"
    assert engine_inputs(bg)["interest_expense"] == pytest.approx(149.631e6)
    assert engine_inputs(bg, basis="model")["interest_expense"] == pytest.approx(149.039e6)


@pytest.mark.parametrize("cik,p", [("0000080424", 0.010364), ("0001067701", 0.017559), ("0001278027", 0.808225)])
def test_model_scores_unchanged_by_credit_basis(cik, p):
    cf = _cf(cik)
    y = build_company_years(cf)[-1]
    assert risk.score(cf, y.fiscal_year_end)["probability"] == pytest.approx(p, abs=5e-7)
