"""Fix 1 (v1.4): figures are mapped to fiscal years by their column headings, never by column position."""
import io
import itertools

import pytest
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from backend.app.documents import pdf_extract

# one company's economics, USD millions, by fiscal year
DATA = {
    2025: {"Net sales": 1200, "Operating income": 150, "Interest expense": 30, "Net income": 90,
           "Cash and cash equivalents": 80, "Total current assets": 400, "Total assets": 2000,
           "Total current liabilities": 300, "Long-term debt": 700, "Total liabilities": 1200,
           "Total stockholders' equity": 800,
           "Depreciation and amortization": 60, "Net cash provided by operating activities": 170,
           "Capital expenditures": -55},
    2024: {"Net sales": 1000, "Operating income": 110, "Interest expense": 28, "Net income": 60,
           "Cash and cash equivalents": 70, "Total current assets": 380, "Total assets": 1900,
           "Total current liabilities": 290, "Long-term debt": 720, "Total liabilities": 1180,
           "Total stockholders' equity": 720,
           "Depreciation and amortization": 58, "Net cash provided by operating activities": 140,
           "Capital expenditures": -50},
    2023: {"Net sales": 900, "Operating income": 95, "Interest expense": 25, "Net income": 50,
           "Cash and cash equivalents": 60, "Total current assets": 360, "Total assets": 1800,
           "Total current liabilities": 280, "Long-term debt": 740, "Total liabilities": 1160,
           "Total stockholders' equity": 640,
           "Depreciation and amortization": 55, "Net cash provided by operating activities": 120,
           "Capital expenditures": -45},
}
STATEMENTS = {
    "Consolidated Statements of Operations": ["Net sales", "Operating income", "Interest expense", "Net income"],
    "Consolidated Balance Sheets": ["Cash and cash equivalents", "Total current assets", "Total assets",
                                    "Total current liabilities", "Long-term debt", "Total liabilities",
                                    "Total stockholders' equity"],
    "Consolidated Statements of Cash Flows": ["Net income", "Depreciation and amortization",
                                              "Net cash provided by operating activities", "Capital expenditures"],
}


def money(v):
    return f"({abs(v):,})" if v < 0 else f"{v:,}"


def make_pdf(orders: dict[str, list[int]]) -> bytes:
    """One page per statement; `orders` gives each statement's column years, left to right."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER, invariant=1)
    for title, rows in STATEMENTS.items():
        years = orders[title]
        xs = [400 + 70 * i for i in range(len(years))]
        y = 740
        c.setFont("Helvetica-Bold", 11)
        c.drawString(54, y, "Example Corp")
        y -= 14
        c.drawString(54, y, title)
        y -= 14
        c.setFont("Helvetica", 9)
        c.drawString(54, y, "(In millions of U.S. dollars)   Fiscal years ended December 31")
        y -= 14
        for x, yr in zip(xs, years):
            c.drawRightString(x, y, str(yr))
        y -= 14
        for label in rows:
            c.drawString(54, y, label)
            for x, yr in zip(xs, years):
                c.drawRightString(x, y, money(DATA[yr][label]))
            y -= 13
        c.showPage()
    c.save()
    return buf.getvalue()


def figures(x) -> dict:
    return {(c.field, c.period): (c.value, c.year) for c in x.candidates}


def same_orders(order):
    return {t: order for t in STATEMENTS}


REFERENCE = figures(pdf_extract.extract(make_pdf(same_orders([2025, 2024]))))


@pytest.mark.parametrize("order", [[2025, 2024], [2024, 2025], [2025, 2024, 2023], [2023, 2024, 2025]],
                         ids=["2025,2024", "2024,2025", "2025,2024,2023", "2023,2024,2025"])
def test_same_statements_give_identical_latest_and_prior_year(order):
    x = pdf_extract.extract(make_pdf(same_orders(order)))
    assert figures(x) == REFERENCE
    assert x.years[:2] == [2025, 2024]
    rev = {c.period: c for c in x.candidates if c.field == "revenue"}
    assert rev["t"].value == 1200e6 and rev["t"].year == 2025
    assert rev["t-1"].value == 1000e6 and rev["t-1"].year == 2024
    assert not any("ambiguous" in i for i in x.issues)


def test_mixed_column_counts_across_statements():
    orders = {"Consolidated Statements of Operations": [2023, 2024, 2025],
              "Consolidated Balance Sheets": [2025, 2024],
              "Consolidated Statements of Cash Flows": [2024, 2025]}
    assert figures(pdf_extract.extract(make_pdf(orders))) == REFERENCE


@pytest.mark.parametrize("order", [list(p) for p in itertools.permutations([2023, 2024, 2025])
                                   if list(p) not in ([2023, 2024, 2025], [2025, 2024, 2023])])
def test_out_of_order_headings_are_flagged_for_review(order):
    x = pdf_extract.extract(make_pdf(same_orders(order)))
    assert any("ambiguous" in i for i in x.issues)
    assert all(c.needs_review for c in x.candidates)
    # still mapped by heading, so no value lands in the wrong year
    assert {k: v[0] for k, v in figures(x).items()} == {k: v[0] for k, v in REFERENCE.items()}


def test_repeated_year_heading_is_ambiguous():
    x = pdf_extract.extract(make_pdf(same_orders([2025, 2025])))
    assert any("repeat a year" in i for i in x.issues)
    assert all(c.needs_review for c in x.candidates)


def test_statements_from_different_years_are_never_combined():
    orders = {"Consolidated Statements of Operations": [2025, 2024],
              "Consolidated Balance Sheets": [2024, 2023],          # one year behind
              "Consolidated Statements of Cash Flows": [2025, 2024]}
    x = pdf_extract.extract(make_pdf(orders))
    latest = {c.field for c in x.candidates if c.period == "t"}
    assert "total_assets" not in latest and "revenue" in latest       # no 2024 balance sheet used as 2025
    ta = next(c for c in x.candidates if c.field == "total_assets" and c.period == "t-1")
    assert ta.value == 1900e6 and ta.year == 2024
    assert any("not used for 2025" in i for i in x.issues)
    assert any(i.startswith("Critical item not found: total assets") for i in x.issues)


def test_existing_fixtures_unchanged():
    from pathlib import Path
    for name, years in (("ar_thousands.pdf", [2025, 2024, 2023]), ("us_10k_millions.pdf", [2026, 2025])):
        x = pdf_extract.extract((Path(__file__).parents[1] / "fixtures" / name).read_bytes())
        assert x.years == years
        assert all(c.year == (years[0] if c.period == "t" else years[1]) for c in x.candidates)
