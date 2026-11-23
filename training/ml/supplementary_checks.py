"""Supplementary checks on the label and the economic ranking.

    python -m training.ml.supplementary_checks         # ~20 s, CPU only

1. Missing labels: why lending-population rows have no observable next-year outcome (insufficient t+1 data,
   t+1 failed hard checks, t+1 not yet reported, firm stopped filing), and a sensitivity analysis that re-scores
   test-window firms that never filed again as STRESSED (all of them, or only those already weak in year t),
   using the frozen deployed network. Distressed exits never receive a label, so this bounds the selection bias.
2. Expected-loss ranking: rank each year by probability x reported gross debt instead of probability alone, and
   compare stressed borrowers caught and stressed debt flagged with probability ranking and debt size alone
   (walk-forward predictions 2016-25).

Writes training/experiments/supplementary_v1/results.json.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sklearn.metrics import average_precision_score

from backend.app.models.inference import StressModel
from training.ml.economic_value import flags
from training.ml.results_data import TARGET, walk_forward
from training.ml.run_baselines import load_dataset

OUT = Path("training/experiments/supplementary_v1")
BASE = Path("configs/experiment_baselines_v1.yaml")
ARTIFACT = Path("backend/models/stress_mlp_v1")
FIRST_UNREPORTED_FY = 2025      # fiscal years whose t+1 annual report was not yet filed at the data cut


def missing_labels() -> dict:
    base = yaml.safe_load(BASE.read_text())
    df = load_dataset(base)
    panel = pd.read_csv(base["panel"], dtype={"cik": str})
    df = df.merge(panel[["cik", "fiscal_year_end", "label_reason"]], on=["cik", "fiscal_year_end"], how="left")
    fy = pd.to_datetime(df["fiscal_year_end"])
    last = pd.to_datetime(panel["fiscal_year_end"]).groupby(panel["cik"]).max()
    un = df[TARGET].isna()
    no_next = df["label_reason"] == "no_consecutive_t+1"
    not_yet = un & no_next & (fy.dt.year >= FIRST_UNREPORTED_FY)
    gap_or_stop = un & no_next & (fy.dt.year < FIRST_UNREPORTED_FY)
    stopped = gap_or_stop & (fy == df["cik"].map(last))
    lab = df[TARGET].notna()
    breakdown = {
        "lending_rows": int(len(df)), "labelled": int(lab.sum()), "unlabelled": int(un.sum()),
        "insufficient_t+1_data": int((un & (df["label_reason"] == "insufficient_t+1_data")).sum()),
        "t+1_failed_hard_checks": int((un & (df["label_reason"] == "t+1_failed_hard_checks")).sum()),
        "t+1_not_yet_reported": int(not_yet.sum()),
        "no_t+1_before_data_end": int(gap_or_stop.sum()),
        "of_which_firm_never_files_again": int(stopped.sum()),
        "stopped_filers_stressed_in_t": float((df.loc[stopped, "stress_t"] == 1).mean()),
        "labelled_rows_stressed_in_t": float((df.loc[lab, "stress_t"] == 1).mean()),
    }
    sp = base["split"]
    asof = pd.to_datetime(df["as_of_date"])
    in_test = (asof >= pd.Timestamp(sp["test_start"])) & (asof < pd.Timestamp(sp["test_end"]))
    model = StressModel.load(ARTIFACT)
    p = model.calibrate(model.logit_from_matrix(model.pre.transform(df).to_numpy()))
    test_lab = in_test & lab
    sens = {"frozen_test": {"rows": int(test_lab.sum()),
                            "pr_auc": float(average_precision_score(df.loc[test_lab, TARGET].astype(int), p[test_lab]))}}
    for name, extra in (("stopped_filers_stressed_in_t_as_stressed", stopped & in_test & (df["stress_t"] == 1)),
                        ("stopped_filers_with_1plus_condition_as_stressed",
                         stopped & in_test & (df["stress_conditions_t"] >= 1)),
                        ("all_stopped_filers_as_stressed", stopped & in_test)):
        rows = test_lab | extra
        y = df.loc[rows, TARGET].fillna(1).astype(int)
        sens[name] = {"added_rows": int(extra.sum()), "pr_auc": float(average_precision_score(y, p[rows])),
                      "mean_network_score_of_added": float(p[extra].mean())}
    return {"breakdown": breakdown, "sensitivity_deployed_network": sens}


def expected_loss_ranking() -> dict:
    df = walk_forward()
    debt = df["gross_debt"].fillna(0).clip(lower=0)
    y = df[TARGET].astype(int).to_numpy()
    stressed_debt = float(debt[y == 1].sum())
    d = df.copy()
    d["debt_only"] = debt
    out = {}
    for m in ("mlp", "logistic", "xgboost", "rule_score"):
        d[f"{m}_x_debt"] = d[m] * debt
    for col in ("mlp", "logistic", "xgboost", "rule_score", "mlp_x_debt", "logistic_x_debt", "xgboost_x_debt",
                "rule_score_x_debt", "debt_only"):
        out[col] = {}
        for b in (0.10, 0.20):
            f = flags(d, col, b)
            out[col][f"{int(b * 100)}%"] = {"reviews": int(f.sum()), "caught": int((f & (y == 1)).sum()),
                                            "stressed_debt_flagged": float(debt[f & (y == 1)].sum()) / stressed_debt}
    return out


def main():
    res = {"experiment": "supplementary_v1", "missing_labels": missing_labels(),
           "expected_loss_ranking_walk_forward": expected_loss_ranking()}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res["missing_labels"], indent=1))
    el = res["expected_loss_ranking_walk_forward"]
    for k in ("mlp", "mlp_x_debt", "debt_only", "rule_score"):
        r = el[k]["10%"]
        print(f"{k:12s} 10%: caught {r['caught']}, stressed debt flagged {r['stressed_debt_flagged']:.0%}")


if __name__ == "__main__":
    main()
