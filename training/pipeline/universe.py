"""Week 2 — reproducible training universe (Blueprint p.05).

Survivorship-aware: candidates come from SEC XBRL `frames` snapshots of total assets in
several past years, so companies that later failed, were acquired or delisted stay in.

Rules (all recorded in the output CSV):
  * total assets >= MIN_ASSETS_USD in at least one snapshot (drops shells / blank-check)
  * stratified random sample across log-size quintiles (fixed seed) — not just mega caps
  * exclude SIC 6000-6799 (banks, insurers, brokers, REITs/trusts) and unknown / blank-check SIC

    python -m training.pipeline.universe --target 600 --out training/data/universe_v1.csv
"""
from __future__ import annotations

import argparse
import csv
import math
import random

from backend.app.documents.sec_client import SECClient

SNAPSHOTS = ["CY2011Q4I", "CY2015Q4I", "CY2019Q4I", "CY2022Q4I"]
MIN_ASSETS_USD = 100e6
SEED = 20261104


def excluded_sic(sic) -> str | None:
    if sic in (None, "", "0"):
        return "sic_missing"
    s = int(sic)
    if 6000 <= s <= 6799:
        return "financial_sector"
    if s in (6770, 9995):
        return "blank_check"
    return None


def candidates(client: SECClient) -> dict[int, dict]:
    pool: dict[int, dict] = {}
    for snap in SNAPSHOTS:
        for row in client.frame("Assets", snap)["data"]:
            c = pool.setdefault(row["cik"], {"cik": row["cik"], "name": row["entityName"], "max_assets": 0.0,
                                             "snapshots": []})
            c["max_assets"] = max(c["max_assets"], float(row["val"]))
            c["snapshots"].append(snap)
    return {k: v for k, v in pool.items() if v["max_assets"] >= MIN_ASSETS_USD}


def stratified_order(pool: dict[int, dict], n_buckets: int = 5) -> list[dict]:
    rows = sorted(pool.values(), key=lambda r: r["max_assets"])
    size = math.ceil(len(rows) / n_buckets)
    rng = random.Random(SEED)
    buckets = [rows[i:i + size] for i in range(0, len(rows), size)]
    for i, b in enumerate(buckets):
        for r in b:
            r["size_quintile"] = i + 1
        rng.shuffle(b)
    # round-robin across buckets so any prefix of the list is size-balanced
    out = []
    for i in range(max(len(b) for b in buckets)):
        out += [b[i] for b in buckets if i < len(b)]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=600)
    ap.add_argument("--out", default="training/data/universe_v1.csv")
    args = ap.parse_args()
    client = SECClient()
    pool = candidates(client)
    print(f"candidates with assets >= ${MIN_ASSETS_USD/1e6:.0f}m in some snapshot: {len(pool)}")
    kept, seen, reasons = [], 0, {}
    for c in stratified_order(pool):
        if len(kept) >= args.target:
            break
        seen += 1
        try:
            meta = client.submissions_meta(c["cik"])
        except Exception as e:  # noqa: BLE001
            reasons["submissions_error"] = reasons.get("submissions_error", 0) + 1
            continue
        why = excluded_sic(meta.get("sic"))
        if why:
            reasons[why] = reasons.get(why, 0) + 1
            continue
        kept.append({"cik": str(c["cik"]).zfill(10), "name": meta.get("name") or c["name"],
                     "sic": meta.get("sic"), "sic_description": meta.get("sicDescription"),
                     "tickers": "|".join(meta.get("tickers") or []), "size_quintile": c["size_quintile"],
                     "max_assets_usd_m": round(c["max_assets"] / 1e6, 1), "snapshots": "|".join(c["snapshots"])})
    with open(args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(kept[0]))
        w.writeheader()
        w.writerows(kept)
    print(f"screened={seen} kept={len(kept)} excluded={reasons} -> {args.out}")


if __name__ == "__main__":
    main()
