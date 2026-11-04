"""E01 (API level) — upload -> review -> finalize -> analyse -> memo -> PDF -> delete, plus audit trail."""
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.api.main import app

client = TestClient(app)
PDF = Path(__file__).parents[1] / "fixtures" / "ar_thousands.pdf"


def _upload():
    with open(PDF, "rb") as fh:
        return client.post("/documents/upload", files={"file": ("bg.pdf", fh, "application/pdf")},
                           data={"company_name": "B&G Foods"}).json()


def test_full_upload_to_memo_flow():
    d = _upload()
    assert d["status"] == "in_review" and not d["can_finalize"]
    assert client.post(f"/documents/{d['id']}/finalize").status_code == 409        # gate holds
    fid = next(f["id"] for f in d["facts"] if f["field"] == "interest_expense" and f["period"] == "t")
    assert client.patch(f"/facts/{fid}/review", json={"decision": "accept"}).status_code == 200
    cid = client.post(f"/documents/{d['id']}/finalize").json()["company_id"]
    assert cid in [c["company_id"] for c in client.get("/companies").json()]

    a = client.post("/analyses", json={"company_id": cid}).json()
    assert a["source"] == "Uploaded annual report" and a["evidence"]["revenue"]["page"] == 2
    assert round(a["metrics"]["net_leverage"]["value"], 2) == 11.59

    m = client.post("/memos", json={"company_id": cid, "covenants": {"max_net_leverage": 3.5}}).json()
    assert m["writer"] == "template" and m["summary"]["flagged"] == 0 and m["summary"]["cited_items"] > 20
    pdf = client.get(f"/memos/{m['id']}/pdf")
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"

    sid = m["sections"][1]["sentences"][0]["id"]
    edited = client.patch(f"/memos/{m['id']}/sentences/{sid}", json={"text": "Revenue will double to 99.9%."}).json()
    s = next(x for sec in edited["sections"] for x in sec["sentences"] if x["id"] == sid)
    assert s["status"] == "flagged" and s["edited"]

    assert client.delete(f"/documents/{d['id']}").status_code == 200
    assert client.get(f"/documents/{d['id']}").status_code == 404
    kinds = [e["kind"] for e in client.get("/audit").json()]
    for k in ("document_uploaded", "fact_reviewed", "document_finalized", "memo_generated", "memo_exported",
              "memo_sentence_edited", "document_deleted"):
        assert k in kinds


def test_review_after_finalize_is_refused():
    d = _upload()
    fid = next(f["id"] for f in d["facts"] if f["field"] == "interest_expense" and f["period"] == "t")
    client.patch(f"/facts/{fid}/review", json={"decision": "accept"})
    client.post(f"/documents/{d['id']}/finalize")
    assert client.patch(f"/facts/{fid}/review", json={"decision": "reject"}).status_code == 409
    client.delete(f"/documents/{d['id']}")


def test_bad_upload_gets_clear_message():
    r = client.post("/documents/upload", files={"file": ("x.pdf", b"not a pdf", "application/pdf")})
    assert r.status_code == 422 and "not a PDF" in r.json()["detail"]


def test_memo_for_curated_company_defaults_to_reporting_currency():
    r = client.post("/memos", json={"company_id": "0000000001"})
    assert r.status_code == 200 and r.json()["package"]["facility.amount"]["value"].startswith("USD")


def test_health_reports_writer():
    assert client.get("/health").json()["writer"] == "template"


def test_security_headers_and_no_store():
    r = client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert client.get("/audit").headers["cache-control"] == "no-store"


def test_upload_rate_limit(monkeypatch):
    from backend.app.api import main
    monkeypatch.setitem(main.RATE_LIMITS, "/documents/upload", (2, 3600))
    main._hits.clear()
    codes = [client.post("/documents/upload", files={"file": ("x.pdf", b"nope", "application/pdf")}).status_code
             for _ in range(3)]
    assert codes == [422, 422, 429]
    main._hits.clear()


def test_unexpected_errors_hide_internals(monkeypatch):
    from backend.app.api import main

    def explode(*a, **k):
        raise RuntimeError("secret internals")
    monkeypatch.setattr(main.risk_service, "score", explode)
    c = TestClient(main.app, raise_server_exceptions=False)
    r = c.post("/predict", json={"company_id": "0000000001"})
    assert r.status_code == 500 and "secret" not in r.text and "reference" in r.json()["detail"]
