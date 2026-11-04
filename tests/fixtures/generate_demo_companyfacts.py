"""Generate a SYNTHETIC companyfacts JSON in SEC format. All numbers are fabricated (USD).

Deliberately includes the traps the real pipeline must survive:
  * each annual fact repeated as a comparative in the next year's 10-K (duplicates)
  * a Q4 3-month fact and a 10-Q fact that must NOT be read as annual (D01)
  * FY2024 revenue restated in the FY2025 10-K (vintage handling)
  * no ShortTermBorrowings tag in later years (zero-if-absent debt bucket)

Run:  python tests/fixtures/generate_demo_companyfacts.py tests/fixtures/demo_companyfacts.json
"""
import json
import sys

M = 1_000_000
YEARS = {  # fy_end -> values in USD millions
    "2023-12-31": dict(rev=1100, oi=150, ni=90, int=18, da=55, cfo=160, capex=70, cash=60, stb=10, cur=20,
                       ltd=270, ta=1500, tl=900, eq=600, ca=500, cl=300),
    "2024-12-31": dict(rev=1180, oi=165, ni=100, int=19, da=58, cfo=175, capex=75, cash=55, stb=0, cur=25,
                       ltd=280, ta=1560, tl=930, eq=630, ca=520, cl=310),
    "2025-12-31": dict(rev=1240, oi=176, ni=108, int=20, da=62, cfo=182, capex=80, cash=50, stb=0, cur=30,
                       ltd=270, ta=1600, tl=940, eq=660, ca=530, cl=320),
}
FILED = {"2023-12-31": ("0000000001-24-000010", "2024-02-20"),
         "2024-12-31": ("0000000001-25-000010", "2025-02-19"),
         "2025-12-31": ("0000000001-26-000010", "2026-02-18")}
TAGS = {"rev": "Revenues", "oi": "OperatingIncomeLoss", "ni": "NetIncomeLoss", "int": "InterestExpense",
        "da": "DepreciationDepletionAndAmortization", "cfo": "NetCashProvidedByUsedInOperatingActivities",
        "capex": "PaymentsToAcquirePropertyPlantAndEquipment", "cash": "CashAndCashEquivalentsAtCarryingValue",
        "stb": "ShortTermBorrowings", "cur": "LongTermDebtCurrent", "ltd": "LongTermDebtNoncurrent",
        "ta": "Assets", "tl": "Liabilities", "eq": "StockholdersEquity", "ca": "AssetsCurrent",
        "cl": "LiabilitiesCurrent"}
INSTANT = {"cash", "stb", "cur", "ltd", "ta", "tl", "eq", "ca", "cl"}


def build() -> dict:
    facts: dict = {}

    def add(tag, e):
        facts.setdefault(tag, {"units": {"USD": []}})["units"]["USD"].append(e)

    ends = list(YEARS)
    for i, end in enumerate(ends):
        y = int(end[:4])
        for k, v in YEARS[end].items():
            if k == "stb" and v == 0:
                continue
            e = {"end": end, "val": v * M, "fy": y, "fp": "FY", "form": "10-K"}
            if k not in INSTANT:
                e["start"] = f"{y}-01-01"
            for j in range(i, min(i + 2, len(ends))):          # original + comparative next year
                accn, fd = FILED[ends[j]]
                add(TAGS[k], {**e, "accn": accn, "filed": fd})
        accn, fd = FILED[end]
        add("Revenues", {"start": f"{y}-10-01", "end": end, "val": YEARS[end]["rev"] * M / 4,
                         "accn": accn, "fy": y, "fp": "FY", "form": "10-K", "filed": fd})
        add("Revenues", {"start": f"{y}-01-01", "end": f"{y}-03-31", "val": YEARS[end]["rev"] * M / 4,
                         "accn": f"0000000001-{str(y)[2:]}-000003", "fy": y, "fp": "Q1", "form": "10-Q",
                         "filed": f"{y}-05-01"})
    for e in facts["Revenues"]["units"]["USD"]:                 # restatement of FY2024 revenue
        if e["end"] == "2024-12-31" and e["accn"] == FILED["2025-12-31"][0] and e.get("start") == "2024-01-01":
            e["val"] = 1175 * M
    return {"cik": 1, "entityName": "Demo Industrials Inc. (SYNTHETIC)", "facts": {"us-gaap": facts}}


if __name__ == "__main__":
    with open(sys.argv[1], "w") as fh:
        json.dump(build(), fh, indent=1)
