"""M03 / M04 — deployed neural model: numpy/torch parity, calibration contract, gating, drivers."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.app.features.feature_set import FEATURES, build_features
from backend.app.features.panel import panel_rows
from backend.app.models import risk
from backend.app.models.inference import ARTIFACT_DIR, StressModel

CF = json.loads((Path(__file__).parents[1] / "fixtures" / "demo_companyfacts.json").read_text())
pytestmark = pytest.mark.skipif(not (ARTIFACT_DIR / "weights.npz").exists(), reason="no trained artifact")


@pytest.fixture(scope="module")
def model():
    return StressModel.load()


def test_numpy_forward_matches_pytorch_logits(model):
    par = np.load(ARTIFACT_DIR / "parity.npz")
    np.testing.assert_allclose(model.logit_from_matrix(par["X"]), par["torch_logits"], atol=1e-6)


def test_probabilities_are_valid_and_monotone_in_logit(model):
    z = np.linspace(-6, 6, 25)
    p = model.calibrate(z)
    assert ((p > 0) & (p < 1)).all() and (np.diff(p) > 0).all()


def test_artifact_metadata_is_honest(model):
    m = model.meta
    assert m["target"] == "label_next_fy" and "probability of default" in m["not_for"]
    assert m["features"] == FEATURES and m["n_seeds"] == 5


def _row(rows, i=-1):
    panel = pd.DataFrame(rows)
    feats = build_features(panel)
    idx = feats.index[i]
    return feats.loc[[idx]], panel.loc[idx].to_dict()


def test_m04_small_company_is_withheld(model):
    rows = panel_rows(CF)
    for r in rows:
        r["v_revenue"] = 20.0
    row, prow = _row(rows)
    assert any("population" in g for g in model.gate(row, prow))


def test_m04_sparse_features_are_withheld(model):
    rows = panel_rows(CF)
    row, prow = _row(rows)
    row = row.copy()
    row.loc[:, FEATURES[:20]] = np.nan
    assert any("features unavailable" in g for g in model.gate(row, prow))


def test_drivers_are_sorted_and_described(model):
    row, _ = _row(panel_rows(CF))
    d = model.drivers(row)
    assert len(d) == 6 and all(x["description"] for x in d)
    mags = [abs(x["logit_contribution"]) for x in d]
    assert mags == sorted(mags, reverse=True)


def test_risk_service_scores_fixture_with_metadata():
    r = risk.score(CF, "2025-12-31")
    assert r["status"] == "scored" and 0 < r["probability"] < 1
    assert r["band"] in ("low", "elevated", "high") and "not a probability of default" in r["disclaimer"].lower()
    assert r["sample_period"].startswith("out-of-time")


def test_point_in_time_scoring_uses_only_visible_filings():
    r = risk.score(CF, "2024-12-31", as_of="2025-06-30")
    assert r["features_as_of"] <= "2025-06-30"
