"""API contract tests — company -> analysis -> scenario, end to end on the synthetic fixture."""
import pytest
from fastapi.testclient import TestClient

from backend.app.api.main import app

client = TestClient(app)
CID = "0000000001"


def test_companies_lists_fixture_marked_synthetic():
    body = client.get("/companies").json()
    assert body[0]["company_id"] == CID and body[0]["synthetic"] is True
    assert body[0]["fiscal_years"] == ["2023-12-31", "2024-12-31", "2025-12-31"]


def test_analysis_returns_metrics_with_evidence():
    r = client.post("/analyses", json={"company_id": CID}).json()
    assert r["fiscal_year_end"] == "2025-12-31" and r["scorable"] and r["review_required"]
    assert r["metrics"]["ebitda"]["value"] == pytest.approx(238.0)            # 176 + 62
    assert r["metrics"]["gross_debt"]["value"] == pytest.approx(300.0)        # 0 + 30 + 270
    assert r["metrics"]["net_leverage"]["value"] == pytest.approx(250 / 238)
    assert r["evidence"]["revenue"]["accession"] == "0000000001-26-000010"
    assert r["risk_model"]["status"] == "scored" and "disclaimer" in r["risk_model"]


def test_point_in_time_analysis():
    r = client.post("/analyses", json={"company_id": CID, "as_of": "2025-06-30"}).json()
    assert r["fiscal_year_end"] == "2024-12-31"


def test_scenario_eur_facility_on_usd_company_is_blocked_without_fx():
    r = client.post("/scenarios", json={"company_id": CID})
    assert r.status_code == 422 and "FX rate" in r.json()["detail"]


def test_scenario_with_fx_returns_three_cases():
    r = client.post("/scenarios", json={"company_id": CID, "facility": {
        "amount": 100, "currency": "EUR", "fx_rate_to_reporting": 1.08, "fx_rate_date": "2026-11-04"}})
    assert r.status_code == 200
    names = [x["name"] for x in r.json()["results"]]
    assert names == ["base", "downside", "severe_downside"]


def test_unknown_company_404():
    assert client.post("/analyses", json={"company_id": "9999999999"}).status_code == 404


def test_predict_and_model_endpoints():
    r = client.post("/predict", json={"company_id": CID}).json()
    assert r["status"] == "scored" and r["fiscal_year_end"] == "2025-12-31"
    m = client.get("/model").json()
    assert m["metadata"]["model"] == "stress_mlp_v1" and m["xray"]["leaderboard"][0]["model"].startswith("MLP")


def test_history_has_one_point_per_year():
    h = client.get(f"/companies/{CID}/history").json()
    assert [p["fiscal_year_end"] for p in h] == ["2023-12-31", "2024-12-31", "2025-12-31"]
    assert h[-1]["metrics"]["ebitda"] == pytest.approx(238.0)


def test_scenario_returns_facility_schedule():
    r = client.post("/scenarios", json={"baseline_override": {"currency": "EUR", "ebitda": 100, "gross_debt": 300,
                                                             "cash": 50, "interest_expense": 20}}).json()
    assert len(r["facility_schedule"]) == 5 and r["facility_schedule"][-1]["closing"] == 0


def test_cors_allows_vercel_frontend_only():
    ok = client.options("/companies", headers={"Origin": "https://creditlens-git-main-fabu153.vercel.app",
                                               "Access-Control-Request-Method": "GET"})
    bad = client.options("/companies", headers={"Origin": "https://evil.example.com",
                                                "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "https://creditlens-git-main-fabu153.vercel.app"
    assert "access-control-allow-origin" not in bad.headers
