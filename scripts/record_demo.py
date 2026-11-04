"""Record the fallback demo video and README screenshots against a running local stack (Blueprint p.20).

    CREDITLENS_CURATED=backend/data/curated uvicorn backend.app.api.main:app --port 8000 &
    (cd frontend && npm run build && npx next start -p 3000) &
    python scripts/record_demo.py            # -> release/demo.webm, docs/screenshots/*.png
    ffmpeg -i release/demo.webm -c:v libx264 -preset veryfast -crf 23 -pix_fmt yuv420p release/creditlens_demo.mp4
"""
import shutil
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3000"
CHROME = "/usr/bin/google-chrome"
OUT = Path("release")
SHOTS = Path("docs/screenshots")
PDF = Path("tests/fixtures/ar_thousands.pdf")
W, H = 1280, 720

CAPTION_JS = """t => {
  let el = document.getElementById('demo-cap');
  if (!el) {
    el = document.createElement('div'); el.id = 'demo-cap';
    Object.assign(el.style, {position: 'fixed', left: '50%', bottom: '22px', transform: 'translateX(-50%)',
      maxWidth: '860px', background: 'rgba(14,27,44,.94)', color: '#fff', padding: '12px 20px', borderRadius: '6px',
      font: '500 19px/1.4 "Newsreader Variable", Georgia, serif', zIndex: 9999, textAlign: 'center',
      boxShadow: '0 6px 24px rgba(0,0,0,.25)'});
    document.body.appendChild(el);
  }
  el.textContent = t; el.style.display = t ? 'block' : 'none';
}"""


def main():
    OUT.mkdir(exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_video"
    shutil.rmtree(tmp, ignore_errors=True)
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        ctx = b.new_context(viewport={"width": W, "height": H}, record_video_dir=str(tmp),
                            record_video_size={"width": W, "height": H})
        pg = ctx.new_page()

        def cap(text, wait=2600):
            pg.evaluate(CAPTION_JS, text)
            pg.wait_for_timeout(int(wait * 1.5))      # paced for reading aloud

        def scroll_to(sel, offset=-80):
            pg.evaluate("([s, o]) => { const e = document.querySelector(s); window.scrollTo({top: e.getBoundingClientRect().top + window.scrollY + o, behavior: 'smooth'}); }", [sel, offset])
            pg.wait_for_timeout(900)

        # 1 — real data enters the system
        pg.goto(BASE + "/", wait_until="networkidle")
        pg.wait_for_selector("text=Pro forma credit metrics", timeout=60000)
        cap("CreditLens: an analyst copilot for a proposed corporate loan. Every number comes from SEC 10-K filings.", 3800)
        pg.select_option("header select >> nth=0", value="0001067701")
        pg.wait_for_selector("h1:has-text('United Rentals')", timeout=30000)
        pg.wait_for_selector("text=Pro forma credit metrics", timeout=30000)
        cap("We open United Rentals: four years of credit metrics computed by versioned formulas.", 3200)
        pg.screenshot(path=str(SHOTS / "workspace.png"))

        # 2 — traceable sources
        pg.click("tr.row:has-text('Net debt / EBITDA')")
        cap("Select any figure: the rail shows its formula, its inputs and the exact 10-K accession it came from.", 3800)

        # 3 — the trained network
        scroll_to("#h-risk")
        cap("A trained neural network screens next-year accounting stress: 1.8%, low, with the inputs that moved it.", 4200)
        pg.screenshot(path=str(SHOTS / "risk_screen.png"))
        pg.goto(BASE + "/model", wait_until="networkidle")
        pg.wait_for_selector("text=Does the network work?", timeout=30000)
        cap("Model X-Ray: tested once on 2021–25 filings it never saw. Level with XGBoost within the margin of error, "
            "and reported as such.", 4400)
        pg.screenshot(path=str(SHOTS / "model_xray.png"))
        scroll_to("section.block:nth-of-type(2)", -60)
        cap("Calibration: predicted risk against what actually happened, bucket by bucket.", 3200)

        # 4 — the loan
        pg.goto(BASE + "/", wait_until="networkidle")
        pg.select_option("header select >> nth=0", value="0001067701")
        pg.wait_for_selector("h1:has-text('United Rentals')", timeout=30000)
        pg.wait_for_selector("text=Pro forma credit metrics", timeout=30000)
        scroll_to("#h-lab")
        cap("The loan lab: a 100m five-year facility at 6%, spent on capex, tested against a 3.5x leverage covenant.", 4000)
        pg.locator("input[type=range]").nth(0).fill("-20")
        pg.locator("input[type=range]").nth(1).fill("200")
        pg.wait_for_selector("text=EBITDA shock -20%", timeout=15000)
        pg.wait_for_timeout(600)
        cap("EBITDA −20% and rates +200 bp: the downside breaches the covenant. Every step of the arithmetic is listed.", 4400)
        pg.screenshot(path=str(SHOTS / "loan_lab.png"))

        # 5 — evidence-constrained memo
        scroll_to("#h-memo")
        pg.click("text=Draft credit memo")
        pg.wait_for_selector(".memo-section", timeout=60000)
        pg.wait_for_timeout(500)
        cap("The credit memo: the writer cannot type numbers. Each figure is inserted by the engines and cited.", 4000)
        pg.locator(".memo-section").nth(5).locator("button.cite").first.click()
        pg.wait_for_timeout(400)
        scroll_to(".memo-section:nth-of-type(6)", -120)
        cap("Select a citation: it resolves to the scenario case, its assumptions and the calculation trail.", 4000)
        pg.screenshot(path=str(SHOTS / "memo.png"))
        s = pg.locator(".memo-section").nth(1).locator(".sentence").first
        s.hover()
        s.locator("button.edit-link").click()
        pg.fill(".sentence-edit textarea", "Revenue grew strongly and margins will reach 45.0% next year.")
        pg.click("text=Save and check")
        pg.wait_for_selector(".sentence.flagged", timeout=15000)
        pg.locator(".sentence.flagged").first.scroll_into_view_if_needed()
        cap("An analyst types an unsupported figure: it is flagged and kept out of the exported PDF.", 4200)

        # 6 — annual report upload
        pg.goto(BASE + "/upload", wait_until="networkidle")
        pg.set_input_files("input[type=file]", str(PDF))
        pg.fill("input[placeholder='As it should appear in the memo']", "B&G Foods")
        pg.fill("input[placeholder='Cross-checks against XBRL']", "1278027")
        cap("Uploading an annual report instead: the PDF is parsed in memory and never stored.", 2600)
        pg.click("text=Extract figures")
        pg.wait_for_selector("text=Check the extracted figures", timeout=60000)
        cap("Each figure shows its page and source line. Net interest is held for review; nothing uncertain is used silently.", 4400)
        pg.screenshot(path=str(SHOTS / "upload_review.png"))
        pg.locator("tr.needs-review button:has-text('Accept')").first.click()
        pg.wait_for_selector("button:has-text('Analyse reviewed figures'):not([disabled])", timeout=15000)
        pg.click("text=Analyse reviewed figures")
        pg.wait_for_selector("h1:has-text('uploaded report')", timeout=60000)
        pg.wait_for_selector("text=Pro forma credit metrics", timeout=30000)
        cap("Same engines, same model: 11.59x leverage and a high stress screen, now cited to pages of the report.", 4200)
        scroll_to("#h-risk")
        cap("Decision support, not a decision: no rating, no default probability, analyst review required.", 4200)
        cap("", 400)
        pg.screenshot(path=str(SHOTS / "uploaded_report_risk.png"))
        doc_cid = pg.url.split("company=")[1]
        video = pg.video.path()
        ctx.close()
        b.close()
    Path(video).replace(OUT / "demo.webm")
    shutil.rmtree(tmp, ignore_errors=True)
    print("video:", OUT / "demo.webm", "| uploaded company to clean up:", doc_cid)


if __name__ == "__main__":
    main()
