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
| 4 | PyTorch MLP, calibration, model card, `/predict` | next |
| 5–8 | Dashboard + loan lab UI, PDF/memo, QA, defence | planned |

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
The Week 4 neural model must beat these on validation before any claim is made.

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
training/
  pipeline/                 universe, coverage report, data dictionary, cross-check
  features/                 panel builder, feature set
  ml/                       splits, preprocessing, evaluation, baseline runner
  data/                     universe_v1.csv, panel_v1.csv, reports/
  experiments/baselines_v1/ frozen results, plots, preprocessors, test predictions
configs/                    frozen assumptions + experiment configs
docs/                       data dictionary, manual cross-check sheet
```

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-ml.txt
pytest -q                                        # 61 tests
uvicorn backend.app.api.main:app --reload        # http://localhost:8000/docs
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
