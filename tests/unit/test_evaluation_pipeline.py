"""Evaluation pipeline: walk-forward folds cannot leak, review budgets are applied per year, and the walk-forward
predictions are out-of-sample exactly once."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from training.ml.splits import walk_forward_masks

ROOT = Path(__file__).resolve().parents[2]


def _rows():
    rng = np.random.default_rng(0)
    asof = pd.to_datetime("2009-01-01") + pd.to_timedelta(rng.integers(0, 365 * 17, 4000), unit="D")
    lag = pd.to_timedelta(rng.integers(200, 800, 4000), unit="D")
    lab = pd.Series(asof + lag)
    lab[rng.random(4000) < 0.1] = pd.NaT                       # outcome not observable
    return pd.DataFrame({"as_of_date": asof, "label_available_date": lab})


@pytest.mark.parametrize("year", range(2016, 2026))
def test_walk_forward_fold_has_no_look_ahead(year):
    df = _rows()
    tr, va, te = walk_forward_masks(df, year, 2)
    asof, lab = pd.to_datetime(df["as_of_date"]), pd.to_datetime(df["label_available_date"])
    v0, t0 = pd.Timestamp(f"{year - 2}-01-01"), pd.Timestamp(f"{year}-01-01")
    assert not (tr & va).any() and not (tr & te).any() and not (va & te).any()
    assert (lab[tr] < v0).all() and (asof[tr] < v0).all()          # every training outcome known before validation
    assert (lab[va] < t0).all() and (asof[va] >= v0).all()         # every validation outcome known before test
    assert (asof[te].dt.year == year).all() and lab[te].notna().all()
    assert tr.sum() > 0 and va.sum() > 0 and te.sum() > 0


def test_review_budget_is_applied_within_each_year_and_skips_unscored_rows():
    from training.ml.economic_value import flags
    df = pd.DataFrame({"year": [2020] * 10 + [2021] * 20,
                       "mlp": list(np.linspace(0, 1, 10)) + list(np.linspace(0, 1, 20)),
                       "altman_z2": [np.nan] * 5 + list(np.linspace(0, 1, 25))})
    f = flags(df, "mlp", 0.10)
    assert f[:10].sum() == 1 and f[9]                                # top 10% of 2020 = 1 row, the riskiest
    assert f[10:].sum() == 2 and f[28] and f[29]                     # top 10% of 2021 = 2 rows
    g = flags(df, "altman_z2", 0.5)
    assert not g[:5].any()                                           # rows without a score are never reviewed


def test_walk_forward_predictions_are_out_of_sample_once_per_company_year():
    p = pd.read_csv(ROOT / "training/experiments/walk_forward_v1/oos_predictions.csv", dtype={"cik": str})
    assert not p.duplicated(["cik", "fiscal_year_end"]).any()
    assert set(p["test_year"]) == set(range(2016, 2026))
    assert (pd.to_datetime(p["as_of_date"]).dt.year == p["test_year"]).all()
