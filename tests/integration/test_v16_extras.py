"""v1.6: maturity wall, textbook scores and peer bands on real filings, without touching the model basis."""
import gzip
import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sklearn.metrics import average_precision_score

from backend.app.api import main
from backend.app.api.main import app
from backend.app.documents.xbrl import build_company_years, engine_inputs
from backend.app.finance.credit_extras import altman_z2

ROOT = Path(__file__).parents[2]
REAL = ROOT / "backend/data/curated"
client = TestClient(app)


@pytest.fixture(autouse=True)
def real_samples(monkeypatch):
    main._curated.cache_clear()                      # _curated() is cached per process
    monkeypatch.setattr(main, "CURATED_DIR", REAL)
    yield
    main._curated.cache_clear()


def _raw(cik):
    with gzip.open(REAL / f"companyfacts_{cik}.json.gz", "rt") as fh:
        return json.load(fh)


@pytest.mark.parametrize("cik", ["0000080424", "0001067701", "0001278027"])
def test_supplement_never_changes_the_model_basis(cik):
    """The v1.6 tags are credit-only: model inputs and the neural score are identical with or without them."""
    merged = main._curated()[cik]
    a, b = build_company_years(_raw(cik)), build_company_years(merged)
    assert [y.fiscal_year_end for y in a] == [y.fiscal_year_end for y in b]
    for ya, yb in zip(a, b):
        assert engine_inputs(ya, basis="model") == engine_inputs(yb, basis="model")
        assert engine_inputs(ya) == engine_inputs(yb)                  # credit ratios unchanged too
    from backend.app.models import risk
    fye = a[-1].fiscal_year_end
    assert risk.score(_raw(cik), fye).get("probability") == risk.score(merged, fye).get("probability")


def test_united_rentals_maturity_wall_matches_the_filing():
    a = client.post("/analyses", json={"company_id": "0001067701", "fiscal_year_end": "2025-12-31"}).json()
    w = a["credit_extras"]["maturities"]
    assert w["available"] and [round(b["value"]) for b in w["buckets"]] == [1577, 851, 1747, 1537, 3170, 5420]
    assert all(b["evidence"]["accession"] and b["evidence"]["tag"].startswith("LongTermDebtMaturities") for b in w["buckets"])
    assert w["coverage_12m"] == pytest.approx(w["cash"] / w["due_12m"])      # FCF not available: cash only
    assert any("Free cash flow is not available" in n for n in w["notes"])


def test_textbook_scores_and_peer_bands_for_a_sample():
    a = client.post("/analyses", json={"company_id": "0001278027"}).json()
    z, o = a["credit_extras"]["altman_z2"], a["credit_extras"]["ohlson_o"]
    assert z["available"] and z["zone"] in ("safe", "grey", "distress") and z["retained_earnings_evidence"]["accession"]
    assert o["available"] and "probability" in o
    bands = a["peers"]["bands"]
    assert {"net_leverage", "ebitda_interest_cover", "altman_z2", "ohlson_o"} <= set(bands)
    b = bands["net_leverage"]
    assert 0 <= b["percentile"] <= 100 and b["peers"] >= 15 and b["years"].startswith("FY2025")   # 52/53-week year
    assert a["peers"]["sic"] == 2000


def test_bank_gets_no_industrial_extras(monkeypatch, tmp_path):
    from backend.app.documents import sec_search
    from backend.app.documents.sec_client import SECClient
    from backend.app.documents.sec_fixtures import transport
    sec_search.set_client(SECClient(cache_dir=tmp_path, retries=1, transport=transport(ROOT / "tests/fixtures/sec")))
    try:
        a = client.post("/analyses", json={"company_id": "0000099901"}).json()
        assert a["credit_extras"]["not_applicable"] and a["peers"] is None
        p = client.post("/analyses", json={"company_id": "0000076605"}).json()       # fixture compacted before v1.6
        assert p["credit_extras"]["maturities"]["available"] is False and p["peers"]["bands"]
    finally:
        sec_search.set_client(None)


def test_classic_benchmark_numbers_follow_from_saved_scores():
    res = json.loads((ROOT / "training/experiments/classic_scores_v1/results.json").read_text())
    tp = pd.read_csv(ROOT / "training/experiments/classic_scores_v1/test_predictions.csv", dtype={"cik": str})
    assert len(tp) == 1086
    for k, risk in (("altman_z2", -tp["altman_z2"]), ("ohlson_o", tp["ohlson_o"])):
        m = risk.notna()
        assert res["overall"][k]["rows"] == int(m.sum())
        assert average_precision_score(tp["label_next_fy"][m], risk[m]) == pytest.approx(res["overall"][k]["pr_auc"])
        assert res["overall"][k]["minus_deployed"]["ci95"][1] < 0          # clearly below the network


def test_panel_scores_use_the_app_formulas():
    """A few panel rows recomputed with the app's own functions give the saved benchmark values."""
    panel = pd.read_csv(ROOT / "training/data/panel_v1.csv", dtype={"cik": str})
    inputs = pd.read_csv(ROOT / "training/data/classic_inputs_v1.csv", dtype={"cik": str})
    sc = pd.read_csv(ROOT / "training/experiments/classic_scores_v1/panel_scores.csv", dtype={"cik": str})
    rows = panel.merge(inputs).merge(sc).dropna(subset=["altman_z2"]).sample(20, random_state=1)
    for _, r in rows.iterrows():
        v = {k: float(r[f"v_{k}"]) for k in ("total_assets", "current_assets", "current_liabilities", "operating_income",
                                              "stockholders_equity", "total_liabilities")}
        v["retained_earnings"] = float(r["retained_earnings"])
        assert altman_z2(v)["value"] == pytest.approx(r["altman_z2"], rel=1e-6)
    # retained earnings follow the point-in-time rule
    ok = inputs.dropna(subset=["re_filed"]).merge(panel[["cik", "fiscal_year_end", "as_of_date"]])
    assert (ok["re_filed"] <= ok["as_of_date"]).all()
