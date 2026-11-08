"""v1.6: debt maturity wall, Altman Z'' and Ohlson O (backend/app/finance/credit_extras.py)."""
import math
from types import SimpleNamespace as NS

import pytest

from backend.app.finance import credit_extras as ce

BASE = {"total_assets": 1000.0, "current_assets": 400.0, "current_liabilities": 250.0, "retained_earnings": 300.0,
        "operating_income": 120.0, "stockholders_equity": 450.0, "total_liabilities": 550.0, "net_income": 60.0,
        "operating_cash_flow": 110.0}


def test_altman_z2_by_hand():
    z = ce.altman_z2(BASE)
    x1, x2, x3, x4 = 150 / 1000, 300 / 1000, 120 / 1000, 450 / 550
    assert z["value"] == pytest.approx(6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4)
    assert z["zone"] == "safe"                                            # 3.62
    assert ce.altman_z2({**BASE, "operating_income": -50, "retained_earnings": -400})["zone"] == "distress"


def test_altman_zone_cut_offs():
    def zone(target):     # vary X1 only to hit an exact Z''
        others = 3.26 * 0.3 + 6.72 * 0.12 + 1.05 * 450 / 550
        wc = (target - others) / 6.56 * 1000
        return ce.altman_z2({**BASE, "current_assets": 250 + wc})["zone"]
    assert zone(2.61) == "safe" and zone(2.59) == "grey" and zone(1.11) == "grey" and zone(1.09) == "distress"


def test_missing_input_is_never_filled():
    z = ce.altman_z2({**BASE, "retained_earnings": None})
    assert z["available"] is False and z["missing"] == ["retained_earnings"] and "value" not in z
    o = ce.ohlson_o(BASE, None, "2024-12-31")
    assert o["available"] is False and "net_income_prior_year" in o["missing"]


def test_ohlson_o_by_hand():
    o = ce.ohlson_o(BASE, {"net_income": 40.0}, "2024-12-31")
    idx = ce.deflator()["index_1968_100"]["2024"]
    t = {"size": math.log(1000 / idx), "tlta": 0.55, "wcta": 0.15, "clca": 250 / 400, "oeneg": 0, "nita": 0.06,
         "futl": 110 / 550, "intwo": 0, "chin": 20 / 100}
    expect = (-1.32 - 0.407 * t["size"] + 6.03 * t["tlta"] - 1.43 * t["wcta"] + 0.0757 * t["clca"] - 1.72 * t["oeneg"]
              - 2.37 * t["nita"] - 1.83 * t["futl"] + 0.285 * t["intwo"] - 0.521 * t["chin"])
    assert o["value"] == pytest.approx(expect) and o["price_index"]["year"] == "2024"
    loss = ce.ohlson_o({**BASE, "net_income": -30, "total_liabilities": 1100}, {"net_income": -10}, "2024-12-31")
    assert loss["terms"]["intwo"] == 1 and loss["terms"]["oeneg"] == 1 and loss["value"] > o["value"]


def test_deflator_uses_latest_complete_year_for_the_current_year():
    v, y = ce.price_index("2099-12-31")
    latest = max(ce.deflator()["index_1968_100"], key=int)
    assert y == latest and v == ce.deflator()["index_1968_100"][latest]
    assert ce.deflator()["index_1968_100"]["1968"] == pytest.approx(100.0)


def fact(v, tag="T", acc="0000000000-25-000001"):
    return NS(value=v * 1e6, tag=tag, accession=acc, form="10-K", filed="2025-02-01", period_end="2024-12-31")


def test_maturity_wall_coverage_and_runway():
    sup = {"debt_maturity_y1": fact(100), "debt_maturity_y2": fact(200), "debt_maturity_y3": fact(300),
           "debt_maturity_y4": fact(50), "debt_maturity_y5": fact(400), "debt_maturity_after5": fact(1000)}
    w = ce.maturity_wall(sup, {"cash": 150.0, "short_term_borrowings": 50.0, "long_term_debt": 1900.0,
                               "current_maturities_ltd": 100.0}, fcf=100.0)
    assert w["available"] and w["schedule_total"] == 2050 and w["due_12m"] == 150
    assert w["coverage_12m"] == pytest.approx((150 + 100) / 150)
    # cumulative need: 50 + 100 = 150 (y1) | 350 (y2) | 650 (y3); cash + n x 100: 250 | 350 | 450 -> through year 2
    assert w["runway_through"] == 2
    assert w["within_two_years_share"] == pytest.approx(300 / 2050)


def test_maturity_wall_negative_fcf_counts_as_zero_and_missing_buckets_are_said():
    sup = {"debt_maturity_y1": fact(100), "debt_maturity_y2": fact(200)}
    w = ce.maturity_wall(sup, {"cash": 120.0, "short_term_borrowings": None}, fcf=-80.0)
    assert w["coverage_12m"] == pytest.approx(1.2) and w["runway_through"] == 1
    assert any("after year 5" in n for n in w["notes"])
    assert [b["value"] for b in w["buckets"]] == [100, 200, None, None, None, None]   # never filled in


def test_maturity_wall_unavailable_without_schedule():
    w = ce.maturity_wall({}, {"cash": 10.0}, fcf=5.0)
    assert w["available"] is False and "nothing is estimated" in w["reason"]
