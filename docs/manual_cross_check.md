# Manual cross-check against the original 10-Ks (Stage A5, v1.1)

The three sample issuers were checked line by line against the **original** 10-K documents on SEC EDGAR, not
against XBRL or an aggregator. Each 10-K was downloaded from EDGAR and read as filed. The submissions index was
used to confirm there is no 10-K/A for the period. Amounts are USD millions. Page numbers are the 10-K's printed
page numbers; for United Rentals they were read from a text conversion of the filing.

"Engine (credit)" is the value used for ratios, loan scenarios and the memo. "Engine (model)" is the value fed
to the neural screen. It is exactly the input basis the network was trained on, and it is deliberately unchanged
in v1.1 (see "Why two bases" below).

## Procter & Gamble — FY ended 30 June 2026

Filing: Form 10-K, accession 0000080424-26-000103.
[Filing index](https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000080424&type=10-K&dateb=&owner=include&count=40)

| Item | 10-K line | 10-K | Engine (credit) | Engine (model) | Difference / cause |
|---|---|---|---|---|---|
| Revenue | Consolidated Statements of Earnings, "Net sales" | 87,032 | 87,032 | 87,032 | — |
| Operating income | "Operating income" | 19,748 | 19,748 | 19,748 | — |
| Interest expense | "Interest expense" | 877 | 877 | 877 | — |
| D&A | Cash flows, "Depreciation and amortization" | 3,160 | 3,160 | 3,160 | — |
| Capex | Cash flows, "Capital expenditures" | (4,409) | 4,409 | 4,409 | sign convention only |
| Cash | Balance sheet, "Cash and cash equivalents" | 9,942 | 9,942 | 9,942 | **Tagged only as cash *including* restricted cash** (R5) |
| Debt due within one year | Balance sheet | 11,296 | 11,294 | 11,294 | 2m: the engine sums commercial paper (4,837) and current long-term debt (6,457); a small "other" amount is not tagged separately. Immaterial |
| Long-term debt | Balance sheet | 22,842 | 22,842 | 22,842 | — |
| Total assets | Balance sheet | 126,521 | 126,521 | 126,521 | — |

Result: EBITDA 22,908; net debt / EBITDA 1.06x; EBITDA / interest 26.1x.

The 10-K never mentions restricted cash. However, the only cash tag P&G files is
`CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents`, so the data cannot *prove* the cash is
unrestricted. Since v1.1, net debt and net debt / EBITDA are therefore marked as qualified (amber), and the memo
says so. They are not presented as clean.

## United Rentals — FY ended 31 December 2025

Filing: Form 10-K, accession 0001067701-26-000007, filed 2026-01-28.
[Filing index](https://www.sec.gov/Archives/edgar/data/1067701/000106770126000007/)

| Item | 10-K line (page) | 10-K | v1.0 engine | Engine (credit) v1.1 | Engine (model) | Difference / cause |
|---|---|---|---|---|---|---|
| Revenue | Statements of Income, "Total revenues" (p.47) | 16,099 | 16,099 | 16,099 | 16,099 | — |
| Operating income | "Operating income" (p.47) | 3,973 | 3,973 | 3,973 | 3,973 | — |
| Interest expense | "Interest expense, net" (p.47) | 716 | 703 | **716** | 703 | v1.0 used "Cash paid for interest" (703, p.50), the only interest tag. **Fixed by R7** |
| D&A | "Depreciation of rental equipment" 2,670 + "Non-rental depreciation and amortization" 438 (p.47) | 3,108 | 438 | **3,108** | 438 | v1.0 used only the non-rental tag, which understated EBITDA by 2,670. **Fixed by R6** |
| Operating cash flow | "Net cash provided by operating activities" (p.50) | 5,190 | 5,190 | 5,190 | 5,190 | — |
| Cash | Balance sheet, "Cash and cash equivalents" (p.46) | 459 | 459 | 459 | 459 | — |
| Current debt | "Short-term debt and current maturities of long-term debt" (p.46) | 1,577 | 1,577 | 1,577 | 1,577 | — |
| Long-term debt | "Long-term debt" (p.46) | 12,652 | 12,652 | 12,652 | 12,652 | includes finance leases (shown as a data warning) |
| Total assets | "Total assets" (p.46) | 29,866 | 29,866 | 29,866 | 29,866 | — |

Effect on the credit view:

| Ratio | v1.0 | v1.1 | 10-K basis |
|---|---|---|---|
| EBITDA | 4,411 | 7,081 | 3,973 + 3,108 = 7,081 |
| Net debt / EBITDA | 3.12x | 1.94x | 13,770 / 7,081 = 1.94x |
| EBITDA / interest | 6.27x | 9.89x | 7,081 / 716 = 9.89x |

This was the material defect found by the reconciliation (D-11 in `defects.md`).

Open item: United Rentals tags no `PaymentsToAcquirePropertyPlantAndEquipment`. Its capex is split into
rental and non-rental purchases, so simple free cash flow is shown as "not available" rather than estimated.

## B&G Foods — FY ended 3 January 2026 (53 weeks)

Filing: Form 10-K, accession 0001104659-26-022961, filed 2026-03-03.
[10-K document](https://www.sec.gov/Archives/edgar/data/1278027/000110465926022961/bgs-20260103x10k.htm)

Amounts in the 10-K are "In thousands". They are shown here in millions.

| Item | 10-K line (page) | 10-K | Engine (credit) | Engine (model) | Difference / cause |
|---|---|---|---|---|---|
| Revenue | Statements of Operations, "Net sales" (p.59) | 1,828.687 | 1,828.687 | 1,828.687 | — |
| Operating income | "Operating income (loss)" (p.59) | 97.147 | 97.147 | 97.147 | — |
| Interest expense | "Interest expense, net" (p.59) | 149.631 | **149.631** | 149.039 | v1.0 used "Cash interest payments" (149.039, p.62). **Fixed by R7** |
| D&A | Cash flows, "Depreciation and amortization" (p.62) | 66.223 | 66.223 | 66.223 | — |
| Operating cash flow | "Net cash provided by operating activities" (p.62) | 101.396 | 101.396 | 101.396 | — |
| Capex | "Capital expenditures" (p.62) | (30.647) | 30.647 | 30.647 | sign convention only |
| Cash | Balance sheet, "Cash and cash equivalents" (p.58) | 56.293 | 56.293 | 56.293 | no restricted cash in the filing |
| Current debt | "Current portion of long-term debt" (p.58) | 4.500 | 4.500 | 4.500 | — |
| Long-term debt | "Long-term debt, net of current portion" (p.58) | 1,945.576 | 1,945.576 | 1,945.576 | the revolver (215.0) sits inside long-term debt (Note 7, p.75) |
| Total assets | "Total assets" (p.58) | 2,834.795 | 2,834.795 | 2,834.795 | — |

Result: net debt / EBITDA 11.59x; EBITDA / interest 1.09x on the credit basis (1.10x on the model basis).

The v1.0 upload fixture `tests/fixtures/ar_thousands.pdf` printed the cash interest figure on its
"Interest expense, net" line. It was regenerated from the 10-K values above. The test
`test_both_templates_match_sec_xbrl_exactly[ar_thousands]` now passes against the credit basis.

## Rules added in v1.1 (credit basis only)

| Rule | When it applies | What it does |
|---|---|---|
| R5 | Only cash *including* restricted cash is tagged | Subtracts a tagged restricted-cash amount. If none is tagged, it keeps the figure and qualifies net debt and net debt / EBITDA, and the memo says so |
| R6 | A separate cost-of-revenue D&A tag is larger than the chosen D&A tag | Total D&A = cost-of-revenue D&A + other D&A (United Rentals: 2,670 + 438) |
| R7 | The only interest tag is cash interest paid, and an income-statement net interest tag exists | Uses the income-statement figure, labelled "net of interest income" |

Each rule is shown in the evidence rail ("used in the ratios, by rule …", with the as-tagged value underneath),
in the data checks, and in the memo appendix.

## Why two bases

The stress network (`backend/models/stress_mlp_v1`) was trained on the v1.0 input definitions across the whole
SEC panel. Changing its inputs for three companies would score them on features the network never saw, and it
would silently change a frozen, evaluated model. The model therefore keeps `basis="model"`, which is exactly the
training inputs. The neural screen output was re-checked after these changes and is unchanged:
P&G 0.010364, United Rentals 0.017559, B&G 0.808225 (`test_model_scores_unchanged_by_credit_basis`).
Moving the network to the corrected definitions would mean a retrain and a new model version, which is out of
scope for Stage A.
