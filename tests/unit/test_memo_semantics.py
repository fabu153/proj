"""Stage E1 (v1.3): sentences whose numbers all reconcile must also say something true about them."""
import gzip
import json
from pathlib import Path

import pytest

from backend.app.memos.package import build_package
from backend.app.memos.validator import validate_sentence
from backend.app.memos.writer import SECTIONS, TemplateWriter
from backend.app.scenarios.loan import Covenants, Facility, Shock

CURATED = Path(__file__).parents[2] / "backend" / "data" / "curated"
CASES = [Shock(name="Base"), Shock(name="Downside", ebitda_shock=-0.2, rate_shock_bps=200),
         Shock(name="Severe", ebitda_shock=-0.35, rate_shock_bps=400),
         Shock(name="Your case", ebitda_shock=-0.1, rate_shock_bps=100)]


def _pk(cik, **fac):
    with gzip.open(CURATED / f"companyfacts_{cik}.json.gz", "rt") as fh:
        cf = json.load(fh)
    return build_package(cf, cik, None, Facility(amount=100, currency="USD", **fac),
                         Covenants(max_net_leverage=3.5, min_ebitda_interest_cover=3.0), 0.0, CASES)


BG = _pk("0001278027")      # revenue fell 5.4%; covenants breached in every case
URI = _pk("0001067701")     # revenue grew 4.9%; covenants hold


def issues(text, pk):
    return validate_sentence(text, "claim", pk)["issues"]


def test_direction_must_match_sign_of_change():
    assert issues("Revenue fell {{metric.revenue_growth.abs}} year on year.", BG) == []
    assert any("direction" in i for i in issues("Revenue grew {{metric.revenue_growth.abs}} year on year.", BG))
    assert any("direction" in i for i in issues("Revenue was down {{metric.revenue_growth.abs}}.", URI))
    assert issues("Revenue rose {{metric.revenue_growth.abs}}.", URI) == []
    # words inside item ids ("downside", "shortfall") are not direction or breach words
    assert issues("In the downside case ({{scen.downside.assumptions}}) revenue rose {{metric.revenue_growth.abs}}.", URI) == []


def test_direction_of_scenario_against_pre_loan_figure():
    assert issues("In the downside case EBITDA / interest falls to {{scen.downside.ebitda_interest_cover}}.", URI) == []
    bad = issues("In the downside case EBITDA / interest rises to {{scen.downside.ebitda_interest_cover}}.", URI)
    assert any("direction" in i for i in bad)
    assert any("direction" in i for i in issues("In the base case gross debt falls to {{scen.base.gross_debt}}.", URI))


def test_negative_headroom_must_be_called_a_breach():
    assert BG.val("scen.downside.headroom_lev") < 0
    assert any("negative headroom" in i for i in issues("Downside headroom is {{scen.downside.headroom_lev}}.", BG))
    assert any("does not say" in i for i in issues("In the downside case the gap is {{scen.downside.headroom_lev_shortfall}}.", BG))
    assert issues("The downside case breaches the covenant by {{scen.downside.headroom_lev_shortfall}}.", BG) == []


def test_positive_headroom_must_not_be_called_a_breach():
    assert URI.val("scen.downside.headroom_lev") > 0
    assert any("positive" in i for i in issues("The downside case breaches the covenant: headroom {{scen.downside.headroom_lev}}.", URI))
    assert issues("The covenant holds in the downside case, with headroom of {{scen.downside.headroom_lev}}.", URI) == []


def test_undefined_ratio_is_not_cited():
    with gzip.open(CURATED / "companyfacts_0001278027.json.gz", "rt") as fh:
        cf = json.load(fh)
    pk = build_package(cf, "0001278027", "2024-12-28", None, None)    # FY2024: operating loss
    assert pk.items["metric.net_leverage.t"]["source"]["status"] in ("undefined", "not_available") or \
        pk.items["metric.ebitda.t"]["value"] > 0
    pk.items["metric.net_leverage.t"]["source"]["status"] = "undefined"   # force the case regardless of the year
    pk.items["metric.net_leverage.t"]["value"] = 1.0
    assert any("undefined ratio" in i for i in issues("Net debt / EBITDA is {{metric.net_leverage.t}}.", pk))


def test_scenario_assumptions_and_results_must_match():
    ok = "In the downside case ({{scen.downside.assumptions}}) net debt / EBITDA reaches {{scen.downside.net_leverage}}."
    assert issues(ok, URI) == []
    mixed = "In the downside case ({{scen.downside.assumptions}}) net debt / EBITDA reaches {{scen.severe.net_leverage}}."
    assert any("scenario" in i for i in issues(mixed, URI))
    named = "In the severe case net debt / EBITDA reaches {{scen.downside.net_leverage}}."
    assert any("names the severe case" in i for i in issues(named, URI))


@pytest.mark.parametrize("pk", [BG, URI], ids=["bg", "uri"])
def test_template_memo_passes_all_checks_and_has_every_section(pk):
    raw = TemplateWriter().write(pk)
    assert [s["key"] for s in raw] == [k for k, _ in SECTIONS]
    flagged = [(s["key"], x["text"], validate_sentence(x["text"], x["kind"], pk)["issues"])
               for s in raw for x in s["sentences"] if validate_sentence(x["text"], x["kind"], pk)["status"] != "ok"]
    assert flagged == []
    keys = {s["key"]: s["sentences"] for s in raw}
    for k in ("executive", "profile", "model", "stress", "covenants", "considerations"):
        assert keys[k], k
    assert any("own case" in x["text"] for x in keys["stress"])


def test_refinancing_memo_does_not_say_gross_debt_rises():
    pk = _pk("0001067701", use_of_proceeds="refinancing")
    raw = {s["key"]: s["sentences"] for s in TemplateWriter().write(pk)}
    assert any("gross debt stays at" in x["text"] for x in raw["stress"])
