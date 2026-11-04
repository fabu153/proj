# Neural experiment `mlp_v1`
_Run 2026-11-04 18:09 UTC · panel sha256 `794ccc3c358c` · torch 2.15.0+cpu · paired with `baselines_v1` (identical rows and split)_

Architecture: 62 → 128 (ReLU, LayerNorm, dropout 0.25) → 64 (ReLU, dropout 0.20) → 32 (ReLU) → 1. AdamW, BCE-with-logits, early stopping on a grouped 15% holdout of training companies. 8 predefined configurations × 5 seeds; selection on mean validation PR-AUC; Platt calibration on validation. Test evaluated once.

## Target `label_next_fy`

Selected configuration: `lr=0.0003,wd=0.0001,pos_weight=none`.

| configuration | val PR-AUC mean | min–max over seeds |
|---|---|---|
| lr=0.0003,wd=0.0001,pos_weight=none | 0.782 | 0.771–0.794 |
| lr=0.0003,wd=0.01,pos_weight=none | 0.780 | 0.773–0.790 |
| lr=0.001,wd=0.01,pos_weight=none | 0.778 | 0.755–0.805 |
| lr=0.001,wd=0.0001,pos_weight=none | 0.778 | 0.756–0.804 |
| lr=0.0003,wd=0.0001,pos_weight=balanced | 0.774 | 0.764–0.788 |
| lr=0.0003,wd=0.01,pos_weight=balanced | 0.773 | 0.758–0.790 |
| lr=0.001,wd=0.01,pos_weight=balanced | 0.771 | 0.748–0.794 |
| lr=0.001,wd=0.0001,pos_weight=balanced | 0.765 | 0.745–0.795 |

| test metric | MLP ensemble (calibrated) | uncalibrated |
|---|---|---|
| PR-AUC | 0.805 (95% CI 0.752–0.853) | 0.805 |
| ROC-AUC | 0.904 | 0.904 |
| Brier | 0.1134 | 0.1134 |
| log loss | 0.3619 | 0.3620 |
| precision / recall at validation-chosen threshold | 0.73 / 0.71 | |

Single-seed test PR-AUC: mean 0.794, range 0.789–0.802.

**Paired comparison on identical test rows** (company-clustered bootstrap of the PR-AUC difference):

| vs | baseline test PR-AUC | MLP − baseline | 95% CI | share of resamples MLP better |
|---|---|---|---|---|
| xgboost | 0.825 | -0.020 | -0.044 to +0.006 | 6% |
| logistic | 0.813 | -0.008 | -0.024 to +0.010 | 18% |
| rule_score | 0.716 | +0.090 | +0.061 to +0.120 | 100% |

Top validation permutation importance (PR-AUC drop): stress_conditions_t (0.021), operating_margin (0.019), net_margin (0.012), ebitda_nonpositive (0.010), roa (0.007), cfo_to_assets (0.004), gross_leverage (0.002), cash_to_assets (0.002).

Plots: `label_next_fy_pr.png`, `label_next_fy_calibration.png`, `label_next_fy_mlp_only_calibration.png`.

## Target `label_onset`

Selected configuration: `lr=0.0003,wd=0.01,pos_weight=none`.

| configuration | val PR-AUC mean | min–max over seeds |
|---|---|---|
| lr=0.0003,wd=0.01,pos_weight=none | 0.222 | 0.201–0.239 |
| lr=0.0003,wd=0.0001,pos_weight=none | 0.221 | 0.202–0.235 |
| lr=0.001,wd=0.01,pos_weight=balanced | 0.217 | 0.206–0.227 |
| lr=0.001,wd=0.0001,pos_weight=none | 0.214 | 0.179–0.241 |
| lr=0.001,wd=0.01,pos_weight=none | 0.209 | 0.178–0.228 |
| lr=0.0003,wd=0.01,pos_weight=balanced | 0.201 | 0.153–0.238 |
| lr=0.0003,wd=0.0001,pos_weight=balanced | 0.201 | 0.153–0.238 |
| lr=0.001,wd=0.0001,pos_weight=balanced | 0.198 | 0.131–0.225 |

| test metric | MLP ensemble (calibrated) | uncalibrated |
|---|---|---|
| PR-AUC | 0.300 (95% CI 0.230–0.418) | 0.300 |
| ROC-AUC | 0.814 | 0.814 |
| Brier | 0.0817 | 0.0791 |
| log loss | 0.2763 | 0.2680 |
| precision / recall at validation-chosen threshold | 0.34 / 0.42 | |

Single-seed test PR-AUC: mean 0.296, range 0.277–0.320.

**Paired comparison on identical test rows** (company-clustered bootstrap of the PR-AUC difference):

| vs | baseline test PR-AUC | MLP − baseline | 95% CI | share of resamples MLP better |
|---|---|---|---|---|
| xgboost | 0.346 | -0.045 | -0.114 to +0.019 | 8% |
| logistic | 0.233 | +0.069 | -0.007 to +0.152 | 95% |
| rule_score | 0.206 | +0.105 | +0.051 to +0.168 | 100% |

Top validation permutation importance (PR-AUC drop): net_leverage (0.021), no_debt (0.017), current_ratio (0.016), d_debt_to_assets (0.015), gross_leverage (0.014), liabilities_to_assets (0.011), cash_to_current_liabilities (0.009), equity_to_assets (0.007).

Plots: `label_onset_pr.png`, `label_onset_calibration.png`, `label_onset_mlp_only_calibration.png`.
