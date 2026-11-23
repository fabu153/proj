"""Shared, read-only loaders for the evaluation analyses (economic value, robustness, results summary).

Two prediction sets, never mixed:
* frozen_test(): the 1,086 held-out rows (filed 2021-25) with the FROZEN predictions of every model — the deployed
  network (mlp_v1), the baselines (baselines_v1) and the textbook scores (classic_scores_v1).
* walk_forward(): 2,021 company-years filed 2016-25, each scored out of sample by models re-fitted every year with
  only the data public at the time (walk_forward_v1).
Both add the borrower's gross debt (USD m), revenue, SIC division and filing-year status from the frozen panel.
An equal-weight average of logistic, XGBoost and MLP ("ensemble_equal") is added to both; it has no fitted
weights, but it was proposed after the walk-forward results were seen, so it is labelled exploratory everywhere.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from backend.app.finance.peers import division
from training.ml.run_baselines import load_dataset
from training.ml.splits import SplitSpec, assign_splits

EXP = Path("training/experiments")
TARGET = "label_next_fy"
FITTED = ["rule_score", "logistic", "xgboost", "mlp", "ensemble_equal"]
TEXTBOOK = {"altman_z2": -1.0, "ohlson_o": 1.0}          # sign that makes "higher = riskier"
LABELS = {"no_skill": "No skill (base rate)", "rule_score": "Rule: conditions met in t", "logistic": "Logistic regression",
          "xgboost": "XGBoost", "mlp": "Neural network (MLP)", "ensemble_equal": "Equal-weight ensemble*",
          "altman_z2": "Altman Z″", "ohlson_o": "Ohlson O"}


def _panel_extras() -> pd.DataFrame:
    p = pd.read_csv("training/data/panel_v1.csv", dtype={"cik": str})
    out = p[["cik", "fiscal_year_end", "sic", "v_revenue", "m_gross_debt"]].rename(
        columns={"v_revenue": "revenue", "m_gross_debt": "gross_debt"})
    out["sector"] = out["sic"].map(lambda s: (division(int(s) // 100) or ((0, 0), "other"))[1])
    return out.drop(columns="sic")


def status(df: pd.DataFrame) -> pd.Series:
    return df["stress_t"].map({1.0: "already stressed", 0.0: "healthy"}).fillna("undetermined")


def frozen_test() -> pd.DataFrame:
    base = yaml.safe_load(Path("configs/experiment_baselines_v1.yaml").read_text())
    df = load_dataset(base)
    split = assign_splits(df, SplitSpec(**base["split"]))
    te = df[(split == "test") & df[TARGET].notna()][["cik", "fiscal_year_end", "as_of_date", TARGET, "label_onset", "stress_t"]]
    te = te.reset_index(drop=True)
    b = pd.read_csv(EXP / "baselines_v1/test_predictions_label_next_fy.csv", dtype={"cik": str}).drop(columns="y")
    m = pd.read_csv(EXP / "mlp_v1/test_predictions_label_next_fy.csv", dtype={"cik": str})[["cik", "fiscal_year_end", "mlp"]]
    c = pd.read_csv(EXP / "classic_scores_v1/panel_scores.csv", dtype={"cik": str})
    out = te.merge(b, how="left").merge(m, how="left").merge(c, how="left").merge(_panel_extras(), how="left")
    assert len(out) == 1086 and out[["logistic", "xgboost", "mlp"]].notna().all().all()
    out["ensemble_equal"] = out[["logistic", "xgboost", "mlp"]].mean(axis=1)
    out["year"] = pd.to_datetime(out["as_of_date"]).dt.year
    out["status_t"] = status(out)
    return out


def walk_forward() -> pd.DataFrame:
    w = pd.read_csv(EXP / "walk_forward_v1/oos_predictions.csv", dtype={"cik": str}).drop(columns=["sic"])
    w = w.merge(_panel_extras(), how="left")
    w["ensemble_equal"] = w[["logistic", "xgboost", "mlp"]].mean(axis=1)
    w["year"] = w["test_year"]
    w["status_t"] = status(w)
    return w


def risk(df: pd.DataFrame, model: str) -> pd.Series:
    """Score with higher = riskier; textbook scores flipped where needed; NaN where a score is missing."""
    return df[model] * TEXTBOOK.get(model, 1.0)
