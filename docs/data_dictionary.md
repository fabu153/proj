# CreditLens data dictionary

Generated from code (`xbrl.TAG_REGISTRY`, `feature_set.FEATURE_DICTIONARY`, `stress_label`). Edit the code, then regenerate — never this file.

## Canonical company-year facts (SEC XBRL, us-gaap, USD)

| field | period | XBRL tags in priority order | role |
|---|---|---|---|
| `revenue` | duration | `Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`, `RevenueFromContractWithCustomerIncludingAssessedTax`, `SalesRevenueNet` | engine input |
| `operating_income` | duration | `OperatingIncomeLoss` | engine input |
| `net_income` | duration | `NetIncomeLoss`, `ProfitLoss` | engine input |
| `interest_expense` | duration | `InterestExpense`, `InterestExpenseNonoperating`, `InterestExpenseDebt`, `InterestAndDebtExpense`, `InterestPaidNet`, `InterestPaid` | engine input |
| `depreciation_amortization` | duration | `DepreciationDepletionAndAmortization`, `DepreciationAndAmortization`, `DepreciationAmortizationAndAccretionNet` | engine input |
| `operating_cash_flow` | duration | `NetCashProvidedByUsedInOperatingActivities` | engine input |
| `capital_expenditures` | duration | `PaymentsToAcquirePropertyPlantAndEquipment`, `PaymentsToAcquireProductiveAssets` | engine input |
| `cash` | instant | `CashAndCashEquivalentsAtCarryingValue`, `CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents` | engine input |
| `short_term_borrowings` | instant | `ShortTermBorrowings`, `CommercialPaper` | engine input |
| `current_maturities_ltd` | instant | `LongTermDebtCurrent`, `LongTermDebtAndCapitalLeaseObligationsCurrent` | engine input |
| `long_term_debt` | instant | `LongTermDebtNoncurrent`, `LongTermDebtAndCapitalLeaseObligations`, `LongTermNotesPayable` | engine input |
| `long_term_debt_total` | instant | `LongTermDebt`, `DebtAndCapitalLeaseObligations`, `DebtLongtermAndShorttermCombinedAmount` | derivation input only |
| `debt_current_total` | instant | `DebtCurrent` | derivation input only |
| `total_assets` | instant | `Assets` | engine input |
| `total_liabilities` | instant | `Liabilities` | engine input |
| `liabilities_and_equity` | instant | `LiabilitiesAndStockholdersEquity` | derivation input only |
| `stockholders_equity` | instant | `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest`, `StockholdersEquity` | engine input |
| `current_assets` | instant | `AssetsCurrent` | engine input |
| `current_liabilities` | instant | `LiabilitiesCurrent` | engine input |

Annual = 10-K/10-K/A/10-KT, duration 350–380 days. Original vintage by default; restatements kept. Derivation rules R1–R4 are documented in `backend/app/documents/xbrl.py::derive`.

## Model features (`features_v1`)

| # | feature | definition | unit |
|---|---|---|---|
| 1 | `ebitda_margin` | (operating income + D&A) / revenue | pct |
| 2 | `operating_margin` | operating income / revenue | pct |
| 3 | `net_margin` | net income / revenue | pct |
| 4 | `roa` | net income / total assets | pct |
| 5 | `cfo_margin` | operating cash flow / revenue | pct |
| 6 | `cfo_to_assets` | operating cash flow / total assets | pct |
| 7 | `fcf_margin` | (CFO - capex) / revenue | pct |
| 8 | `capex_intensity` | capex / revenue | pct |
| 9 | `gross_leverage` | gross debt / EBITDA (undefined if EBITDA <= 0) | x |
| 10 | `net_leverage` | net debt / EBITDA (undefined if EBITDA <= 0) | x |
| 11 | `debt_to_assets` | gross debt / total assets | pct |
| 12 | `liabilities_to_assets` | total liabilities / total assets | pct |
| 13 | `equity_to_assets` | stockholders' equity / total assets | pct |
| 14 | `cfo_to_debt` | operating cash flow / gross debt (undefined if no debt) | x |
| 15 | `fcf_to_debt` | (CFO - capex) / gross debt (undefined if no debt) | x |
| 16 | `ebit_interest_cover` | operating income / interest expense | x |
| 17 | `ebitda_interest_cover` | EBITDA / interest expense | x |
| 18 | `implied_cost_of_debt` | interest expense / gross debt | pct |
| 19 | `current_ratio` | current assets / current liabilities | x |
| 20 | `cash_to_assets` | cash / total assets | pct |
| 21 | `cash_to_current_liabilities` | cash / current liabilities | x |
| 22 | `short_term_debt_share` | (short-term borrowings + current LTD) / gross debt | pct |
| 23 | `log_assets` | ln(total assets, USD m) | log |
| 24 | `revenue_growth` | revenue_t / revenue_t-1 - 1 | pct |
| 25 | `d_ebitda_margin` | change in EBITDA margin | pp |
| 26 | `d_debt_to_assets` | change in debt / assets | pp |
| 27 | `debt_growth` | gross debt_t / gross debt_t-1 - 1 | pct |
| 28 | `d_cfo_to_assets` | change in CFO / assets | pp |
| 29 | `ebitda_nonpositive` | 1 if EBITDA <= 0 | flag |
| 30 | `no_debt` | 1 if gross debt == 0 | flag |
| 31 | `stress_conditions_t` | number of the 3 stress conditions met in year t (unknown = 0, masked) | count |

Each feature also gets a `<feature>__missing` indicator after train-only median imputation.

## Label (`stress_v1`)

`label_next_fy` = 1 if at least 2 of 3 hold in fiscal year t+1: EBIT/interest < 1.5x; gross debt/EBITDA > 5.0x (or debt with EBITDA ≤ 0); CFO < 0. Undeterminable → missing (never 0). `label_onset` = same outcome restricted to firms not stressed in year t.

## Panel columns (`training/data/panel_v1.csv`)

| column | meaning |
|---|---|
| `as_of_date` | latest filing date of year-t facts — earliest moment a prediction can be made |
| `label_available_date` | filing date of year t+1 facts — when the outcome became public |
| `v_*` | canonical fact, USD millions | 
| `m_*` | engine metric (`finance/metrics.py`) |
| `stress_t`, `cond_*_t` | label rule applied to year t (feature-safe) |
| `critical_coverage` | share of 7 critical facts present |
