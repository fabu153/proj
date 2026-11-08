"""Stage 2 — search any U.S. public company. SEC is always mocked (tests/fixtures/sec); nothing here calls SEC."""
import gzip
import io
import json
from pathlib import Path

import httpx
import pdfplumber
import pytest
from fastapi.testclient import TestClient

from backend.app.api import main
from backend.app.api.main import app
from backend.app.documents import sec_search
from backend.app.documents.sec_client import SECClient
from backend.app.documents.sec_fixtures import transport

client = TestClient(app)
FIX = Path(__file__).parents[1] / "fixtures" / "sec"
REAL = Path(__file__).parents[2] / "backend" / "data" / "curated"
PATK, BANK, IFRS, NOXBRL = "0000076605", "0000099901", "0000099902", "0000099903"


def _use(tmp_path, tr, **kw):
    sec_search.set_client(SECClient(user_agent="CreditLens-Tests test@example.org", cache_dir=tmp_path,
                                    retries=2, backoff_s=0.0, transport=tr, **kw))


@pytest.fixture(autouse=True)
def mocked_sec(tmp_path, monkeypatch):
    data = {}
    for p in REAL.glob("companyfacts_*.json.gz"):
        with gzip.open(p, "rt") as fh:
            d = json.load(fh)
        data[str(d["cik"]).zfill(10)] = d
    monkeypatch.setattr(main, "_curated", lambda: data)
    calls = []
    fixture = transport(FIX)

    def record(req):
        calls.append(str(req.url))
        return fixture.handle_request(req)
    _use(tmp_path, httpx.MockTransport(record))
    yield calls
    sec_search.set_client(None)


# ------------------------------------------------------------------ search
def _search(q):
    return client.get("/companies/search", params={"q": q})


def test_exact_ticker_ranks_first():
    r = _search("patk").json()["results"]
    assert r[0]["cik"] == PATK and r[0]["match"] == "ticker" and r[0]["tickers"] == ["PATK"]
    assert _search("BRK.B").json()["results"][0]["name"] == "BERKSHIRE HATHAWAY INC"      # dot or dash


def test_partial_name():
    r = _search("patrick ind").json()["results"]
    assert r[0]["cik"] == PATK and r[0]["name"] == "PATRICK INDUSTRIES INC"


def test_cik_with_or_without_zeros():
    for q in ("76605", "0000076605", "CIK0000076605"):
        assert _search(q).json()["results"][0]["cik"] == PATK, q


def test_similar_names_are_all_shown_with_ticker_and_cik():
    r = _search("united").json()["results"]
    names = [x["name"] for x in r]
    assert "UNITED RENTALS, INC." in names and "UNITED PARCEL SERVICE INC" in names
    assert any("NORTH AMERICA" in n for n in names)
    assert all(x["cik"] and len(x["cik"]) == 10 for x in r)
    uri = next(x for x in r if x["name"] == "UNITED RENTALS, INC.")
    assert uri["tickers"] == ["URI"] and uri["curated"] is True


def test_one_entry_per_company_with_all_tickers():
    r = _search("berkshire").json()["results"]
    assert len(r) == 1 and set(r[0]["tickers"]) == {"BRK-B", "BRK-A"}


def test_empty_invalid_and_unmatched_queries():
    assert _search("").status_code == 422
    assert _search("   ").status_code == 422
    assert _search("x" * 200).status_code == 422
    assert _search("zzqqxx nothing").json()["results"] == []
    assert _search("%%%").json()["results"] == []


def test_index_is_fetched_once_and_cached(mocked_sec):
    _search("patk"), _search("united"), _search("pg")
    assert sum("company_tickers" in u for u in mocked_sec) == 1


def test_browser_never_needs_sec(mocked_sec):
    """All SEC traffic is the server's; the API answers the browser with its own data (through /api)."""
    _search("patk")
    assert all(u.startswith(("https://www.sec.gov/files/", "https://data.sec.gov/")) for u in mocked_sec)


# ------------------------------------------------------------------ resolve + analyse a non-curated issuer
def _resolve(cik):
    return client.post("/companies/resolve", json={"cik": cik})


def test_selection_resolves_the_right_company_and_it_is_fully_analysable():
    res = _resolve("76605").json()
    assert res["outcome"] == "full" and res["company"]["company_id"] == PATK
    assert res["company"]["name"] == "PATRICK INDUSTRIES INC" and res["company"]["curated"] is False
    assert res["company"]["tickers"] == ["PATK"] and res["score_status"] == "scored"
    fye = res["fiscal_year_end"]
    a = client.post("/analyses", json={"company_id": PATK, "fiscal_year_end": fye}).json()
    assert a["company_name"] == "PATRICK INDUSTRIES INC" and a["risk_model"]["status"] == "scored"
    ev = a["evidence"]["revenue"]
    assert ev["accession"] and ev["form"].startswith("10-K") and ev["tag"]                # evidence kept
    # listed for whoever opened it, not on everyone's start page
    assert PATK in [c["company_id"] for c in client.get("/companies", params={"include": PATK}).json()]
    assert PATK not in [c["company_id"] for c in client.get("/companies").json()]


def test_point_in_time_and_original_vintage_logic_is_unchanged():
    """The live record goes through the same pipeline as a file on disk: identical analysis, identical score."""
    from backend.app.documents.xbrl import build_company_years
    from backend.app.models import risk
    with gzip.open(FIX / f"companyfacts_{PATK}.json.gz", "rt") as fh:
        offline = json.load(fh)
    live = sec_search.load(PATK)
    ys_off, ys_live = build_company_years(offline), build_company_years(live)
    assert [y.fiscal_year_end for y in ys_off] == [y.fiscal_year_end for y in ys_live]
    assert [y.available_as_of for y in ys_off] == [y.available_as_of for y in ys_live]
    fye = ys_live[-1].fiscal_year_end
    assert risk.score(offline, fye)["probability"] == risk.score(live, fye)["probability"]
    # as-of: a year filed after the as-of date is not visible
    early = build_company_years(live, as_of=ys_live[-1].available_as_of[:4] + "-01-01")
    assert all(y.available_as_of < ys_live[-1].available_as_of for y in early)


def test_stress_and_memo_for_a_searched_company_cite_its_own_filings():
    fye = _resolve(PATK).json()["fiscal_year_end"]
    body = {"company_id": PATK, "fiscal_year_end": fye,
            "facility": {"amount": 200, "currency": "USD", "coupon": 0.065, "floating": True, "tenor_years": 5,
                         "use_of_proceeds": "capex"},
            "covenants": {"max_net_leverage": 3.5, "min_ebitda_interest_cover": 4.0}, "existing_floating_share": 0.3,
            "shocks": [{"name": "Base", "ebitda_shock": 0, "rate_shock_bps": 0},
                       {"name": "Downside", "ebitda_shock": -0.2, "rate_shock_bps": 200},
                       {"name": "Your case", "ebitda_shock": -0.1, "rate_shock_bps": 100}]}
    s = client.post("/scenarios", json=body)
    assert s.status_code == 200 and s.json()["snapshot"]["id"]
    assert client.post("/scenarios/grid", json={k: body[k] for k in ("company_id", "fiscal_year_end", "facility",
                                                                       "covenants", "existing_floating_share")}).status_code == 200
    m = client.post("/memos", json=body).json()
    assert m["package"]["meta.company"]["display"] == "PATRICK INDUSTRIES INC"
    assert m["snapshot"]["id"] == s.json()["snapshot"]["id"]
    pdf = client.get(f"/memos/{m['id']}/pdf", params={"snapshot": m["snapshot"]["id"]})
    assert pdf.status_code == 200
    with pdfplumber.open(io.BytesIO(pdf.content)) as doc:
        text = "\n".join(p.extract_text() or "" for p in doc.pages)
    assert "PATRICK INDUSTRIES" in text
    srcs = [f["source"] for it in m["package"].values() if it["source"].get("trail")
            for f in it["source"]["trail"]["facts"] if f["source"].get("kind") == "sec"]
    assert srcs and all(x["accession"] and "/edgar/data/76605/" in x["url"] for x in srcs)


def test_financial_sector_filer_is_analysed_but_never_scored():
    res = _resolve(BANK).json()
    assert res["outcome"] == "score_withheld" and res["company"]["company_id"] == BANK
    assert res["sic"] == "6022" and any("financial-sector" in g for g in res["gate_reasons"])
    a = client.post("/analyses", json={"company_id": BANK}).json()
    assert a["risk_model"]["status"] == "withheld" and "probability" not in a["risk_model"]
    assert a["metrics"]["net_leverage"]["value"] is not None                                  # ratios still work
    assert res["loan_lab_available"] is True and "loan lab and the memo still work" in res["message"]


def test_filer_without_us_gaap_statements():
    res = _resolve(IFRS).json()
    assert res["outcome"] == "no_supported_statements" and res["company"] is None
    assert "IFRS" in res["message"] and "upload" in res["message"]


def test_filer_without_any_xbrl():
    res = _resolve(NOXBRL)
    assert res.status_code == 200 and res.json()["outcome"] == "no_supported_statements"


def test_unknown_cik_is_404():
    assert _resolve("1234567").status_code == 404
    assert client.post("/analyses", json={"company_id": "0001234567"}).status_code == 404


def test_some_metrics_unavailable_are_never_filled_in(tmp_path):
    """Drop interest expense from the filing: the outcome says so and the ratios are unavailable, not zero."""
    with gzip.open(FIX / f"companyfacts_{PATK}.json.gz", "rt") as fh:
        cf = json.load(fh)
    for t in list(cf["facts"]["us-gaap"]):
        if "Interest" in t:
            del cf["facts"]["us-gaap"][t]
    base = transport(FIX)

    def handler(req):
        if req.url.path.endswith(f"CIK{PATK}.json") and "companyfacts" in req.url.path:
            return httpx.Response(200, json=cf)
        return base.handle_request(req)
    _use(tmp_path, httpx.MockTransport(handler))
    res = _resolve(PATK).json()
    assert res["outcome"] in ("partial", "score_withheld")
    assert "EBITDA / interest" in res["metrics_unavailable"]
    assert res["loan_lab_available"] is False and "loan lab and memo cannot run" in res["message"]
    a = client.post("/analyses", json={"company_id": PATK}).json()
    assert a["metrics"]["ebitda_interest_cover"]["value"] is None
    assert a["metrics"]["ebitda_interest_cover"]["status"] == "not_available"


# ------------------------------------------------------------------ SEC failures
def test_sec_rate_limit_is_reported_as_such(tmp_path):
    _use(tmp_path, httpx.MockTransport(lambda req: httpx.Response(429)))
    r = _search("patk")
    assert r.status_code == 429 and "rate limit" in r.json()["detail"]
    r = _resolve(PATK)
    assert r.status_code == 429 and "rate limit" in r.json()["detail"]


def test_sec_network_failure_is_reported_as_such(tmp_path):
    def down(req):
        raise httpx.ConnectError("no route", request=req)
    _use(tmp_path, httpx.MockTransport(down))
    r = _search("patk")
    assert r.status_code == 502 and "cannot be reached" in r.json()["detail"]
    r = _resolve(PATK)
    assert r.status_code == 502 and "unavailable" in r.json()["detail"]


def test_sec_refusing_the_user_agent_is_explained(tmp_path):
    _use(tmp_path, httpx.MockTransport(lambda req: httpx.Response(403)))
    r = _resolve(PATK)
    assert r.status_code == 502 and "SEC_USER_AGENT" in r.json()["detail"]


def test_a_cached_list_is_used_when_sec_goes_down(tmp_path):
    _search("patk")                                          # warm the on-disk cache through the fixture client
    cache = sec_search.client().cache_dir
    sec_search.set_client(SECClient(cache_dir=cache, retries=1, backoff_s=0,
                                    transport=httpx.MockTransport(lambda req: httpx.Response(503))))
    import os
    import time
    p = cache / "company_tickers_exchange.json.gz"
    old = time.time() - 3 * 86400
    os.utime(p, (old, old))                                  # expired, and SEC is down
    r = _search("patk").json()
    assert r["results"][0]["cik"] == PATK and "cached copy" in r["index"]["source"]


# ------------------------------------------------------------------ nothing else changes
def test_curated_samples_and_uploads_untouched(mocked_sec):
    cs = client.get("/companies").json()
    assert {c["company_id"] for c in cs} == {"0000080424", "0001067701", "0001278027"}
    assert all(c["curated"] for c in cs)
    res = _resolve("0001067701").json()                      # a curated issuer is served from the sample file
    assert res["company"]["curated"] is True and res["source"] == "SEC XBRL companyfacts"
    a = client.post("/analyses", json={"company_id": "0001067701"}).json()
    assert a["source"] == "SEC XBRL companyfacts"
    assert not any("companyfacts" in u or "submissions" in u for u in mocked_sec)   # no SEC call for samples


def test_whole_suite_runs_without_sec():
    """conftest points every test at the mocked SEC; an unknown CIK is a clean 404, not a network call."""
    import os
    sec_search.set_client(None)
    assert os.environ.get("CREDITLENS_SEC_FIXTURES")
    assert isinstance(sec_search.client()._http._transport, httpx.MockTransport)
    assert client.post("/analyses", json={"company_id": "9999999999"}).status_code == 404
