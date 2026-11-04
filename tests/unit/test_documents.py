"""D02 / D03 — annual-report PDF extraction on two different templates, confidence and the review gate."""
import gzip
import json
from pathlib import Path

import pytest

from backend.app.documents import pdf_extract, uploads
from backend.app.documents.xbrl import build_company_years, engine_inputs

FX = Path(__file__).parents[1] / "fixtures"
CURATED = Path(__file__).parents[2] / "backend" / "data" / "curated"


def _t(x, field):
    return next(c for c in x.candidates if c.field == field and c.period == "t")


@pytest.fixture(scope="module")
def pg():
    return pdf_extract.extract((FX / "us_10k_millions.pdf").read_bytes())


@pytest.fixture(scope="module")
def bg():
    return pdf_extract.extract((FX / "ar_thousands.pdf").read_bytes())


def test_d02_scale_currency_years_detected(pg, bg):
    assert (pg.scale_label, pg.currency, pg.years, pg.fiscal_year_end) == ("millions", "USD", [2026, 2025], "2026-06-30")
    assert (bg.scale_label, bg.years[:2], bg.fiscal_year_end) == ("thousands", [2025, 2024], "2026-01-03")


@pytest.mark.parametrize("name,cik", [("us_10k_millions.pdf", "0000080424"), ("ar_thousands.pdf", "0001278027")])
def test_both_templates_match_sec_xbrl_exactly(name, cik):
    x = pdf_extract.extract((FX / name).read_bytes())
    with gzip.open(CURATED / f"companyfacts_{cik}.json.gz", "rt") as fh:
        y = build_company_years(json.load(fh))[-1]
    v = engine_inputs(y)
    for f in ("revenue", "operating_income", "interest_expense", "depreciation_amortization", "operating_cash_flow",
              "capital_expenditures", "cash", "long_term_debt", "total_assets", "current_liabilities"):
        assert _t(x, f).value == pytest.approx(v[f], rel=1e-9), f


def test_prior_year_column_and_parentheses(pg, bg):
    assert next(c for c in pg.candidates if c.field == "revenue" and c.period == "t-1").value == 84_284e6
    assert _t(bg, "operating_income").value == 97_147e3
    assert next(c for c in bg.candidates if c.field == "operating_income" and c.period == "t-1").value == -177_277e3
    assert _t(bg, "capital_expenditures").value > 0          # shown as (30,647) in the cash-flow statement


def test_note_column_and_narrative_numbers_ignored(bg):
    assert _t(bg, "revenue").value == 1_828_687e3             # not the "3" in the Note column
    assert _t(bg, "revenue").page == 2                         # not the shareholder letter on page 1


def test_d03_net_interest_needs_review(bg):
    c = _t(bg, "interest_expense")
    assert c.confidence == "medium" and c.needs_review and "net" in c.reasons[0]


def test_rejects_non_pdf_empty_and_oversize():
    for bad, msg in ((b"", "empty"), (b"hello world", "not a PDF"), (b"%PDF-" + b"0" * (pdf_extract.MAX_BYTES + 1), "larger")):
        with pytest.raises(pdf_extract.ExtractionError, match=msg):
            pdf_extract.extract(bad)


def test_cross_check_flags_disagreement_with_xbrl():
    x = pdf_extract.extract((FX / "us_10k_millions.pdf").read_bytes()).to_dict()
    next(c for c in x["candidates"] if c["field"] == "revenue" and c["period"] == "t")["value"] *= 1.1
    with gzip.open(CURATED / "companyfacts_0000080424.json.gz", "rt") as fh:
        n = uploads.cross_check_xbrl(x, json.load(fh))
    rev = next(c for c in x["candidates"] if c["field"] == "revenue" and c["period"] == "t")
    assert n == 1 and rev["needs_review"] and "differs from SEC XBRL" in rev["reasons"][-1]


def _doc(status_interest="needs_review", fye_inferred=False):
    facts = [{"field": f, "period": "t", "status": "auto_accepted", "value": 1.0, "reviewed_value": None, "page": 2,
              "reasons": []} for f in pdf_extract.CRITICAL]
    facts[2]["status"] = status_interest
    facts[2]["reasons"] = ["interest shown net of interest income"]
    return {"facts": facts, "fye_inferred": fye_inferred, "fiscal_year_end": "2026-01-03", "currency": "USD",
            "scale_label": "thousands"}


def test_gate_blocks_until_critical_fact_reviewed():
    assert uploads.blocking_reasons(_doc())[0].startswith("Review interest expense")
    assert uploads.blocking_reasons(_doc("accepted")) == []
    assert "Confirm the fiscal year-end" in uploads.blocking_reasons(_doc("accepted", fye_inferred=True))[0]


def test_corrected_and_rejected_values_flow_correctly():
    f = {"status": "corrected", "value": 5.0, "reviewed_value": 7.0}
    assert uploads.effective_value(f) == 7.0
    assert uploads.effective_value({**f, "status": "rejected"}) is None
    assert uploads.effective_value({**f, "status": "needs_review"}) is None
