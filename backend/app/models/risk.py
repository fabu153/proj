"""Risk-scoring service: company filings -> gated, calibrated, explained stress screen."""
from __future__ import annotations

import json
from typing import Optional

import pandas as pd

from ..features.feature_set import build_features
from ..features.panel import panel_rows
from .inference import ARTIFACT_DIR, get_model

CRITICAL_INPUTS = ["revenue", "operating_income", "interest_expense", "depreciation_amortization",
                   "operating_cash_flow", "long_term_debt", "total_assets"]
NAMES = {"revenue": "revenue", "operating_income": "operating income", "interest_expense": "interest expense",
         "depreciation_amortization": "depreciation and amortization", "operating_cash_flow": "operating cash flow",
         "long_term_debt": "long-term debt", "total_assets": "total assets"}

DISCLAIMER = ("Indicative next-fiscal-year accounting-stress screen from a trained neural network. "
              "Not a probability of default, not a rating, not a lending decision. Analyst review required.")


def _period(meta: dict, as_of: Optional[str]) -> str:
    w = meta["data_windows"]
    if as_of is None:
        return "unknown"
    if as_of <= w["train_features_filed"][1]:
        return "training period"
    if as_of <= w["val_features_filed"][1]:
        return "validation period"
    if as_of <= w["test_features_filed"][1]:
        return "test period"
    return "out-of-time (after the evaluation window)"


def _training_ciks() -> set[str]:
    p = ARTIFACT_DIR / "training_ciks.json"
    return set(json.loads(p.read_text())) if p.exists() else set()


def score(companyfacts: dict, fiscal_year_end: str, as_of: Optional[str] = None) -> dict:
    model = get_model()
    if model is None:
        return {"status": "model_unavailable", "message": "No trained model artifact deployed.",
                "disclaimer": DISCLAIMER}
    rows = panel_rows(companyfacts, as_of=as_of)
    panel = pd.DataFrame(rows)
    feats = build_features(panel)
    hit = feats[feats["fiscal_year_end"] == fiscal_year_end]
    if hit.empty:
        return {"status": "withheld", "gate_reasons": ["fiscal year not available"], "disclaimer": DISCLAIMER}
    idx = hit.index[0]
    row, prow = feats.loc[[idx]], panel.loc[idx].to_dict()
    meta = model.meta
    base = {"model": {"name": meta["model"], "target": meta["target"], "label_version": meta["label_version"],
                      "feature_version": meta["feature_version"], "trained_at": meta["trained_at"],
                      "test_pr_auc": meta["test_metrics_calibrated"]["pr_auc"],
                      "test_pr_auc_ci95": meta["test_bootstrap"]["pr_auc_ci95"],
                      "xgboost_benchmark_test_pr_auc": meta["xgboost_test_pr_auc"]},
            "features_as_of": prow.get("as_of_date"), "sample_period": _period(meta, prow.get("as_of_date")),
            "in_training_universe": prow["cik"] in _training_ciks(), "disclaimer": DISCLAIMER}
    reasons = model.gate(row, prow)
    ccy = companyfacts.get("currency", "USD")
    if ccy != "USD":
        # FIN-03: trained on USD-million SEC data with a USD 50m revenue gate; a currency code is not a normalization
        reasons.insert(0, f"figures are in {ccy}: the network was trained on U.S. dollar data with dollar-based size "
                          "inputs, and no validated currency conversion of its inputs exists, so it is not applied. "
                          "Credit ratios and loan scenarios are unaffected")
    if reasons:
        return {"status": "withheld", "gate_reasons": reasons, **base}
    p = float(model.predict_proba(row)[0])
    n_missing = int(row.iloc[0][model.pre.features].isna().sum())
    unavailable = [NAMES[k] for k in CRITICAL_INPUTS if prow.get(f"v_{k}") is None or pd.isna(prow.get(f"v_{k}"))]
    return {"status": "scored", "probability": p, "band": model.band(p),
            "label": "Estimated chance of next-fiscal-year accounting stress",
            "drivers": model.drivers(row), "features_missing": n_missing,
            "critical_inputs_unavailable": unavailable, **base}
