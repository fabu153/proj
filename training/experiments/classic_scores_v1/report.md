# classic_scores_v1: Altman Z″ and Ohlson O against the network

**Question.** How do the two textbook bankruptcy scores, used exactly as published, rank next-year accounting
stress on the same held-out rows as the deployed network?

**Answer.** Both are clearly weaker. On all borrowers their PR-AUC is about 0.63, against about 0.81 for the network
on the same rows. The paired difference is −0.18, and its 95% interval lies well below zero. On new stress only
(borrowers healthy in the filing year) they score 0.18–0.20, against about 0.31.

## Method

- **Scores.** Both use their original coefficients, with no refitting, computed by the app's own code in
  `backend/app/finance/credit_extras.py`:
  - **Altman Z″ (1995).** The four-ratio version for non-manufacturers: 6.56 WC/TA + 3.26 RE/TA +
    6.72 EBIT/TA + 1.05 BE/TL, with operating income used as EBIT. A lower score means more risk.
  - **Ohlson O (1980), model 1.**
    - Total assets are in USD millions. The U.S. GDP implicit price deflator, rebased to 1968 = 100 (BEA via
      FRED, `backend/data/macro/gdp_deflator.json`), stands in for Ohlson's GNP price index.
    - Operating cash flow stands in for "funds provided by operations".
    - A higher score means more risk.
    - The units of total assets only shift O by a constant, so they do not affect the ranking metrics. They do
      affect the 1970s probability, which is why the app shows O's rank, not its probability.
- **Inputs.**
  - Everything comes from the frozen `panel_v1.csv`, except retained earnings.
  - Retained earnings come from SEC's companyconcept API (`RetainedEarningsAccumulatedDeficit`). The value used is
    the one from the first 10-K that reported the year, and only if that 10-K was filed by the row's as-of date.
    This is the panel's point-in-time rule; the code and a test check it.
  - Retained earnings are found for 88% of the panel rows (`training/data/classic_inputs_v1.csv`).
  - Prior-year net income (needed for O) follows the consecutive-year, already-public rule of the history
    experiments.
- **Rows.**
  - All borrowers: the same 1,086 held-out rows (2021–25) as the network.
  - New stress only: the canonical `label_onset` rows.
  - A score is computed only when every input is reported. Each comparison is made on the rows where the score
    exists, against the deployed network on **those same rows**.
- **Uncertainty.** Company-clustered bootstrap with 1,000 resamples, paired.
- **Status.** The test window had already been inspected before, so these results are exploratory.

## Results

| Population | Score | Rows (coverage) | PR-AUC (95% CI) | ROC-AUC | Network on same rows | Difference (95% CI) |
|---|---|---|---|---|---|---|
| All borrowers (base rate 30%) | Altman Z″ | 1,023 (94%) | 0.635 (0.543–0.711) | 0.776 | 0.818 | −0.183 (−0.260 to −0.117) |
| All borrowers | Ohlson O | 1,034 (95%) | 0.626 (0.541–0.714) | 0.780 | 0.808 | −0.182 (−0.248 to −0.120) |
| New stress only (base rate 10%) | Altman Z″ | 688 (95%) | 0.203 (0.138–0.318) | 0.686 | 0.313 | −0.110 (−0.216 to +0.002) |
| New stress only | Ohlson O | 698 (96%) | 0.182 (0.125–0.285) | 0.685 | 0.317 | −0.135 (−0.236 to −0.029) |

## Reading

- The textbook scores still carry real information: their ROC-AUC is about 0.78, well above chance. They are,
  however, far less sharp than the network or the XGBoost benchmark, both of which were trained on this label and
  population. They were built for bankruptcy in the 1960s–70s, not for this accounting-stress label.
- The comparison flatters the textbook scores slightly, if anything: rows they cannot score drop out of both columns.
- In the app they appear beside the neural screen as **references**, with peer percentiles. They never feed the
  network.

## Reproduce

```bash
SEC_USER_AGENT="Name email" python -m training.ml.classic_scores      # fetches retained earnings once (549 requests)
python -m training.ml.classic_scores --offline                        # re-evaluates from the saved inputs
pytest tests/integration/test_v16_extras.py tests/unit/test_credit_extras.py
```
