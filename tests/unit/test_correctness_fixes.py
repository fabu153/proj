"""Correctness fixes found in review: each test reproduces the input that used to give a wrong answer."""
import gzip
import json
import math
import os
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pandas as pd
import pytest
import yaml
from pydantic import ValidationError

from backend.app.api import main
from backend.app.documents.pdf_extract import detect_scale, detect_year_end, split_line
from backend.app.documents import sec_client
from backend.app.documents.sec_client import SECClient, SECError
from backend.app.documents.xbrl import consecutive
from backend.app.features.feature_set import FEATURES
from backend.app.finance.credit_extras import maturity_wall
from backend.app.labels import stress_label as sl
from backend.app.memos import service
from backend.app.memos.package import build_package
from backend.app.memos.pdf import render_pdf
from backend.app.memos.validator import validate_sentence
from backend.app.models.inference import get_model
from backend.app.scenarios.loan import (DEFAULT_CASES, Baseline, Covenants, Facility, ScenarioInputError, Shock,
                                        UseOfProceeds, run_scenario)

CID = "0000000001"
ASSUMPTIONS = yaml.safe_load((Path(__file__).parents[2] / "configs" / "assumptions.yaml").read_text())


# ------------------------------------------------------------------ the code honours the frozen assumptions
def test_label_thresholds_are_the_frozen_assumptions():
    a = ASSUMPTIONS["stress_label"]
    assert (sl.EBIT_COVER_MAX, sl.LEVERAGE_MAX, sl.CFO_MIN, sl.MIN_CONDITIONS) == (
        a["ebit_interest_cover_below"], a["gross_debt_to_ebitda_above"], a["cfo_below"], a["min_conditions"])


def test_stress_cases_and_sample_facility_are_the_frozen_assumptions():
    cases = ASSUMPTIONS["stress_cases"]
    assert [(s.ebitda_shock, s.rate_shock_bps) for s in DEFAULT_CASES] == [
        (cases[k]["ebitda_shock"], cases[k]["rate_shock_bps"]) for k in ("base", "downside", "severe_downside")]
    f, fac = ASSUMPTIONS["sample_facility"], Facility(amount=100)
    assert (fac.currency, fac.coupon, fac.tenor_years) == (f["currency"], f["coupon"], f["tenor_years"])


@pytest.mark.parametrize("vals, label", [
    # exactly at a threshold: "below 1.5x", "above 5.0x" and "CFO below 0" do not fire
    ({"operating_income": 1.5, "interest_expense": 1, "gross_debt": 50, "ebitda": 10, "operating_cash_flow": 0}, 0),
    ({"operating_income": 1.49, "interest_expense": 1, "gross_debt": 50.1, "ebitda": 10, "operating_cash_flow": 0}, 1),
    ({"operating_income": 1, "interest_expense": 1, "gross_debt": 1, "ebitda": 10, "operating_cash_flow": None}, None),
    ({"operating_income": 9, "interest_expense": 1, "gross_debt": 1, "ebitda": 10, "operating_cash_flow": None}, 0),
    ({"operating_income": -5, "interest_expense": 0, "gross_debt": 0, "ebitda": -2, "operating_cash_flow": -1}, 0),
    ({"operating_income": -5, "interest_expense": 0, "gross_debt": 1, "ebitda": -2, "operating_cash_flow": -1}, 1),
])
def test_stress_label_boundaries(vals, label):
    assert sl.stress_label(vals).label == label


# ------------------------------------------------------------------ inference gate
def test_missing_revenue_is_outside_the_model_population():
    m, row = get_model(), pd.DataFrame([{f: 0.0 for f in FEATURES}])
    ok = {"scorable": 1, "v_revenue": 1000.0, "critical_coverage": 1.0}
    assert not [r for r in m.gate(row, ok) if "population" in r]
    assert [r for r in m.gate(row, {**ok, "v_revenue": float("nan")}) if "population" in r]


# ------------------------------------------------------------------ loan engine
def test_a_ratio_exactly_at_its_limit_passes():
    cover = run_scenario(Baseline(currency="USD", ebitda=21, gross_debt=0, cash=0, interest_expense=0),
                         Facility(amount=100, currency="USD", coupon=0.07, floating=False), Shock(),
                         Covenants(min_ebitda_interest_cover=3.0))
    assert cover.ebitda_interest_cover != 3.0                          # 2.9999999999999996: float noise
    a = cover.covenant_status["min_ebitda_interest_cover"]
    assert a.state.value == "pass" and a.headroom == 0.0
    lev = run_scenario(Baseline(currency="USD", ebitda=0.3, gross_debt=2.1, cash=0, interest_expense=0.01), None,
                       Shock(), Covenants(max_net_leverage=7.0))
    assert lev.net_leverage > 7.0                                      # 7.000000000000001
    assert lev.covenant_status["max_net_leverage"].state.value == "pass"


@pytest.mark.parametrize("model, kw", [(Baseline, {"currency": "USD", "ebitda": math.nan, "gross_debt": 1, "cash": 0,
                                                   "interest_expense": 1}),
                                       (Facility, {"amount": math.inf}),
                                       (Covenants, {"max_net_leverage": math.nan})])
def test_nan_and_infinity_are_refused(model, kw):
    with pytest.raises(ValidationError):
        model(**kw)


def test_refinancing_at_the_suggested_rounded_rate_runs():
    base = Baseline(currency="USD", ebitda=50, gross_debt=100, cash=10, interest_expense=10)
    fac = Facility(amount=100, currency="USD", use_of_proceeds=UseOfProceeds.REFINANCING, refinanced_debt_rate=0.1004)
    r = run_scenario(base, fac, Shock())                               # 10.04 vs 10.00 reported: rounding only
    assert r.interest_expense == pytest.approx(6.0) and any("capped at 10.00" in s for s in r.steps)
    with pytest.raises(ScenarioInputError, match="conflicts with the reported figures"):
        run_scenario(base, fac.model_copy(update={"refinanced_debt_rate": 0.12}), Shock())


# ------------------------------------------------------------------ maturity wall: missing is not zero
def _sup(**buckets):
    return {k: SimpleNamespace(value=v, tag="T", accession="A", form="10-K", filed="2025-02-01",
                               period_end="2024-12-31") for k, v in buckets.items()}


VALS = {"cash": 50.0, "short_term_borrowings": 0.0, "long_term_debt": 900.0, "current_maturities_ltd": 10.0}
ALL = {"debt_maturity_y1": 10, "debt_maturity_y2": 10, "debt_maturity_y3": 100, "debt_maturity_y4": 100,
       "debt_maturity_y5": 100, "debt_maturity_after5": 590}


@pytest.mark.parametrize("lt, cm, balance", [(0.0, 0.0, 0.0), (900.0, 10.0, 910.0), (None, None, None)])
def test_long_term_debt_balance_of_zero_is_zero(lt, cm, balance):
    w = maturity_wall(_sup(**ALL), {**VALS, "long_term_debt": lt, "current_maturities_ltd": cm}, 5.0, 1)
    assert w["long_term_debt_balance"] == balance


# ------------------------------------------------------------------ memo: contractual breach
def test_a_contractual_leverage_breach_is_written_and_printed():
    memo = service.generate(main._cf(CID), CID, None, Facility(amount=100, currency="USD"),
                            Covenants(max_net_leverage=3.5, nonpositive_ebitda_breaches_leverage=True),
                            prefer_llm=False,
                            shocks=[Shock(name="Base"), Shock(name="Downside", ebitda_shock=-1.0),
                                    Shock(name="Your case", ebitda_shock=-1.0)])
    cov = next(s for sec in memo["sections"] if sec["key"] == "covenants" for s in sec["sentences"]
               if "own case" in s["text"])
    assert cov["status"] == "ok" and "breached" in cov["text"], cov
    summary = next(s for sec in memo["sections"] if sec["key"] == "executive" for s in sec["sentences"]
                   if "downside case breaches" in s["text"])
    assert summary["status"] == "ok", summary                          # used to cite a missing shortfall item
    assert memo["summary"]["flagged"] == 0
    assert render_pdf(memo)[:5] == b"%PDF-"                            # used to fail: -None


# ------------------------------------------------------------------ memo validator: typed numbers
@pytest.fixture(scope="module")
def pk():
    return build_package(main._cf(CID), CID, None, Facility(amount=100, currency="USD"), None)


def test_validator_flags_numbers_it_used_to_skip(pk):
    fcf = pk.val("metric.fcf_simple.t")
    assert fcf > 0
    ok = lambda t: validate_sentence(t, "claim", pk)["status"] == "ok"  # noqa: E731
    assert ok(f"Free cash flow was USD {fcf:,.1f}m in {{{{meta.fye}}}}.")
    assert not ok(f"Free cash flow was USD -{fcf:,.1f}m in {{{{meta.fye}}}}.")       # explicit wrong sign
    assert not ok("Debt of USD500m is due, says {{meta.company}}.")                   # glued to a currency
    assert not ok("Debt of c.500m is due, says {{meta.company}}.")                    # glued to an abbreviation
    assert not ok("Revenue was 2,050 at {{meta.company}}.")                           # an amount, not a year
    assert ok("The 2025 10-K of {{meta.company}} is the source.")                      # a year and a form name
    assert not ok(f"Free cash flow was USD \u2212{fcf:,.1f}m in {{{{meta.fye}}}}.")   # a typeset minus sign
    assert ok("See Appendix C.2 and the Class C1 notes of {{meta.company}}.")         # references, not amounts
    m = pk.val("metric.ebitda_margin.t") * 100
    assert ok(f"The EBITDA margin of {{{{meta.company}}}} is {m:.1f}%-{m:.1f}%.")   # a range, not minus


# ------------------------------------------------------------------ PDF extraction
@pytest.mark.parametrize("line, values", [
    ("Long-term debt 4 $ 1,250 $ -", [1250.0, 0.0]),          # a hyphen printed for nil keeps the columns aligned
    ("Short-term borrowings 9 - 150", [0.0, 150.0]),           # "- 150" is a nil dash and 150, not -150
    ("Interest expense $ (12.5) $ (11.0)", [-12.5, -11.0]),
    ("Revenue -5 -7", [-5.0, -7.0]),
    ("Long-term debt, net 1,250 1,100", [1250.0, 1100.0]),
    ("Other income \u22125 10", [-5.0, 10.0]),                   # a typeset minus sign
    ("Revenue - net 1,000 900", [1000.0, 900.0]),
])
def test_nil_dashes_keep_year_columns_aligned(line, values):
    assert split_line(line, 2)[1] == values


def test_a_dash_inside_a_label_is_never_a_value():
    assert split_line("Revenue - net 1,000", 2) is None            # one value for two columns: not read
    assert split_line("Total - continuing operations 500", 2) is None


def test_year_end_is_the_latest_listed_year():
    assert detect_year_end("For the years ended December 31, 2021, 2022 and 2023", 2023) == ("2023-12-31", False)
    assert detect_year_end("Fiscal years ended January 3, 2026 and December 28, 2024", 2025) == ("2026-01-03", False)
    assert detect_year_end("fiscal years ended September 24, 2022, September 30, 2023 and September 28, 2024",
                           2024) == ("2024-09-28", False)
    assert detect_year_end("Year ended December 31, 2023, 2025 Senior Notes", 2023) == ("2023-12-31", False)


def test_share_counts_do_not_set_the_unit_scale():
    assert detect_scale("(In thousands)\nWeighted average shares: 12.3 millions of shares") == (1e3, "thousands")


def test_consecutive_fiscal_years():
    assert consecutive("2024-12-31", "2025-12-31") and consecutive("2024-12-28", "2026-01-03")   # 53-week year
    assert not consecutive("2023-12-31", "2025-12-31")


# ------------------------------------------------------------------ SEC client cache and throttling
def _client(tmp_path, handler, **kw):
    return SECClient(cache_dir=tmp_path, transport=httpx.MockTransport(handler), backoff_s=0.01, **kw)


def test_sec_cache_recovers_from_damage_and_clock_changes(tmp_path):
    calls = []
    c = _client(tmp_path, lambda req: (calls.append(1), httpx.Response(200, json={"n": len(calls)}))[1], retries=0)
    assert c._cached("https://x/a", "a", False) == {"n": 1}                    # retries=0 still makes the request
    (tmp_path / "a.json.gz").write_bytes(gzip.compress(b'{"n": 1')[:-6])       # a write cut short
    assert c._cached("https://x/a", "a", False, max_age_s=3600) == {"n": 2}
    future = time.time() + 10 ** 7
    os.utime(tmp_path / "a.json.gz", (future, future))                         # stamped in the future
    assert c._cached("https://x/a", "a", False, max_age_s=3600) == {"n": 3}
    assert c._cached("https://x/a", "a", False, max_age_s=3600) == {"n": 3}    # fresh now: served from the cache
    assert not list(tmp_path.glob("*.tmp"))


def test_sec_long_retry_after_fails_fast(tmp_path):
    calls = []
    c = _client(tmp_path, lambda req: (calls.append(1), httpx.Response(429, headers={"retry-after": "600"}))[1])
    with pytest.raises(SECError) as e:
        c._fetch("https://x/slow")
    assert e.value.kind == "throttled" and len(calls) == 1


def test_sec_retry_after_as_an_http_date(tmp_path):
    from email.utils import format_datetime
    from datetime import datetime, timedelta, timezone
    later = format_datetime(datetime.now(timezone.utc) + timedelta(minutes=10), usegmt=True)
    calls = []
    c = _client(tmp_path, lambda req: (calls.append(1), httpx.Response(429, headers={"retry-after": later}))[1])
    with pytest.raises(SECError):
        c._fetch("https://x/slow")
    assert len(calls) == 1                                             # ten minutes away: not waited out


def test_sec_cache_leaves_no_temp_file_when_writing_fails(tmp_path, monkeypatch):
    c = _client(tmp_path, lambda req: httpx.Response(200, json={"n": 1}))
    monkeypatch.setattr(sec_client.json, "dump", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        c._cached("https://x/a", "a", False)
    assert not list(tmp_path.glob("*.tmp")) and not (tmp_path / "a.json.gz").exists()


def test_sec_short_retry_after_is_waited(tmp_path):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(200, json={}) if len(calls) > 1 else httpx.Response(503, headers={"retry-after": "0"})
    assert _client(tmp_path, handler)._fetch("https://x/a")[0] == {} and len(calls) == 2


RAW_FACTS = {"cik": 1, "entityName": "T", "facts": {"us-gaap": {"Revenues": {"units": {"USD": [{"val": 1}]}},
                                                              "SomethingUnused": {"units": {"USD": []}}}}}
FACTS_FILE = "companyfacts_0000000001.json.gz"


def _rewrite(path: Path, change) -> None:
    with gzip.open(path, "rt") as fh:
        d = json.load(fh)
    change(d)
    with gzip.open(path, "wt") as fh:
        json.dump(d, fh)


def test_cached_companyfacts_record_their_tag_list(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(sec_client, "_warned", set())
    c = _client(tmp_path, lambda req: httpx.Response(200, json=RAW_FACTS))
    cf = c.company_facts(1)
    assert set(cf) == {"cik", "entityName", "facts"} and "SomethingUnused" not in cf["facts"]["us-gaap"]
    with gzip.open(tmp_path / FACTS_FILE, "rt") as fh:
        assert "Revenues" in json.load(fh)[sec_client.TAGS_KEY]
    with caplog.at_level("WARNING", logger="creditlens"):
        assert c.company_facts(1) == cf                                 # from the cache, complete: nothing to say
    assert not caplog.records


def test_a_cache_file_missing_newer_tags_is_reported_once_not_refetched(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(sec_client, "_warned", set())
    calls = []
    c = _client(tmp_path, lambda req: (calls.append(1), httpx.Response(200, json=RAW_FACTS))[1])
    c.company_facts(1)
    _rewrite(tmp_path / FACTS_FILE, lambda d: d[sec_client.TAGS_KEY].remove("Revenues"))   # cut before Revenues
    with caplog.at_level("WARNING", logger="creditlens"):
        c.company_facts(1)
        c.company_facts(1)
    warned = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert len(warned) == 1 and "Revenues" in warned[0] and "refresh=True" in warned[0]
    assert len(calls) == 1                                              # reported; the download is the operator's call
    c.company_facts(1, refresh=True)
    with gzip.open(tmp_path / FACTS_FILE, "rt") as fh:
        assert "Revenues" in json.load(fh)[sec_client.TAGS_KEY]


def test_a_cache_file_from_before_tag_lists_is_reported(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(sec_client, "_warned", set())
    c = _client(tmp_path, lambda req: httpx.Response(200, json=RAW_FACTS))
    c.company_facts(1)
    _rewrite(tmp_path / FACTS_FILE, lambda d: d.pop(sec_client.TAGS_KEY))
    with caplog.at_level("WARNING", logger="creditlens"):
        assert "Revenues" in c.company_facts(1)["facts"]["us-gaap"]
    assert any("before cache files recorded their XBRL tag list" in r.getMessage() for r in caplog.records)


# ------------------------------------------------------------------ model card export keeps hand-written sections
def test_model_card_export_keeps_hand_written_sections():
    from training.ml.export_xray import keep_hand_sections
    old = "# Card\n\n## Results\nr\n\n## Error analysis\nby hand\n\n## Limitations\nl\n"
    new = "# Card\n\n## Results\nR2\n\n## Limitations\nL2\n"
    assert keep_hand_sections(new, old) == ("# Card\n\n## Results\nR2\n\n## Error analysis\nby hand\n\n"
                                            "## Limitations\nL2\n")
    assert keep_hand_sections(new, "") == new


# ------------------------------------------------------------------ engine: rate floor, flag tolerance, unusable inputs
def test_a_rate_cut_cannot_take_the_debt_left_after_refinancing_below_zero():
    base = Baseline(currency="USD", ebitda=50, gross_debt=200, cash=0, interest_expense=10, existing_floating_share=1.0)
    refi = Facility(amount=100, currency="USD", coupon=0.06, use_of_proceeds=UseOfProceeds.REFINANCING,
                    refinanced_debt_rate=0.09)            # leaves 100 of debt carrying 1.00 of interest (1%)
    with pytest.raises(ScenarioInputError, match="below zero"):
        run_scenario(base, refi, Shock(rate_shock_bps=-300))     # used to give interest 1.00: -2.00 on that debt
    capex = refi.model_copy(update={"use_of_proceeds": UseOfProceeds.CAPEX, "refinanced_debt_rate": None})
    assert run_scenario(base, capex, Shock(rate_shock_bps=-300)).interest_expense == pytest.approx(10 + 6 - 9)


def test_the_cover_below_one_flag_ignores_float_noise():
    r = run_scenario(Baseline(currency="USD", ebitda=7, gross_debt=0, cash=0, interest_expense=0),
                     Facility(amount=100, currency="USD", coupon=0.07, floating=False), Shock(),
                     Covenants(min_ebitda_interest_cover=1.0))
    assert r.ebitda_interest_cover != 1.0 and "INTEREST_COVER_BELOW_1X" not in r.flags
    assert r.covenant_status["min_ebitda_interest_cover"].state.value == "pass"


def test_negative_cash_or_debt_is_not_usable_by_the_loan_engine(monkeypatch):
    from backend.app.documents import xbrl
    from backend.app.scenarios.snapshot import credit_baseline
    vals = {"revenue": 1e9, "operating_income": 1e8, "depreciation_amortization": 1e7, "interest_expense": 1e7,
            "short_term_borrowings": 0.0, "current_maturities_ltd": 0.0, "long_term_debt": 5e8, "cash": -1e6}
    monkeypatch.setattr(xbrl, "engine_inputs", lambda cy, basis="credit": vals)
    base, missing = credit_baseline(SimpleNamespace(cash_basis="unrestricted"), "USD", 0.0)
    assert base is None and missing == ["cash (reported as negative)"]         # used to raise a validation error


# ------------------------------------------------------------------ memo source trail: uploaded figures without a page
def test_an_analyst_entered_upload_figure_is_never_cited_as_sec():
    from backend.app.memos.pdf import _source_text
    from backend.app.memos.trail import _source
    f = SimpleNamespace(page=0, accession="upload-9fc6c788", extraction_method="manual", filed="2026-11-14",
                        tag="manual", form="upload", period_end="2025-12-31")
    src = _source({"cik": "doc9fc6c788"}, f)
    assert src["kind"] == "upload" and src["page"] is None and "url" not in src
    assert "entered by the analyst" in _source_text({"source": {"kind": "filing", "accession": "upload-9fc6c788"}})
