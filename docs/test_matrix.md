# Test matrix (Blueprint p.22)

_Generated 2026-11-04 22:32 UTC by `scripts/test_matrix.py`: 194 passed, 0 failed, 0 skipped (browser tests run only with `E2E_BASE_URL`)._

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
| FIN-01 | Refinancing interest (v1.1) | New-loan interest never erased; conflicts refused | 7 | ✅ pass |
| FIN-02 | Restricted cash (v1.1) | Unrestricted cash or qualified net debt | 4 | ✅ pass |
| FIN-03 | Currency / scope gating (v1.1) | Non-USD neural score withheld, ratios kept | 1 | ✅ pass |
| DATA-01 | Review completeness and dates (v1.1) | Missing / invalid inputs block analysis | 15 | ✅ pass |
| A5 | 10-K reconciliation rules R5-R7 (v1.1) | Credit basis matches the 10-K; model basis frozen | 7 | ✅ pass |
| WF-01 | Start page to memo (v1.1) | Guided journey with progress and wake-up states | 1 | ✅ pass |
| WF-02 | Shared analysis snapshot (v1.1) | Table, memo and PDF share one snapshot id | 7 | ✅ pass |
| HYG | Upload privacy hygiene (v1.1) | Uploads unlisted; audit operator-only | 2 | ✅ pass |
| A11Y | WCAG 2.1 AA (axe-core) | No serious/critical violations | 4 | ✅ pass |
| SEC | Security controls | Validation, limits, headers, deletion | 6 | ✅ pass |

## Release acceptance (Blueprint p.22)

| Condition | Evidence |
|---|---|
| 100% of critical arithmetic unit tests pass | F01–F04, S01 rows above; `docs/scenario_crosscheck.xlsx` reconciliation |
| Neural model evaluated on held-out data with documented limitations | `training/model_card/stress_mlp_v1.md`, Model X-Ray page |
| Displayed figures traceable to inputs, formula and model versions | G02; evidence rail; memo appendix |
| 3 curated cases demo-stable; 2 report formats upload and review | E01; `tests/fixtures/*.pdf` templates (D02, D03) |
| Memo validation reports zero unsupported numerical claims; user can correct and regenerate | G01; memo edit tests |
