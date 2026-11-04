"""Stage B2 (v1.1) — WF-02: the loan table, the memo and the PDF describe one versioned analysis snapshot."""
import gzip
import io
import json
from pathlib import Path

import pdfplumber
import pytest
from fastapi.testclient import TestClient

from backend.app.api import main
from backend.app.api.main import app

client = TestClient(app)
REAL = Path(__file__).parents[2] / "backend" / "data" / "curated"


@pytest.fixture(autouse=True)
def real_issuers(monkeypatch):
    """These checks need the three real SEC issuers, not the synthetic fixture the other API tests use."""
    data = {}
    for p in REAL.glob("companyfacts_*.json.gz"):
        with gzip.open(p, "rt") as fh:
            d = json.load(fh)
        data[str(d["cik"]).zfill(10)] = d
    monkeypatch.setattr(main, "_curated", lambda: data)
PG, URI = "0000080424", "0001067701"
CASES = [{"name": "Base", "ebitda_shock": 0, "rate_shock_bps": 0},
         {"name": "Downside", "ebitda_shock": -0.2, "rate_shock_bps": 200},
         {"name": "Severe", "ebitda_shock": -0.35, "rate_shock_bps": 400},
         {"name": "Your case", "ebitda_shock": -0.15, "rate_shock_bps": 150}]


def _body(cid=URI, **over):
    b = {"company_id": cid, "facility": {"amount": 750, "currency": "USD", "coupon": 0.065, "floating": True,
                                         "tenor_years": 5, "use_of_proceeds": "capex"},
         "covenants": {"max_net_leverage": 3.0, "min_ebitda_interest_cover": 4.0},
         "existing_floating_share": 0.3, "shocks": CASES}
    b.update(over)
    return b


def _pdf_text(memo_id):
    r = client.get(f"/memos/{memo_id}/pdf")
    assert r.status_code == 200
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def test_wf02_same_inputs_same_snapshot_in_table_memo_and_pdf():
    s = client.post("/scenarios", json=_body()).json()
    m = client.post("/memos", json=_body()).json()
    sid = s["snapshot"]["id"]
    assert len(sid) == 12 and m["snapshot"]["id"] == sid and m["package"]["meta.snapshot"]["value"] == sid
    assert s["snapshot"]["inputs"] == m["snapshot"]["inputs"]
    # the custom case reaches the memo with the loan table's numbers
    yours = next(r for r in s["results"] if r["name"] == "Your case")
    assert m["package"]["scen.custom.net_leverage"]["value"] == pytest.approx(yours["net_leverage"])
    assert m["package"]["scen.custom.assumptions"]["value"] == "EBITDA -15%, rates +150 bp"
    assert any("analyst's own case" in x["text"] for sec in m["sections"] for x in sec["sentences"])
    assert m["summary"]["flagged"] == 0
    text = _pdf_text(m["id"])
    for needle in (f"Assumptions (analysis snapshot {sid})", "USD 750.0m, 5-year, floating at 6.50%",
                   "Case: Your case", "EBITDA -15%, rates +150 bp", "max net debt / EBITDA 3.00x",
                   "Existing debt at floating rate", "30.00%", f"Analysis snapshot {sid}"):
        assert needle in text, needle


@pytest.mark.parametrize("change", [
    {"facility": {"amount": 800, "currency": "USD", "use_of_proceeds": "capex"}},
    {"covenants": {"max_net_leverage": 3.25, "min_ebitda_interest_cover": 4.0}},
    {"existing_floating_share": 0.4},
    {"shocks": CASES[:3] + [{"name": "Your case", "ebitda_shock": -0.2, "rate_shock_bps": 150}]},
])
def test_wf02_any_input_change_gives_a_new_snapshot(change):
    a = client.post("/scenarios", json=_body()).json()["snapshot"]["id"]
    b = client.post("/scenarios", json=_body(**change)).json()["snapshot"]["id"]
    assert a != b


def test_wf02_snapshot_is_deterministic():
    ids = {client.post("/scenarios", json=_body()).json()["snapshot"]["id"] for _ in range(3)}
    assert len(ids) == 1


def test_wf02_refinancing_case_matches_between_table_and_memo():
    body = _body(facility={"amount": 1000, "currency": "USD", "coupon": 0.06, "use_of_proceeds": "refinancing"})
    s = client.post("/scenarios", json=body).json()
    m = client.post("/memos", json=body).json()
    base = next(r for r in s["results"] if r["name"] == "Base")
    assert m["snapshot"]["id"] == s["snapshot"]["id"]
    assert m["package"]["scen.base.interest_expense"]["value"] == pytest.approx(base["interest_expense"])
    assert m["package"]["scen.base.gross_debt"]["value"] == pytest.approx(s["baseline"]["gross_debt"])


def test_memo_caveats_for_combined_cash_and_credit_rules():
    pg = client.post("/memos", json=_body(PG)).json()
    txt = " ".join(x["text"] for sec in pg["sections"] for x in sec["sentences"])
    assert "includes restricted cash that the filing does not separate" in txt and pg["summary"]["flagged"] == 0
    uri = client.post("/memos", json=_body(URI)).json()
    txt = " ".join(x["text"] for sec in uri["sections"] for x in sec["sentences"])
    assert "total depreciation and amortization" in txt and "income-statement interest expense" in txt
    rules = uri["package"]["data.credit_rules"]["source"]["rules"]
    assert rules["depreciation_amortization"].startswith("R6") and rules["interest_expense"].startswith("R7")
