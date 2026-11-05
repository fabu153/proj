"""Stage F (v1.3): the stress heatmap is computed cell by cell by the existing Python scenario engine."""
import gzip
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.api import main
from backend.app.api.main import app
from backend.app.scenarios import loan

ROOT = Path(__file__).parents[2]
client = TestClient(app)
BODY = {"company_id": "0001278027", "facility": {"amount": 100, "currency": "USD", "floating": True},
        "covenants": {"max_net_leverage": 6.0, "min_ebitda_interest_cover": 1.0}, "existing_floating_share": 0.5}


@pytest.fixture(autouse=True)
def real_issuers(monkeypatch):
    data = {}
    for p in (ROOT / "backend/data/curated").glob("companyfacts_*.json.gz"):
        with gzip.open(p, "rt") as fh:
            d = json.load(fh)
        data[str(d["cik"]).zfill(10)] = d
    monkeypatch.setattr(main, "_curated", lambda: data)


def test_grid_shape_and_axes_match_the_roadmap():
    g = client.post("/scenarios/grid", json=BODY).json()
    assert g["ebitda_shocks"] == [-0.5, -0.4, -0.3, -0.2, -0.1, 0.0, 0.1]
    assert g["rate_shocks_bps"] == [0, 100, 200, 300, 400, 500]
    assert len(g["cells"]) == 6 and all(len(r) == 7 for r in g["cells"])


def test_every_cell_is_one_engine_call_with_identical_results(monkeypatch):
    calls = []
    real = loan.run_scenario

    def spy(*a, **k):
        calls.append(a[2])
        return real(*a, **k)
    monkeypatch.setattr(main, "run_scenario", spy)
    g = client.post("/scenarios/grid", json=BODY).json()
    assert len(calls) == 42
    base, _ = main._baseline("0001278027", None, 0.5)
    fac, cov = loan.Facility(**BODY["facility"]), loan.Covenants(**BODY["covenants"])
    for row in g["cells"]:
        for c in row:
            ref = real(base, fac, loan.Shock(ebitda_shock=c["ebitda_shock"], rate_shock_bps=c["rate_shock_bps"]), cov)
            assert c["net_leverage"] == pytest.approx(ref.net_leverage)
            assert c["ebitda_interest_cover"] == pytest.approx(ref.ebitda_interest_cover)
            assert c["headroom_lev"] == pytest.approx(ref.covenant_headroom["max_net_leverage"])
            assert c["breach"] == any(v < 0 for v in ref.covenant_headroom.values())


def test_grid_cell_matches_the_loan_table_for_the_same_case():
    g = client.post("/scenarios/grid", json=BODY).json()
    cell = g["cells"][2][3]                                  # +200 bp, EBITDA -20%
    s = client.post("/scenarios", json={**BODY, "shocks": [{"name": "Your case", "ebitda_shock": -0.2,
                                                             "rate_shock_bps": 200}]}).json()["results"][0]
    assert (cell["ebitda_shock"], cell["rate_shock_bps"]) == (-0.2, 200)
    assert cell["net_leverage"] == pytest.approx(s["net_leverage"])
    assert cell["ebitda_interest_cover"] == pytest.approx(s["ebitda_interest_cover"])


def test_rate_shock_moves_cover_not_leverage():
    g = client.post("/scenarios/grid", json=BODY).json()
    col = [row[5] for row in g["cells"]]                     # EBITDA unchanged
    assert len({round(c["net_leverage"], 9) for c in col}) == 1
    covers = [c["ebitda_interest_cover"] for c in col]
    assert covers == sorted(covers, reverse=True) and covers[0] > covers[-1]


def test_grid_rejects_out_of_range_shocks_and_mixed_currency():
    assert client.post("/scenarios/grid", json={**BODY, "ebitda_shocks": [-2.0]}).status_code == 422
    r = client.post("/scenarios/grid", json={**BODY, "facility": {"amount": 100, "currency": "EUR"}})
    assert r.status_code == 422 and "FX" in r.text.upper()
