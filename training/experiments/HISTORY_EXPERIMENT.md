# Experiment: using two prior years of accounts (not deployed)

**Question.** The deployed network (`stress_mlp_v1`) reads one annual report: year *t* plus five one-year changes.
Does it help to look back two more years?

**Protocol.** The same as `mlp_v1` in every respect except the inputs:
- the same 4,435 company-years and row filters;
- the same chronological split and purge;
- train-only preprocessing;
- 8 configurations × 5 seeds, chosen on 2019–20 validation PR-AUC;
- Platt calibration on validation;
- one test on the same 1,086 held-out rows (filed 2021–25), paired row-for-row with the frozen v1 predictions.

A prior year is used only if it is the consecutive fiscal year of the same company and was already public when
year *t* was filed. A control run of the same pipeline with v1 inputs reproduces the deployed model exactly
(paired difference 0.000; `mlp_history_v1/control_v1_inputs/`).

| Model (test, n = 1,086) | Inputs | PR-AUC | ROC-AUC | Brier | Flags at validation threshold | New-stress onsets caught (of 96) |
|---|---|---|---|---|---|---|
| **v1, deployed** — MLP | year *t* + 1-year changes (62) | 0.805 | 0.904 | 0.113 | 229 correct, 84 false | 15 |
| **A** — same MLP + history inputs | + t-1, t-2 of 8 ratios, 4 multi-year summaries (102) | 0.804 | 0.905 | 0.111 | 227 correct, 72 false | 19 |
| **B** — GRU over t-2, t-1, t | 3 × (62 + presence flag) | **0.821** | 0.904 | 0.112 | 220 correct, 66 false | 17 |
| XGBoost benchmark (v1 inputs) | year *t* | 0.825 | 0.906 | 0.109 | — | — |

**Paired differences against v1** (resampling whole companies, 1,000 draws):
- A − v1: PR-AUC −0.001 (95% interval −0.022 to +0.019).
- B − v1: PR-AUC +0.015 (−0.002 to +0.034); B is better in 96% of resamples.
- On new-stress onsets only, PR-AUC: v1 0.395, A 0.406, B 0.419; neither difference is significant.

**Reading.**
- History in hand-made lag inputs (A) changes almost nothing.
- Letting a recurrent network read three years (B) raises PR-AUC to within 0.004 of XGBoost and cuts false alarms
  by a fifth.
- None of the models becomes an early-warning tool: all catch fewer than 1 in 5 new onsets, because new stress
  usually comes from events one annual report does not show.

**Caveats before adopting B.**
1. The test window has now been used to compare three models. Picking the best of them on that window
   flatters its score, so B's +0.015 is an upper estimate. Confirming it needs data none of the models was chosen
   on, such as next year's filings once their outcomes are known.
2. The gain is not statistically significant at 95%.
3. Uploaded reports carry only two years, so B would often run with one year missing. Only 53 of the 1,086 test
   rows had fewer than three years, which is too few to judge that case.

Re-run: `python -m training.ml.experiment_history [--control]` and `python -m training.ml.experiment_sequence`
(about 1–2 minutes each, CPU). Results: `mlp_history_v1/results.json` and `gru_history_v1/results.json`.

## Follow-up: onset-specific GRU (gru_onset_v1)

A GRU trained only on currently healthy companies did **not** improve onset detection: test PR-AUC 0.254, against
0.319 for the deployed network on the same 727 onset rows. See `gru_onset_v1/report.md`.
