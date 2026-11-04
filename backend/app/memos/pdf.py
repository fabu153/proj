"""Render a validated memo to PDF (Blueprint p.14: 'Generate PDF from validated JSON').

Only sentences that passed validation (or were fixed by the analyst) are printed. Each carries
bracketed citation numbers that resolve in the evidence appendix to a filing/page, formula,
model or scenario assumption. Flagged sentences are listed separately as excluded.
"""
from __future__ import annotations

import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

INK = colors.HexColor("#0e1b2c")
SLATE = colors.HexColor("#56677a")
AMBER = colors.HexColor("#a4650a")


def _source_text(it: dict) -> str:
    s = it["source"]
    k = s.get("kind")
    if k == "filing":
        if s.get("page"):
            return f"Uploaded report p.{s['page']} ({s.get('method', 'PDF')})"
        if s.get("accession"):
            return f"10-K XBRL {s.get('tag')}, accession {s['accession']}, filed {s.get('filed')}"
        return "Not reported"
    if k == "formula":
        return f"Formula {s.get('formula')} (v{s.get('version')})"
    if k == "model":
        return f"Neural stress model {s.get('name', 'stress_mlp_v1')}; inputs as of {s.get('features_as_of', 'n/a')}"
    if k == "model_evaluation":
        return "Frozen test-window evaluation (model card)"
    if k == "scenario":
        return f"Loan engine v{s.get('engine_version')}, {s.get('case')} case"
    if k == "assumption":
        return "Analyst input in the loan lab"
    if k == "data_checks":
        return "Data-quality checks"
    return s.get("detail", k or "")


def _ranges(nums: list[int]) -> str:
    """[1,2,3,5] -> '1–3, 5'."""
    out, start = [], None
    for i, n in enumerate(nums):
        if start is None:
            start = n
        if i == len(nums) - 1 or nums[i + 1] != n + 1:
            out.append(f"{start}–{n}" if n > start else str(n))
            start = None
    return ", ".join(out)


def render_pdf(memo: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm,
                            bottomMargin=18 * mm, title=f"Credit memo — {memo['package']['meta.company']['value']}",
                            author="CreditLens (analyst review required)")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontName="Times-Roman", fontSize=20, textColor=INK, alignment=TA_LEFT,
                        spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Times-Roman", fontSize=13.5, textColor=INK, spaceBefore=10,
                        spaceAfter=4)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontName="Helvetica", fontSize=9.6, leading=13.5, spaceAfter=3)
    small = ParagraphStyle("s", parent=body, fontSize=8, leading=10.5, textColor=SLATE)
    banner = ParagraphStyle("ban", parent=body, textColor=AMBER, fontName="Helvetica-Bold", fontSize=9)

    pk = memo["package"]
    cited: list[str] = []

    def num(ref: str) -> int:
        if ref not in cited:
            cited.append(ref)
        return cited.index(ref) + 1

    flow = [Paragraph(f"Credit memo: {escape(pk['meta.company']['display'])}", h1),
            Paragraph(f"Fiscal year ending {escape(memo['fiscal_year_end'])} · generated {escape(memo['created_at'])} · "
                      f"writer {escape(memo['writer'])}", small),
            Spacer(1, 4),
            Paragraph("ANALYST REVIEW REQUIRED — decision support only; not a rating, not a probability of default, "
                      "not a lending decision.", banner), Spacer(1, 6)]
    excluded = []
    for sec in memo["sections"]:
        ok = [s for s in sec["sentences"] if s["status"] == "ok"]
        excluded += [(sec["title"], s) for s in sec["sentences"] if s["status"] != "ok"]
        if not ok:
            continue
        flow.append(Paragraph(escape(sec["title"]), h2))
        para = []
        for s in ok:
            nums = sorted(num(r) for r in s["refs"])
            marks = f"<super><font size=6.5 color='#0f7c7a'>[{_ranges(nums)}]</font></super>" if nums else ""
            para.append(escape(s["text"]) + marks + ("<font size=7 color='#56677a'> (edited)</font>" if s["edited"] else ""))
        flow.append(Paragraph(" ".join(para), body))

    flow.append(Paragraph("Evidence appendix", h2))
    rows = [["#", "Item", "Value", "Source"]]
    for i, ref in enumerate(cited, 1):
        it = pk[ref]
        rows.append([str(i), Paragraph(escape(it["label"]), small), Paragraph(escape(it["display"]), small),
                     Paragraph(escape(_source_text(it)), small)])
    t = Table(rows, colWidths=[8 * mm, 52 * mm, 32 * mm, 78 * mm], repeatRows=1)
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8), ("FONT", (0, 1), (0, -1), "Helvetica", 8),
                           ("LINEBELOW", (0, 0), (-1, 0), 0.6, INK), ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#d4dae1")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3)]))
    flow.append(t)
    if excluded:
        flow.append(Paragraph("Excluded sentences (failed validation, not part of the memo)", h2))
        for title, s in excluded:
            flow.append(Paragraph(f"{escape(title)}: “{escape(s['text'])}” — {escape('; '.join(s['issues']))}", small))
    flow += [Spacer(1, 8), Paragraph(
        f"Package SHA-256 {memo['package_sha256'][:16]}… · memo {memo['id'][:12]} · {len(cited)} cited items. Numbers are "
        "inserted from deterministic engines; generated text cannot introduce figures.", small)]
    doc.build(flow)
    return buf.getvalue()
