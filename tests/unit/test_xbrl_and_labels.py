"""D01 / D02 / M01 — XBRL normalization, point-in-time vintage, and the pre-registered label."""
import json
from pathlib import Path

import pytest

from backend.app.documents.xbrl import build_company_years, engine_inputs, is_annual
from backend.app.labels.stress_label import onset_label, stress_label

CF = json.loads((Path(__file__).parents[1] / "fixtures" / "demo_companyfacts.json").read_text())
M = 1_000_000


def _year(years, end):
    return next(y for y in years if y.fiscal_year_end == end)


def test_d01_quarterly_facts_never_read_as_annual():
    years = build_company_years(CF)
    assert [y.fiscal_year_end for y in years] == ["2023-12-31", "2024-12-31", "2025-12-31"]
    assert _year(years, "2025-12-31").facts["revenue"].value == 1240 * M   # not the 310m Q4 slice
    assert not is_annual({"start": "2025-10-01", "end": "2025-12-31", "form": "10-K"}, "duration")
    assert not is_annual({"start": "2025-01-01", "end": "2025-12-31", "form": "10-Q"}, "duration")


def test_d02_units_scaled_once_to_millions():
    v = engine_inputs(_year(build_company_years(CF), "2025-12-31"))
    assert v["revenue"] / M == 1240 and v["interest_expense"] / M == 20


def test_original_vintage_kept_and_restatement_recorded():
    y24 = _year(build_company_years(CF), "2024-12-31")
    assert y24.facts["revenue"].value == 1180 * M
    assert y24.restatements["revenue"][0].value == 1175 * M
    assert any("restated" in w for w in y24.warnings)
    latest = _year(build_company_years(CF, vintage="latest"), "2024-12-31")
    assert latest.facts["revenue"].value == 1175 * M


def test_m01_point_in_time_cutoff_hides_future_filings():
    years = build_company_years(CF, as_of="2025-06-30")
    assert [y.fiscal_year_end for y in years] == ["2023-12-31", "2024-12-31"]
    y24 = _year(years, "2024-12-31")
    assert "revenue" not in y24.restatements            # restatement filed 2026, invisible in mid-2025
    assert all(f.filed <= "2025-06-30" for f in y24.facts.values() if f)


def test_absent_short_term_borrowings_zero_filled_with_warning():
    y25 = _year(build_company_years(CF), "2025-12-31")
    assert y25.facts["short_term_borrowings"] is None
    assert engine_inputs(y25)["short_term_borrowings"] == 0.0
    assert any("short_term_borrowings" in w for w in y25.warnings)


def test_balance_sheet_identity_hard_check():
    bad = json.loads(json.dumps(CF))
    for e in bad["facts"]["us-gaap"]["Assets"]["units"]["USD"]:
        e["val"] *= 2
    assert not build_company_years(bad)[0].scorable


def test_every_fact_has_provenance():
    for y in build_company_years(CF):
        for f in y.facts.values():
            if f:
                assert f.accession and f.filed and f.tag and f.form in {"10-K", "10-K/A", "10-KT"}


# ------------------------------------------------------------------ pre-registered stress label
def test_label_two_of_three_fires():
    lab = stress_label({"operating_income": 10, "interest_expense": 10, "gross_debt": 600, "ebitda": 100,
                        "operating_cash_flow": 50})
    assert lab.label == 1 and lab.coverage_weak and lab.leverage_high and not lab.cash_flow_weak


def test_label_one_of_three_is_not_stress():
    lab = stress_label({"operating_income": 10, "interest_expense": 10, "gross_debt": 100, "ebitda": 100,
                        "operating_cash_flow": 50})
    assert lab.label == 0


def test_label_debt_with_negative_ebitda_counts_as_high_leverage():
    lab = stress_label({"operating_income": -20, "interest_expense": 5, "gross_debt": 50, "ebitda": -5,
                        "operating_cash_flow": 10})
    assert lab.leverage_high and lab.coverage_weak and lab.label == 1


def test_label_missing_data_is_censored_not_zero():
    lab = stress_label({"operating_income": 10, "interest_expense": 10, "operating_cash_flow": 50})
    assert lab.label is None and lab.reason == "insufficient_t+1_data"


def test_onset_excludes_already_stressed():
    s, ok = stress_label({"operating_income": -1, "interest_expense": 1, "gross_debt": 10, "ebitda": -1,
                          "operating_cash_flow": -1}), stress_label({"operating_income": 50, "interest_expense": 1,
                          "gross_debt": 10, "ebitda": 60, "operating_cash_flow": 40})
    assert onset_label(s, s) is None and onset_label(ok, s) == 1 and onset_label(ok, ok) == 0
