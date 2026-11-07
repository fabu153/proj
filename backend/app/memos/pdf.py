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
        rules = "; ".join((s.get("rules") or {}).values())
        return f"Data-quality checks{': ' + rules if rules else ''}{' (' + s['detail'] + ')' if s.get('detail') and not rules else ''}"
    if k == "snapshot":
        return s.get("detail", "Analysis snapshot")
    return s.get("detail", k or "")


def _header_block(memo: dict, small, body) -> list:
    """Borrower / fiscal year / proposed facility / purpose / analyst-review status, before any prose."""
    pk = memo["package"]
    d = lambda k: pk[k]["display"] if k in pk else "not set"     # noqa: E731
    facility = (f"{d('facility.amount')} {d('facility.tenor')} {d('facility.structure')} at {d('facility.coupon')}"
                if "facility.amount" in pk else "none entered")
    s = memo.get("summary", {})
    flagged, edited = s.get("flagged", 0), sum(x.get("edited", False) for sec in memo["sections"] for x in sec["sentences"])
    status = ("Draft, not yet reviewed by an analyst. "
              + (f"{flagged} sentence{'s' if flagged != 1 else ''} failed the checks and {'are' if flagged != 1 else 'is'} "
                 "excluded below." if flagged else "All sentences passed the evidence and consistency checks.")
              + (f" {edited} sentence{'s' if edited != 1 else ''} edited by the analyst." if edited else ""))
    snap = (memo.get("snapshot") or {}).get("id")
    rows = [("Borrower", d("meta.company")), ("Fiscal year", f"ending {d('meta.fye')} ({d('meta.source')})"),
            ("Proposed facility", facility), ("Purpose", d("facility.use") if "facility.use" in pk else "not set"),
            ("Analyst review", status),
            ("Prepared", f"{memo['created_at']} · writer {memo['writer']}" + (f" · snapshot {snap}" if snap else ""))]
    t = Table([[Paragraph(f"<b>{escape(a)}</b>", small), Paragraph(escape(b), small)] for a, b in rows],
              colWidths=[34 * mm, 136 * mm])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, INK), ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#d4dae1")),
                           ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f5f6f4")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return [Spacer(1, 4), t]


def _stress_table(pk: dict, small) -> list:
    """Before loan / base / downside / severe / your case side by side, from the cited package items."""
    cases = [c for c in ("base", "downside", "severe", "custom") if f"scen.{c}.net_leverage" in pk]
    if not cases:
        return []
    names = {"base": "Base", "downside": "Downside", "severe": "Severe", "custom": "Your case"}
    d = lambda k: pk[k]["display"] if k in pk and pk[k]["value"] is not None else "n/a"   # noqa: E731
    strip = lambda x: x.replace(f"{pk['meta.company'].get('ccy', '')}", "")                # noqa: E731

    def hr(c, item):
        st = pk.get(f"scen.{c}.{item}_state", {}).get("value")
        if st is None:
            return "—"
        if st == "not testable":
            return "not testable (N/A)"
        v = pk[f"scen.{c}.{item}"]["value"]
        return f"breach {-v:.2f}x" if st == "breach" else f"pass +{v:.2f}x"
    rows = [["", "Before loan"] + [names[c] for c in cases],
            ["Assumptions", "reported"] + [d(f"scen.{c}.assumptions").replace("no EBITDA or rate shock", "no shock") for c in cases],
            ["EBITDA", d("metric.ebitda.t")] + [d(f"scen.{c}.ebitda") for c in cases],
            ["Gross debt", d("metric.gross_debt.t")] + [d(f"scen.{c}.gross_debt") for c in cases],
            ["Net debt", d("metric.net_debt.t")] + [d(f"scen.{c}.net_debt") for c in cases],
            ["Net debt / EBITDA", d("metric.net_leverage.t")] + [d(f"scen.{c}.net_leverage") for c in cases],
            ["EBITDA / interest", d("metric.ebitda_interest_cover.t")] + [d(f"scen.{c}.ebitda_interest_cover") for c in cases]]
    if any(f"scen.{c}.headroom_lev_state" in pk for c in cases):
        rows.append(["Headroom: max net debt / EBITDA", "—"] + [hr(c, "headroom_lev") for c in cases])
    if any(f"scen.{c}.headroom_cov_state" in pk for c in cases):
        rows.append(["Headroom: min EBITDA / interest", "—"] + [hr(c, "headroom_cov") for c in cases])
    rows = [[Paragraph(f"<font color='#b3262e'><b>{escape(str(x))}</b></font>" if str(x).startswith("breach")
                       else escape(strip(str(x))), small) for x in r] for r in rows]
    w = 170 * mm
    t = Table(rows, colWidths=[42 * mm] + [(w - 42 * mm) / (len(cases) + 1)] * (len(cases) + 1), repeatRows=1)
    style = [("LINEBELOW", (0, 0), (-1, 0), 0.6, INK), ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#d4dae1")),
             ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
    t.setStyle(TableStyle(style))
    return [Spacer(1, 4), t, Spacer(1, 2),
            Paragraph("Headroom is the distance to the covenant limit; a breach shows the shortfall. Not testable means "
                      "the ratio is undefined (EBITDA at or below zero, or no interest expense); it is not counted as a "
                      "breach. EBITDA shocks move EBITDA by a share of its size, so a downside deepens a loss.", small)]


def _trails(memo: dict, pk: dict, h2, small, num) -> list:
    """E2: filing -> normalized fact -> calculation -> memo statement, for the four headline figures."""
    keys = [k for k in ("metric.ebitda.t", "metric.net_debt.t", "metric.net_leverage.t", "metric.ebitda_interest_cover.t")
            if k in pk and pk[k]["source"].get("trail")]
    if not keys:
        return []
    out = [Paragraph("Source trail for headline figures", h2),
           Paragraph("Each figure from the filing to the memo: where it was reported, the normalized fact (with any rule "
                     "applied), the calculation, and the first memo sentence that cites it.", small)]
    sentences = [(x, sec["title"]) for sec in memo["sections"] for x in sec["sentences"] if x["status"] == "ok"]
    for k in keys:
        it, tr = pk[k], pk[k]["source"]["trail"]
        filing = []
        for f in tr["facts"]:
            src = f["source"]
            if src.get("kind") == "sec" and not src.get("derived") and f.get("as_filed"):
                where = f"{f['as_filed']['value']:,.0f} USD, tag {src['tag']}, {src['form']} filed {src['filed']}, accession {src['accession']}"
            elif src.get("kind") == "sec":
                where = f"derived by rule from accession {src['accession']}"
            elif src.get("kind") == "upload":
                where = f"uploaded report p.{src['page']}"
            else:
                where = "not reported"
            norm = "n/a" if f["normalized"] is None else f"{f['normalized']:,.1f}m"
            rule = f" (rule {f['rule'].replace('_', ' ')})" if f.get("rule") else ""
            filing.append(f"{f['label']}: {where} → {norm}{rule}")
        calc = [f"{st['label']} = {st['expression']}" for st in tr["steps"]]
        stmt = next(((x["text"], t) for x, t in sentences if k in x["refs"]), None)
        rows = [["Filing → normalized", "<br/>".join(escape(x) for x in filing)],
                ["Calculation", "<br/>".join(escape(x) for x in calc)],
                ["Memo statement", f"“{escape(stmt[0])}” ({escape(stmt[1])}, [{num(k)}])" if stmt else "not cited in the memo"]]
        t = Table([[Paragraph(f"<b>{a}</b>", small), Paragraph(b, small)] for a, b in rows], colWidths=[34 * mm, 136 * mm])
        t.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.6, INK), ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#d4dae1")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 2)]))
        out += [Spacer(1, 4), Paragraph(f"<b>{escape(it['label'])}: {escape(it['display'])}</b>", small), t]
    return out


def _assumptions(snap: dict, h2, small) -> list:
    """The complete inputs of the analysis snapshot, so the PDF can be reproduced in the loan lab (WF-02)."""
    i = snap["inputs"]
    f, c, b = i.get("facility") or {}, i.get("covenants") or {}, i.get("baseline") or {}
    ccy = b.get("currency") or f.get("currency", "")
    pct = lambda x: "n/a" if x is None else f"{x * 100:.2f}%"   # noqa: E731
    xx = lambda x: "not tested" if x is None else f"{x:.2f}x"   # noqa: E731
    m = lambda x: "n/a" if x is None else f"{x:,.1f}m"          # noqa: E731
    rows = [["Input", "Value"],
            ["Baseline (credit basis)", f"EBITDA {ccy} {m(b.get('ebitda'))}, gross debt {m(b.get('gross_debt'))}, cash "
                                        f"{m(b.get('cash'))}, interest {m(b.get('interest_expense'))}" if b else "not available"],
            ["Cash basis", i.get("cash_basis", "").replace("_", " ")]]
    if f:
        refi = f.get("refinanced_debt_rate")
        rows += [["Facility", f"{f['currency']} {f['amount']:,.1f}m, {f['tenor_years']}-year, "
                              f"{'floating' if f['floating'] else 'fixed'} at {pct(f['coupon'])}, repayment "
                              f"{f['annual_amortization']:,.1f}m a year"],
                 ["Use of proceeds", f["use_of_proceeds"].replace("_", " ") +
                  (f", retired debt at {pct(refi)}" if refi is not None else
                   ", retired debt at the average cost of debt" if f["use_of_proceeds"] == "refinancing" else "")]]
        if f.get("fx_rate_to_reporting"):
            rows.append(["FX rate", f"{f['fx_rate_to_reporting']} {ccy} per {f['currency']} ({f.get('fx_rate_date') or 'no date'})"])
    rows += [["Existing debt at floating rate", pct(b.get("existing_floating_share", 0.0))],
             ["Covenants", f"max net debt / EBITDA {xx(c.get('max_net_leverage'))}; "
                           f"min EBITDA / interest {xx(c.get('min_ebitda_interest_cover'))}"]]
    for s in i.get("cases", []):
        rows.append([f"Case: {s['name']}", f"EBITDA {s['ebitda_shock'] * 100:+.0f}%, rates {s['rate_shock_bps']:+.0f} bp"])
    rows.append(["Snapshot", f"{snap['id']} (loan engine v{i.get('engine_version')}, snapshot format v{i.get('snapshot_version')})"])
    t = Table([[Paragraph(escape(str(a)), small), Paragraph(escape(str(v)), small)] for a, v in rows],
              colWidths=[52 * mm, 118 * mm], repeatRows=1)
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 0.6, INK),
                           ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#d4dae1")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 2)]))
    return [Paragraph("Assumptions (analysis snapshot " + escape(snap["id"]) + ")", h2), t]


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

    flow = [Paragraph(f"Credit memo: {escape(pk['meta.company']['display'])}", h1)]
    flow += _header_block(memo, small, body)
    flow += [Spacer(1, 6),
             Paragraph("ANALYST REVIEW REQUIRED — decision support only; not a rating, not a probability of default, "
                       "not a lending decision.", banner),
             Paragraph(f"Amounts in {escape(memo.get('currency', 'USD'))} millions unless stated. Every number is inserted from the "
                       "deterministic engines and cited in brackets; the appendix gives each source.", small),
             Spacer(1, 4)]
    excluded = []
    for sec in memo["sections"]:
        ok = [s for s in sec["sentences"] if s["status"] == "ok"]
        excluded += [(sec["title"], s) for s in sec["sentences"] if s["status"] != "ok"]
        if not ok and sec["key"] != "stress":
            continue
        if not ok and not any(k.startswith("scen.") and k.endswith(".ebitda") for k in pk):
            continue
        flow.append(Paragraph(escape(sec["title"]), h2))
        para = []
        for s in ok:
            nums = sorted(num(r) for r in s["refs"])
            marks = f"<super><font size=6.5 color='#0f7c7a'>[{_ranges(nums)}]</font></super>" if nums else ""
            para.append(escape(s["text"]) + marks + ("<font size=7 color='#56677a'> (edited)</font>" if s["edited"] else ""))
        flow.append(Paragraph(" ".join(para), body))
        if sec["key"] == "stress":
            flow += _stress_table(pk, small)

    snap = memo.get("snapshot")
    if snap and snap.get("inputs"):
        flow += _assumptions(snap, h2, small)

    flow += _trails(memo, pk, h2, small, num)

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
        (f"Analysis snapshot {snap['id']} · " if snap else "") +
        f"Package SHA-256 {memo['package_sha256'][:16]}… · memo {memo['id'][:12]} · {len(cited)} cited items. Numbers are "
        "inserted from deterministic engines; generated text cannot introduce figures.", small)]
    doc.build(flow)
    return buf.getvalue()
