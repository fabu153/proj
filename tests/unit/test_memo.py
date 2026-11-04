"""G01 / G02 — evidence-constrained memo: every number reconciles to the package, every claim is cited."""
import gzip
import json
import re
from pathlib import Path

import pytest

from backend.app.memos.package import build_package
from backend.app.memos.pdf import _ranges, render_pdf
from backend.app.memos.validator import validate_sentence
from backend.app.memos.writer import TemplateWriter
from backend.app.scenarios.loan import Covenants, Facility

CURATED = Path(__file__).parents[2] / "backend" / "data" / "curated"


def _cf(cik):
    with gzip.open(CURATED / f"companyfacts_{cik}.json.gz", "rt") as fh:
        return json.load(fh)


@pytest.fixture(scope="module", params=["0000080424", "0001067701", "0001278027"])
def pk(request):
    return build_package(_cf(request.param), request.param, None, Facility(amount=100, currency="USD"),
                         Covenants(max_net_leverage=3.5, min_ebitda_interest_cover=3.0))


def test_g01_template_memo_has_no_unsupported_numbers(pk):
    for sec in TemplateWriter().write(pk):
        for s in sec["sentences"]:
            v = validate_sentence(s["text"], s["kind"], pk)
            assert v["status"] == "ok", (s["text"], v["issues"])


def test_g02_every_claim_cites_existing_items(pk):
    for sec in TemplateWriter().write(pk):
        for s in sec["sentences"]:
            v = validate_sentence(s["text"], s["kind"], pk)
            assert all(r in pk.items for r in v["refs"])
            if s["kind"] == "claim":
                assert v["refs"]


def test_rendered_numbers_equal_engine_values(pk):
    # the rendered net leverage must be exactly the engine's value formatted
    v = validate_sentence("Net leverage was {{metric.net_leverage.t}}.", "claim", pk)
    assert v["text"] == f"Net leverage was {pk.val('metric.net_leverage.t'):.2f}x."


def test_typed_number_matching_package_is_linked(pk):
    typed = f"Net leverage was {pk.val('metric.net_leverage.t'):.2f}x."
    v = validate_sentence(typed, "claim", pk)
    assert v["status"] == "ok" and "metric.net_leverage.t" in v["refs"]


def test_invented_number_is_flagged(pk):
    v = validate_sentence("Margins should reach 47.3% next year.", "claim", pk)
    assert v["status"] == "flagged" and "47.3%" in v["issues"][0]


@pytest.mark.parametrize("bad", ["The borrower is investment grade.", "This is effectively a BBB-rated credit.",
                                 "The probability of default is low.", "We approve the facility.",
                                 "Repayment is guaranteed."])
def test_restricted_credit_language_is_flagged(pk, bad):
    assert any("restricted" in i for i in validate_sentence(bad, "framing", pk)["issues"])


def test_unknown_reference_and_uncited_claim_flagged(pk):
    assert "unknown reference" in validate_sentence("Value {{metric.nope.t}}.", "claim", pk)["issues"][0]
    assert "cites no evidence" in validate_sentence("The company is strong.", "claim", pk)["issues"][0]


def test_years_are_not_treated_as_figures(pk):
    assert validate_sentence("In 2025 the company reported {{fact.revenue.t}}.", "claim", pk)["status"] == "ok"


def test_pdf_contains_only_validated_sentences_and_appendix(pk):
    memo = {"id": "x" * 32, "fiscal_year_end": pk.val("meta.fye"), "created_at": "2026-11-05T00:00:00Z",
            "writer": "template", "package_sha256": pk.sha256(), "package": pk.items,
            "sections": [{"key": "a", "title": "Test", "sentences": [
                {**validate_sentence("Revenue was {{fact.revenue.t}}.", "claim", pk), "id": "a-1", "edited": False},
                {**validate_sentence("Margins reach 47.3%.", "claim", pk), "id": "a-2", "edited": False}]}]}
    pdf = render_pdf(memo)
    assert pdf[:5] == b"%PDF-" and len(pdf) > 2000


def test_citation_ranges():
    assert _ranges([1, 2, 3, 5, 7, 8]) == "1–3, 5, 7–8"


def test_package_values_come_from_engines(pk):
    assert re.match(r"^USD -?[\d,.]+m$", pk.items["fact.revenue.t"]["display"])
    assert pk.items["scen.downside.net_leverage"]["source"]["kind"] == "scenario"
    assert pk.items["metric.net_leverage.t"]["source"]["formula"] == "net_debt / ebitda"
