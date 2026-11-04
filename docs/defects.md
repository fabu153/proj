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

## Known limitations (accepted, documented, not defects)

- The neural network does not beat XGBoost on test (paired CI includes zero); reported in the model card.
- Upload parser supports text-based PDFs of U.S.-style primary statements; no OCR; tested on two layouts.
- Upload test PDFs are renderings of real reported figures, not the original filings (SEC blocks unattended
  document downloads without a contact e-mail). Testing on original 10-K PDFs is the first post-release task.
- Render free tier sleeps after ~15 minutes idle; first request can take up to a minute.
