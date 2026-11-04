"""Torch-free inference for the trained stress MLP.

The network is small (62 -> 128 -> 64 -> 32 -> 1), so the API runs the forward pass in numpy
from exported weights. This keeps PyTorch (~700 MB) out of the deployed image; a parity test
checks numpy == torch on stored inputs to 1e-6.

Output contract: a calibrated next-fiscal-year ACCOUNTING-STRESS screening probability.
Not a probability of default, not a rating.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from ..features.feature_set import FEATURE_DICTIONARY, FEATURES
from ..features.preprocess import Preprocessor

ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "models" / "stress_mlp_v1"


def _relu(x):
    return np.maximum(x, 0.0)


def _layernorm(x, g, b, eps=1e-5):
    mu = x.mean(axis=-1, keepdims=True)
    var = x.var(axis=-1, keepdims=True)
    return (x - mu) / np.sqrt(var + eps) * g + b


def forward(w: dict[str, np.ndarray], X: np.ndarray) -> np.ndarray:
    """Eval-mode forward pass (dropout is identity). Returns logits, shape (n,)."""
    h = _layernorm(_relu(X @ w["W1"].T + w["b1"]), w["ln_g"], w["ln_b"])
    h = _relu(h @ w["W2"].T + w["b2"])
    h = _relu(h @ w["W3"].T + w["b3"])
    return (h @ w["W4"].T + w["b4"])[:, 0]


@dataclass
class StressModel:
    seeds: list[dict[str, np.ndarray]]
    pre: Preprocessor
    platt_a: float
    platt_b: float
    meta: dict

    # ------------------------------------------------------------------ loading
    @classmethod
    def load(cls, path: Path = ARTIFACT_DIR) -> "StressModel":
        npz = np.load(path / "weights.npz")
        n_seeds = int(npz["n_seeds"])
        seeds = [{k.split("__", 1)[1]: npz[k] for k in npz.files if k.startswith(f"s{i}__")} for i in range(n_seeds)]
        pre = Preprocessor.from_json((path / "preprocessor.json").read_text())
        cal = json.loads((path / "calibrator.json").read_text())
        meta = json.loads((path / "metadata.json").read_text())
        if meta["features"] != FEATURES:
            raise RuntimeError("Artifact feature list does not match code FEATURES — retrain or bump version")
        return cls(seeds, pre, cal["a"], cal["b"], meta)

    # ------------------------------------------------------------------ scoring
    def logit_from_matrix(self, X: np.ndarray) -> np.ndarray:
        return np.mean([forward(w, X) for w in self.seeds], axis=0)

    def calibrate(self, z: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-(self.platt_a * z + self.platt_b)))

    def predict_proba(self, feats: pd.DataFrame) -> np.ndarray:
        return self.calibrate(self.logit_from_matrix(self.pre.transform(feats).to_numpy()))

    def band(self, p: float) -> str:
        for name, (lo, hi) in self.meta["risk_bands"].items():
            if lo <= p < hi or (hi == 1.0 and p == 1.0):
                return name
        return "unknown"

    def drivers(self, row: pd.DataFrame, top_k: int = 6) -> list[dict]:
        """Occlusion attribution: change in logit when one feature is replaced by the training median
        (and its missing flag cleared). Positive = pushes risk UP. Association, not causation."""
        X = self.pre.transform(row).to_numpy()
        base = self.logit_from_matrix(X)[0]
        cols = self.pre.output_columns()
        out = []
        for f in FEATURES:
            Xo = X.copy()
            Xo[0, cols.index(f)] = (self.pre.median[f] - self.pre.mean[f]) / self.pre.std[f]
            Xo[0, cols.index(f"{f}__missing")] = 0.0
            delta = base - self.logit_from_matrix(Xo)[0]
            raw = row.iloc[0][f]
            out.append({"feature": f, "description": FEATURE_DICTIONARY[f][0], "unit": FEATURE_DICTIONARY[f][1],
                        "value": None if pd.isna(raw) else float(raw),
                        "train_median": self.pre.median[f], "logit_contribution": float(delta)})
        out.sort(key=lambda d: abs(d["logit_contribution"]), reverse=True)
        return out[:top_k]

    # ------------------------------------------------------------------ gating (test M04)
    def gate(self, row: pd.DataFrame, panel_row: dict) -> list[str]:
        g = self.meta["inference_gate"]
        reasons = []
        if g["require_scorable"] and not panel_row.get("scorable"):
            reasons.append("hard data-quality checks failed")
        rev = panel_row.get("v_revenue")
        if rev is None or rev < g["min_revenue_usd_m"]:
            reasons.append(f"outside model population (revenue < USD {g['min_revenue_usd_m']}m or missing)")
        if panel_row.get("critical_coverage", 0) < g["min_critical_coverage"]:
            reasons.append("too few critical financial facts available")
        n_missing = int(row[FEATURES].isna().sum(axis=1).iloc[0])
        if n_missing > g["max_missing_features"]:
            reasons.append(f"{n_missing} of {len(FEATURES)} model features unavailable")
        return reasons


@lru_cache
def get_model() -> Optional[StressModel]:
    try:
        return StressModel.load()
    except FileNotFoundError:
        return None
