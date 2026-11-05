# Defect log

Every defect found while building and testing CreditLens, how it was found, and the fix. Severity follows the
blueprint's risk table: **High** = could show a wrong number or block the demo; **Medium** = misleading or degraded;
**Low** = cosmetic. All are closed; each fix has a regression test where one is possible.

| ID | Found in | Sev. | Defect | Root cause | Fix and regression test |
|---|---|---|---|---|---|
| DF-01 | Week 2 label audit | High | Leverage condition unknown for 54% of company-years | Debt captured only via `LongTermDebtNoncurrent`; many filers tag total debt as `LongTermDebt` | Fallback tags with derivation rules R1–R4 that never double count current debt; coverage 59% → 66%, labelled rows +15%. `test_xbrl_derivations.py` |
| DF-02 | Week 2 label audit | High | Stress prevalence 58% in the smallest size quintile | Pre-revenue biotechs are "stressed" by construction (losses, negative CFO) | Population gate (revenue ≥ USD 50m) decided before any model was fitted; `configs/experiment_baselines_v1.yaml` |
| DF-03 | Week 2 cross-check | Medium | 9% of values disagreed with SEC frames | Frames carry restated values; the panel keeps the original vintage by design | Like-for-like check (same tag, latest vintage): 99.4–99.7% agreement; residual 13 explained by 8-K recasts. `training/pipeline/cross_check.py` |
| DF-04 | Week 3 review | Low | Warning said current debt was "treated as 0" after rule R1 had filled it | Generic warning emitted before derivation | Derived values supersede the warning. `test_real_issuer_r1_supersedes_zero_fill_warning` |
| DF-05 | Week 5 screenshot review | Medium | Loan lab empty on first load | Default EUR facility on a USD reporter is blocked until an FX rate is entered | Facility defaults to the reporting currency; EUR still available with explicit FX |
| DF-06 | Week 5 screenshot review | Medium | B&G fiscal years shown as FY2022, 2023, 2024, 2026 | 52/53-week year ending 3 Jan 2026 labelled by calendar year | Year-ends in the first week of January take the prior year's label (`fyLabel`) |
| DF-07 | Week 5 screenshot review | Low | Covenant ruler labels overlapped when cases clustered | Labels drawn on the track | Values moved to a legend under each ruler |
| DF-08 | Week 5 mobile check | Medium | Page wider than the phone screen | Grid children default to `min-width: auto` | `.workspace > * { min-width: 0 }`; tables scroll inside their panel |
| DF-09 | Live deployment | High | Vercel site could not reach the API | CORS allowed only `creditlens*.vercel.app`; the project is `proj` | Pattern covers both names and preview URLs. `test_cors_allows_proj_vercel_deployments` |
| DF-10 | CI | High | Frontend build failed, which held back the Render deploy | `next/font/google` got an empty response from Google Fonts at build time | Fonts bundled via `@fontsource-variable`; no network needed to build |
| DF-11 | Week 6 flow test | Medium | Memo request returned 422 | Memo default facility was EUR, so the FX safeguard blocked it | Default facility follows the reporting currency. `test_memo_for_curated_company_defaults_to_reporting_currency` |
| DF-12 | Week 6 test | Medium | P&G current debt flagged as disagreeing with XBRL | "Debt due within one year" combines short-term borrowings and current maturities; XBRL splits them | Combined lines compared with the sum. `test_cross_check_flags_disagreement_with_xbrl` |
| DF-13 | Week 6 memo review | Low | "Revenue declined -5.4%", "headroom is -8.70x" | Signed values rendered inside sign-carrying wording | Magnitude items (`revenue_growth.abs`, `*_shortfall`) and breach phrasing |
| DF-14 | Week 6 memo review | Medium | Analyst edit "down 5.4%" flagged as unsupported | Number matching required the sign | Magnitudes match when direction is in words; invented figures still flagged. `test_typed_number_matching_package_is_linked` |
| DF-15 | Week 7 E2E test | Low | Browser console error while choosing EUR | UI sent a request it knew the API would refuse | FX prompt shown client-side until a rate is entered. `test_e01_issuer_to_memo_pdf` asserts a clean console |
| DF-16 | Week 7 axe scan | Medium | Two WCAG AA failures: band-chip contrast, "Before loan" header contrast | Teal/grey text on tinted or white backgrounds below 4.5:1 | Darker text tokens. `test_wcag_aa_no_serious_violations` |
| DF-17 | Week 7 axe scan | Medium | Scrollable tables not reachable by keyboard | `overflow-x` regions without focus | Regions are focusable and labelled. Same test |
| DF-18 | v1.1 A5 10-K reconciliation | High | United Rentals EBITDA 4,411 instead of 7,081; net debt / EBITDA 3.12x instead of 1.94x | Rental-fleet depreciation (2,670) is tagged inside cost of revenue; only the non-rental D&A tag (438) was read | Credit-basis rule R6 adds the cost-of-revenue D&A. `test_r6_united_rentals_total_da_matches_10k` |
| DF-19 | v1.1 A5 reconciliation | High | Interest expense was cash interest paid for United Rentals (703 vs 716) and B&G (149.0 vs 149.6) | When no P&L interest tag existed, `InterestPaidNet` was used | R7 prefers income-statement net interest. `test_r7_income_statement_interest_preferred_to_cash_paid` |
| DF-20 | v1.1 A2 | Medium | P&G net debt presented as clean although its only cash tag includes restricted cash | No distinction between cash and cash + restricted cash | R5 subtracts tagged restricted cash or qualifies net debt and net debt / EBITDA (amber, memo caveat). `test_fin02_*`, `test_memo_caveats_for_combined_cash_and_credit_rules` |
| DF-21 | v1.1 A1 | High | Refinancing at a high "retired debt" rate could wipe out the new loan's interest | Saved interest could exceed reported interest; a `max(…, 0)` clamp hid the inconsistency | Retired rate defaults to the average cost of debt; inconsistent inputs are refused with the maximum allowed rate; clamp removed. `test_fin01_*` |
| DF-22 | v1.1 A1 | Medium | A rate cut could push floating-rate interest below zero | No floor check | Refused with a clear message. `test_rate_cut_cannot_push_floating_rate_below_zero` |
| DF-23 | v1.1 A4 | High | Uploads assumed USD and a unit scale when the statements stated none; any `NNNN-NN-NN` passed as a year-end | Defaults in the parser; regex-only date check | Currency, units and year-end must be confirmed; real calendar dates only; confirming units rescales every figure. `test_data01_*` |
| DF-24 | v1.1 A4 | Medium | A critical line the parser missed could not be entered, and its absence was not visible downstream | No manual-entry path | Enter the figure (with page) or mark it unavailable; shown in the workspace, memo and risk screen, never zero-filled. `test_data01_missing_critical_fact_*`, `test_data01_entered_fact_*` |
| DF-25 | v1.1 A3 | High | A EUR upload was scored by a network trained on USD data with USD size inputs | Currency carried as a label only | Neural score withheld for non-USD figures with the reason; ratios and scenarios unaffected. `test_fin03_non_usd_upload_withholds_neural_score_but_keeps_ratios` |
| DF-26 | v1.1 B2 | Medium | The memo could describe different inputs from the loan table, and "Your case" never reached the memo | Memo rebuilt fixed cases from its own defaults | One analysis snapshot (SHA-256 id) shared by table, memo and PDF; PDF prints all assumptions; memo marked "Outdated — regenerate". `test_wf02_*`, E2E `test_e01_*` |
| DF-27 | v1.1 hygiene | Medium | `/audit` was public and finalized uploads were listed to every visitor | No access separation in a demo | Uploads listed only via their own link; `/audit` needs an operator token. `test_full_upload_to_memo_flow` |
| DF-28 | v1.1 A5 | Medium | B&G upload fixture printed cash interest on its "Interest expense, net" line | Fixture built from XBRL, not the 10-K | Regenerated from the 10-K; fixtures are now byte-stable. `test_both_templates_match_sec_xbrl_exactly` |
| DF-29 | v1.1 B4 | Low | Loan table kept showing old results as current while recalculating | No stale state | "Recalculating" tag and dimmed table until new results arrive |
| DF-30 | v1.1 B1 | Medium | On a cold start the site could sit on "Loading…" indefinitely | No timeout or retry | Wake-up status with elapsed time, timeouts, retries and a "Try again" action |
| DF-31 | v1.1 A4 | Low | One malformed upload could break the company list for everyone | Exceptions not isolated | Malformed uploads are logged and skipped. `test_malformed_upload_does_not_break_company_list` |
| DF-32 | v1.1 axe scan | Medium | Review-table exception colours below 4.5:1 | Teal and amber text on tinted rows | Darker text and edge markers instead of tinted rows. `test_data01_unlabelled_report_needs_confirmation` |
| DF-33 | v1.2 replay tests | Medium | The stress-label function returned "not stressed" for numpy inputs that met two conditions | `x is True` is false for `np.bool_` | Conditions return plain `bool`; the training panel was unaffected (4,322 rows re-checked). `test_stress_label_accepts_numpy_values` |
| DF-34 | v1.2 X-Ray review | Low | The calibration chart's observed line stopped at 50% | Two lines with separate data arrays on one numeric axis | Both series in one data array |
| DF-35 | v1.2 X-Ray review | Low | Data-window counts (1,626 / 497 / 1,307) did not match the evaluated rows (1,219 / 389 / 1,086) | The panel's window counts were shown next to metrics on gated rows | The X-Ray shows the scored rows and says which gate applies |

## Known limitations (accepted, documented, not defects)

- The neural network does not beat XGBoost on test (paired CI includes zero); reported in the model card.
- Upload parser supports text-based PDFs of U.S.-style primary statements; no OCR; tested on two layouts.
- Upload test PDFs are renderings of real reported figures, not the original filings. The figures themselves were
  reconciled line by line against the original 10-Ks (`docs/manual_cross_check.md`).
- The neural screen keeps its v1.0 input definitions (model basis) so its frozen evaluation stays valid; the
  credit ratios use the corrected v1.1 credit basis. Retraining on the corrected definitions needs a new model version.
- The network catches only 15 of 96 new stress onsets on the test window; it is mainly a persistence detector
  (Model X-Ray, "Where it fails").
- United Rentals tags no single capex line, so its simple free cash flow is shown as not available.
- Render free tier sleeps after ~15 minutes idle; first request can take up to a minute.
