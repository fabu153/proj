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

## Error analysis on the frozen test window (added v1.2, no retraining)

Per-row MLP test predictions were not written at training time. They were recovered by re-running the frozen
artifact on the frozen test rows (`python -m training.ml.export_replay`). The re-run reproduces the recorded
evaluation exactly (PR-AUC and ROC-AUC to 1e-12, Brier to 1e-8, and the confusion matrix at the validation
threshold count for count), and it is saved as `training/experiments/mlp_v1/test_predictions_label_next_fy.csv`.

| At the validation-chosen threshold (0.446) | Stressed next year | Not stressed |
|---|---|---|
| Flagged | 229 correct warnings | 84 false alarms |
| Not flagged | 93 missed | 680 correct all-clears |

| Screening band | Company-years | Mean prediction | Observed stress |
|---|---|---|---|
| low (0%–15%) | 634 | 4.0% | 6.6% |
| elevated (15%–40%) | 120 | 26.0% | 34.2% |
| high (40%–100%) | 332 | 70.1% | 72.0% |

**Persistence versus onset.** The 1,086 test rows split by filing-year status:

| Filing-year status | Rows | Stressed next year | Caught at the 0.446 threshold | False alarms |
|---|---:|---:|---:|---:|
| Already stressed (2+ conditions met) | 299 | 226 | 214 | 66 |
| Confirmed not stressed (canonical onset population, `label_onset`) | 727 | 73 | 6 | 8 |
| Status could not be determined (one condition met, others unreported) | 60 | 23 | 9 | 10 |

So it caught 214 of 226 persisting cases but only **6 of 73 new onsets** from confirmed-healthy accounts. Earlier
versions of this card said "15 of 96": that figure also counted the 60 undeterminable company-years as healthy
(96 = 73 + 23; 15 = 6 + 9). The frozen evaluation files are unchanged; only the population label was corrected
(v1.5). 66 of the 84 false alarms were companies already stressed that recovered. The network is mainly a persistence detector, so it should not be presented as an early
warning of new stress. Its *ranking* of healthy borrowers is about as good as specialist onset models
(PR-AUC 0.319 versus 0.300–0.346); the single threshold is the bottleneck. A separate watch-list threshold is under
research and not deployed (`training/experiments/onset_watchlist_v1/report.md`).

The Historical Model Replay (`/replay`) shows held-out cases selected by a fixed rule
(`backend/data/replay/replay_v1.json`, `selection_rule`).

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
