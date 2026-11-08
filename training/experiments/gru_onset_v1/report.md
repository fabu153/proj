# gru_onset_v1: a three-year GRU trained for stress onset (research only, not deployed)

**Result in one line.** The onset GRU does not beat the existing onset models. On the same 727 test rows it ranks
new stress onsets worse than the onset MLP, the onset XGBoost and the deployed general network. Deployment is
not recommended.

> **Test-set status.** The 2021–2025 test window has already been inspected in baselines_v1, mlp_v1,
> mlp_history_v1 and gru_history_v1. No later outcomes exist yet, so this is an exploratory comparison on
> data that has been seen before, not an independent confirmation. Architecture and hyperparameters were fixed in
> advance (`configs/experiment_gru_onset_v1.yaml`) and chosen on validation data only. There was one test run and
> no further tuning.

## 1. Hypothesis

The deployed network is trained on every borrower, and most of its stressed cases are companies that were already
stressed. A network trained only on companies that are currently *not* stressed, and that sees how their
accounts moved over three years, might be better at spotting a **new** deterioration.

## 2. Target and sample

The onset target is the canonical `label_onset` from `backend/app/labels/stress_label.py`:

- the company's year-t status is **determinable and not stressed**;
- the target is whether it is stressed in t+1, and that status must also be determinable.

"Stressed" keeps the established definition: at least two of EBIT/interest < 1.5x, gross debt/EBITDA > 5x (or
positive debt with EBITDA ≤ 0), and negative operating cash flow. This is an accounting-stress proxy, not a
default. Rows whose year-t status cannot be determined are **excluded, not treated as healthy**, and rows already
stressed are excluded.

The rows, filters, chronological split and label-publication purge are exactly those of `baselines_v1`:

| Split (by filing date of year t) | Rows | Onsets | Prevalence | Companies |
|---|---:|---:|---:|---:|
| Train (before 2019) | 886 | 65 | 7.3% | 210 |
| Validation (2019–20) | 295 | 18 | 6.1% | 143 |
| Test (2021–25) | 727 | 73 | 10.0% | 205 |

These are the same 727 test rows as the existing onset baselines and the onset MLP. All comparisons are paired row
for row, and the code asserts this.

**Why this differs from "15 of 96 onsets".** The figure quoted for the deployed model (15 of 96) comes from
`gru_history_v1`. That run defined "not stressed at t" as *fewer than two conditions, with unknown conditions
counted as not met*, which counts some undeterminable years as healthy (787 rows, 96 onsets). The canonical
cohort here is stricter (727 rows, 73 onsets).

## 3. Inputs and architecture

- **Steps.** One step per available year in t−2, t−1, t. Each step holds the same 31 standardized measures and
  31 missing-value flags as the deployed network, plus "years before t / 2".
- **Prior years.** A prior year is used only if it is the same company's consecutive fiscal year and was already
  public when year t was filed. This is the point-in-time rule of `experiment_history.py`.
- **Missing years are skipped, not zero-filled.** Sequences have 1–3 steps and are packed
  (`pack_padded_sequence`). The GRU never reads a placeholder year, and a test shows the output is unchanged
  whatever is in the padding. This differs from `gru_history_v1`, which fed zeros plus a presence flag.
- **Network.** GRU(63→64), then LayerNorm, Dropout(0.25), Linear(64,32), ReLU, Linear(32,1). This is the same
  architecture as `gru_history_v1`; no architecture search was run.
- **Preprocessing.** Winsorizing, median imputation and standardization are fitted on the **training onset rows
  only**, then applied to every history year.
- **Training.** The `mlp_v1` protocol: 8 predeclared configurations × 5 seeds, early stopping on a 15% holdout of
  training *companies*, selection on mean validation PR-AUC, mean logit of the 5 seeds, Platt calibration on
  validation, and an alert threshold at the validation maximum F1.
- **Selected configuration.** lr = 0.0003, wd = 0.01, balanced class weights. Validation PR-AUC was 0.193, with
  seeds ranging 0.138–0.258.

**Onset MLP reproduced exactly.** `mlp_v1` did not save per-row onset predictions. Its onset network was retrained
with the identical code and seeds and reproduced the published test PR-AUC exactly (0.3001), so the paired
comparison uses the real model.

## 4. Results on the test window (727 rows, 73 onsets)

| Model | PR-AUC (95% CI, by company) | ROC-AUC | Brier | Log loss |
|---|---|---:|---:|---:|
| No skill (base rate) | 0.100 | 0.500 | 0.0911 | 0.331 |
| Rule score (conditions in t) | 0.206 (0.144–0.289) | 0.676 | 0.0820 | 0.293 |
| Onset logistic | 0.233 (0.165–0.339) | 0.755 | 0.0943 | 0.337 |
| **Onset GRU (this experiment)** | **0.254 (0.177–0.355)** | 0.733 | 0.0864 | 0.304 |
| Onset MLP | 0.300 (0.230–0.418) | 0.814 | 0.0817 | 0.276 |
| General 3-year GRU (gru_history_v1) | 0.317 (0.228–0.439) | 0.790 | 0.0811 | 0.285 |
| **Deployed general network (stress_mlp_v1)** | 0.319 (0.233–0.443) | 0.803 | 0.0802 | 0.275 |
| Onset XGBoost | **0.346** (0.257–0.471) | 0.798 | 0.0818 | 0.283 |

### Paired differences: onset GRU minus each model (company-clustered bootstrap, 1,000 resamples)

| Compared with | PR-AUC difference (95% CI) | Share of resamples where GRU is better | ROC-AUC difference (95% CI) |
|---|---|---:|---|
| Onset XGBoost | −0.092 (−0.186 to −0.018) | 1% | −0.065 (−0.106 to −0.025) |
| Deployed general network | −0.065 (−0.155 to +0.004) | 4% | −0.070 (−0.110 to −0.031) |
| General 3-year GRU | −0.063 (−0.142 to +0.006) | 4% | −0.057 (−0.086 to −0.029) |
| Onset MLP | −0.046 (−0.122 to +0.009) | 6% | −0.081 (−0.124 to −0.040) |
| Onset logistic | +0.022 (−0.053 to +0.087) | 69% | −0.022 (−0.065 to +0.020) |
| Rule score | +0.049 (−0.024 to +0.125) | 91% | +0.058 (−0.001 to +0.123) |

### At the threshold chosen on validation

| Model | Flagged | Onsets caught | False alarms | Missed | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| Onset GRU | 118 | 28 | 90 | 45 | 24% | 38% |
| Onset MLP | 90 | 31 | 59 | 42 | 34% | 42% |
| Onset XGBoost | 72 | 29 | 43 | 44 | 40% | 40% |
| Onset logistic | 73 | 17 | 56 | 56 | 23% | 23% |
| Rule score | 99 | 33 | 66 | 40 | 33% | 45% |
| Deployed network at its own threshold (0.446) | 14 | 6 | 8 | 67 | 43% | 8% |

### At equal alert budgets (each model flags its own top-scored rows)

| Budget (rows flagged) | Onset GRU | Onset MLP | Onset XGBoost | Deployed network | General GRU | Onset logistic |
|---|---|---|---|---|---|---|
| 5% (36) | 11 caught / 25 false | 15 / 21 | 16 / 20 | 13 / 23 | 15 / 21 | 8 / 28 |
| 10% (73) | 20 / 53 | 27 / 46 | 30 / 43 | 26 / 47 | 23 / 50 | 17 / 56 |
| 15% (109) | 28 / 81 | 37 / 72 | 36 / 73 | 34 / 75 | 33 / 76 | 29 / 80 |
| 20% (145) | 28 / 117 | 42 / 103 | 43 / 102 | 41 / 104 | 41 / 104 | 39 / 106 |

### Calibration (test, five equal-size bins)

The onset GRU's probabilities are too low in the upper bins: it predicts 8% where 18% occur, and 14% where 19%
occur. The deployed network is closer at the top (27% predicted, 28% observed). Full tables are in
`results.json` → `calibration_test`.

### By years of history available

| History | Test rows | Onsets | Note |
|---|---:|---:|---|
| 3 years | 706 | 69 | GRU 0.254, onset MLP 0.287, onset XGBoost 0.332, deployed 0.315 |
| 2 years | 13 | 4 | Too few for any conclusion |
| 1 year | 8 | 0 | No onsets, so no PR-AUC |

Almost every test row already has three years of history. The handling of missing years therefore barely affects
the result, and its value cannot be judged from this test window.

## 5. Interpretation

1. **The onset-only network loses on ranking.** On PR-AUC it is below the onset XGBoost (the gap's confidence
   interval excludes zero) and below the onset MLP and both general networks (the intervals just touch zero, and
   the GRU is better in only 4–6% of resamples). On ROC-AUC it is worse than all four, with intervals
   excluding zero. It beats only the logistic and rule baselines, and not significantly.
2. **The likely cause is sample size, not the idea.** Restricting training to healthy companies leaves
   **886 rows with 65 onsets**. A recurrent network has more parameters than an MLP, and validation has only 18
   onsets to choose between configurations. The seeds' test PR-AUCs range from 0.22 to 0.30, so the model is unstable.
3. **The deployed network already ranks onsets about as well as the specialists.** On this cohort it scores
   0.319 PR-AUC, between the onset MLP (0.300) and the onset XGBoost (0.346). At a 10% review budget it catches 26
   of 73 onsets, against 27 and 30. Its weak onset recall (6 of 73 at its 0.446 threshold) comes mostly from **where
   the alert threshold sits**: one threshold serves both already-stressed and healthy borrowers, and it is set for
   the mixed population.

## 6. Does this justify more research? Should it be deployed?

**Deployment: no.** The model is worse than models that already exist, its calibration is weaker, and its seeds
disagree.

**More research on this architecture: not now.** Repeating it with more configurations would be a search for a
better number on a test window that has already been seen. The real constraint is data (65 training onsets).
Research becomes worthwhile again when either of these happens:

- the panel grows, e.g. a wider universe or quarterly filings (10-Q), giving several times as many onsets; or
- outcomes for fiscal 2026 and later are published, giving a genuinely untouched test window.

**Cheaper ideas worth testing first** (not done here; each needs its own predeclared protocol):

- **A separate watch-list threshold** for currently healthy borrowers on the existing deployed network. At a 10%
  budget it would catch about a third of onsets instead of 8%. The threshold would have to be fixed on
  validation (only 18 onsets), so it should first be checked on the 2026 outcomes.
- **Onset XGBoost as a second-opinion indicator.** It is the strongest onset ranker here, but its 95% interval
  overlaps the deployed network's.

## 7. Pros and cons of an eventual onset model in the app

| | |
|---|---|
| **For** | It would answer the question a lender cares most about for a healthy borrower: *is this one starting to slip?* |
| | Three-year inputs match how analysts read trends, and the missing-year handling here is explicit and tested. |
| | The experiment pipeline is reproducible and paired, so a future version could be judged quickly on new outcomes. |
| **Against** | On current data it is **less accurate** than the network already deployed, on this very task. |
| | A second score would confuse users. Two probabilities for "stress next year" on one screen need careful explanation and gating. |
| | 65 training onsets cannot support a stable neural model: results move a lot between seeds. |
| | Any app change means new artifacts, a new manifest, Model X-Ray and replay updates, and re-validation. That costs a great deal for no measured gain. |
| | The test window has already been inspected, so nothing here can be called a clean confirmation. |

## 8. Reproduce

```bash
python -m training.ml.experiment_onset_gru      # about 3 minutes on 4 CPU threads; writes only this folder
pytest tests/integration/test_research_gru_onset.py
```

- **Inputs.** `training/data/panel_v1.csv` (SHA-256 in `results.json`), `configs/experiment_gru_onset_v1.yaml`
  (copied here as `config_snapshot.yaml`), `configs/experiment_baselines_v1.yaml` and
  `configs/experiment_mlp_v1.yaml`. Seeds are fixed, and the onset MLP must reproduce 0.3001 or the run is wrong. A second run on 2026-11-08
  produced a byte-identical `test_predictions.csv`.
- **Files.** `results.json` (all metrics), `test_predictions.csv` (one row per test observation, every model's
  probability and the years of history), `config_snapshot.yaml` and this report.
- **Not touched.** `backend/models/`, the release manifest, calibration artifacts, Model X-Ray and the historical
  replay.
