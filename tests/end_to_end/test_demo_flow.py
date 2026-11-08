"""E01 — the complete analyst journey in a real browser, plus a WCAG 2.1 AA scan (axe-core).

Runs against a live frontend + API; skipped unless E2E_BASE_URL is set:

    CREDITLENS_CURATED=backend/data/curated uvicorn backend.app.api.main:app --port 8000 &
    (cd frontend && npm run build && npx next start -p 3000) &
    E2E_BASE_URL=http://localhost:3000 E2E_API_URL=http://localhost:8000 pytest tests/end_to_end -q
"""
import os
from pathlib import Path

import pytest

BASE = os.environ.get("E2E_BASE_URL")
API = os.environ.get("E2E_API_URL", "http://localhost:8000")
CHROME = os.environ.get("E2E_CHROME", "/usr/bin/google-chrome")
AXE = Path(__file__).parents[2] / "frontend" / "node_modules" / "axe-core" / "axe.min.js"
PDF = Path(__file__).parents[1] / "fixtures" / "ar_thousands.pdf"
PDF_C = Path(__file__).parents[1] / "fixtures" / "ar_unlabelled.pdf"
pytestmark = pytest.mark.skipif(not BASE, reason="set E2E_BASE_URL to run browser tests")


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        kw = {"executable_path": CHROME} if Path(CHROME).exists() else {}
        b = p.chromium.launch(args=["--no-sandbox"], **kw)
        yield b
        b.close()


@pytest.fixture
def page(browser):
    pg = browser.new_page(viewport={"width": 1400, "height": 950}, accept_downloads=True)
    pg.errors = []
    pg.on("console", lambda m: pg.errors.append(m.text) if m.type == "error" else None)
    yield pg
    pg.close()


def test_e01_issuer_to_memo_pdf(page):
    # B1: start page -> sample company
    page.goto(BASE + "/", wait_until="networkidle")
    page.wait_for_selector(".company-list a", timeout=90000)
    assert "Course demo" in page.inner_text(".demo-banner")
    page.locator(".company-list a").first.click()
    page.wait_for_selector("text=Pro forma credit metrics", timeout=60000)
    assert page.locator(".progress li.done").count() >= 3
    # inspect data: a ledger row opens its formula and filing
    page.click("tr.row:has-text('EBITDA / interest')")
    assert "ebitda / interest_expense" in page.inner_text(".evidence .formula")
    assert page.locator(".evidence a[href*='sec.gov/Archives']").count() >= 1
    # add a EUR facility: blocked until an FX rate is given, then calculated
    page.select_option(".controls select >> nth=0", "EUR")
    page.wait_for_selector("text=Currencies are never mixed silently", timeout=15000)
    page.fill("input[placeholder='e.g. spot rate']", "1.08")
    page.fill("input[placeholder='YYYY-MM-DD']", "2026-11-04")
    page.wait_for_selector("text=Facility 100.00 EUR x 1.08", timeout=15000)
    # stress: move the EBITDA slider and see the audit trail update
    page.locator("input[type=range]").first.fill("-30")
    page.wait_for_selector("text=EBITDA shock -30%", timeout=15000)
    # memo, citation, PDF
    page.wait_for_selector("text=Current · snapshot", timeout=15000)
    # C3: the deterministic loan stress never changes the neural score
    score = page.inner_text(".risk-head .pct")
    page.locator("input[type=range]").first.fill("-50")
    page.wait_for_selector("text=Current · snapshot", timeout=15000)
    assert page.inner_text(".risk-head .pct") == score
    page.locator("input[type=range]").first.fill("-30")
    page.wait_for_selector("text=EBITDA shock -30%", timeout=15000)
    page.click("text=Draft credit memo")
    page.wait_for_selector(".memo-section", timeout=60000)
    assert "All sentences passed the evidence checks" in page.inner_text(".memo")
    assert "EUR 100m" in page.inner_text(".memo-header")
    # E2 / OUT-02: clicking a headline figure opens its source trail, down to the SEC accession
    page.locator("button.num-link.has-trail").first.click()
    page.wait_for_selector("text=Source trail", timeout=5000)
    trail = page.inner_text(".trail")
    for step in ("1 · FILING", "2 · NORMALIZED FACT", "3 · CALCULATION", "4 · MEMO STATEMENT"):
        assert step in trail.upper(), step
    assert page.locator(".trail a[href*='sec.gov/Archives']").count() >= 1
    lab_snap = page.inner_text(".ok-tag code")
    assert lab_snap in page.inner_text(".memo")                      # WF-02: memo carries the table's snapshot
    # WF-02: change an input -> the memo is outdated and its PDF is withdrawn until regenerated
    page.get_by_label("Amount (m)").fill("150")
    page.wait_for_selector("text=Outdated — regenerate", timeout=15000)
    assert page.locator("button[data-testid=memo-pdf][disabled]").count() == 1      # Fix 4: no export of an old memo
    page.click("text=Regenerate now")
    page.wait_for_selector("a[data-testid=memo-pdf]", timeout=60000)
    assert "EUR 150m" in page.inner_text(".memo-header")
    assert page.locator(".progress li.done").count() == 5
    page.locator("button.cite").first.click()
    page.wait_for_selector("text=Memo citation")
    with page.expect_download() as dl:
        page.click("text=Download PDF")
    path = dl.value.path()
    assert Path(path).read_bytes()[:5] == b"%PDF-"
    assert page.errors == []


def _pdf_enabled(page):
    return page.locator("a[data-testid=memo-pdf]").count() == 1


def _memo_ready(page):
    page.wait_for_selector("text=Current · snapshot", timeout=60000)
    if page.locator("text=Regenerate now").count():
        page.click("text=Regenerate now")
    elif page.locator("text=Draft credit memo").count():
        page.click("text=Draft credit memo")
    page.wait_for_selector("a[data-testid=memo-pdf]", timeout=60000)


def test_fix4_no_outdated_memo_can_be_exported(page):
    """Every input change withdraws the PDF at once; invalid input and a late memo reply never re-enable it."""
    page.goto(BASE + "/workspace?company=0001067701", wait_until="networkidle")
    page.wait_for_selector("text=Current · snapshot", timeout=90000)
    _memo_ready(page)
    slider = lambda i: page.locator("input[type=range]").nth(i)   # noqa: E731
    changes = [
        ("amount", lambda: page.get_by_label("Amount (m)").fill("150")),
        ("coupon", lambda: page.get_by_label("All-in coupon (%)").fill("7.5")),
        ("ebitda shock", lambda: slider(0).fill("-35")),
        ("rate shock", lambda: slider(1).fill("300")),
        ("covenant", lambda: page.get_by_label("Max net debt / EBITDA (x)").fill("3.75")),
    ]
    for what, act in changes:
        act()
        assert not _pdf_enabled(page), f"PDF still enabled right after changing {what}"
        page.wait_for_selector("text=Outdated — regenerate", timeout=15000)
        assert not _pdf_enabled(page), what
        _memo_ready(page)
    # currency: blocked until an FX rate is given, then outdated, never exportable in between
    page.select_option(".controls select >> nth=0", "EUR")
    assert not _pdf_enabled(page)
    page.wait_for_selector("text=Currencies are never mixed silently", timeout=15000)
    assert not _pdf_enabled(page)
    page.fill("input[placeholder='e.g. spot rate']", "1.08")
    page.fill("input[placeholder='YYYY-MM-DD']", "2026-11-04")
    page.wait_for_selector("text=Outdated — regenerate", timeout=15000)
    assert not _pdf_enabled(page)
    _memo_ready(page)
    page.fill("input[placeholder='e.g. spot rate']", "1.10")
    assert not _pdf_enabled(page)
    page.wait_for_selector("text=Outdated — regenerate", timeout=15000)
    _memo_ready(page)
    # invalid / half-typed input: the PDF is unavailable while the field holds it, and back when it is valid again
    amt = page.get_by_label("Amount (m)")
    amt.fill("")
    page.wait_for_selector("text=incomplete or invalid number", timeout=5000)
    assert not _pdf_enabled(page) and amt.get_attribute("aria-invalid") == "true"
    assert page.locator(".ok-tag").count() == 0                  # the table does not claim to be current
    amt.fill("-20")
    assert not _pdf_enabled(page)
    amt.fill("150")                                              # same value as the memo's: the same snapshot again
    page.wait_for_selector("a[data-testid=memo-pdf]", timeout=15000)
    # a memo reply that arrives after the inputs changed is not current
    def slow(route):
        import time
        time.sleep(3)
        route.continue_()
    page.route("**/api/memos", slow)
    page.click("text=Redraft")
    page.wait_for_selector("text=Drafting from snapshot", timeout=5000)
    amt.fill("175")
    page.wait_for_selector(".memo-bar button:not([disabled]):has-text('Regenerate')", timeout=30000)
    page.wait_for_selector("text=Outdated — regenerate", timeout=15000)
    assert not _pdf_enabled(page)
    page.unroute("**/api/memos")
    assert page.errors == []


def test_f_heatmap_cell_populates_the_loan_lab(page):
    page.goto(BASE + "/workspace?company=0001278027", wait_until="networkidle")
    page.wait_for_selector("table.heat button.cell", timeout=90000)
    assert page.locator("table.heat button.cell").count() == 42
    assert page.locator("table.heat button.cell.breach").count() >= 1
    page.locator("table.heat tbody tr").nth(3).locator("button.cell").nth(1).click()       # +300 bp, EBITDA -40%
    page.wait_for_selector("text=EBITDA shock -40%", timeout=15000)
    assert "-40%" in page.inner_text(".controls") and "+300 bp" in page.inner_text(".controls")
    assert page.locator("table.heat button.cell.active").count() == 1
    page.click(".seg button:has-text('EBITDA / interest')")
    assert "x" in page.locator("table.heat button.cell").first.inner_text()
    page.add_script_tag(path=str(AXE))
    res = _axe(page)
    assert res == [], res
    assert page.errors == []


def test_works_when_the_api_host_is_blocked(page):
    """An ad blocker that blocks the API's own domain (e.g. onrender.com) must not break the site: the browser
    only talks to the site's /api path, which forwards to the service."""
    from urllib.parse import urlparse
    host = urlparse(API).netloc
    blocked = []
    page.route(lambda url: urlparse(url).netloc == host, lambda route: (blocked.append(route.request.url), route.abort()))
    page.goto(BASE + "/", wait_until="networkidle")
    page.wait_for_selector(".company-list a", timeout=90000)
    page.locator(".company-list a").first.click()
    page.wait_for_selector("text=Current · snapshot", timeout=60000)
    page.click("text=Draft credit memo")
    page.wait_for_selector(".memo-header", timeout=60000)
    with page.expect_download() as dl:
        page.click("text=Download PDF")
    assert Path(dl.value.path()).read_bytes()[:5] == b"%PDF-"
    assert blocked == [], blocked                       # the browser never needed the API's domain


def test_loan_lab_numbers_can_be_cleared_and_retyped(page):
    page.goto(BASE + "/workspace?company=0001067701", wait_until="networkidle")
    page.wait_for_selector("text=Current · snapshot", timeout=90000)
    amt = page.get_by_label("Amount (m)")
    amt.click()
    amt.press("End")
    for _ in range(3):
        amt.press("Backspace")
    assert amt.input_value() == ""                      # nothing forces a "1" back in
    amt.type("200")
    page.wait_for_selector("text=Facility 200.00", timeout=15000)
    tenor = page.get_by_label("Tenor (years)")
    tenor.fill("45")
    amt.click()
    assert tenor.input_value() == "30"                  # out of range is clamped when leaving the field
    # the evidence panel stays below the sticky progress bar and inside the window
    bar, rail = page.locator(".workspace-progress").bounding_box(), page.locator("aside.rail").bounding_box()
    assert rail["y"] >= bar["y"] + bar["height"] and rail["y"] + rail["height"] <= page.viewport_size["height"]


def test_upload_review_analyse(page):
    page.goto(BASE + "/upload", wait_until="networkidle")
    page.set_input_files("input[type=file]", str(PDF))
    page.fill("input[placeholder='As it should appear in the memo']", "E2E B&G Foods")
    page.click("text=Extract figures")
    page.wait_for_selector("text=Check the extracted figures", timeout=60000)
    assert page.locator("button:has-text('Analyse reviewed figures')").is_disabled()
    page.locator("tr.needs-review button:has-text('Accept')").first.click()
    page.wait_for_selector("button:has-text('Analyse reviewed figures'):not([disabled])", timeout=15000)
    page.click("text=Analyse reviewed figures")
    page.wait_for_url("**/workspace?company=doc*", timeout=60000)
    page.wait_for_selector("h1:has-text('uploaded report')", timeout=60000)
    assert "11.59x" in page.inner_text("table.ledger")
    assert "from the uploaded report, page" in page.inner_text(".rail")
    # clean up through the API
    cid = page.url.split("company=")[1]
    import httpx
    doc = httpx.get(f"{API}/documents/{cid}").json()
    assert httpx.delete(f"{API}/documents/{doc['id']}").status_code == 200


def test_data01_unlabelled_report_needs_confirmation(page):
    """B3: missing currency, units, year-end and a critical line are exceptions the analyst resolves explicitly."""
    page.goto(BASE + "/upload", wait_until="networkidle")
    page.set_input_files("input[type=file]", str(PDF_C))
    page.fill("input[placeholder='As it should appear in the memo']", "E2E unlabelled")
    page.click("text=Extract figures")
    page.wait_for_selector("text=Check the extracted figures", timeout=60000)
    assert "4 missing" in page.inner_text(".review-summary")
    assert page.locator("tbody tr").first.get_attribute("class") == "missing"     # exceptions first
    assert page.locator("button:has-text('Analyse reviewed figures')").is_disabled()
    page.add_script_tag(path=str(AXE))
    res = _axe(page)
    assert res == [], res
    page.locator(".doc-meta select").nth(0).select_option("USD")
    page.wait_for_selector(".doc-meta >> text=confirmed")
    page.locator(".doc-meta select").nth(1).select_option("thousands")
    page.wait_for_selector("th:has-text('USD m')")
    page.locator(".doc-meta input[type=date]").fill("2026-01-03")
    page.locator(".doc-meta").get_by_role("button", name="Confirm", exact=True).click()
    page.wait_for_selector(".review-summary >> text=1 missing", timeout=15000)
    row = page.locator("tr.missing")
    row.locator("input[type=number]").first.fill("101.396")
    assert "= 101,396,000 USD" in row.inner_text()                      # explicit millions -> units conversion
    row.get_by_role("button", name="Enter").click()
    page.wait_for_selector("text=Entered by you")
    page.locator("tr.needs-review button:has-text('Accept')").first.click()
    page.wait_for_selector("button:has-text('Analyse reviewed figures'):not([disabled])", timeout=15000)
    page.click("text=Analyse reviewed figures")
    page.wait_for_url("**/workspace?company=doc*", timeout=60000)
    page.wait_for_selector("text=Not checked against SEC", timeout=60000)
    import httpx
    cid = page.url.split("company=")[1]
    doc = httpx.get(f"{API}/documents/{cid}").json()
    assert httpx.delete(f"{API}/documents/{doc['id']}").status_code == 200
    assert page.errors == []


def test_ml02_replay_hides_outcome_until_revealed(page):
    """Stage D: nothing about the next year is requested or shown before 'Reveal next-year outcome'."""
    urls = []
    page.on("request", lambda r: urls.append(r.url))
    page.goto(BASE + "/replay", wait_until="networkidle")
    page.wait_for_selector("text=Reveal next-year outcome", timeout=90000)
    assert page.locator("button.example").count() == 3
    assert not any("/outcome" in u for u in urls)
    assert "hidden" in page.inner_text(".timeline")
    page.add_script_tag(path=str(AXE))
    assert _axe(page) == []
    page.click("text=Reveal next-year outcome")
    page.wait_for_selector(".assessment", timeout=15000)
    assert any("/outcome" in u for u in urls)
    assert _axe(page) == []
    page.locator("button.example").nth(1).click()
    page.wait_for_selector("text=Reveal next-year outcome", timeout=15000)
    assert page.locator(".assessment").count() == 0                      # hidden again for the next case
    assert page.errors == []


def _axe(page):
    return page.evaluate("""async () => (await axe.run(document, {runOnly: {type: 'tag',
        values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations
        .filter(v => ['serious', 'critical'].includes(v.impact))
        .map(v => ({id: v.id, n: v.nodes.length, sample: v.nodes.map(n => n.target.join(" ") + " " + (n.any[0]?.message ?? "")).join(" | ")}))""")


@pytest.mark.parametrize("path,wait", [("/", ".company-list a"), ("/workspace", "text=Pro forma credit metrics"),
                                       ("/model", "#where-it-fails"), ("/replay", "text=Reveal next-year outcome"), ("/upload", "text=Extract figures")])
def test_wcag_aa_no_serious_violations(page, path, wait):
    page.goto(BASE + path, wait_until="networkidle")
    page.wait_for_selector(wait, timeout=60000)
    page.add_script_tag(path=str(AXE))
    res = _axe(page)
    assert res == [], res


# ------------------------------------------------------------------ Stage 2: search any U.S. public company
# Works against the mocked SEC (API started with CREDITLENS_SEC_FIXTURES=tests/fixtures/sec) or live SEC.
def _fixture_mode():
    import json
    import urllib.request
    with urllib.request.urlopen(API + "/companies/search?q=EXAMPLE%20IFRS") as r:
        return any("TEST FIXTURE" in x["name"] for x in json.load(r)["results"])


def test_search_keyboard_only_to_memo_pdf(page):
    """Find a non-curated issuer by ticker using only the keyboard, run stresses and export a sourced memo."""
    page.goto(BASE + "/", wait_until="networkidle")
    box = page.get_by_role("combobox", name="Company name, ticker or CIK")
    box.wait_for(timeout=60000)
    box.focus()
    page.keyboard.type("PATK")
    page.wait_for_selector("[role=option]:has-text('PATRICK INDUSTRIES')", timeout=20000)
    opt = page.locator("[role=option]").first
    assert "PATK" in opt.inner_text() and "CIK 0000076605" in opt.inner_text()
    assert box.get_attribute("aria-activedescendant") == opt.get_attribute("id")
    page.add_script_tag(path=str(AXE))
    assert _axe(page) == []                                              # open listbox is accessible
    page.keyboard.press("Enter")
    page.wait_for_url("**/workspace?company=0000076605", timeout=20000)
    page.wait_for_selector("[data-outcome]", timeout=90000)
    assert page.locator("h1").first.inner_text().startswith("PATRICK INDUSTRIES")   # SEC spells it with a comma
    page.wait_for_selector("text=Current · snapshot", timeout=60000)
    page.wait_for_selector("table.heat button.cell", timeout=60000)
    page.locator("input[type=range]").first.fill("-30")
    page.wait_for_selector("text=EBITDA shock -30%", timeout=15000)
    page.wait_for_selector("text=Current · snapshot", timeout=15000)
    page.click("text=Draft credit memo")
    page.wait_for_selector("a[data-testid=memo-pdf]", timeout=60000)
    assert "PATRICK INDUSTRIES" in page.inner_text(".memo-header")
    page.locator("button.num-link.has-trail").first.click()
    page.wait_for_selector("text=Source trail", timeout=5000)
    assert page.locator(".trail a[href*='sec.gov/Archives/edgar/data/76605/']").count() >= 1
    with page.expect_download() as dl:
        page.click("a[data-testid=memo-pdf]")
    assert Path(dl.value.path()).read_bytes()[:5] == b"%PDF-"
    page.add_script_tag(path=str(AXE))
    assert _axe(page) == []
    assert page.errors == []


def test_search_states_and_stale_replies(page):
    page.goto(BASE + "/", wait_until="networkidle")
    box = page.get_by_role("combobox", name="Company name, ticker or CIK")
    box.wait_for(timeout=60000)
    box.fill("zzqqxx nothing")
    page.wait_for_selector("text=No U.S. SEC registrant matches", timeout=20000)
    # SEC failure is shown as such, with a retry
    page.route("**/api/companies/search*", lambda r: r.fulfill(status=429, json={"detail": "SEC EDGAR is limiting requests right now (rate limit). Wait a minute and try again."}))
    box.fill("patk")
    page.wait_for_selector("text=rate limit", timeout=20000)
    page.unroute("**/api/companies/search*")
    page.click(".search-msg button:has-text('Try again')")
    page.wait_for_selector("[role=option]:has-text('PATRICK')", timeout=20000)
    page.errors = [e for e in page.errors if "429" not in e]          # the injected rate-limit reply
    # a slow reply to an older query never replaces the newer one
    held = []
    page.route("**/api/companies/search*", lambda r: held.append(r) if "q=united" in r.request.url else r.continue_())
    box.fill("united")
    page.wait_for_timeout(600)                                            # past the debounce: "united" is in flight
    assert len(held) == 1
    box.fill("berkshire")
    page.wait_for_selector("[role=option]:has-text('BERKSHIRE')", timeout=20000)
    held[0].continue_()                                                   # the older reply arrives last
    page.wait_for_timeout(1500)
    names = page.locator("[role=option] .hit-name").all_inner_texts()
    assert names and all("BERKSHIRE" in n for n in names), names
    page.unroute("**/api/companies/search*")
    page.keyboard.press("Escape")
    assert page.locator("[role=listbox]").is_hidden()
    assert page.errors == []


def test_searched_company_outcomes(page):
    if not _fixture_mode():
        pytest.skip("needs the mocked SEC fixtures (CREDITLENS_SEC_FIXTURES)")
    page.goto(BASE + "/workspace?company=0000099902", wait_until="networkidle")
    page.wait_for_selector("[data-outcome=no_supported_statements]", timeout=60000)
    assert "IFRS" in page.inner_text("[data-outcome]")
    assert page.locator("text=Pro forma credit metrics").count() == 0     # nothing invented
    page.goto(BASE + "/workspace?company=0000099901", wait_until="networkidle")
    page.wait_for_selector("[data-outcome=score_withheld]", timeout=60000)
    assert "financial-sector" in page.inner_text("[data-outcome]")
    page.wait_for_selector("[data-testid=lab-unavailable]", timeout=60000)   # banks: no loan lab (v1.5.1)
    page.route("**/api/companies/resolve", lambda r: r.fulfill(status=502, json={"detail": "SEC EDGAR is unavailable right now, so this company's filings cannot be loaded."}))
    page.goto(BASE + "/workspace?company=0000076605", wait_until="networkidle")
    page.wait_for_selector("text=This company could not be loaded", timeout=60000)
    assert "SEC EDGAR is unavailable" in page.inner_text(".sec-outcome")
    page.unroute("**/api/companies/resolve")
    page.click("text=Try again")
    page.wait_for_selector("[data-outcome=full]", timeout=60000)
    assert [e for e in page.errors if "502" not in e] == []            # only the injected SEC failure


# ------------------------------------------------------------------ v1.5: onset definitions + research in Model X-Ray
def test_model_xray_research_section(page):
    page.goto(BASE + "/model", wait_until="networkidle")
    page.wait_for_selector("#research", timeout=90000)
    fails = page.inner_text("#where-it-fails")
    assert "6 of 73" in fails and "214 of 226" in fails and "15 of 96" in fails     # canonical, with the old figure labelled
    sec = page.locator("#research")
    assert "Not used in the app" in sec.inner_text()
    tables = sec.locator("table.research-table")
    assert tables.count() == 2                                                    # overall and onset kept apart
    for i in range(2):
        assert tables.nth(i).locator(".kind.deployed").count() == 1
    assert "1,086" in sec.inner_text() and "727 company-years" in sec.inner_text()
    for name in ("Onset-specific GRU", "Onset-specific MLP", "General three-year GRU", "XGBoost benchmark"):
        assert name in sec.inner_text()
    assert "33" in sec.locator("table.research-wl").inner_text()
    # no new live score anywhere: the workspace still shows exactly one neural screen
    page.add_script_tag(path=str(AXE))
    assert _axe(page) == []
    assert page.errors == []


# ------------------------------------------------------------------ v1.5.1 polish
def test_bank_shows_banner_and_makes_no_lab_calls(page):
    if not _fixture_mode():
        pytest.skip("needs the mocked SEC fixtures (CREDITLENS_SEC_FIXTURES)")
    calls = []
    page.on("request", lambda r: calls.append(r.url) if "/scenarios" in r.url or "/memos" in r.url else None)
    page.goto(BASE + "/workspace?company=0000099901", wait_until="networkidle")
    page.wait_for_selector("[data-testid=financial-banner]", timeout=60000)
    assert "don't apply to banks" in page.inner_text("[data-testid=financial-banner]")
    assert not page.locator("details.sector-details").get_attribute("open")      # figures folded away by default
    page.wait_for_selector("[data-testid=lab-unavailable]")
    page.wait_for_timeout(1500)
    assert calls == [] and page.locator("table.heat").count() == 0               # loan_lab.available guards the calls
    assert "not a credit measure" in page.inner_text(".evidence")
    page.add_script_tag(path=str(AXE))
    assert _axe(page) == []
    assert page.errors == []


def test_heatmap_opens_on_interest_cover(page):
    page.goto(BASE + "/workspace?company=0001067701", wait_until="networkidle")
    page.wait_for_selector("table.heat button.cell", timeout=90000)
    assert page.locator("[role=radio][aria-checked=true]").first.inner_text().startswith("EBITDA / interest")
    assert "reprice only floating-rate debt" in page.inner_text(".heat-hint")
    page.click("[role=radio]:has-text('Net debt / EBITDA')")
    assert "does not depend on interest rates" in page.inner_text(".heat-hint")
