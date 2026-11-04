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
    page.goto(BASE + "/", wait_until="networkidle")
    page.wait_for_selector("text=Pro forma credit metrics", timeout=60000)
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
    page.click("text=Draft credit memo")
    page.wait_for_selector(".memo-section", timeout=60000)
    assert "All sentences passed the evidence checks" in page.inner_text(".memo")
    assert "EUR 100m" in page.inner_text(".memo-section >> nth=0")
    page.locator("button.cite").first.click()
    page.wait_for_selector("text=Memo citation")
    with page.expect_download() as dl:
        page.click("text=Download PDF")
    path = dl.value.path()
    assert Path(path).read_bytes()[:5] == b"%PDF-"
    assert page.errors == []


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
    page.wait_for_selector("h1:has-text('uploaded report')", timeout=60000)
    assert "11.59x" in page.inner_text("table.ledger")
    assert "from the uploaded report, page" in page.inner_text(".rail")
    # clean up through the API
    cid = page.url.split("company=")[1]
    import httpx
    doc = httpx.get(f"{API}/documents/{cid}").json()
    assert httpx.delete(f"{API}/documents/{doc['id']}").status_code == 200


@pytest.mark.parametrize("path,wait", [("/", "text=Pro forma credit metrics"), ("/model", "text=Does the network work?"),
                                       ("/upload", "text=Extract figures")])
def test_wcag_aa_no_serious_violations(page, path, wait):
    page.goto(BASE + path, wait_until="networkidle")
    page.wait_for_selector(wait, timeout=60000)
    page.add_script_tag(path=str(AXE))
    res = page.evaluate("""async () => (await axe.run(document, {runOnly: {type: 'tag',
        values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations
        .filter(v => ['serious', 'critical'].includes(v.impact))
        .map(v => ({id: v.id, n: v.nodes.length, sample: v.nodes[0].target.join(' ')}))""")
    assert res == [], res
