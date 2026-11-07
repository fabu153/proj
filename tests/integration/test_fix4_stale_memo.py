"""Fix 4 — an outdated memo can never be exported as current.

Server side: the PDF endpoint takes the snapshot the loan lab shows and refuses (409) a memo built from any other.
Each input the UI lets the user change (amount, coupon, currency/FX, EBITDA shock, rate shock, covenants) must change
the snapshot, so a memo drafted before the change no longer exports. The browser-side gate is tested in
tests/end_to_end/test_demo_flow.py.
"""
import gzip
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.api import main
from backend.app.api.main import app

client = TestClient(app)
REAL = Path(__file__).parents[2] / "backend" / "data" / "curated"
URI = "0001067701"


@pytest.fixture(autouse=True)
def real_issuers(monkeypatch):
    data = {}
    for p in REAL.glob("companyfacts_*.json.gz"):
        with gzip.open(p, "rt") as fh:
            d = json.load(fh)
        data[str(d["cik"]).zfill(10)] = d
    monkeypatch.setattr(main, "_curated", lambda: data)


def _body(**fac):
    f = {"amount": 750, "currency": "USD", "coupon": 0.065, "floating": True, "tenor_years": 5, "use_of_proceeds": "capex"}
    f.update(fac.pop("facility", {}))
    b = {"company_id": URI, "facility": f, "covenants": {"max_net_leverage": 3.0, "min_ebitda_interest_cover": 4.0},
         "existing_floating_share": 0.3,
         "shocks": [{"name": "Base", "ebitda_shock": 0, "rate_shock_bps": 0},
                    {"name": "Downside", "ebitda_shock": -0.2, "rate_shock_bps": 200}]}
    b.update(fac)
    return b


CHANGES = {
    "amount": _body(facility={"amount": 900}),
    "coupon": _body(facility={"coupon": 0.07}),
    "currency_fx": _body(facility={"currency": "EUR", "fx_rate_to_reporting": 1.08}),
    "fx_rate": None,   # filled below: a change of the FX rate alone
    "ebitda_shock": _body(shocks=[{"name": "Base", "ebitda_shock": 0, "rate_shock_bps": 0},
                                  {"name": "Downside", "ebitda_shock": -0.3, "rate_shock_bps": 200}]),
    "rate_shock": _body(shocks=[{"name": "Base", "ebitda_shock": 0, "rate_shock_bps": 0},
                                {"name": "Downside", "ebitda_shock": -0.2, "rate_shock_bps": 300}]),
    "covenants": _body(covenants={"max_net_leverage": 3.5, "min_ebitda_interest_cover": 4.0}),
}
CHANGES["fx_rate"] = _body(facility={"currency": "EUR", "fx_rate_to_reporting": 1.10})


def _snap(body):
    r = client.post("/scenarios", json=body)
    assert r.status_code == 200, r.text
    return r.json()["snapshot"]["id"]


def test_current_memo_exports():
    m = client.post("/memos", json=_body()).json()
    sid = _snap(_body())
    assert m["snapshot"]["id"] == sid
    r = client.get(f"/memos/{m['id']}/pdf", params={"snapshot": sid})
    assert r.status_code == 200 and r.content[:4] == b"%PDF"


@pytest.mark.parametrize("what", list(CHANGES))
def test_any_input_change_blocks_the_old_memo(what):
    m = client.post("/memos", json=_body()).json()
    old = m["snapshot"]["id"]
    ref = _body(facility={"currency": "EUR", "fx_rate_to_reporting": 1.08}) if what == "fx_rate" else _body()
    if what == "fx_rate":
        m = client.post("/memos", json=ref).json()
        old = m["snapshot"]["id"]
    new = _snap(CHANGES[what])
    assert new != old, f"changing {what} must change the snapshot"
    r = client.get(f"/memos/{m['id']}/pdf", params={"snapshot": new})
    assert r.status_code == 409 and old in r.json()["detail"] and new in r.json()["detail"]


def test_late_memo_for_old_inputs_is_refused_against_new_snapshot():
    """A memo request sent before the change and answered after it describes the old snapshot, not the new one."""
    new = _snap(_body(facility={"amount": 900}))
    late = client.post("/memos", json=_body()).json()          # the reply to the request sent with the old inputs
    assert late["snapshot"]["id"] != new
    assert client.get(f"/memos/{late['id']}/pdf", params={"snapshot": new}).status_code == 409


def test_invalid_inputs_produce_no_snapshot():
    for bad in (_body(facility={"amount": -5}), _body(facility={"coupon": 2.0}),
                _body(facility={"currency": "EUR"})):           # foreign currency without an FX rate
        r = client.post("/scenarios", json=bad)
        assert r.status_code == 422, (bad["facility"], r.status_code)
