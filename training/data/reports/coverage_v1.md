# CreditLens dataset coverage report & label audit
_Generated 2026-11-04 17:33 UTC from SEC XBRL companyfacts. Label version: stress_v1._

## Universe and panel
- Companies in universe: **600**; with ≥1 annual row: **549**; fetch/parse failures: **0**
- Company-years: **5850** (fiscal years 2007–2026)
- Passing hard checks (scorable): **94.8%**
- Mean critical-field coverage: **86.4%**; rows with all 7 critical fields: **42.8%**
- Rows with a determinable next-year label: **3827** (65.4%)

### Why rows have no label
| reason | count |
|---|---|
| labelled | 3827 |
| insufficient_t+1_data | 1162 |
| no_consecutive_t+1 | 602 |
| t+1_failed_hard_checks | 259 |

### Field availability (share of company-years with a value)
| field | available |
|---|---|
| long_term_debt | 0.663 |
| current_maturities_ltd | 0.675 |
| short_term_borrowings | 0.682 |
| depreciation_amortization | 0.830 |
| operating_cash_flow | 0.887 |
| revenue | 0.887 |
| current_liabilities | 0.908 |
| current_assets | 0.909 |
| total_liabilities | 0.916 |
| interest_expense | 0.918 |
| capital_expenditures | 0.923 |
| total_assets | 0.927 |
| operating_income | 0.938 |
| stockholders_equity | 0.967 |
| net_income | 0.978 |
| cash | 0.981 |

## Label audit — next-fiscal-year stress (2 of 3)
- Overall prevalence: **29.53%** (1130 positives / 3827)
- Onset prevalence (not stressed in t): **8.37%** (210 positives / 2508)
- Persistence: P(stress t+1 | stress t) = **81.4%**; P(stress t+1 | not stress t) = **8.4%**

### Which conditions fire in year t (all scorable rows)
| condition | share_true | share_unknown |
|---|---|---|
| EBIT cover < 1.5x | 0.325 | 0.139 |
| Debt/EBITDA > 5x or debt w/ EBITDA ≤ 0 | 0.185 | 0.479 |
| CFO < 0 | 0.195 | 0.113 |

### Prevalence by fiscal year (t)
| fy | labelled | positives | prevalence |
|---|---|---|---|
| 2007.000 | 21.000 | 4.000 | 0.190 |
| 2008.000 | 75.000 | 13.000 | 0.173 |
| 2009.000 | 188.000 | 38.000 | 0.202 |
| 2010.000 | 221.000 | 44.000 | 0.199 |
| 2011.000 | 251.000 | 51.000 | 0.203 |
| 2012.000 | 238.000 | 61.000 | 0.256 |
| 2013.000 | 226.000 | 60.000 | 0.265 |
| 2014.000 | 218.000 | 63.000 | 0.289 |
| 2015.000 | 235.000 | 66.000 | 0.281 |
| 2016.000 | 242.000 | 77.000 | 0.318 |
| 2017.000 | 226.000 | 69.000 | 0.305 |
| 2018.000 | 226.000 | 74.000 | 0.327 |
| 2019.000 | 243.000 | 103.000 | 0.424 |
| 2020.000 | 263.000 | 95.000 | 0.361 |
| 2021.000 | 253.000 | 84.000 | 0.332 |
| 2022.000 | 237.000 | 83.000 | 0.350 |
| 2023.000 | 228.000 | 77.000 | 0.338 |
| 2024.000 | 201.000 | 63.000 | 0.313 |
| 2025.000 | 35.000 | 5.000 | 0.143 |

### Prevalence by size quintile (1 = smallest)
| size_quintile | labelled | positives | prevalence |
|---|---|---|---|
| 1 | 449.000 | 269.000 | 0.599 |
| 2 | 510.000 | 245.000 | 0.480 |
| 3 | 811.000 | 215.000 | 0.265 |
| 4 | 979.000 | 235.000 | 0.240 |
| 5 | 1078.000 | 166.000 | 0.154 |

### Prevalence by sector (SIC division)
| division | labelled | positives | prevalence |
|---|---|---|---|
| Agriculture | 33.000 | 7.000 | 0.212 |
| Construction | 64.000 | 12.000 | 0.188 |
| Manufacturing | 1730.000 | 569.000 | 0.329 |
| Mining & energy | 180.000 | 52.000 | 0.289 |
| Retail | 371.000 | 53.000 | 0.143 |
| Services | 766.000 | 265.000 | 0.346 |
| Transport & communications | 295.000 | 114.000 | 0.386 |
| Utilities | 241.000 | 28.000 | 0.116 |
| Wholesale | 147.000 | 30.000 | 0.204 |

## Known limitations
- Proxy for accounting stress, not default; thresholds are declared assumptions (configs/assumptions.yaml).
- EBITDA = operating income + D&A (unadjusted); D&A tag coverage limits EBITDA availability.
- Interest-expense tagging varies (gross/net, capitalized); missing interest leaves coverage unknown.
- Companies absent from all four assets snapshots (2011/15/19/22) are not in the universe.
- XBRL begins ~2009-2011 depending on filer size; earliest years are thinner.
