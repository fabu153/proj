"""Stage A (v1.1) — DATA-01 review completeness and FIN-03 currency gating, through the API."""
import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import store
from backend.app.api.main import app
from backend.app.documents import pdf_extract

client = TestClient(app)
PDF = Path(__file__).parents[1] / "fixtures" / "ar_thousands.pdf"


def _unconfirmed_doc(drop=("operating_cash_flow",)):
    """The B&G report as if its statements stated no currency, unit scale or year-end, with a figure not found."""
    raw = PDF.read_bytes()
    x = pdf_extract.extract(raw).to_dict()
    printed = 1e3                                       # unconfirmed scale: values are kept as printed
    for c in x["candidates"]:
        c["value"] /= printed
    x["candidates"] = [c for c in x["candidates"] if not (c["field"] in drop and c["period"] == "t")]
    x.update(currency=None, scale_label=None, fiscal_year_end=None, fiscal_year_end_inferred=True)
    doc_id = store.create_document(filename="t.pdf", sha256=hashlib.sha256(raw).hexdigest(), extraction=x,
                                   company_name="Unconfirmed Co")
    return client.get(f"/documents/{doc_id}").json()


def _fact(d, field, period="t"):
    return next(f for f in d["facts"] if f["field"] == field and f["period"] == period and f["status"] != "manual")


def test_data01_everything_unconfirmed_blocks_with_actionable_reasons():
    d = _unconfirmed_doc()
    b = " | ".join(d["blocking"])
    for s in ("Confirm the reporting currency", "Confirm the unit scale", "Confirm the fiscal year-end",
              "Not found: operating cash flow. Enter it from the report or mark it unavailable",
              "Review interest expense"):
        assert s in b
    assert not d["can_finalize"] and client.post(f"/documents/{d['id']}/finalize").status_code == 409
    client.delete(f"/documents/{d['id']}")


@pytest.mark.parametrize("body", [{"fiscal_year_end": "2026-02-30"}, {"fiscal_year_end": "1970-12-31"},
                                  {"fiscal_year_end": "03/01/2026"}, {"currency": "XYZ"}, {"scale_label": "lakhs"}])
def test_data01_invalid_metadata_is_rejected(body):
    d = _unconfirmed_doc()
    assert client.patch(f"/documents/{d['id']}", json=body).status_code == 422
    client.delete(f"/documents/{d['id']}")


def test_data01_confirming_scale_rescales_every_figure():
    d = _unconfirmed_doc()
    before = _fact(d, "revenue")["value"]
    d = client.patch(f"/documents/{d['id']}", json={"scale_label": "thousands"}).json()
    assert _fact(d, "revenue")["value"] == pytest.approx(before * 1e3) == pytest.approx(1_828_687_000)
    d = client.patch(f"/documents/{d['id']}", json={"scale_label": "millions"}).json()      # change of mind
    assert _fact(d, "revenue")["value"] == pytest.approx(1_828_687e6)
    client.delete(f"/documents/{d['id']}")


def _complete(currency, cfo=None):
    d = _unconfirmed_doc()
    i = d["id"]
    client.patch(f"/documents/{i}", json={"currency": currency, "scale_label": "thousands",
                                          "fiscal_year_end": "2026-01-03"})
    r = client.post(f"/documents/{i}/facts", json={"field": "operating_cash_flow", "value": cfo, "page": 3,
                                                   "note": "test"})
    assert r.status_code == 200
    d = r.json()
    client.patch(f"/facts/{_fact(d, 'interest_expense')['id']}/review", json={"decision": "accept"})
    d = client.get(f"/documents/{i}").json()
    assert d["blocking"] == [] and d["can_finalize"]
    return d


def test_data01_missing_critical_fact_marked_unavailable_is_shown_not_zero_filled():
    d = _complete("USD", cfo=None)
    assert d["unavailable_critical"] == ["operating cash flow"]
    cid = client.post(f"/documents/{d['id']}/finalize").json()["company_id"]
    a = client.post("/analyses", json={"company_id": cid}).json()
    assert a["unavailable_inputs"] == ["operating cash flow"]
    assert a["evidence"]["operating_cash_flow"] is None
    assert a["metrics"]["fcf_simple"]["status"] != "ok" and a["metrics"]["fcf_simple"]["value"] is None
    assert client.post(f"/documents/{d['id']}/facts", json={"field": "revenue", "value": 1}).status_code == 409
    client.delete(f"/documents/{d['id']}")


def test_data01_entered_fact_is_used_with_its_provenance():
    d = _complete("USD", cfo=101_396_000)
    f = next(x for x in d["facts"] if x["field"] == "operating_cash_flow" and x["status"] == "manual")
    assert f["label"] == "Entered by analyst" and f["page"] == 3
    cid = client.post(f"/documents/{d['id']}/finalize").json()["company_id"]
    a = client.post("/analyses", json={"company_id": cid}).json()
    assert a["evidence"]["operating_cash_flow"]["value"] == pytest.approx(101.396)
    assert "manual" in a["evidence"]["operating_cash_flow"]["extraction_method"]
    client.delete(f"/documents/{d['id']}")


def test_unknown_fact_field_is_rejected():
    d = _unconfirmed_doc()
    assert client.post(f"/documents/{d['id']}/facts", json={"field": "ebitda", "value": 1}).status_code == 422
    client.delete(f"/documents/{d['id']}")


def test_fin03_non_usd_upload_withholds_neural_score_but_keeps_ratios():
    d = _complete("EUR", cfo=101_396_000)
    cid = client.post(f"/documents/{d['id']}/finalize").json()["company_id"]
    a = client.post("/analyses", json={"company_id": cid}).json()
    assert a["currency"] == "EUR" and a["metrics"]["net_leverage"]["value"] == pytest.approx(11.59, abs=0.01)
    p = client.post("/predict", json={"company_id": cid}).json()
    assert p["status"] == "withheld" and "probability" not in p
    assert p["gate_reasons"][0].startswith("figures are in EUR")
    s = client.post("/scenarios", json={"company_id": cid, "facility": {"amount": 100, "currency": "EUR"}})
    assert s.status_code == 200
    client.delete(f"/documents/{d['id']}")


def test_upload_of_uncurated_cik_says_not_checked():
    with open(PDF, "rb") as fh:
        d = client.post("/documents/upload", files={"file": ("bg.pdf", fh, "application/pdf")},
                        data={"company_name": "B&G Foods", "cik": "999999"}).json()
    assert d["sec_check"].startswith("Not checked against SEC: CIK 999999")
    client.delete(f"/documents/{d['id']}")


def test_malformed_upload_does_not_break_company_list(monkeypatch):
    from backend.app.documents import uploads
    d = _complete("USD", cfo=1.0)
    cid = client.post(f"/documents/{d['id']}/finalize").json()["company_id"]

    def broken(doc):
        raise ValueError("corrupt row")
    monkeypatch.setattr(uploads, "to_companyfacts", broken)
    r = client.get("/companies", params={"include": cid})
    assert r.status_code == 200 and cid not in [c["company_id"] for c in r.json()] and len(r.json()) >= 1
    monkeypatch.undo()
    client.delete(f"/documents/{d['id']}")


def test_data01_real_pdf_without_currency_units_or_year_end():
    """Fixture C: the same statements with no currency, units, year-end or cash-flow line, uploaded for real."""
    with open(PDF.parent / "ar_unlabelled.pdf", "rb") as fh:
        d = client.post("/documents/upload", files={"file": ("c.pdf", fh, "application/pdf")},
                        data={"company_name": "Unlabelled Co"}).json()
    assert d["currency"] is None and d["scale_label"] is None and d["fye_inferred"]
    b = " | ".join(d["blocking"])
    assert "Confirm the reporting currency" in b and "Confirm the unit scale" in b and "Confirm the fiscal year-end" in b
    assert "Not found: operating cash flow" in b
    rev = _fact(d, "revenue")["value"]
    assert rev == 1_828_687                                       # kept as printed until the units are confirmed
    d = client.patch(f"/documents/{d['id']}", json={"currency": "USD", "scale_label": "thousands",
                                                    "fiscal_year_end": "2026-01-03"}).json()
    assert _fact(d, "revenue")["value"] == 1_828_687_000
    client.delete(f"/documents/{d['id']}")
