# Baseline experiment `baselines_v1`
_Run 2026-11-04 17:33 UTC · panel sha256 `794ccc3c358c` · features_v1 · python 3.13.18 · sklearn 1.9.1 · xgboost 3.4.1_

Outcome is a **next-fiscal-year accounting-stress proxy**, not a probability of default. Hyperparameters and thresholds were chosen on validation; test was evaluated once.

## Splits (chronological by filing date, purged)
| split | rows | companies | positives | prevalence | features filed | latest label public |
|---|---|---|---|---|---|---|
| train | 1626 | 310 | 262 | 21.49% | 2009-11-25 → 2018-12-20 | 2018-12-20 |
| val | 497 | 229 | 84 | 21.59% | 2019-01-23 → 2020-12-07 | 2020-12-17 |
| test | 1307 | 304 | 322 | 29.65% | 2021-01-07 → 2025-11-21 | 2026-11-04 |

Rows excluded by purge or outside windows: 1005.

## Target: `label_next_fy`

| model | val PR-AUC | test PR-AUC (95% CI, company bootstrap) | test ROC-AUC (95% CI) | test Brier | test log loss | precision @val thr | recall @val thr |
|---|---|---|---|---|---|---|---|
| no_skill | 0.216 | 0.297 | 0.500 | 0.2152 | 0.6261 | 0.30 | 1.00 |
| rule_score | 0.692 | 0.716 (0.656–0.773) | 0.870 (0.843–0.896) | 0.1161 | 0.3780 | 0.76 | 0.70 |
| logistic | 0.810 | 0.813 (0.758–0.861) | 0.903 (0.879–0.925) | 0.1142 | 0.3610 | 0.75 | 0.71 |
| xgboost | 0.834 | 0.825 (0.772–0.870) | 0.906 (0.881–0.928) | 0.1089 | 0.3522 | 0.76 | 0.70 |

Test prevalence 29.65% (no-skill PR-AUC ≈ prevalence). Plots: `label_next_fy_pr.png`, `label_next_fy_calibration.png`.

**Logistic C** = 0.01; **XGBoost** depth 2, min_child_weight 5, 71 trees.

Top XGBoost drivers (gain): ebit_interest_cover, stress_conditions_t, ebitda_interest_cover, net_margin, cfo_margin__missing, cfo_to_assets, roa, fcf_margin.

Segment stability (xgboost, test PR-AUC): by year 2021: 0.800 (n=244), 2022: 0.818 (n=218), 2023: 0.769 (n=217), 2024: 0.867 (n=194), 2025: 0.883 (n=213); by size quintile Q1: 0.927, Q2: 0.905, Q3: 0.887, Q4: 0.701, Q5: 0.749.

## Target: `label_onset`

| model | val PR-AUC | test PR-AUC (95% CI, company bootstrap) | test ROC-AUC (95% CI) | test Brier | test log loss | precision @val thr | recall @val thr |
|---|---|---|---|---|---|---|---|
| no_skill | 0.061 | 0.100 | 0.500 | 0.0911 | 0.3309 | 0.10 | 1.00 |
| rule_score | 0.098 | 0.206 (0.144–0.289) | 0.676 (0.621–0.738) | 0.0820 | 0.2929 | 0.33 | 0.45 |
| logistic | 0.187 | 0.233 (0.165–0.339) | 0.755 (0.686–0.819) | 0.0943 | 0.3373 | 0.23 | 0.23 |
| xgboost | 0.314 | 0.346 (0.257–0.471) | 0.798 (0.736–0.858) | 0.0818 | 0.2826 | 0.40 | 0.40 |

Test prevalence 10.04% (no-skill PR-AUC ≈ prevalence). Plots: `label_onset_pr.png`, `label_onset_calibration.png`.

**Logistic C** = 10.0; **XGBoost** depth 3, min_child_weight 5, 16 trees.

Top XGBoost drivers (gain): stress_conditions_t, ebit_interest_cover, cfo_to_debt, roa, gross_leverage, implied_cost_of_debt, cfo_to_assets, revenue_growth.

Segment stability (xgboost, test PR-AUC): by year 2021: 0.290 (n=154), 2022: 0.527 (n=139), 2023: 0.437 (n=151), 2024: 0.309 (n=133), 2025: 0.207 (n=150); by size quintile Q1: 0.686, Q2: 0.619, Q3: 0.477, Q4: 0.357, Q5: 0.249.

## Reading these results honestly
- The rule score uses year-t stress conditions; stress is persistent, so it is a strong, cheap baseline. Any neural model in Week 4 must beat it, logistic and XGBoost on validation before claims are made.
- Probabilities are uncalibrated here; Week 4 fits a calibration layer on held-out data.
- Correlated rows of one company are handled by clustering the bootstrap on company.
