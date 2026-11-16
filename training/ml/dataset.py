"""The model population, loaded the same way by every experiment, export and test.

Kept apart from run_baselines.py so that reading the panel does not import XGBoost (and its native OpenMP
library); run_baselines re-exports both names for older imports.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from backend.app.features.feature_set import build_features


def sha256_file(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_dataset(cfg: dict) -> pd.DataFrame:
    panel = pd.read_csv(cfg["panel"], dtype={"cik": str})
    rf = cfg["row_filters"]
    feats = build_features(panel)    # built on the full panel so t-1 trends see the prior year
    if rf.get("min_revenue_usd_m") is not None:
        rev = panel.set_index(panel.index)["v_revenue"]
        feats = feats[rev.loc[feats.index] >= rf["min_revenue_usd_m"]]
    if rf.get("require_scorable"):
        feats = feats[feats["scorable"] == 1]
    feats = feats[feats["critical_coverage"] >= rf.get("min_critical_coverage", 0)]
    return feats.reset_index(drop=True)
