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

**Release v1.0.0** — 150 automated tests + 5 browser tests; every blueprint test ID passes (`docs/test_matrix.md`).
Demo: `docs/demo_script.md`, fallback video `release/creditlens_demo.mp4`, sample memos `docs/samples/`.

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

## Week 7–8 — quality and release

- `tests/end_to_end/` drives the full journeys in Chrome and runs axe-core WCAG 2.1 AA scans
  (`E2E_BASE_URL=http://localhost:3000 pytest tests/end_to_end`).
- `python scripts/test_matrix.py` regenerates `docs/test_matrix.md`; `docs/defects.md` logs 17 defects and their fixes.
- Security: upload type/size/page limits, no file persistence, retention purge, rate limits, security headers,
  `no-store` on uploads and memos, generic errors with a request reference, audit trail at `GET /audit`.
- `release/manifest.json` freezes 24 artifacts (data, model, configs, fixtures) by SHA-256;
  `tests/unit/test_release_manifest.py` fails if any changes. Re-freeze deliberately with
  `python scripts/freeze_release.py <version>`.
- `scripts/record_demo.py` re-records the captioned fallback video and the screenshots in `docs/screenshots/`.

## Deploy

| Part | Host | Setup |
|---|---|---|
| API | Render (`render.yaml`) | Blueprint from the repo; deploys after CI passes |
| Web | Vercel | Import the repo, **Root Directory = `frontend`**, project name `creditlens`, env `NEXT_PUBLIC_API_URL=<Render URL>` |

The API accepts browser calls from `https://creditlens*.vercel.app` (production and previews). If the Vercel
project has another name, add its URL to `CREDITLENS_CORS_ORIGINS` on Render.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-ml.txt
pytest -q                                        # 150 tests
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
