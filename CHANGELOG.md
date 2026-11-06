# Changelog

## 1.3.3 — Works with ad blockers

- The browser no longer calls the API's hosting domain (onrender.com), which some ad blockers block. It calls
  `/api/...` on the site's own domain, and Next.js / Vercel forward those requests to the service
  (`frontend/next.config.mjs`). No CORS round-trip is needed, and the visitor's IP is still passed on for rate limits.
- Every API response is `no-store`, so the proxy never serves a cached answer.
- New browser test: with the API's domain blocked in the browser, the full journey to the PDF still works.

## 1.3.2 — Connection diagnostics

- When the page cannot reach the analysis service it now shows the browser's last error, explains it ("Failed to
  fetch" means the request was blocked or the network cannot reach the service; a timeout means the server is
  still starting), and links to the service's health check so the user can tell the two apart.

## 1.3.1 — Wake-up fix

- The start page could sit on "Connecting to the analysis service…" indefinitely if the browser paused its timers
  (background tab, sleeping laptop). Elapsed time and a 75 s deadline now run on their own clock, "Try again now"
  appears from 25 s, and the page always ends in either the company list or a clear message.
- `.github/workflows/keep-warm.yml` pings the API every 10 minutes from 06:00 to 22:00 UTC so it is rarely asleep;
  run it manually before a demo, or disable it to let the API sleep.

## 1.3.0 — Stage E (finished result) and Stage F (stress heatmap)

No frozen artifact changed: the release manifest remains at 1.2.0 and its 27 hashes still verify.

### E1 Credit memo
- **Layout:** the PDF and the on-screen memo open with Borrower, Fiscal year, Proposed facility, Purpose and
  Analyst-review status. A four-sentence executive assessment follows, then compact sections: financial profile,
  key strengths, key risks, neural stress screen, stress cases (with a before-loan / base / downside / severe /
  your-case table), covenant headroom (signed, with breaches shown as shortfalls), diligence questions,
  assumptions with the snapshot id, source trails and the evidence appendix.
- **Semantic checks** on every sentence, in addition to number reconciliation:
  - direction words must match the sign of the change, including "rises to / falls to" against the pre-loan figure;
  - negative covenant headroom must be called a breach, and positive headroom must not be;
  - undefined ratios cannot be cited;
  - one sentence cannot pair one stress case's assumptions with another case's results.
  The template writer passes all of them; the language-model writer remains optional and is held to the same checks.

### E2 Source trails
- Clicking a figure in the memo opens its trail for EBITDA, net debt, net debt / EBITDA and EBITDA / interest:
  filing (SEC accession with an EDGAR link, or uploaded-report page) → normalized fact in USD millions with any
  rule (R1–R7) → calculation with the actual numbers → the memo sentence that cites it. The PDF prints the same
  four trails.

### E3 Presentation
- The demo script follows the roadmap's three-minute flow: P&G financials → network vs XGBoost → EUR 100m with an
  explicit dated FX rate → matched memo and PDF → one replay reveal. The captioned backup video, screenshots and
  sample memos are regenerated.

### F Stress heatmap
- `POST /scenarios/grid` runs the existing Python engine once per cell: EBITDA −50% to +10% by rates 0 to +500 bp,
  42 runs. The loan lab shows net debt / EBITDA, EBITDA / interest or covenant headroom, colours breached and
  tight cells, and clicking a cell loads it into "your case".

### Acceptance IDs
- Renamed to match the roadmap's checklist: ML-02 = replay held-out with no leakage; OUT-01 = demo borrowers
  reconcile to the 10-Ks (new test pinning each borrower's key figures); OUT-02 = memo drilldowns. The earlier
  "sliders never change the score" check is now C3.

### Fixes
- The grey "n/a" in the credit profile failed contrast on the selected-row tint (2.5:1, now 4.6:1).

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
