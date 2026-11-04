"""S01 / F03 / F04 — engine reconciles exactly with the independent spreadsheet (docs/scenario_crosscheck.xlsx).

The workbook was recalculated by LibreOffice; we read its inputs and cached results, run the Python
engine on the same inputs, and require agreement. No LibreOffice needed at test time.
"""
from pathlib import Path

import pytest
from openpyxl import load_workbook

from backend.app.scenarios.loan import Baseline, Covenants, Facility, Shock, UseOfProceeds, run_scenario

WB = Path(__file__).parents[2] / "docs" / "scenario_crosscheck.xlsx"
USE = {1: UseOfProceeds.CAPEX, 2: UseOfProceeds.RETAINED_CASH, 3: UseOfProceeds.REFINANCING}


def _cases():
    wb = load_workbook(WB, data_only=True)
    ws, mp = wb["Cases"], {r[0].value: r[1].value for r in wb["Map"].iter_rows(min_row=2)}
    col = 2
    while ws.cell(4, col).value:
        yield ws.cell(4, col).value, {k: ws.cell(row, col).value for k, row in mp.items()}
        col += 1


CASES = list(_cases())


def test_workbook_has_all_cases_and_no_errors():
    assert len(CASES) == 8
    for _, v in CASES:
        assert not any(isinstance(x, str) and x.startswith("#") for x in v.values())


@pytest.mark.parametrize("name,v", CASES, ids=[c[0] for c in CASES])
def test_engine_matches_spreadsheet(name, v):
    usd = v["fx"] != 1
    base = Baseline(currency="USD" if usd else "EUR", ebitda=v["ebitda"], gross_debt=v["gross_debt"], cash=v["cash"],
                    interest_expense=v["interest"], existing_floating_share=v["float_share"])
    fac = Facility(amount=v["amount"], currency="EUR", coupon=v["coupon"], floating=bool(v["floating"]),
                   use_of_proceeds=USE[v["use"]], refinanced_debt_rate=v["refi_rate"],
                   fx_rate_to_reporting=v["fx"] if usd else None)
    r = run_scenario(base, fac, Shock(ebitda_shock=v["ebitda_shock"], rate_shock_bps=v["rate_bps"]),
                     Covenants(max_net_leverage=v["cov_lev"], min_ebitda_interest_cover=v["cov_cover"]))
    tol = dict(rel=1e-9, abs=1e-9)
    assert r.gross_debt == pytest.approx(v["gd_pf"], **tol)
    assert r.cash == pytest.approx(v["cash_pf"], **tol)
    assert r.interest_expense == pytest.approx(v["int_s"], **tol)
    assert r.net_leverage == pytest.approx(v["net_lev"], **tol)
    assert r.ebitda_interest_cover == pytest.approx(v["cover"], **tol)
    assert r.covenant_headroom["max_net_leverage"] == pytest.approx(v["hr_lev"], **tol)
    assert r.covenant_headroom["min_ebitda_interest_cover"] == pytest.approx(v["hr_cov"], **tol)
