# CreditLens AI

Evidence-linked credit analyst copilot — IE Master in Finance, AI in Finance capstone.

> Decision support only. Outputs are an **indicative next-fiscal-year accounting-stress screen**,
> not a probability of default, not a credit rating, and never a loan approval. Analyst review required.

## Status

| Week | Deliverable | State |
|---|---|---|
| 1 | Metric dictionary, EUR 100m loan/stress engine, XBRL normalizer, API, tests | ✅ |
| 2 | 600-company survivorship-aware universe, 5,850 company-year panel, coverage report + label audit, data dictionary, frames cross-check | ✅ |
| 3 | 31 leak-safe features, purged chronological split, train-only preprocessing, 4 baselines, frozen test results | ✅ |
| 4 | PyTorch MLP (8 configs × 5 seeds), Platt calibration, paired comparison, model card, `/predict`, `/model` | ✅ |
| 5 | Next.js analyst workspace (ledger, evidence rail, trends, neural screen, loan lab), Model X-Ray page, Excel reconciliation of 8 loan cases | ✅ |
| 6 | Annual-report upload with page-cited extraction and review gate; evidence-checked credit memo; PDF export | ✅ |
| 7 | Browser E2E tests, WCAG 2.1 AA scans, security hardening, test matrix, defect log | ✅ |
| 8 | Frozen v1.0.0 (checksummed), demo script, fallback video, sample memos, defence deck | ✅ |
| v1.6 | Peer percentiles; debt maturity wall and liquidity runway; Altman Z″ and Ohlson O as textbook benchmarks | ✅ |
| v1.5 | Canonical onset statistics; watch-list threshold research; Experimental research in Model X-Ray | ✅ |
| v1.4 | Search any U.S. public company (server-side SEC, five clear outcomes); fiscal-year columns by heading; negative-EBITDA stress; PASS / BREACH / NOT TESTABLE covenants; no outdated memo export | ✅ |
| v1.3 | Stage E finished memo (header block, compact sections, semantic sentence checks), source trails for four headline figures, three-minute demo; Stage F stress heatmap from the Python engine | ✅ |
| v1.2 | Stage C Model X-Ray in three layers (what it learned, how it performed, where it fails) and Stage D Historical Model Replay on frozen held-out predictions | ✅ |
| v1.1 | Stage A financial correctness (10-K reconciliation, refinancing, restricted cash, currency gating, review completeness) and Stage B workflow (start page, shared analysis snapshot, review summary, loading/stale states) | ✅ |

**Release v1.6.0** — 323 automated tests + 20 browser tests, 343 passed, 0 failed (`docs/test_matrix.md`; browser tests run against mocked SEC).
Model artifacts unchanged since v1.0.0; see `CHANGELOG.md` for what changed and why.
Demo: `docs/demo_script.md`, fallback video `release/creditlens_demo.mp4`, sample memos `docs/samples/`.

> Course demo. Use public company filings and sample data only; do not upload confidential documents.

## Week 2–3 headline results

Panel: 549 companies with filings, 5,850 company-years (FY2007–2026). Pipeline period selection agrees with SEC's
own calendar frames on **99.4–99.7%** of 2,560 tag-consistent comparisons; 8.9% of values were later restated,
which is why the panel keeps the **original** vintage.

Model population (decided at the Week-2 gate, before fitting): year-t revenue ≥ USD 50m, scorable, ≥ 4/7 critical
facts. Split by filing date with purge: train 2009–2018, validation 2019–2020, **test 2021–2025 (evaluated once)**.

| next-FY stress (test prevalence 29.7%) | PR-AUC (95% CI, company bootstrap) | ROC-AUC |
|---|---|---|
| no-skill | 0.297 | 0.500 |
| rule score (stress conditions in year t) | 0.716 (0.656–0.773) | 0.870 |
| logistic regression | 0.813 (0.758–0.861) | 0.903 |
| XGBoost | **0.825** (0.772–0.870) | **0.906** |

Onset of stress (firms not stressed in year t, test prevalence 10.0%): XGBoost PR-AUC 0.346 vs rule 0.206 —
the harder, more useful monitoring target. Full report: `training/experiments/baselines_v1/report.md`.

## Week 4 — neural model

| next-FY stress, same test rows | PR-AUC (95% CI) | ROC-AUC | Brier |
|---|---|---|---|
| **MLP ensemble, calibrated (deployed)** | 0.805 (0.752–0.853) | 0.904 | 0.113 |
| XGBoost | 0.825 (0.772–0.870) | 0.906 | 0.109 |
| logistic regression | 0.813 (0.758–0.861) | 0.903 | 0.114 |
| rule score | 0.716 (0.656–0.773) | 0.870 | 0.116 |

Paired, company-clustered bootstrap: MLP − XGBoost = −0.020 (95% CI −0.044 to +0.006), i.e. not reliably
different; MLP − rule = +0.090 (+0.061 to +0.120). The network is deployed because the course requires deep
learning; XGBoost is shown beside it as the benchmark, and the model card says so. Report:
`training/experiments/mlp_v1/report.md`; card: `training/model_card/stress_mlp_v1.md`.

The API runs the network in **numpy** from exported weights (parity with PyTorch tested to 1e-6), so the
deployed image needs no PyTorch. Scores are withheld for company-years outside the model's population or with
too many missing inputs (test M04).

## Week 5 — analyst workspace

`frontend/` (Next.js 15): company and fiscal-year picker; a ledger of 12 credit metrics over 4 years where every
row opens its formula, inputs and source 10-K accession; trend charts; the neural screen with drivers; the loan
lab (facility, FX, use of proceeds, coupon, amortization, stress sliders, covenants) with covenant headroom rulers
and an audit trail of every step; and a Model X-Ray page. All numbers come from the API.

`docs/scenario_crosscheck.xlsx` recomputes 8 loan cases with independent Excel formulas (LibreOffice-recalculated);
`tests/unit/test_scenario_crosscheck.py` requires the engine to match it to 1e-9.

## Repository map

```
backend/app/
  finance/metrics.py        deterministic ratio engine (p.08)
  scenarios/loan.py         sources & uses, FX, rate/EBITDA shocks, covenants (p.09, p.13)
  documents/xbrl.py         SEC XBRL -> point-in-time canonical facts, derivation rules R1-R4
  documents/sec_client.py   throttled, cached EDGAR client
  labels/stress_label.py    pre-registered 2-of-3 stress label
  api/main.py               FastAPI: /companies /analyses /scenarios
backend/data/curated/       real demo issuers: Procter & Gamble, United Rentals, B&G Foods
backend/models/stress_mlp_v1 deployed network: weights, preprocessor, calibrator, X-Ray exhibits
backend/app/features/       panel row, features, preprocessing shared by training and the API
frontend/                   Next.js analyst workspace and Model X-Ray
training/
  pipeline/                 universe, coverage report, data dictionary, cross-check
  features/                 panel builder, feature set
  ml/                       splits, preprocessing, evaluation, baseline runner
  data/                     universe_v1.csv, panel_v1.csv, reports/
  experiments/baselines_v1/ frozen results, plots, preprocessors, test predictions
configs/                    frozen assumptions + experiment configs
docs/                       data dictionary, manual cross-check sheet
```

## Week 6 — annual reports and the credit memo

**Upload** (`/upload`, `POST /documents/upload`): text-based PDFs of U.S.-style primary statements. The parser finds
the three statements, detects scale, currency and fiscal year-end, reads the latest two years, and cites the page and
source line of every figure with a confidence level. With a CIK, figures are cross-checked against SEC XBRL. Analysis
is blocked until every critical figure that is not high-confidence has been accepted, corrected or rejected. Reviewed
figures then run through the same engines and model as SEC data. The PDF is parsed in memory and never stored; extracted
figures expire after 24 hours or on `DELETE /documents/{id}`. Tested on two layouts (`tests/fixtures/*.pdf`, rendered
from real reported figures); both reproduce SEC XBRL values exactly.

**Memo** (`POST /memos`, PDF at `/memos/{id}/pdf`): built from a `CreditAnalysisPackage` of ~45 sourced items. Writers
place `{{item}}` references and never type numbers; a validator flags untraceable figures, uncited claims and
rating/PD/approval language, and flagged sentences are left out of the PDF. Analyst edits are re-checked the same way.
Without an API key the memo is written from templates; to use a language model set on Render:

| Variable | Value |
|---|---|
| `CREDITLENS_LLM_PROVIDER` | `anthropic` (default) or `openai` |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | your key (Render environment only, never the repo) |
| `CREDITLENS_LLM_MODEL` | optional for Anthropic (default `claude-sonnet-5-5`); required for OpenAI |

Only the package (labels, formatted values, source descriptions) is sent to the provider, never an uploaded document.

## v1.6 — Credit-analyst views

- **Peers.** Each ledger ratio shows its percentile among comparable companies (same SIC group and fiscal year,
  widened until there are 15 peers). It is descriptive only.
- **Debt maturities.** Principal due by year from the 10-K schedule, a liquidity runway, and how many years cash
  plus free cash flow covers. Every figure links to its filing.
- **Textbook scores.** Altman Z″ and Ohlson O sit beside the neural screen as references. On the held-out years
  they rank stress clearly worse than the network (Model X-Ray, section 4).
- **Not built: "Ask the filing" chat.** The production API has no LLM key: memos use the deterministic template
  writer, by design and at no cost. A chat would need a paid key, per-question cost, rate limits and defences
  against prompt injection. Most "why did X change" questions are already answered by the year columns, the
  formula and source trail behind every figure, and the memo. If an LLM is added later, the validator and
  `{{item}}` references already enforce the rule that no number is invented.

## v1.5 — Onset research (Model X-Ray, section 4)

- **One onset definition.** "New stress" always means the canonical `label_onset` population: confirmed not
  stressed in the filing year. The deployed network catches 6 of those 73 onsets at its threshold. The figure
  quoted before v1.5, "15 of 96", also counted 60 company-years whose status could not be determined.
- **Onset-specific GRU** (`training/experiments/gru_onset_v1/report.md`): test PR-AUC 0.254 against 0.319 for the
  deployed network on the same 727 rows; not deployed.
- **Watch-list threshold** (`training/experiments/onset_watchlist_v1/report.md`): flagging the top ~10% of healthy
  borrowers by the deployed score catches 33 of 73 onsets instead of 6. Research only; to be confirmed on
  fiscal-2026 outcomes.
- **Model X-Ray** shows all of this in an *Experimental research* section, with overall-stress and onset-only
  results in separate tables and deployed versus experimental models marked. No new score in the app.

## v1.4 — Any U.S. public company

- **Search.** Type a name, ticker or CIK on the start page. The API searches SEC's company list and, when you pick
  one, loads its XBRL companyfacts server side (`/companies/search`, `/companies/resolve`; the browser never calls
  SEC). The filings go through the same pipeline as the samples, with accession links and source trails.
- **Honest coverage.** The workspace says whether the company is fully analysable, has metrics unavailable, is
  outside the network's population (financials, shells, too little data), has no U.S. GAAP statements, or could not
  be loaded because SEC is unavailable or rate-limiting. Nothing missing is estimated.
- **Setting.** `SEC_USER_AGENT` must contain a contact email (SEC refuses the company list otherwise); it is set in
  `render.yaml`. `CREDITLENS_SEC_FIXTURES=tests/fixtures/sec` serves mocked SEC responses for tests and offline demos.
- **Fixes.** Year columns mapped by heading; negative EBITDA shocked by its size; explicit covenant states; PDF
  export only for a memo that matches the loan lab (`CHANGELOG.md`, `docs/defects.md` DF-40 to DF-46).

## v1.3 — Stages E and F

- **Memo.** It opens with borrower, fiscal year, facility, purpose and review status. It has compact sections
  including a stress-case table and signed covenant headroom. Every sentence is checked for direction, headroom
  sign, undefined ratios and mixed stress cases, on top of number reconciliation.
- **Source trails.** Click EBITDA, net debt, net debt / EBITDA or EBITDA / interest in the memo to see the SEC
  accession or report page, the normalized fact, the calculation and the sentence. The PDF prints the same trails.
- **Stress heatmap.** `POST /scenarios/grid` runs `run_scenario` once per cell (EBITDA −50% to +10% by rates 0 to
  +500 bp). Click a cell to load it into the loan lab.

## v1.2 — Stages C and D

- **Model X-Ray (`/model`).** Three layers: what the network learned (target, input groups, architecture, data
  windows), how it performed (PR-AUC 0.805, ROC-AUC 0.904, Brier 0.113, matched baselines with XGBoost's higher
  point estimate stated) and where it fails. The network caught 214 of 226 persisting cases but only 6 of 73 new
  stress onsets from confirmed-healthy accounts (written "15 of 96" before v1.5, see below), and 66 of its 84 false
  alarms were recoveries.
- **Historical Model Replay (`/replay`).** Held-out 2021–25 company-years show the frozen forecast first. The
  next-year outcome is revealed on request, from `GET /replay/cases/{id}/outcome`. The forecast endpoints carry no
  outcome fields.
- **Frozen predictions.** `python -m training.ml.export_replay` re-scores the frozen test rows with the frozen
  network. It writes `training/experiments/mlp_v1/test_predictions_label_next_fy.csv` and
  `backend/data/replay/replay_v1.json` only if they reproduce the recorded metrics exactly.

## v1.1 — Stages A and B

- **Two value bases.** Ratios, loan scenarios and the memo use the *credit basis*. It applies the 10-K
  reconciliation rules R5 (unrestricted cash), R6 (total D&A) and R7 (income-statement interest). The neural screen
  uses the *model basis*, which is exactly its training inputs, so its frozen evaluation stays valid
  (`docs/manual_cross_check.md`).
- **Loan engine 1.1.0.** Refinancing retires debt at the entered rate or the average cost of debt. Inputs that
  contradict the reported figures are refused with a reason, never clamped.
- **Uploads.** Currency, units and year-end must be confirmed when the report does not state them. Missing
  critical figures can be entered from the report (with page) or marked unavailable. Non-USD figures get no
  neural score. Uploads are visible only through their own link. `GET /audit` needs `x-admin-token`
  (`CREDITLENS_ADMIN_TOKEN`).
- **Analysis snapshot.** `POST /scenarios` returns `snapshot.id`, the SHA-256 of the canonical inputs (first
  12 hex digits). `POST /memos` with the same inputs, including `shocks`, carries the same id. The UI marks a memo
  "Outdated — regenerate" when the ids differ. The PDF prints every assumption and the id.
- **Workflow.** The start page (`/`) leads to the workspace (`/workspace`) with a progress cue. The site waits
  visibly for a sleeping API, with retries and "Try again". Stale results are dimmed and labelled.

## Week 7–8 — quality and release

- `tests/end_to_end/` drives the full journeys in Chrome and runs axe-core WCAG 2.1 AA scans
  (`E2E_BASE_URL=http://localhost:3000 pytest tests/end_to_end`).
- `python scripts/test_matrix.py` regenerates `docs/test_matrix.md`; `docs/defects.md` logs 37 defects and their fixes.
- Security: upload type/size/page limits, no file persistence, retention purge, rate limits, security headers,
  `no-store` on uploads and memos, generic errors with a request reference, operator-only audit trail at `GET /audit`.
- `release/manifest.json` freezes 27 artifacts (data, model, configs, fixtures) by SHA-256;
  `tests/unit/test_release_manifest.py` fails if any changes. Re-freeze deliberately with
  `python scripts/freeze_release.py <version> "<reason>"` (it refuses if model artifacts changed).
- `scripts/record_demo.py` re-records the captioned fallback video and the screenshots in `docs/screenshots/`.

## Deploy

| Part | Host | Setup |
|---|---|---|
| API | Render (`render.yaml`) | Blueprint from the repo; deploys after CI passes |
| Web | Vercel | Import the repo, **Root Directory = `frontend`**, project name `creditlens`, env `NEXT_PUBLIC_API_URL=<Render URL>` |

The browser calls `/api/...` on the site's own domain; `frontend/next.config.mjs` forwards those requests to
`NEXT_PUBLIC_API_URL` (a Vercel external rewrite), so ad blockers that block `onrender.com` do not break the site.
The API also accepts direct browser calls from `https://creditlens*.vercel.app` (production and previews). If the Vercel
project has another name, add its URL to `CREDITLENS_CORS_ORIGINS` on Render.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-ml.txt
pytest -q                                        # 323 tests (+20 browser tests with E2E_BASE_URL)
uvicorn backend.app.api.main:app --reload        # http://localhost:8000/docs
cd frontend && npm install && npm run dev        # http://localhost:3000
```

Reproduce the data and experiment (≈15 min, hits SEC EDGAR politely):

```bash
export SEC_USER_AGENT="CreditLens-Capstone <your contact email>"
python -m training.pipeline.universe --target 600
python -m training.features.build_panel --universe training/data/universe_v1.csv \
  --out training/data/panel_v1.csv --report training/data/reports/coverage_v1.md
python -m training.pipeline.cross_check
python -m training.ml.run_baselines --config configs/experiment_baselines_v1.yaml
```

## Design rules enforced in code

- **No LLM arithmetic.** Every number comes from a versioned Python function with its inputs attached.
- **Missing is not zero.** Unavailable inputs return `not_available`; meaningless ratios return `undefined`;
  undeterminable labels are dropped, never set to 0.
- **Point-in-time.** Features are usable from the filing date; labels carry their own publication date; splits purge
  any training label published after the next window starts.
- **Train-only preprocessing.** Winsorization bounds, medians and scalers are fitted on train and frozen to JSON.
- **Leases** are excluded from gross debt where tags allow; bundled tags and cash-interest fallbacks are flagged.

Infrastructure note: before deploying beyond a student demo, consider a review with IE Cloud Services.
