"""Render two annual-report-style statement PDFs for the upload tests (Blueprint p.12, Week 6 exit gate).

Figures are the companies' reported values, checked line by line against the original 10-Ks (P&G FY2026,
accession 0000080424-26-000103; B&G Foods FY2025, accession 0001104659-26-022961; docs/manual_cross_check.md).
The layouts are test renderings, not the original documents. v1.1 corrected two lines: B&G "Interest expense, net"
(v1.0 used cash interest paid) and P&G "Debt due within one year" (includes the 3m "Other" line). Two deliberately different templates:

  A  us_10k_millions.pdf   P&G-style 10-K: "Amounts in millions", $ signs, 2 year columns, cover
                           and narrative pages, capex shown in parentheses.
  C  ar_unlabelled.pdf     Template B without currency, unit scale, year-end date or operating cash flow
                           (exercises the review gate, DATA-01).
  B  ar_thousands.pdf      B&G-style annual report: "In thousands", a Note column, 3 year columns,
                           em-dash zeros, 52/53-week year-end, numbers inside narrative text.

    python tests/fixtures/generate_statement_pdfs.py
"""
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent
PG = {  # USD millions, FY2026 then FY2025
    "rev": (87032, 84284), "oi": (19748, 20451), "int": (877, 907), "ni": (16046, 15974),
    "da": (3160, 2847), "cfo": (19556, 17817), "capex": (4409, 3773), "cash": (9942, 9556),
    "stb_cur": (11296, 9513), "ltd": (22842, 24995), "ca": (26208, 25392), "ta": (126521, 125231),
    "cl": (38694, 36058), "tl": (72210, 72946), "eq": (54311, 52284),
}
BG = {  # USD thousands, FY2025 (ended Jan 3 2026), FY2024, FY2023
    "rev": (1828687, 1932454, 2062313), "oi": (97147, -177277, 80419), "int": (149631, 157447, 151333),
    "ni": (-43257, -251251, -66198), "da": (66223, 68614, 69620), "cfo": (101396, 130914, 247759),
    "capex": (30647, 27263, 25689), "cash": (56293, 50583, 41094), "cur": (4500, 5625, 22000),
    "stb": (0, 0, 0), "ltd": (1945576, 2014823, 2023088), "ca": (739818, 781444, 802824),
    "ta": (2834795, 2994052, 3463290), "cl": (222841, 236865, 262418), "tl": (2381870, 2469245, 2627827),
    "eq": (452925, 524807, 835463),
}


def money(v, dollar=False, dash_zero=False):
    if v == 0 and dash_zero:
        return "—"
    s = f"{abs(v):,}"
    s = f"({s})" if v < 0 else s
    return f"$ {s}" if dollar else s


class Doc:
    def __init__(self, path):
        self.c = canvas.Canvas(str(path), pagesize=LETTER, invariant=1)   # byte-stable output
        self.y = 740

    def text(self, s, x=54, size=9, bold=False, dy=13):
        self.c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        self.c.drawString(x, self.y, s)
        self.y -= dy

    def row(self, label, vals, xs, bold=False, indent=0, note=None, note_x=None):
        self.c.setFont("Helvetica-Bold" if bold else "Helvetica", 9)
        self.c.drawString(54 + indent, self.y, label)
        if note is not None:
            self.c.drawRightString(note_x, self.y, note)
        for v, x in zip(vals, xs):
            self.c.drawRightString(x, self.y, v)
        self.y -= 13

    def page(self):
        self.c.showPage()
        self.y = 740

    def save(self):
        self.c.save()


def template_a():
    d = Doc(OUT / "us_10k_millions.pdf")
    xs = [470, 550]
    d.text("UNITED STATES SECURITIES AND EXCHANGE COMMISSION", size=11, bold=True)
    d.text("FORM 10-K   Annual report for the fiscal year ended June 30, 2026")
    d.text("THE PROCTER & GAMBLE COMPANY (test rendering of reported figures)", bold=True)
    d.y -= 20
    for line in ["Item 7. Management's Discussion and Analysis",
                 "Net sales increased 3% to $87.0 billion in fiscal 2026. Operating cash flow was $19.6 billion.",
                 "We expect capital spending of approximately 5% of net sales in fiscal 2027.",
                 "Total shareholder return over 10 years exceeded 180%."]:
        d.text(line)
    d.page()
    d.text("CONSOLIDATED STATEMENTS OF EARNINGS", size=11, bold=True)
    d.text("Amounts in millions except per share amounts; Years ended June 30")
    d.row("", ["2026", "2025"], xs, bold=True)
    d.row("NET SALES", [money(PG["rev"][0], True), money(PG["rev"][1], True)], xs)
    d.row("Cost of products sold", ["42,180", "41,164"], xs)
    d.row("Selling, general and administrative expense", ["22,304", "22,669"], xs)
    d.row("Intangible asset impairment", ["2,800", "—"], xs)
    d.row("OPERATING INCOME", [money(v) for v in PG["oi"]], xs, bold=True)
    d.row("Interest expense", [money(v) for v in PG["int"]], xs)
    d.row("Interest income", ["(420)", "(470)"], xs)
    d.row("Other non-operating income, net", ["410", "390"], xs)
    d.row("EARNINGS BEFORE INCOME TAXES", ["19,701", "20,404"], xs, bold=True)
    d.row("Income taxes", ["3,655", "4,430"], xs)
    d.row("NET EARNINGS", [money(PG["ni"][0], True), money(PG["ni"][1], True)], xs, bold=True)
    d.row("Basic net earnings per common share", ["6.81", "6.75"], xs)
    d.page()
    d.text("CONSOLIDATED BALANCE SHEETS", size=11, bold=True)
    d.text("Amounts in millions; As of June 30")
    d.row("", ["2026", "2025"], xs, bold=True)
    d.text("Assets", bold=True)
    d.row("Cash and cash equivalents", [money(PG["cash"][0], True), money(PG["cash"][1], True)], xs, indent=8)
    d.row("Accounts receivable", ["6,201", "6,118"], xs, indent=8)
    d.row("TOTAL CURRENT ASSETS", [money(v) for v in PG["ca"]], xs, bold=True)
    d.row("Property, plant and equipment, net", ["23,450", "22,152"], xs, indent=8)
    d.row("TOTAL ASSETS", [money(PG["ta"][0], True), money(PG["ta"][1], True)], xs, bold=True)
    d.text("Liabilities and Shareholders' Equity", bold=True)
    d.row("Accounts payable", ["15,801", "15,227"], xs, indent=8)
    d.row("Debt due within one year", [money(v) for v in PG["stb_cur"]], xs, indent=8)
    d.row("TOTAL CURRENT LIABILITIES", [money(v) for v in PG["cl"]], xs, bold=True)
    d.row("Long-term debt", [money(v) for v in PG["ltd"]], xs, indent=8)
    d.row("TOTAL LIABILITIES", [money(v) for v in PG["tl"]], xs, bold=True)
    d.row("TOTAL SHAREHOLDERS' EQUITY", [money(v) for v in PG["eq"]], xs, bold=True)
    d.row("TOTAL LIABILITIES AND SHAREHOLDERS' EQUITY", [money(PG["ta"][0], True), money(PG["ta"][1], True)], xs, bold=True)
    d.page()
    d.text("CONSOLIDATED STATEMENTS OF CASH FLOWS", size=11, bold=True)
    d.text("Amounts in millions; Years ended June 30")
    d.row("", ["2026", "2025"], xs, bold=True)
    d.row("NET EARNINGS", [money(v) for v in PG["ni"]], xs)
    d.row("Depreciation and amortization", [money(v) for v in PG["da"]], xs, indent=8)
    d.row("Share-based compensation expense", ["590", "613"], xs, indent=8)
    d.row("TOTAL OPERATING ACTIVITIES", [money(v) for v in PG["cfo"]], xs, bold=True)
    d.row("Capital expenditures", [money(-v) for v in PG["capex"]], xs, indent=8)
    d.row("Proceeds from asset sales", ["120", "478"], xs, indent=8)
    d.row("TOTAL INVESTING ACTIVITIES", ["(4,850)", "(3,551)"], xs, bold=True)
    d.save()


def template_b(unlabelled=False):
    """unlabelled=True renders C, ar_unlabelled.pdf: the same statements with no currency, no unit scale, no
    year-end date and no operating-cash-flow line, to exercise the review gate (DATA-01) end to end."""
    d = Doc(OUT / ("ar_unlabelled.pdf" if unlabelled else "ar_thousands.pdf"))
    xs, nx = [420, 490, 560], 330
    usd = not unlabelled

    def mny(v, dollar=False, dash_zero=False):   # variant C prints no currency symbols
        return money(v, dollar and usd, dash_zero)
    d.text("B&G Foods, Inc. Annual Report (test rendering of reported figures)", size=11, bold=True)
    d.y -= 10
    for line in (["Letter to shareholders",
                  "In fiscal 2025 net sales were $1.83 billion, down 5.4% from $1.93 billion in fiscal 2024.",
                  "We reduced long-term debt by $69 million and remain focused on deleveraging toward 5.5x.",
                  "Our 52-week fiscal year 2025 ended on January 3, 2026."] if usd else
                 ["Letter to shareholders", "Fiscal 2025 was a year of deleveraging and portfolio simplification."]):
        d.text(line)
    d.page()
    d.text("B&G Foods, Inc. and Subsidiaries", bold=True)
    d.text("Consolidated Statements of Operations", size=11, bold=True)
    d.text("(In thousands, except per share data)   Fiscal years ended January 3, 2026, December 28, 2024 and December 30, 2023"
           if usd else "Fiscal years 2025, 2024 and 2023")
    d.row("", ["2025", "2024", "2023"], xs, bold=True, note="Note", note_x=nx)
    d.row("Net sales", [mny(v, True) for v in BG["rev"]], xs, note="3", note_x=nx)
    d.row("Cost of goods sold", ["1,423,111", "1,513,876", "1,632,912"], xs)
    d.row("Gross profit", ["405,576", "418,578", "429,401"], xs)
    d.row("Impairment of assets held for sale", ["—", "322,000", "63,000"], xs, note="6", note_x=nx)
    d.row("Operating income (loss)", [mny(v) for v in BG["oi"]], xs)
    d.row("Interest expense, net", [mny(v) for v in BG["int"]], xs, note="9", note_x=nx)
    d.row("Net loss", [mny(v, True) for v in BG["ni"]], xs, bold=True)
    d.page()
    d.text("Consolidated Balance Sheets", size=11, bold=True)
    d.text("(In thousands)" if usd else "")
    d.row("", ["2025", "2024", "2023"], xs, bold=True)
    d.row("Cash and cash equivalents", [mny(v, True) for v in BG["cash"]], xs)
    d.row("Total current assets", [mny(v) for v in BG["ca"]], xs)
    d.row("Total assets", [mny(v, True) for v in BG["ta"]], xs, bold=True)
    d.row("Current portion of long-term debt", [mny(v) for v in BG["cur"]], xs, note="9", note_x=nx)
    d.row("Short-term borrowings", [mny(v, dash_zero=True) for v in BG["stb"]], xs)
    d.row("Total current liabilities", [mny(v) for v in BG["cl"]], xs)
    d.row("Long-term debt, net of current portion", [mny(v) for v in BG["ltd"]], xs, note="9", note_x=nx)
    d.row("Total liabilities", [mny(v) for v in BG["tl"]], xs, bold=True)
    d.row("Total stockholders' equity", [mny(v) for v in BG["eq"]], xs, bold=True)
    d.page()
    d.text("Consolidated Statements of Cash Flows", size=11, bold=True)
    d.text("(In thousands)" if usd else "")
    d.row("", ["2025", "2024", "2023"], xs, bold=True)
    d.row("Net loss", [mny(v) for v in BG["ni"]], xs)
    d.row("Depreciation and amortization", [mny(v) for v in BG["da"]], xs)
    if usd:
        d.row("Net cash provided by operating activities", [mny(v) for v in BG["cfo"]], xs, bold=True)
    d.row("Capital expenditures", [mny(-v) for v in BG["capex"]], xs)
    d.row("Net cash used in investing activities", ["(18,102)", "(14,915)", "(6,700)"], xs, bold=True)
    d.save()


if __name__ == "__main__":
    template_a()
    template_b()
    template_b(unlabelled=True)
    print("wrote", OUT / "us_10k_millions.pdf", OUT / "ar_thousands.pdf", OUT / "ar_unlabelled.pdf")
