# onset_watchlist_v1: a watch-list threshold for currently healthy borrowers (research only)

**Question.** The deployed network catches only 6 of 73 new stress onsets at its single alert threshold. Would a
separate, lower threshold used only for borrowers that are healthy today catch materially more of them, and at
what cost in false alarms?

**Answer.** Yes, by a large margin. A threshold set on validation to flag about 10% of healthy borrowers catches
**33 of 73 onsets (45%) instead of 6 (8%)**, at a precision of 34% against a 10% base rate. The price is
64 false alarms instead of 8. **Recommendation:** treat this as the most promising onset improvement so far, but
**do not deploy it yet**. Check it first on fiscal-2026 outcomes, because the validation evidence is thin (18
onsets) and the test window has been inspected before. Nothing in the app changed.

## Setup

- **Model.** The deployed `stress_mlp_v1`, unchanged. Its scores were recomputed with the app's own numpy
  inference and reproduce the published test predictions exactly (largest difference below 1e-15).
- **Population.** The canonical onset cohort (`label_onset`): year-t status determinable and **not stressed**,
  and t+1 status determinable. Validation (filed 2019–20) has 295 rows, 18 onsets and 143 companies. Test (filed
  2021–25) has 727 rows, 73 onsets and 205 companies.
- **Thresholds.** The original threshold is 0.446, the validation maximum F1 on the whole population. For a 5%,
  10%, 15% or 20% budget, the threshold is the score that flags that share of the **validation** healthy cohort.
  It is chosen from validation scores alone, never from outcomes, and is applied unchanged to test.
- **Uncertainty.** A company-clustered bootstrap with 1,000 resamples. Changes against the original threshold
  are paired: the same resampled companies are used for both.
- **Status of the test window.** The 2021–25 test window was inspected in earlier experiments, so the test
  figures are exploratory.

## Results on the test window (727 healthy borrowers, 73 onsets)

| Threshold | Flagged (share) | Onsets caught | Missed | False alarms | Precision (95% CI) | Recall (95% CI) |
|---|---:|---:|---:|---:|---|---|
| Original 0.446 | 14 (2%) | 6 | 67 | 8 | 43% (17–73%) | 8% (3–15%) |
| 5% budget, 0.304 | 47 (6%) | 17 | 56 | 30 | 36% (22–55%) | 23% (14–33%) |
| **10% budget, 0.186** | **97 (13%)** | **33** | **40** | **64** | **34% (24–45%)** | **45% (34–57%)** |
| 15% budget, 0.129 | 134 (18%) | 40 | 33 | 94 | 30% (22–39%) | 55% (43–66%) |
| 20% budget, 0.101 | 157 (22%) | 45 | 28 | 112 | 29% (22–37%) | 62% (49–74%) |

Paired change against the original threshold, 95% intervals:

| Budget | Extra onsets caught | Extra false alarms | Recall gain |
|---|---|---|---|
| 5% | +5 to +18 | +11 to +34 | +7 to +24 points |
| 10% | +18 to +38 | +37 to +75 | +26 to +49 points |
| 15% | +23 to +46 | +61 to +112 | +36 to +58 points |
| 20% | +28 to +52 | +78 to +131 | +42 to +66 points |

Every budget catches significantly more onsets than the original threshold. None of the intervals includes zero.

### On validation (where the thresholds were set)

| Threshold | Flagged | Caught (of 18) | False alarms | Precision | Recall |
|---|---:|---:|---:|---:|---:|
| Original | 6 | 3 | 3 | 50% | 17% |
| 5% | 15 | 4 | 11 | 27% | 22% |
| 10% | 30 | 5 | 25 | 17% | 28% |
| 15% | 45 | 6 | 39 | 13% | 33% |
| 20% | 59 | 9 | 50 | 15% | 50% |

## Reading the results

1. **The deployed network's onset weakness is mostly a threshold problem.** Its ranking of healthy borrowers is
   about as good as the specialist onset models (gru_onset_v1). The single threshold is set for a population where
   most stress is persistent, so it sits too high for healthy borrowers.
2. **Ten percent looks like the balanced choice.** It catches nearly half of the onsets, and about 1 in 3 flags is
   a real onset, 3.4 times the base rate. Going from 10% to 20% adds 12 catches for 48 more false alarms.
3. **The budgets were overshot on test.** Scores ran higher in 2021–25: the 10% threshold flagged 13% of test
   borrowers. A monitoring rule would need its flag rate tracked and the threshold re-set periodically.
4. **Validation looked weaker than test.** At 10%, validation precision was 17% (5 of 30); the validation years
   (2019–20) had a lower onset rate, 6% against 10%. With 18 validation onsets every validation figure is very
   uncertain. This is the main reason not to deploy yet.

## Recommendation

- **Do not deploy now.** If adopted later, show the result as a *watch-list flag* for currently healthy
  borrowers ("monitor more closely"), not as a second probability. Keep the probability and the existing threshold
  unchanged.
- **Confirm on fiscal-2026 outcomes** with the 10% threshold (0.186) fixed **in advance**, as recorded in
  `results.json`. That would be the first untouched test.
- Before use, define how a flagged borrower is handled (for example a closer review) and monitor the flag rate.

## Reproduce

```bash
python -m training.ml.onset_watchlist          # seconds; writes only this folder
pytest tests/integration/test_research_onset_consistency.py
```

The files here are `results.json` (all counts, thresholds and intervals), `predictions.csv` (validation and test
onset rows with the deployed score) and `config_snapshot.yaml` (the predeclared rule).
