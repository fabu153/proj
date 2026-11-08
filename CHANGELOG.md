# Changelog

## 1.5.0 — One onset definition; watch-list research; experimental research in Model X-Ray

No model, calibration, replay or release-manifest file changed (manifest 1.2.0, 27 hashes still verified).

### Onset statistics corrected
- Every onset figure now uses the canonical `label_onset` population: companies **confirmed not stressed** in the
  filing year. On the 1,086 held-out rows: 299 already stressed (226 stayed stressed, 214 caught), 727 confirmed
  healthy (73 onsets, **6 caught**), 60 with an undeterminable filing-year status (23 stressed, 9 caught).
- The earlier "15 of 96" counted those 60 undeterminable company-years as healthy (96 = 73 + 23; 15 = 6 + 9). The
  frozen replay file keeps that figure; Model X-Ray now shows the canonical breakdown and labels the old figure.
- `mlp_history_v1` and `gru_history_v1` were re-run with the canonical definition. Their predictions are
  byte-identical to the original runs; only the onset breakdown changed. `HISTORY_EXPERIMENT.md`, the model card,
  README, demo script and defect log were updated (DF-47). One misquoted row in `HISTORY_EXPERIMENT.md` was
  corrected (227/72 → 235/80 flags).

### Research: watch-list threshold for healthy borrowers (not deployed)
- `training/experiments/onset_watchlist_v1/`: the deployed network's unchanged scores, with thresholds fixed on
  validation scores to flag 5/10/15/20% of healthy borrowers. At 10% it catches 33 of 73 onsets instead of 6
  (precision 34%, 64 false alarms instead of 8). Recommendation: confirm on fiscal-2026 outcomes before any use.

### Model X-Ray: section 4, Experimental research
- Two separate tables: next-year stress on all 1,086 rows, and new stress on the 727 healthy rows. Deployed,
  experimental, benchmark and reference rows are marked; paired differences against the deployed network with
  company-clustered intervals; key findings and limitations; the watch-list research. No new live score.
- Data: `backend/data/research/research_v1.json`, built by `training/ml/export_research.py` from the saved
  experiment results (not a model artifact, not in the release manifest).

## Research — gru_onset_v1 (not deployed)
- A three-year GRU trained only on companies not stressed in year t, to detect new stress
  (`training/experiments/gru_onset_v1/report.md`). Canonical `label_onset` cohort: 886 / 295 / 727 rows with
  65 / 18 / 73 onsets. Missing prior years are skipped (packed sequences), not zero-filled.
- Result: test PR-AUC 0.254, against 0.300 for the onset MLP (reproduced exactly), 0.346 for the onset XGBoost
  and 0.319 for the deployed network on the same rows. Not deployed; the report recommends against it.
- Exploratory only: the 2021–25 test window had already been inspected. Nothing in `backend/models`, the
  manifest, Model X-Ray or the replay changed. The research tests (`tests/integration/test_research_gru_onset.py`)
  check the cohort, point-in-time history, missing-year handling and that every published number follows from
  the saved predictions.

## 1.4.0 — Search any U.S. public company; four correctness fixes

No frozen artifact changed: the model, its preprocessing, calibration and gates, the replay predictions and the
release manifest (1.2.0, 27 hashes) are untouched. The loan engine is now 1.2.0, so analysis snapshot ids differ
from v1.3 and the sample memos in `docs/samples/` were regenerated.

### Search a U.S. public company
- The start page puts **Search a U.S. public company** and **Upload an annual report** side by side, with a quick
  demo of the three curated issuers below.
- Search by name, ticker or CIK (`GET /companies/search?q=`). Suggestions show name, tickers, CIK and exchange;
  debounced, with only the latest reply shown; keyboard accessible (ARIA combobox); loading, empty and error states.
- Choosing a company opens the workspace, which loads it through `POST /companies/resolve`: SEC companyfacts and
  the identity record are fetched **by the server** (the browser only talks to `/api`) through `SECClient`
  (User-Agent from `SEC_USER_AGENT`, ≤ 4 requests/s, short retries, 12-hour disk + memory cache; the company list
  is cached for a day and an older copy is used if SEC is down).
- The record goes through the unchanged XBRL pipeline: original vintages, filing-date availability, accession
  numbers, derivation rules and source trails work exactly as for the samples.
- Five outcomes are told apart: fully analysable; some metrics unavailable (shown as unavailable, never estimated,
  with a note if the loan lab cannot run); neural screen withheld (with the reason); no supported statements
  (e.g. IFRS 20-F filers, funds, shells); SEC unavailable or rate-limited (with a retry).
- The training universe screen now also applies to searched companies: financial-sector (SIC 6000–6799), shell
  and unclassified filers are never scored by the network (`backend/app/features/universe_rules.py`, shared with
  `training/pipeline/universe.py`).
- Tests mock SEC (`tests/fixtures/sec`, `CREDITLENS_SEC_FIXTURES` for browser runs); nothing in CI calls SEC.

### Correctness fixes
- **Year columns (PDF upload).** Figures are mapped by each column's year heading, not by position: 2- and
  3-column statements in either order, and mixed column counts, give the same t and t-1. Out-of-order or repeated
  headings are flagged for review, and a statement without the latest year is never combined with the others.
- **Negative EBITDA.** Shocks move EBITDA by a share of its size, `stressed = base + |base| × shock`, so a downside
  deepens a loss; zero EBITDA is never shocked into an invented value. Explained in the loan lab and the trail.
- **Covenant states.** Each covenant is PASS, BREACH or NOT TESTABLE (with a reason) in the loan table, heatmap,
  memo and PDF. Not testable is never counted as a breach; an explicit `nonpositive_ebitda_breaches_leverage`
  policy flag exists for agreements that define it so, off by default.
- **No outdated memo export.** The PDF button is enabled only when a memo exists, the loan lab is current, and the
  memo's snapshot equals the lab's with no draft or half-typed input pending. A memo reply that arrives after the
  inputs changed is shown as outdated. The PDF endpoint also refuses a snapshot mismatch (409).

## 1.3.4 — Input and panel fixes

- Loan lab number fields can be cleared and retyped: a value is applied only when it is a valid number within the
  limits, and leaving the field restores or clamps anything else (`NumInput`).
- The right-hand evidence panel sits below the sticky progress bar, fits the window and scrolls on its own; a newly
  opened citation starts at its top.

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
