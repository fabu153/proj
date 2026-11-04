"""Bundle evaluation exhibits into the deployed artifact (served by GET /model) and write the model card.

    python -m training.ml.export_xray
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from backend.app.models.inference import ARTIFACT_DIR
from training.ml.run_baselines import load_dataset
from training.ml.splits import SplitSpec, assign_splits


def _ci(ci) -> str:
    return "" if not ci else f"{ci[0]:.3f}–{ci[1]:.3f}"


def main():
    mlp =json.loads(Path("training/experiments/mlp_v1/results.json").read_text())["results"]["label_next_fy"]
    base = json.loads(Path("training/experiments/baselines_v1/results.json").read_text())["results"]["label_next_fy"]
    audit = json.loads(Path("training/experiments/baselines_v1/split_audit.json").read_text())
    meta = json.loads((ARTIFACT_DIR / "metadata.json").read_text())

    # which companies contributed TRAINING rows (to flag in-sample scores in the UI)
    cfg = yaml.safe_load(Path("configs/experiment_baselines_v1.yaml").read_text())
    df = load_dataset(cfg)
    split = assign_splits(df, SplitSpec(**cfg["split"]))
    train_ciks = sorted(df.loc[(split == "train") & df["label_next_fy"].notna(), "cik"].unique())
    (ARTIFACT_DIR / "training_ciks.json").write_text(json.dumps(train_ciks))

    leaderboard = [{"model": "MLP ensemble (deployed)", "test_pr_auc": mlp["ensemble"]["test_calibrated"]["pr_auc"],
                    "ci95": mlp["ensemble"]["test_bootstrap"]["pr_auc_ci95"],
                    "test_roc_auc": mlp["ensemble"]["test_calibrated"]["roc_auc"],
                    "test_brier": mlp["ensemble"]["test_calibrated"]["brier"]}]
    for name, label in (("xgboost", "XGBoost"), ("logistic", "Logistic regression"),
                        ("rule_score", "Rule score (year-t conditions)"), ("no_skill", "No-skill base rate")):
        t = base[name]["test"]
        leaderboard.append({"model": label, "test_pr_auc": t["pr_auc"],
                            "ci95": base[name].get("test_bootstrap", {}).get("pr_auc_ci95"),
                            "test_roc_auc": t["roc_auc"], "test_brier": t["brier"]})
    xray = {"leaderboard": leaderboard, "paired_vs_baselines": mlp["paired_vs_baselines"],
            "calibration_test": mlp["calibration_table_test"], "search": mlp["search"],
            "selected_config": mlp["selected_config"], "per_seed_test_pr_auc": mlp["per_seed_test_pr_auc"],
            "permutation_importance_val": mlp["permutation_importance_val"],
            "threshold_test": mlp["ensemble"]["test_at_val_threshold"], "splits": audit,
            "limitations": [
                "Target is an accounting-stress proxy (2 of 3: EBIT cover < 1.5x, debt/EBITDA > 5x, CFO < 0), "
                "not default.",
                "The MLP does not beat XGBoost on test (paired difference CI includes zero, point estimate lower); "
                "it is deployed to meet the deep-learning objective, with XGBoost reported as the benchmark.",
                "Stress is persistent: current-year stress conditions are the strongest single driver.",
                "Test prevalence (29.7%) exceeds training prevalence (21.5%); calibration was fitted on 2019-20 "
                "validation data and may understate risk in later regimes.",
                "Drivers are occlusion attributions (association), not causal effects.",
                "U.S. non-financial SEC filers with revenue >= USD 50m only; not valid for other populations.",
                "EBITDA is unadjusted (operating income + D&A); interest may be cash interest where P&L tag absent."]}
    (ARTIFACT_DIR / "xray.json").write_text(json.dumps(xray, indent=1))

    e = mlp["ensemble"]
    pc = mlp["paired_vs_baselines"]
    card = f"""# Model card — `stress_mlp_v1`

**Intended use.** {meta['intended_use']}
**Not for:** {', '.join(meta['not_for'])}.

## Model
- Feedforward network, PyTorch: {meta['architecture']['block1']}; {meta['architecture']['block2']};
  {meta['architecture']['block3']}; {meta['architecture']['output']}.
- Inputs: {len(meta['features'])} ratio/trend features (`{meta['feature_version']}`) + missingness indicators;
  train-only winsorization (1/99 pct), median imputation and standardization.
- Selected configuration `{mlp['selected_config']}` from 8 predefined options × 5 seeds (mean validation PR-AUC).
- Deployed score = mean logit of 5 seeds, Platt-calibrated on validation (a = {json.loads((ARTIFACT_DIR/'calibrator.json').read_text())['a']:.3f},
  b = {json.loads((ARTIFACT_DIR/'calibrator.json').read_text())['b']:.3f}). Served in numpy; parity with PyTorch verified to 1e-6.

## Data
- SEC XBRL companyfacts, 600-company survivorship-aware universe; label `{meta['label_version']}` (next fiscal year).
- Population: revenue ≥ USD 50m, scorable, ≥ 4 of 7 critical facts.
- Splits by filing date with purge — train {audit['train']['rows']} rows ({audit['train']['as_of_min']} → {audit['train']['as_of_max']}),
  validation {audit['val']['rows']}, test {audit['test']['rows']} ({audit['test']['as_of_min']} → {audit['test']['as_of_max']}).

## Results on the frozen test window (evaluated once)
| model | test PR-AUC | 95% CI | ROC-AUC | Brier |
|---|---|---|---|---|
""" + "\n".join(f"| {r['model']} | {r['test_pr_auc']:.3f} | {_ci(r['ci95'])} | "
                f"{r['test_roc_auc']:.3f} | {r['test_brier']:.4f} |" for r in leaderboard) + f"""

Paired MLP − XGBoost PR-AUC: {pc['mlp_minus_xgboost']['mean_diff']:+.3f}
(95% CI {pc['mlp_minus_xgboost']['ci95'][0]:+.3f} to {pc['mlp_minus_xgboost']['ci95'][1]:+.3f}).
At the validation-chosen threshold: precision {e['test_at_val_threshold']['precision']:.2f},
recall {e['test_at_val_threshold']['recall_sensitivity']:.2f}, flag rate {e['test_at_val_threshold']['flag_rate']:.0%}.

## Serving safeguards
- Score withheld when: hard data checks fail, revenue < USD 50m, < 4 of 7 critical facts, or > 12 of 31 features missing.
- Bands (display only): low < 15%, elevated 15–40%, high ≥ 40%.
- Every response states the sample period of the features and whether the company contributed training rows.

## Limitations
""" + "\n".join(f"- {x}" for x in xray["limitations"]) + "\n"
    Path("training/model_card").mkdir(exist_ok=True)
    Path("training/model_card/stress_mlp_v1.md").write_text(card)
    print("wrote xray.json, training_ciks.json, model card;", len(train_ciks), "training companies")


if __name__ == "__main__":
    main()
