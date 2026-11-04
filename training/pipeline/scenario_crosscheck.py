"""Week 5 — independent spreadsheet reconciliation of the loan/stress engine (Blueprint p.19 exit gate).

Builds docs/scenario_crosscheck.xlsx: every case is a column of blue input cells and black Excel
formulas written independently of backend/app/scenarios/loan.py. After LibreOffice recalculates
it, tests/unit/test_scenario_crosscheck.py reads the inputs AND the spreadsheet results, runs the
Python engine on the same inputs, and requires agreement to 1e-9.

    python -m training.pipeline.scenario_crosscheck   # then recalc with LibreOffice (see README)
"""
from __future__ import annotations

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

OUT = "docs/scenario_crosscheck.xlsx"
USE_CODES = {"capex": 1, "retained_cash": 2, "refinancing": 3}

# name, inputs. Baseline is the Blueprint p.09 illustrative company (EUR m).
B = dict(ebitda=100, gross_debt=300, cash=50, interest=20, float_share=0.0, amount=100, fx=1.0, coupon=0.06,
         floating=1, use="capex", refi_rate=0.05, ebitda_shock=0.0, rate_bps=0, cov_lev=4.0, cov_cover=3.0)
CASES = [
    ("Base: EUR 100m capex", {}),
    ("Downside: EBITDA -20%, +200bp", dict(ebitda_shock=-0.20, rate_bps=200)),
    ("Severe: EBITDA -35%, +400bp", dict(ebitda_shock=-0.35, rate_bps=400)),
    ("Proceeds retained as cash", dict(use="retained_cash")),
    ("Refinance at 5.0%", dict(use="refinancing")),
    ("USD reporter, FX 1.10", dict(fx=1.10)),
    ("50% existing floating, +200bp", dict(float_share=0.5, rate_bps=200)),
    ("Fixed-rate facility, +300bp", dict(floating=0, rate_bps=300)),
]

INPUT_ROWS = [  # key, label, number format
    ("ebitda", "EBITDA (m)", "#,##0.0"), ("gross_debt", "Gross debt (m)", "#,##0.0"), ("cash", "Cash (m)", "#,##0.0"),
    ("interest", "Interest expense (m)", "#,##0.0"), ("float_share", "Existing debt floating share", "0.0%"),
    ("amount", "Facility amount (facility ccy, m)", "#,##0.0"), ("fx", "FX: reporting ccy per facility ccy", "0.0000"),
    ("coupon", "Facility coupon", "0.00%"), ("floating", "Facility floating? (1/0)", "0"),
    ("use", "Use of proceeds (1 capex, 2 cash, 3 refi)", "0"), ("refi_rate", "Rate on refinanced debt", "0.00%"),
    ("ebitda_shock", "EBITDA shock", "0.0%"), ("rate_bps", "Rate shock (bp)", "0"),
    ("cov_lev", "Covenant: max net leverage (x)", "0.00x"), ("cov_cover", "Covenant: min EBITDA cover (x)", "0.00x"),
]
# key, label, formula template ({r[key]} -> cell of that row in the same column), format
CALC_ROWS = [
    ("amt", "Facility in reporting ccy", "={amount}*{fx}", "#,##0.00"),
    ("repaid", "Existing debt repaid", "=IF({use}=3,MIN({amt},{gross_debt}),0)", "#,##0.00"),
    ("gd_pf", "Pro forma gross debt", "={gross_debt}+{amt}-{repaid}", "#,##0.00"),
    ("cash_pf", "Pro forma cash", "={cash}+IF({use}=2,{amt},0)+IF({use}=3,{amt}-{repaid},0)", "#,##0.00"),
    ("ex_int", "Existing interest after refi", "={interest}-{repaid}*{refi_rate}", "#,##0.00"),
    ("ex_float", "Existing floating debt", "=IF({gross_debt}>0,{gross_debt}*{float_share}*({gross_debt}-{repaid})/{gross_debt},0)", "#,##0.00"),
    ("new_int", "New facility interest", "={amt}*{coupon}", "#,##0.00"),
    ("float_debt", "Total floating debt", "={ex_float}+{amt}*{floating}", "#,##0.00"),
    ("ebitda_s", "Stressed EBITDA", "={ebitda}*(1+{ebitda_shock})", "#,##0.00"),
    ("int_s", "Stressed interest", "=MAX({ex_int}+{new_int}+{float_debt}*{rate_bps}/10000,0)", "#,##0.00"),
    ("nd", "Net debt", "={gd_pf}-{cash_pf}", "#,##0.00"),
    ("net_lev", "Net leverage (x)", '=IF({ebitda_s}>0,{nd}/{ebitda_s},"n/a")', "0.000x"),
    ("cover", "EBITDA interest cover (x)", '=IF({int_s}>0,{ebitda_s}/{int_s},"n/a")', "0.000x"),
    ("hr_lev", "Headroom: max net leverage", '=IF(ISNUMBER({net_lev}),{cov_lev}-{net_lev},"n/a")', "0.000x;(0.000x)"),
    ("hr_cov", "Headroom: min cover", '=IF(ISNUMBER({cover}),{cover}-{cov_cover},"n/a")', "0.000x;(0.000x)"),
]


def build() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Cases"
    f = Font(name="Arial", size=10)
    blue, bold = Font(name="Arial", size=10, color="0000FF"), Font(name="Arial", size=10, bold=True)
    head_fill = PatternFill("solid", start_color="0B1F3A")
    thin = Border(bottom=Side(style="thin", color="999999"))

    ws["A1"] = "CreditLens — independent spreadsheet check of the loan & stress engine"
    ws["A1"].font = Font(name="Arial", size=12, bold=True)
    ws["A2"] = ("Blue = inputs (edit freely). Black = formulas, written independently of the Python engine. "
                "Baseline is the Blueprint p.09 illustrative company, EUR millions. "
                "tests/unit/test_scenario_crosscheck.py compares every result to backend/app/scenarios/loan.py.")
    ws["A2"].font = Font(name="Arial", size=9, italic=True)
    ws["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=1 + len(CASES))
    ws.row_dimensions[2].height = 30

    hr = 4
    ws.cell(hr, 1, "Line item").font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
    ws.cell(hr, 1).fill = head_fill
    rows: dict[str, int] = {}
    r = hr + 1
    ws.cell(r, 1, "INPUTS").font = bold
    r += 1
    for key, label, _ in INPUT_ROWS:
        rows[key] = r
        ws.cell(r, 1, label).font = f
        r += 1
    r += 1
    ws.cell(r, 1, "CALCULATIONS").font = bold
    r += 1
    for key, label, _, _ in CALC_ROWS:
        rows[key] = r
        ws.cell(r, 1, label).font = bold if key in ("net_lev", "cover", "hr_lev", "hr_cov") else f
        r += 1

    for j, (name, over) in enumerate(CASES):
        col = 2 + j
        L = get_column_letter(col)
        c = ws.cell(hr, col, name)
        c.font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
        c.fill = head_fill
        c.alignment = Alignment(wrap_text=True, horizontal="center", vertical="center")
        vals = {**B, **over}
        vals["use"] = USE_CODES[vals["use"]]
        for key, _, fmt in INPUT_ROWS:
            cell = ws.cell(rows[key], col, vals[key])
            cell.font, cell.number_format = blue, fmt
        ref = {k: f"{L}{v}" for k, v in rows.items()}
        for key, _, tmpl, fmt in CALC_ROWS:
            cell = ws.cell(rows[key], col, tmpl.format(**ref))
            cell.font = bold if key in ("net_lev", "cover", "hr_lev", "hr_cov") else f
            cell.number_format = fmt
            if key in ("net_lev", "cover"):
                cell.border = thin
    ws.cell(rows["ebitda"], 2).comment = Comment("Source: CreditLens blueprint p.09 illustrative case (fabricated).", "CreditLens")
    ws.cell(rows["refi_rate"], 2).comment = Comment("Only used when use of proceeds = 3 (refinancing).", "CreditLens")
    ws.column_dimensions["A"].width = 40
    for j in range(len(CASES)):
        ws.column_dimensions[get_column_letter(2 + j)].width = 17
    ws.row_dimensions[hr].height = 42
    ws.freeze_panes = ws.cell(hr + 1, 2)

    meta = wb.create_sheet("Map")
    meta.append(["key", "row"])
    for k, v in rows.items():
        meta.append([k, v])
    for row in meta.iter_rows():
        for cell in row:
            cell.font = f
    wb.save(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    build()
