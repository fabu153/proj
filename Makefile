# One-command reproduction of the CreditLens evaluation results. Everything runs on CPU; times are for 2 cores.
#
#   make setup            install the exact Python versions used (2-4 min)
#   make results          headline numbers, tables and figures from the committed experiment results (~1 min)
#   make experiments      re-run every evaluation from the frozen panel, then rebuild the results (~10 min)
#   make verify-training  re-train baselines + deployed network in a scratch folder; check bit-identical (~5 min)
#   make test             automated test suite (~1 min)
#   make data             rebuild the panel from SEC EDGAR (~15 min; needs SEC_USER_AGENT="Name email")

PY ?= python3

.PHONY: setup results experiments verify-training test data all

setup:
	$(PY) -m pip install -r requirements-repro.txt --extra-index-url https://download.pytorch.org/whl/cpu

results:
	$(PY) -m training.ml.results_summary

experiments:
	$(PY) -m training.ml.classic_scores --offline
	$(PY) -m training.ml.walk_forward
	$(PY) -m training.ml.economic_value
	$(PY) -m training.ml.robustness
	$(PY) -m training.ml.onset_watchlist
	$(PY) -m training.ml.supplementary_checks
	$(PY) -m training.ml.results_summary

verify-training:
	$(PY) -m scripts.verify_training

test:
	$(PY) -m pytest -q

data:
	@test -n "$$SEC_USER_AGENT" || (echo 'set SEC_USER_AGENT="Name contact-email" first' && exit 1)
	$(PY) -m training.pipeline.universe --target 600
	$(PY) -m training.features.build_panel --universe training/data/universe_v1.csv \
	  --out training/data/panel_v1.csv --report training/data/reports/coverage_v1.md
	$(PY) -m training.pipeline.cross_check

all: experiments verify-training test
