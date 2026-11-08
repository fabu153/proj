"""Peer percentiles for the ledger (descriptive; never a model input).

A company-year is ranked against other companies in the training panel's lending population
(backend/data/peers/peers_v1.json). Peer group, widest last, the first with at least MIN_PEERS companies:
  1. same SIC major group (2 digits), same fiscal year      2. same major group, fiscal years t-2..t
  3. same SIC division, same fiscal year                     4. same division, t-2..t
  5. all industries, same fiscal year                        6. all industries, t-2..t
Each peer company counts once (its latest fiscal year in the window); the company itself is excluded.
Percentile = share of peers with a lower value (ties count half), so 18 means 18% of peers are lower.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

PEERS = Path(__file__).resolve().parents[2] / "data" / "peers" / "peers_v1.json"
MIN_PEERS = 15
PEERS_VERSION = "1.0.0"

MAJOR = {
    1: "agricultural production (crops)", 2: "agricultural production (livestock)", 7: "agricultural services",
    9: "fishing, hunting and trapping", 10: "metal mining", 12: "coal mining", 13: "oil and gas extraction",
    14: "non-metallic minerals mining", 15: "general building contractors", 16: "heavy construction",
    17: "construction special trades", 20: "food and kindred products", 21: "tobacco products",
    22: "textile mill products", 23: "apparel", 24: "lumber and wood products", 25: "furniture and fixtures",
    26: "paper and allied products", 27: "printing and publishing", 28: "chemicals and allied products",
    29: "petroleum refining", 30: "rubber and plastics products", 31: "leather products",
    32: "stone, clay and glass products", 33: "primary metals", 34: "fabricated metal products",
    35: "industrial machinery and computer equipment", 36: "electronic and electrical equipment",
    37: "transportation equipment", 38: "instruments and related products", 39: "miscellaneous manufacturing",
    40: "railroads", 41: "local and interurban passenger transit", 42: "trucking and warehousing",
    44: "water transportation", 45: "air transportation", 46: "pipelines", 47: "transportation services",
    48: "communications", 49: "electric, gas and sanitary services", 50: "wholesale trade (durable goods)",
    51: "wholesale trade (non-durable goods)", 52: "building materials and garden supply retail",
    53: "general merchandise stores", 54: "food stores", 55: "automotive dealers and service stations",
    56: "apparel and accessory stores", 57: "home furnishings stores", 58: "restaurants",
    59: "miscellaneous retail", 70: "hotels and lodging", 72: "personal services", 73: "business services",
    75: "automotive repair and services", 78: "motion pictures", 79: "amusement and recreation services",
    80: "health services", 82: "educational services", 87: "engineering and management services",
}
DIVISIONS = [((1, 9), "agriculture, forestry and fishing"), ((10, 14), "mining"), ((15, 17), "construction"),
             ((20, 39), "manufacturing"), ((40, 49), "transportation, communications and utilities"),
             ((50, 51), "wholesale trade"), ((52, 59), "retail trade"), ((60, 67), "finance"),
             ((70, 89), "services"), ((91, 99), "public administration")]


def fiscal_year(fye: str) -> int:
    """Same rule as the app's FY labels: a 52/53-week year ending in the first week of January belongs to the
    previous fiscal year (B&G Foods' year ended 2026-01-03 is FY2025)."""
    y = int(fye[:4])
    return y - 1 if fye[5:7] == "01" and int(fye[8:10]) <= 7 else y


def division(major: int) -> Optional[tuple[tuple[int, int], str]]:
    return next((d for d in DIVISIONS if d[0][0] <= major <= d[0][1]), None)


@lru_cache(maxsize=1)
def table() -> dict:
    d = json.loads(PEERS.read_text())
    cols = d["columns"]
    d["_rows"] = [dict(zip(cols, r)) for r in d["rows"]]
    for r in d["_rows"]:
        r["_fy"] = fiscal_year(r["fiscal_year_end"])
        r["_major"] = int(r["sic"]) // 100
    return d


def sic_of(cik: str) -> Optional[int]:
    """SIC of a company that is itself in the panel (the curated samples), else None."""
    return next((r["sic"] for r in table()["_rows"] if r["cik"] == cik), None)


def _pick_latest(rows: list[dict]) -> list[dict]:
    by = {}
    for r in rows:
        if r["cik"] not in by or r["fiscal_year_end"] > by[r["cik"]]["fiscal_year_end"]:
            by[r["cik"]] = r
    return list(by.values())


def percentiles(values: dict[str, Optional[float]], cik: str, sic, fiscal_year_end: str) -> dict:
    """values: metric -> this company's value (same definitions as the peer table). Returns metric -> band."""
    t = table()
    fy = fiscal_year(fiscal_year_end)
    major = int(sic) // 100 if sic not in (None, "", "0") else None
    groups = []
    if major is not None:
        groups.append((f"SIC {major:02d}: {MAJOR.get(major, f'major group {major:02d}')}", lambda r: r["_major"] == major))
        dv = division(major)
        if dv:
            groups.append((f"SIC division: {dv[1]}", lambda r, dv=dv: dv[0][0] <= r["_major"] <= dv[0][1]))
    groups.append(("all non-financial companies", lambda r: True))
    out = {}
    for m, meta in t["metrics"].items():
        x = values.get(m)
        if x is None:
            continue
        band = None
        for label, member in groups:
            for years in ((fy, fy), (fy - 2, fy)):
                peers = _pick_latest([r for r in t["_rows"] if member(r) and years[0] <= r["_fy"] <= years[1]
                                      and r["cik"] != cik and r.get(m) is not None])
                if len(peers) >= MIN_PEERS:
                    vals = [r[m] for r in peers]
                    lower = sum(v < x for v in vals) + 0.5 * sum(v == x for v in vals)
                    vals.sort()
                    q = lambda f: vals[min(len(vals) - 1, int(f * (len(vals) - 1) + 0.5))]  # noqa: E731
                    band = {"percentile": round(100 * lower / len(vals)), "peers": len(vals), "group": label,
                            "years": f"FY{years[1]}" if years[0] == years[1] else f"FY{years[0]}-{years[1]}",
                            "p25": q(0.25), "median": q(0.5), "p75": q(0.75), "stronger": meta["stronger"]}
                    break
            if band:
                break
        if band:
            out[m] = band
    return {"version": PEERS_VERSION, "basis": t["basis"], "population": t["population"], "bands": out,
            "min_peers": MIN_PEERS}
