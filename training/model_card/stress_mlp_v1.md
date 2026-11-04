# Model card — `stress_mlp_v1`

**Intended use.** Screening indicator of next-fiscal-year accounting stress for U.S. non-financial issuers with revenue >= USD 50m. Decision support only; analyst review required.
**Not for:** probability of default, credit rating, regulatory capital, automatic loan decisions.

## Model
- Feedforward network, PyTorch: Linear(62,128) -> ReLU -> LayerNorm -> Dropout(0.25); Linear(128,64) -> ReLU -> Dropout(0.20);
  Linear(64,32) -> ReLU; Linear(32,1) logit; sigmoid at inference.
- Inputs: 31 ratio/trend features (`features_v1`) + missingness indicators;
  train-only winsorization (1/99 pct), median imputation and standardization.
- Selected configuration `lr=0.0003,wd=0.0001,pos_weight=none` from 8 predefined options × 5 seeds (mean validation PR-AUC).
- Deployed score = mean logit of 5 seeds, Platt-calibrated on validation (a = 0.910,
  b = -0.171). Served in numpy; parity with PyTorch verified to 1e-6.

## Data
- SEC XBRL companyfacts, 600-company survivorship-aware universe; label `stress_v1` (next fiscal year).
- Population: revenue ≥ USD 50m, scorable, ≥ 4 of 7 critical facts.
- Splits by filing date with purge — train 1626 rows (2009-11-25 → 2018-12-20),
  validation 497, test 1307 (2021-01-07 → 2025-11-21).

## Results on the frozen test window (evaluated once)
| model | test PR-AUC | 95% CI | ROC-AUC | Brier |
|---|---|---|---|---|
| MLP ensemble (deployed) | 0.805 | 0.752–0.853 | 0.904 | 0.1134 |
| XGBoost | 0.825 | 0.772–0.870 | 0.906 | 0.1089 |
| Logistic regression | 0.813 | 0.758–0.861 | 0.903 | 0.1142 |
| Rule score (year-t conditions) | 0.716 | 0.656–0.773 | 0.870 | 0.1161 |
| No-skill base rate | 0.297 |  | 0.500 | 0.2152 |

Paired MLP − XGBoost PR-AUC: -0.020
(95% CI -0.044 to +0.006).
At the validation-chosen threshold: precision 0.73,
recall 0.71, flag rate 29%.

## Serving safeguards
- Score withheld when: hard data checks fail, revenue < USD 50m, < 4 of 7 critical facts, or > 12 of 31 features missing.
- Bands (display only): low < 15%, elevated 15–40%, high ≥ 40%.
- Every response states the sample period of the features and whether the company contributed training rows.

## Limitations
- Target is an accounting-stress proxy (2 of 3: EBIT cover < 1.5x, debt/EBITDA > 5x, CFO < 0), not default.
- The MLP does not beat XGBoost on test (paired difference CI includes zero, point estimate lower); it is deployed to meet the deep-learning objective, with XGBoost reported as the benchmark.
- Stress is persistent: current-year stress conditions are the strongest single driver.
- Test prevalence (29.7%) exceeds training prevalence (21.5%); calibration was fitted on 2019-20 validation data and may understate risk in later regimes.
- Drivers are occlusion attributions (association), not causal effects.
- U.S. non-financial SEC filers with revenue >= USD 50m only; not valid for other populations.
- EBITDA is unadjusted (operating income + D&A); interest may be cash interest where P&L tag absent.
