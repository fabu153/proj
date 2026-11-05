"""Stage E2 / OUT-02 (v1.3): key memo numbers trace to statements and engine inputs.

Four drilldowns (EBITDA, net debt, net debt / EBITDA, EBITDA / interest): filing (accession or page) ->
normalized fact -> calculation -> memo statement. The trail is recomputed here from its own facts.
"""
import gzip
import io
import json
from pathlib import Path

import pdfplumber
import pytest
from fastapi.testclient import TestClient

from backend.app.api import main
from backend.app.api.main import app

ROOT = Path(__file__).parents[2]
client = TestClient(app)
HEADLINE = ["metric.ebitda.t", "metric.net_debt.t", "metric.net_leverage.t", "metric.ebitda_interest_cover.t"]
BODY = {"facility": {"amount": 100, "currency": "USD"}, "covenants": {"max_net_leverage": 3.5, "min_ebitda_interest_cover": 3.0},
        "shocks": [{"name": "Base", "ebitda_shock": 0, "rate_shock_bps": 0},
                   {"name": "Downside", "ebitda_shock": -0.2, "rate_shock_bps": 200},
                   {"name": "Severe", "ebitda_shock": -0.35, "rate_shock_bps": 400},
                   {"name": "Your case", "ebitda_shock": -0.1, "rate_shock_bps": 100}]}


@pytest.fixture(autouse=True)
def real_issuers(monkeypatch):
    data = {}
    for p in (ROOT / "backend/data/curated").glob("companyfacts_*.json.gz"):
        with gzip.open(p, "rt") as fh:
            d = json.load(fh)
        data[str(d["cik"]).zfill(10)] = d
    monkeypatch.setattr(main, "_curated", lambda: data)


def recompute(trail):
    v = {f["field"]: f["normalized"] or 0.0 for f in trail["facts"]}
    ebitda = v.get("operating_income", 0) + v.get("depreciation_amortization", 0)
    gross = v.get("short_term_borrowings", 0) + v.get("current_maturities_ltd", 0) + v.get("long_term_debt", 0)
    net = gross - v.get("cash", 0)
    return {"ebitda": lambda: ebitda, "net_debt": lambda: net, "net_leverage": lambda: net / ebitda,
            "ebitda_interest_cover": lambda: ebitda / v["interest_expense"]}


@pytest.mark.parametrize("cik", ["0000080424", "0001067701", "0001278027"])
def test_out02_four_headline_figures_trace_filing_to_memo(cik):
    m = client.post("/memos", json={"company_id": cik, **BODY}).json()
    pk = m["package"]
    for key in HEADLINE:
        item, trail = pk[key], pk[key]["source"]["trail"]
        metric = key.split(".")[1]
        # 1 filing: every fact cites an SEC 10-K accession with a working EDGAR path
        for f in trail["facts"]:
            src = f["source"]
            if src["kind"] == "none":           # line absent from the filing: shown as treated as 0, with the reason
                assert f["normalized"] in (0, None) and "treated as 0" in (f["note"] or "")
                continue
            assert src["kind"] == "sec" and src["form"] == "10-K" and src["accession"].count("-") == 2
            assert src["url"] == f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{src['accession'].replace('-', '')}/"
            # 2 normalized: as filed / 1e6 unless a named rule changed it
            if f["as_filed"] and not f["rule"]:
                assert f["normalized"] == pytest.approx(f["as_filed"]["value"] / 1e6)
            if f["rule"]:
                assert f["basis"] in ("credit", "derived") and f["rule"][:2] in ("R1", "R2", "R3", "R4", "R5", "R6", "R7")
        # 3 calculation: the chain recomputes to the memo's value
        assert trail["steps"][-1]["metric"] == metric
        assert item["value"] == pytest.approx(recompute(trail)[metric](), rel=1e-12)
        assert trail["steps"][-1]["expression"].endswith(item["display"].replace("USD ", "").replace("m", "")) or \
            metric in ("ebitda", "net_debt")
        # 4 memo statement: at least one validated sentence cites the figure
        assert any(key in x["refs"] and x["status"] == "ok" for s in m["sections"] for x in s["sentences"]), key


def test_out02_united_rentals_trail_shows_the_10k_reconciliation_rules():
    pk = client.post("/memos", json={"company_id": "0001067701", **BODY}).json()["package"]
    facts = {f["field"]: f for f in pk["metric.ebitda_interest_cover.t"]["source"]["trail"]["facts"]}
    assert facts["depreciation_amortization"]["as_filed"]["value"] == 438e6 and facts["depreciation_amortization"]["normalized"] == 3108
    assert facts["depreciation_amortization"]["rule"].startswith("R6")
    assert facts["interest_expense"]["normalized"] == 716 and facts["interest_expense"]["rule"].startswith("R7")
    steps = pk["metric.net_leverage.t"]["source"]["trail"]["steps"]
    assert [s["expression"] for s in steps] == ["3,973.0 + 3,108.0 = 7,081.0", "0.0 + 1,577.0 + 12,652.0 = 14,229.0",
                                                "14,229.0 - 459.0 = 13,770.0", "13,770.0 / 7,081.0 = 1.94x"]


def test_out02_pdf_prints_the_trails():
    m = client.post("/memos", json={"company_id": "0001067701", **BODY}).json()
    with pdfplumber.open(io.BytesIO(client.get(f"/memos/{m['id']}/pdf").content)) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    assert "Source trail for headline figures" in text
    for needle in ("Net debt / EBITDA (FY2025): 1.94x", "13,770.0 / 7,081.0 = 1.94x", "accession 0001067701-26-000007",
                   "rule R6", "Memo statement", "Borrower", "Proposed facility", "Analyst review"):
        assert needle in text, needle


def test_out02_uploaded_report_trail_cites_pages():
    with open(ROOT / "tests/fixtures/ar_thousands.pdf", "rb") as fh:
        d = client.post("/documents/upload", files={"file": ("bg.pdf", fh, "application/pdf")},
                        data={"company_name": "B&G Foods"}).json()
    fid = next(f["id"] for f in d["facts"] if f["field"] == "interest_expense" and f["period"] == "t")
    client.patch(f"/facts/{fid}/review", json={"decision": "accept"})
    cid = client.post(f"/documents/{d['id']}/finalize").json()["company_id"]
    pk = client.post("/memos", json={"company_id": cid, **BODY}).json()["package"]
    for f in pk["metric.net_leverage.t"]["source"]["trail"]["facts"]:
        if f["as_filed"]:
            assert f["source"]["kind"] == "upload" and f["source"]["page"] >= 1
    assert pk["metric.net_leverage.t"]["value"] == pytest.approx(11.59, abs=0.005)
    client.delete(f"/documents/{d['id']}")
