# Test matrix (Blueprint p.22)

_Generated 2026-11-04 19:58 UTC by `scripts/test_matrix.py`: 155 passed, 0 failed, 0 skipped (browser tests run only with `E2E_BASE_URL`)._

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
| A11Y | WCAG 2.1 AA (axe-core) | No serious/critical violations | 3 | ✅ pass |
| SEC | Security controls | Validation, limits, headers, deletion | 6 | ✅ pass |

## Release acceptance (Blueprint p.22)

| Condition | Evidence |
|---|---|
| 100% of critical arithmetic unit tests pass | F01–F04, S01 rows above; `docs/scenario_crosscheck.xlsx` reconciliation |
| Neural model evaluated on held-out data with documented limitations | `training/model_card/stress_mlp_v1.md`, Model X-Ray page |
| Displayed figures traceable to inputs, formula and model versions | G02; evidence rail; memo appendix |
| 3 curated cases demo-stable; 2 report formats upload and review | E01; `tests/fixtures/*.pdf` templates (D02, D03) |
| Memo validation reports zero unsupported numerical claims; user can correct and regenerate | G01; memo edit tests |
