"""Fix 2 (negative-EBITDA shocks) and Fix 3 (PASS / BREACH / NOT TESTABLE covenants), engine v1.2.0."""
import gzip
import io
import json
from pathlib import Path

import pdfplumber
import pytest
from fastapi.testclient import TestClient

from backend.app.api import main
from backend.app.scenarios.loan import ENGINE_VERSION, Baseline, Covenants, CovenantState, Facility, Shock, run_scenario

ROOT = Path(__file__).parents[2]
COV = Covenants(max_net_leverage=3.5, min_ebitda_interest_cover=3.0)


def base(ebitda, interest=10.0, debt=200.0, cash=20.0):
    return Baseline(currency="USD", ebitda=ebitda, gross_debt=debt, cash=cash, interest_expense=interest)


# ------------------------------------------------------------------ Fix 2
@pytest.mark.parametrize("b,shock,expected", [(100, -0.2, 80), (-100, -0.2, -120), (-100, 0.2, -80), (100, 0.2, 120),
                                              (-50, -0.5, -75), (100, 0.0, 100)])
def test_shock_moves_ebitda_by_a_share_of_its_size(b, shock, expected):
    r = run_scenario(base(b), None, Shock(ebitda_shock=shock))
    assert r.ebitda == pytest.approx(expected)


def test_downside_never_improves_a_loss():
    for s in (-0.05, -0.2, -0.35, -0.5, -1.0):
        assert run_scenario(base(-40), None, Shock(ebitda_shock=s)).ebitda < -40


def test_positive_ebitda_unchanged_from_previous_convention():
    for b in (1.0, 50.0, 7081.0):
        for s in (-0.5, -0.2, 0.1):
            assert run_scenario(base(b), None, Shock(ebitda_shock=s)).ebitda == pytest.approx(b * (1 + s))


def test_zero_ebitda_shock_is_not_applied_and_says_so():
    r = run_scenario(base(0.0), None, Shock(ebitda_shock=-0.2))
    assert r.ebitda == 0.0 and "EBITDA_ZERO_SHOCK_NOT_APPLICABLE" in r.flags
    assert any("no absolute effect" in s for s in r.steps)
    assert r.net_leverage is None                                # leverage stays undefined


def test_negative_ebitda_trail_explains_the_convention():
    r = run_scenario(base(-100), None, Shock(ebitda_shock=-0.2))
    assert any("applied to the size of the loss" in s and "-120.00" in s for s in r.steps)
    assert ENGINE_VERSION == "1.2.0"


# ------------------------------------------------------------------ Fix 3
def states(r):
    return {k: a.state for k, a in r.covenant_status.items()}


def test_positive_ebitda_pass_and_breach():
    ok = run_scenario(base(100, debt=200), None, Shock(), COV)        # 1.8x, cover 10x
    assert states(ok) == {"max_net_leverage": CovenantState.PASS, "min_ebitda_interest_cover": CovenantState.PASS}
    bad = run_scenario(base(40, debt=200, interest=20), None, Shock(), COV)   # 4.5x, cover 2x
    assert states(bad) == {"max_net_leverage": CovenantState.BREACH, "min_ebitda_interest_cover": CovenantState.BREACH}
    assert bad.covenant_headroom["max_net_leverage"] == pytest.approx(3.5 - 180 / 40)    # numerically unchanged
    assert "COVENANT_BREACH:max_net_leverage" in bad.flags


@pytest.mark.parametrize("ebitda", [-50.0, 0.0])
def test_nonpositive_ebitda_leverage_is_not_testable_by_default(ebitda):
    r = run_scenario(base(ebitda), None, Shock(), COV)
    a = r.covenant_status["max_net_leverage"]
    assert a.state is CovenantState.NOT_TESTABLE and a.value is None and a.headroom is None
    assert "undefined" in a.reason
    assert "COVENANT_BREACH:max_net_leverage" not in r.flags and "COVENANT_NOT_TESTABLE:max_net_leverage" in r.flags


def test_negative_ebitda_interest_cover_is_a_valid_breach():
    r = run_scenario(base(-50.0), None, Shock(), COV)                 # cover -5x is a real number below 3x
    assert r.covenant_status["min_ebitda_interest_cover"].state is CovenantState.BREACH


def test_contractual_policy_turns_undefined_leverage_into_breach_only_when_chosen():
    cov = Covenants(max_net_leverage=3.5, nonpositive_ebitda_breaches_leverage=True)
    a = run_scenario(base(-50.0), None, Shock(), cov).covenant_status["max_net_leverage"]
    assert a.state is CovenantState.BREACH and "agreement treats this as a breach" in a.reason


def test_zero_interest_cover_is_not_testable():
    r = run_scenario(base(100, interest=0.0, debt=0.0, cash=10), None, Shock(), COV)
    a = r.covenant_status["min_ebitda_interest_cover"]
    assert a.state is CovenantState.NOT_TESTABLE and "interest expense is zero" in a.reason


# ------------------------------------------------------------------ outputs agree (API, heatmap, memo, PDF)
@pytest.fixture
def client(monkeypatch):
    data = {}
    for p in (ROOT / "backend/data/curated").glob("companyfacts_*.json.gz"):
        with gzip.open(p, "rt") as fh:
            d = json.load(fh)
        data[str(d["cik"]).zfill(10)] = d
    monkeypatch.setattr(main, "_curated", lambda: data)
    return TestClient(main.app)


BG_LOSS_YEAR = {"company_id": "0001278027", "fiscal_year_end": "2024-12-28",          # EBITDA about -109m
                "facility": {"amount": 100, "currency": "USD"},
                "covenants": {"max_net_leverage": 6.0, "min_ebitda_interest_cover": 1.0}}


def test_missing_interest_blocks_the_scenario_with_a_reason(client, monkeypatch):
    from backend.app.scenarios import snapshot
    real = snapshot.credit_baseline
    monkeypatch.setattr(main, "credit_baseline", lambda cy, ccy, fs: (None, ["interest_expense"]))
    r = client.post("/scenarios", json=BG_LOSS_YEAR)
    assert r.status_code == 422 and "interest_expense" in r.json()["detail"]
    monkeypatch.setattr(main, "credit_baseline", real)


def test_table_heatmap_memo_and_pdf_agree_on_states(client):
    s = client.post("/scenarios", json={**BG_LOSS_YEAR, "shocks": [{"name": "Base"}, {"name": "Downside",
                                        "ebitda_shock": -0.2, "rate_shock_bps": 200}]}).json()
    base_r, down = s["results"]
    assert base_r["ebitda"] < 0 and down["ebitda"] < base_r["ebitda"]                       # Fix 2 end to end
    assert down["covenant_status"]["max_net_leverage"]["state"] == "not_testable"
    assert down["covenant_status"]["min_ebitda_interest_cover"]["state"] == "breach"
    g = client.post("/scenarios/grid", json=BG_LOSS_YEAR).json()
    cell = g["cells"][2][3]                                                              # -20%, +200 bp
    assert cell["state_lev"] == "not_testable" and cell["state_cov"] == "breach" and cell["breach"]
    assert all(c["state_lev"] == "not_testable" for row in g["cells"] for c in row)
    m = client.post("/memos", json={**BG_LOSS_YEAR, "shocks": [{"name": "Base"}, {"name": "Downside",
                                     "ebitda_shock": -0.2, "rate_shock_bps": 200}]}).json()
    assert m["summary"]["flagged"] == 0
    assert m["package"]["scen.downside.headroom_lev_state"]["value"] == "not testable"
    assert "scen.downside.headroom_lev" not in m["package"]                              # no fabricated headroom
    txt = " ".join(x["text"] for sec in m["sections"] for x in sec["sentences"])
    assert "cannot be tested" in txt and "breached by" in txt
    with pdfplumber.open(io.BytesIO(client.get(f"/memos/{m['id']}/pdf").content)) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    assert "not testable (N/A)" in text and "breach " in text


def test_validator_rejects_calling_an_untestable_covenant_a_breach(client):
    from backend.app.memos.package import Package
    from backend.app.memos.validator import validate_sentence
    m = client.post("/memos", json=BG_LOSS_YEAR).json()
    pk = Package(m["currency"])
    pk.items = m["package"]
    bad = validate_sentence("In the downside case the covenant is breached: {{scen.downside.headroom_lev_reason}}.", "claim", pk)
    assert bad["status"] == "flagged" and any("cannot be tested" in i for i in bad["issues"])
