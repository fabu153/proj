"""Peer distribution for the ledger's percentile bands.

    python -m training.ml.export_peers      # after training.ml.classic_scores (adds Z'' and O columns)

Writes backend/data/peers/peers_v1.json: one row per company-year of the lending population in panel_v1 (scorable,
revenue >= USD 50m, critical coverage >= 4 of 7 — the training row filters), with its SIC code and the ledger ratios
as computed on the training-panel basis. The app ranks a company against these rows (backend/app/finance/peers.py).
Descriptive only: nothing here feeds the model.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from training.ml.run_baselines import sha256_file

OUT = Path("backend/data/peers/peers_v1.json")
METRICS = {  # ledger key -> (panel column, label, which direction is stronger credit)
    "revenue_growth": ("m_revenue_growth", "Revenue growth", "higher"),
    "ebitda_margin": ("m_ebitda_margin", "EBITDA margin", "higher"),
    "gross_leverage": ("m_gross_leverage", "Gross debt / EBITDA", "lower"),
    "net_leverage": ("m_net_leverage", "Net debt / EBITDA", "lower"),
    "ebit_interest_cover": ("m_ebit_interest_cover", "EBIT / interest", "higher"),
    "ebitda_interest_cover": ("m_ebitda_interest_cover", "EBITDA / interest", "higher"),
    "current_ratio": ("m_current_ratio", "Current ratio", "higher"),
    "altman_z2": ("altman_z2", "Altman Z''", "higher"),
    "ohlson_o": ("ohlson_o", "Ohlson O", "lower"),
}


def main():
    base = yaml.safe_load(Path("configs/experiment_baselines_v1.yaml").read_text())
    rf = base["row_filters"]
    p = pd.read_csv(base["panel"], dtype={"cik": str})
    p = p[(p["scorable"] == 1) & (p["v_revenue"] >= rf["min_revenue_usd_m"]) & (p["critical_coverage"] >= rf["min_critical_coverage"])]
    cs = pd.read_csv("training/experiments/classic_scores_v1/panel_scores.csv", dtype={"cik": str})
    p = p.merge(cs, on=["cik", "fiscal_year_end"], how="left")
    cols = [c for c, _, _ in METRICS.values()]
    rows = []
    for _, r in p.iterrows():
        rows.append([r["cik"], r["fiscal_year_end"], int(r["sic"])] +
                    [None if pd.isna(r[c]) else round(float(r[c]), 6) for c in cols])
    out = {"version": "peers_v1", "source": {"panel": base["panel"], "panel_sha256": sha256_file(base["panel"]),
                                             "classic_scores": "training/experiments/classic_scores_v1/panel_scores.csv"},
           "population": "panel_v1 lending population: scorable, revenue >= USD 50m, >= 4 of 7 critical fields "
                         "(U.S. non-financial SEC filers, fiscal years 2007-2026)",
           "basis": "ratios as in the training panel (model basis: credit-basis corrections R5-R7 not applied)",
           "metrics": {k: {"label": lab, "stronger": d} for k, (_, lab, d) in METRICS.items()},
           "columns": ["cik", "fiscal_year_end", "sic"] + list(METRICS),
           "rows": rows}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")) + "\n")
    print(f"wrote {OUT}: {len(rows)} company-years, {p['cik'].nunique()} companies")


if __name__ == "__main__":
    main()
