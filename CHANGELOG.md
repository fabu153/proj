# Changelog

## 1.1.0 — Stage A (financial correctness) and Stage B (workflow)

Reason for the new release: the 10-K reconciliation (A5) showed that some credit figures used by the
ratios, loan scenarios and memo differed from the filings. The stress model, its evaluation and its frozen
predictions are **unchanged** (`release/manifest.json`: `model_artifacts_unchanged: true`). The re-frozen
files are the three curated SEC caches (refetched with the supplemental tags behind rules R5–R7) and the
upload fixtures (B&G interest corrected; new fixture C; byte-stable rendering).

### Stage A
- **FIN-01 refinancing:** debt retired at the entered rate or the average cost of debt; inputs that would
  erase the new loan's interest are refused with the maximum allowed rate; no silent clamp; rate cuts cannot
  push interest below zero. Loan engine 1.1.0.
- **FIN-02 restricted cash (R5):** net debt uses unrestricted cash; where restricted cash cannot be separated,
  net debt and net debt / EBITDA are qualified and the memo says so.
- **R6 / R7:** total D&A includes cost-of-revenue D&A (United Rentals EBITDA 4,411 → 7,081); interest is the
  income-statement figure rather than cash paid (United Rentals 703 → 716, B&G 149.0 → 149.6).
  Credit basis only; the neural screen keeps its training basis.
- **FIN-03 currency gating:** the neural score is withheld for non-USD figures; ratios and scenarios still run.
- **DATA-01 review completeness:** currency, unit scale and year-end must be confirmed when the report does not
  state them; real calendar dates only; missing critical figures can be entered (with page) or marked unavailable,
  never zero-filled; uploads not checked against SEC say so.
- **A5:** `docs/manual_cross_check.md` reconciles P&G, United Rentals and B&G Foods with their original 10-Ks.
- **Hygiene:** uploads are listed only through their own link; `/audit` requires an operator token; the site is
  labelled as a course demo.

### Stage B
- **B1 / WF-01:** start page (sample company or upload), progress cue Company → Financials → Neural screen →
  Loan lab → Committee memo, API wake-up status with timeouts, retries and "Try again".
- **B2 / WF-02:** one analysis snapshot (SHA-256 of the canonical inputs, 12 hex digits) shared by the loan table,
  memo and PDF, including "Your case"; the memo is marked "Outdated — regenerate" when the inputs change; the PDF
  prints every assumption and the snapshot id.
- **B3:** review summary (missing / need review / accepted), exceptions first, always-visible currency, units,
  year-end and SEC status, corrections in millions with the explicit conversion shown.
- **B4:** loading, success and error states everywhere; stale results are dimmed and labelled; ratio labels
  unified as "net debt / EBITDA", "EBITDA / interest" and "next-FY accounting-stress screen".

## 1.0.0
Initial release (Weeks 1–8).
