# Changelog

## 1.2.0 — Stage C (deep-learning evidence) and Stage D (Historical Model Replay)

Reason for the new release: two new frozen artifacts, both derived from the unchanged model. The first is the
held-out MLP predictions, re-scored by the frozen network; they reproduce the recorded test evaluation exactly.
The second is the replay dataset built from them. No model artifact, training result or curated filing changed
(`release/manifest.json`: `model_artifacts_unchanged: true`).

### Stage C
- **C1 Model X-Ray in three layers.**
  - What the network learned: target definition, 31 inputs in 8 groups, network diagram, training, validation and
    test windows.
  - How it performed: PR-AUC, ROC-AUC and Brier with intervals and no-skill references; why PR-AUC matters for a
    30% outcome; matched baseline table; calibration; outcomes by screening band.
  - Where it fails: the confusion matrix at the validation-chosen threshold, persistence versus onset (15 of 96 new
    stress onsets caught), false alarms that were recoveries (66 of 84), scope limits, and how to read log-odds
    driver bars.
- **C2 Honest comparison.** XGBoost's higher point estimate (0.825 vs 0.805) and lower Brier are stated outright.
  The workspace explains the score in one sentence and links to the X-Ray.
- **C3 Separate purposes.** The neural score is labelled as independent of the loan lab. A browser test moves the
  slider and checks the score does not change; an API test checks the scenario response carries no score.

### Stage D
- **Historical Model Replay at `/replay`.**
  - 12 held-out 2021–25 company-years chosen by a fixed, documented rule, including three examples: a correct
    warning, a false alarm and a miss.
  - Filing timeline, known-at-time snapshot, the frozen forecast with drivers and the XGBoost benchmark, then
    "Reveal next-year outcome" with the three label conditions and an assessment against same-range observed rates.
  - The outcome sits behind its own endpoint, so nothing about the future reaches the browser before it is requested.
- `python -m training.ml.export_replay` rebuilds both artifacts and refuses to write if the re-scored predictions
  do not reproduce the frozen metrics.

### Fixes
- The stress-label function counted numpy booleans as "not met". The training panel was unaffected (all 4,322 rows
  re-checked), but the function is now robust.
- The calibration chart broke its observed line above 50%.
- The X-Ray's data-window counts mixed panel rows with scored rows.

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
