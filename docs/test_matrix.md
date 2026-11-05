# Test matrix (Blueprint p.22)

_Generated 2026-11-05 07:44 UTC by `scripts/test_matrix.py`: 232 passed, 0 failed, 0 skipped (browser tests run only with `E2E_BASE_URL`)._

| ID | Check | Pass condition | Tests | Result |
|---|---|---|---|---|
| F01 | EBITDA / debt / coverage math | Matches golden fixture | 3 | ✅ pass |
| F02 | Negative EBITDA / zero interest | No misleading ratios or crash | 4 | ✅ pass |
| F03 | Refinancing versus capex use | Correct net-debt effects | 10 | ✅ pass |
| F04 | EUR loan against USD statements | Explicit FX or blocked | 3 | ✅ pass |
| D01 | Annual vs quarterly classification | No quarter as annual | 1 | ✅ pass |
| D02 | Units and sign conventions | Scaling detected | 4 | ✅ pass |
| D03 | PDF extraction uncertainty | Low confidence requires review | 4 | ✅ pass |
| M01 | No future labels in model input | As-of audit passes | 4 | ✅ pass |
| M02 | Train-only preprocessing | Fold pipelines tested | 2 | ✅ pass |
| M03 | Probability calibration | Metrics + plot reported | 2 | ✅ pass |
| M04 | Unknown / poor-coverage company | Output withheld with reason | 2 | ✅ pass |
| S01 | EBITDA -20%, rate +200 bp | Expected outputs reproduced | 9 | ✅ pass |
| G01 | Narrative numeric claims | All reconcile to package | 10 | ✅ pass |
| G02 | References / source links | Every claim resolves | 5 | ✅ pass |
| E01 | Complete demo user journey | PDF exported without manual intervention | 3 | ✅ pass |
| FIN-01 | Refinance cannot erase new-loan interest | Regression example and API test | 7 | ✅ pass |
| FIN-02 | Restricted cash handled explicitly | Source reconciliation and ratio test | 4 | ✅ pass |
| FIN-03 | Non-USD upload not scored by USD-trained model | Gated model test | 1 | ✅ pass |
| DATA-01 | Missing/rejected critical figures, impossible dates | Upload and API tests | 15 | ✅ pass |
| WF-01 | Sample company -> memo -> PDF first try | Browser smoke test | 1 | ✅ pass |
| WF-02 | Changed loan -> memo stale -> regenerate | Browser/API test | 8 | ✅ pass |
| ML-01 | Model X-Ray matches frozen metadata, honest benchmarks | Metadata consistency test | 2 | ✅ pass |
| ML-02 | Replay from held-out rows, no future leakage | Date/split invariant test | 8 | ✅ pass |
| OUT-01 | Three demo borrowers reconcile to original filings | Manual cross-check + test | 10 | ✅ pass |
| OUT-02 | Key memo numbers trace to statements and inputs | Four citation drilldowns | 6 | ✅ pass |
| E1 | Memo semantic checks and structure | Direction, signed headroom, undefined ratios, case mixing | 9 | ✅ pass |
| C3 | Neural score separate from loan stress | Sliders never change the score | 2 | ✅ pass |
| F | Stress heatmap from the Python engine | One engine call per cell, matches loan table | 5 | ✅ pass |
| HYG | Upload privacy hygiene | Uploads unlisted; audit operator-only | 2 | ✅ pass |
| A11Y | WCAG 2.1 AA (axe-core) | No serious/critical violations | 5 | ✅ pass |
| SEC | Security controls | Validation, limits, headers, deletion | 6 | ✅ pass |

## Release acceptance (Blueprint p.22)

| Condition | Evidence |
|---|---|
| 100% of critical arithmetic unit tests pass | F01–F04, S01 rows above; `docs/scenario_crosscheck.xlsx` reconciliation |
| Neural model evaluated on held-out data with documented limitations | `training/model_card/stress_mlp_v1.md`, Model X-Ray page |
| Displayed figures traceable to inputs, formula and model versions | G02; evidence rail; memo appendix |
| 3 curated cases demo-stable; 2 report formats upload and review | E01; `tests/fixtures/*.pdf` templates (D02, D03) |
| Memo validation reports zero unsupported numerical claims; user can correct and regenerate | G01; memo edit tests |
