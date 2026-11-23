"""Robustness of the ranking across years, sectors, company size and filing-year status.

    python -m training.ml.robustness

For each subgroup and model: rows, stressed, prevalence, PR-AUC, and lift = PR-AUC / prevalence (PR-AUC depends on
the base rate, so lift makes subgroups with different base rates comparable), plus calibration-in-the-large
(mean predicted probability vs observed rate) by year for the probabilistic models. Run on the walk-forward
out-of-sample predictions (2016-25) and on the frozen 2021-25 test (deployed network).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

from training.ml.results_data import TARGET, frozen_test, risk, walk_forward

OUT = Path("training/experiments/robustness_v1")
MODELS = ["rule_score", "logistic", "xgboost", "mlp", "ensemble_equal", "altman_z2", "ohlson_o"]
PROB = ["logistic", "xgboost", "mlp", "ensemble_equal"]
MIN_POS = 10          # subgroups with fewer stressed rows (or fewer non-stressed) are reported but not scored


def group_table(df: pd.DataFrame, key: str) -> list[dict]:
    rows = []
    for g, d in df.groupby(key, sort=True):
        y = d[TARGET].to_numpy().astype(int)
        r = {"group": str(g), "rows": int(len(d)), "stressed": int(y.sum()), "prevalence": float(y.mean())}
        if y.sum() >= MIN_POS and (len(y) - y.sum()) >= MIN_POS:
            for m in MODELS:
                s = risk(d, m).to_numpy()
                ok = ~np.isnan(s)
                if y[ok].sum() >= MIN_POS:
                    ap = float(average_precision_score(y[ok], s[ok]))
                    r[m] = {"pr_auc": ap, "lift": ap / float(y[ok].mean()), "rows": int(ok.sum())}
        rows.append(r)
    return rows


def calibration_by_year(df: pd.DataFrame) -> list[dict]:
    out = []
    for yr, d in df.groupby("year"):
        out.append({"year": int(yr), "observed": float(d[TARGET].mean()),
                    **{f"{m}_mean_predicted": float(d[m].mean()) for m in PROB}})
    return out


def main():
    res = {"experiment": "robustness_v1", "min_positives_to_score": MIN_POS}
    for name, df in (("walk_forward_2016_2025", walk_forward()), ("frozen_test_2021_2025", frozen_test())):
        q = df["revenue"].quantile([1 / 3, 2 / 3]).to_numpy()
        df["size"] = np.select([df["revenue"] <= q[0], df["revenue"] <= q[1]],
                               ["1 small", "2 mid"], "3 large")
        res[name] = {"size_cutoffs_revenue_usd_m": [float(x) for x in q],
                     "by_year": group_table(df, "year"), "by_sector": group_table(df, "sector"),
                     "by_size": group_table(df, "size"), "by_status_in_t": group_table(df, "status_t"),
                     "calibration_by_year": calibration_by_year(df)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(res, indent=1) + "\n")
    for k in ("by_year", "by_sector", "by_size", "by_status_in_t"):
        print(k)
        for r in res["walk_forward_2016_2025"][k]:
            print("  ", r["group"], r["rows"], r["stressed"], " ".join(f"{m}={r[m]['pr_auc']:.2f}" for m in MODELS if m in r))


if __name__ == "__main__":
    main()
