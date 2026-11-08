"""Research tests for training/experiments/gru_onset_v1 (not deployed). They check the cohort, the point-in-time
sequences, the missing-year handling and that the published numbers follow from the saved predictions."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from sklearn.metrics import average_precision_score

from backend.app.features.feature_set import build_features
from training.ml import onset_data as X
from training.ml.run_baselines import load_dataset
from training.ml.splits import SplitSpec, assign_splits

ROOT = Path(__file__).parents[2]
OUT = ROOT / "training/experiments/gru_onset_v1"


@pytest.fixture(scope="module")
def data():
    import os
    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        base = yaml.safe_load(Path("configs/experiment_baselines_v1.yaml").read_text())
        df = load_dataset(base)
        split = assign_splits(df, SplitSpec(**base["split"]))
        all_feats = build_features(pd.read_csv(base["panel"], dtype={"cik": str}))
    finally:
        os.chdir(cwd)
    return df, split, all_feats


def test_onset_cohort_is_canonical(data):
    df, split, _ = data
    sub = X.onset_cohort(df)
    assert (sub["stress_t"] == 0).all()                                   # confirmed not stressed in t
    assert df.loc[df["stress_t"].isna(), "label_onset"].isna().all()      # unknown status is excluded, not "healthy"
    assert df.loc[df["stress_t"] == 1, "label_onset"].isna().all()        # already stressed: excluded
    sp = split.loc[sub.index]
    sizes = {s: (int((sp == s).sum()), int(sub.loc[sp == s, "label_onset"].sum())) for s in ("train", "val", "test")}
    assert sizes == {"train": (886, 65), "val": (295, 18), "test": (727, 73)}


def test_history_is_point_in_time_and_consecutive(data):
    df, split, all_feats = data
    sub = X.onset_cohort(df)
    te = sub[split.loc[sub.index] == "test"]
    hist = X.history_index(te, all_feats)
    for (_, row), steps in zip(te.iterrows(), hist):
        assert 1 <= len(steps) <= 3 and steps[-1][0] == 0
        for back, idx in steps[:-1]:
            h = all_feats.loc[idx]
            assert h["cik"] == row["cik"]
            assert pd.Timestamp(h["as_of_date"]) <= pd.Timestamp(row["as_of_date"])       # already published
            days = (pd.Timestamp(row["fiscal_year_end"]) - pd.Timestamp(h["fiscal_year_end"])).days
            assert 330 * back <= days <= 400 * back                                          # the right prior year
        assert [b for b, _ in steps] == sorted([b for b, _ in steps], reverse=True)          # oldest first


def test_missing_years_are_never_read_as_data():
    """Whatever sits in the padded positions, the output is the same: missing years are skipped, not zero-filled."""
    torch = pytest.importorskip("torch")                  # CI installs no torch; runs where the experiment runs
    from training.ml.experiment_onset_gru import OnsetGRU
    torch.manual_seed(0)
    m = OnsetGRU(5).eval()
    x = torch.randn(4, 3, 5)
    lengths = torch.tensor([1, 2, 3, 2])
    junk = x.clone()
    for r, n in enumerate(lengths.tolist()):
        junk[r, n:] = 1e3
    assert torch.allclose(m(x, lengths), m(junk, lengths))
    # and a one-year company differs from a company whose two earlier years were all zeros
    z = torch.zeros(1, 3, 5)
    z[0, 2] = x[0, 0]
    assert not torch.allclose(m(x[:1], torch.tensor([1])), m(z, torch.tensor([3])))


def test_sequences_put_year_t_last_with_its_lag_feature():
    Z = np.arange(12, dtype=np.float32).reshape(3, 4)
    S, L = X.sequences([[(2, "a"), (0, "c")], [(0, "b")]], Z, {"a": 0, "b": 1, "c": 2})
    assert L.tolist() == [2, 1]
    assert S[0, 0, :-1].tolist() == Z[0].tolist() and S[0, 0, -1] == 1.0       # t-2 (a gap year t-1 is skipped)
    assert S[0, 1, :-1].tolist() == Z[2].tolist() and S[0, 1, -1] == 0.0       # year t last
    assert S[1, 0, :-1].tolist() == Z[1].tolist() and not S[1, 1:].any()


@pytest.mark.skipif(not (OUT / "results.json").exists(), reason="experiment not run")
def test_published_numbers_follow_from_saved_predictions():
    res = json.loads((OUT / "results.json").read_text())
    pr = pd.read_csv(OUT / "test_predictions.csv", dtype={"cik": str})
    assert res["status"].startswith("research only") and "already inspected" in res["test_set_status"]
    assert len(pr) == res["cohort"]["test"]["rows"] == 727 and pr["y"].sum() == 73
    for k, m in res["test"].items():
        assert abs(average_precision_score(pr["y"], pr[k]) - m["pr_auc"]) < 1e-6, k
    assert res["onset_mlp_reproduction"]["identical"]
    base = pd.read_csv(ROOT / "training/experiments/baselines_v1/test_predictions_label_onset.csv", dtype={"cik": str})
    assert pr[["cik", "fiscal_year_end"]].merge(base, how="left")["xgboost"].notna().all()     # same rows as baselines
    assert set(pr["years_of_history"]) <= {1, 2, 3}


def test_experiment_never_writes_to_the_app():
    src = (ROOT / "training/ml/experiment_onset_gru.py").read_text()
    assert "backend/models" not in src.split('"""', 2)[2] and "replay" not in src.split('"""', 2)[2].lower()
    assert 'OUT = Path("training/experiments/gru_onset_v1")' in src
