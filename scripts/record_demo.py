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

        # 0:00-0:30 — P&G, source-backed financials
        pg.goto(BASE + "/", wait_until="networkidle")
        pg.wait_for_selector(".company-list a", timeout=90000)
        cap("CreditLens: an analyst copilot for a proposed corporate loan. Start from a sample company or a public annual report.", 3400)
        pg.screenshot(path=str(SHOTS / "start.png"))
        pg.click(".company-list a:has-text('PROCTER')")
        pg.wait_for_selector("text=Pro forma credit metrics", timeout=60000)
        cap("Procter & Gamble, fiscal 2026: every figure comes from its 10-K filings through a versioned formula.", 3400)
        pg.screenshot(path=str(SHOTS / "workspace.png"))
        pg.click("tr.row:has-text('Net debt / EBITDA')")
        cap("Net debt / EBITDA 1.06x: the rail shows the formula, the inputs and the 10-K accession. Amber means qualified: "
            "P&G only tags cash including restricted cash.", 4400)

        # 0:30-1:10 — the trained network and the XGBoost benchmark
        scroll_to("#h-risk")
        cap("A trained neural network reads the same annual report: a 1.0% chance of accounting stress next year, low band.", 3800)
        pg.screenshot(path=str(SHOTS / "risk_screen.png"))
        pg.goto(BASE + "/model", wait_until="networkidle")
        pg.wait_for_selector("#where-it-fails", timeout=30000)
        cap("Model X-Ray: 31 inputs, a 62-128-64-32-1 network, five seeds averaged, tested once on 2021-25 filings it never saw.", 4200)
        pg.screenshot(path=str(SHOTS / "model_xray.png"))
        scroll_to("#how-it-performed", -40)
        cap("PR-AUC 0.805 against 0.825 for XGBoost: XGBoost's point estimate is higher, the difference is within the margin "
            "of error, and we say so.", 4600)
        scroll_to("#where-it-fails", -40)
        cap("Where it fails: it catches stress that persists, but only 6 of 73 new onsets from healthy accounts.", 3800)

        # 1:10-1:50 — EUR 100m facility with an explicit FX rate, stressed
        pg.goto(BASE + "/workspace?company=0000080424", wait_until="networkidle")
        pg.wait_for_selector("text=Pro forma credit metrics", timeout=60000)
        scroll_to("#h-lab")
        pg.select_option(".controls select >> nth=0", "EUR")
        pg.wait_for_selector("text=Currencies are never mixed silently", timeout=15000)
        cap("A EUR 100m facility against USD statements: the engine refuses to mix currencies until a rate is entered.", 3800)
        pg.fill("input[placeholder='e.g. spot rate']", "1.08")
        pg.fill("input[placeholder='YYYY-MM-DD']", "2026-11-05")
        pg.wait_for_selector("text=Facility 100.00 EUR x 1.08", timeout=15000)
        pg.locator("input[type=range]").nth(0).fill("-30")
        pg.locator("input[type=range]").nth(1).fill("200")
        pg.wait_for_selector("text=EBITDA shock -30%", timeout=15000)
        pg.wait_for_timeout(600)
        cap("Illustrative rate 1.08 USD per EUR. EBITDA -30% and rates +200 bp: net debt / EBITDA 1.52x, far inside a 3.5x "
            "covenant. For P&G this facility is small.", 4600)
        pg.screenshot(path=str(SHOTS / "loan_lab.png"))
        scroll_to(".heatmap", -60)
        cap("The stress heatmap: 42 runs of the same Python engine. Click any cell to load it into your case.", 3600)
        pg.screenshot(path=str(SHOTS / "heatmap.png"))

        # 1:50-2:25 — matched memo and PDF
        scroll_to("#h-memo")
        pg.click("text=Draft credit memo")
        pg.wait_for_selector(".memo-header", timeout=60000)
        pg.wait_for_timeout(400)
        cap("The committee memo carries the loan lab's snapshot id. Every number is inserted by the engines, never typed.", 3800)
        pg.locator("button.num-link.has-trail").first.click()
        pg.wait_for_selector(".trail", timeout=10000)
        cap("Click a figure: filing and accession, normalized fact, calculation, and the memo sentence that uses it.", 4200)
        pg.screenshot(path=str(SHOTS / "memo.png"))
        pg.get_by_label("Amount (m)").fill("150")
        pg.wait_for_selector("text=Outdated — regenerate", timeout=15000)
        scroll_to(".notice.outdated", -160)
        cap("Change the loan and the memo is marked outdated until regenerated: table, memo and PDF share one snapshot.", 3800)
        pg.click("text=Regenerate now")
        pg.wait_for_selector("text=Download PDF", timeout=60000)
        cap("Regenerated and exportable as a PDF with assumptions, stress table and source trails.", 3000)

        # 2:25-3:00 — one historical replay, outcome revealed
        pg.goto(BASE + "/replay", wait_until="networkidle")
        pg.wait_for_selector("text=Reveal next-year outcome", timeout=30000)
        pg.locator("button.example").nth(2).click()
        pg.wait_for_selector("text=Reveal next-year outcome", timeout=15000)
        cap("Historical replay: Jazz Pharmaceuticals, fiscal 2021, as the network scored it when the 10-K was filed, "
            "before the outcome was known.", 4200)
        pg.screenshot(path=str(SHOTS / "replay.png"))
        pg.click("text=Reveal next-year outcome")
        pg.wait_for_selector(".assessment", timeout=15000)
        scroll_to("#h-outcome", -100)
        cap("The outcome a year later: accounting stress followed. The same page shows a false alarm and a miss.", 4000)
        cap("Decision support, not a decision: no rating, no default probability, analyst review required.", 3600)
        cap("", 400)

        video = pg.video.path()
        ctx.close()                                # the video ends on the closing caption

        # upload screenshot, in a separate context that is not recorded (not part of the 3-minute flow)
        up = b.new_context(viewport={"width": W, "height": H}).new_page()
        up.goto(BASE + "/upload", wait_until="networkidle")
        up.set_input_files("input[type=file]", str(PDF))
        up.fill("input[placeholder='As it should appear in the memo']", "B&G Foods")
        up.fill("input[placeholder='Cross-checks against XBRL']", "1278027")
        up.click("text=Extract figures")
        up.wait_for_selector("text=Check the extracted figures", timeout=60000)
        up.screenshot(path=str(SHOTS / "upload_review.png"))
        up.click("text=Delete this upload")
        up.wait_for_selector("text=Extract figures", timeout=30000)
        doc_cid = "deleted"
        b.close()
    Path(video).replace(OUT / "demo.webm")
    shutil.rmtree(tmp, ignore_errors=True)
    print("video:", OUT / "demo.webm", "| uploaded company to clean up:", doc_cid)


if __name__ == "__main__":
    main()
