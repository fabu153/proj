"""M01 / M02 — feature construction, purged chronological splits, train-only preprocessing."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.app.features.panel import panel_rows
from backend.app.features.feature_set import FEATURES, build_features
from backend.app.features.preprocess import Preprocessor
from training.ml.splits import SplitSpec, assign_splits

CF = json.loads((Path(__file__).parents[1] / "fixtures" / "demo_companyfacts.json").read_text())


def test_feature_count_within_blueprint_range():
    assert 20 <= len(FEATURES) <= 35


def test_features_have_no_inf_and_trends_need_consecutive_years():
    f = build_features(pd.DataFrame(panel_rows(CF)))
    assert not np.isinf(f[FEATURES].to_numpy(dtype=float)).any()
    assert np.isnan(f.iloc[0]["d_ebitda_margin"])            # first year: no t-1
    assert f.iloc[1]["d_ebitda_margin"] == pytest.approx(223 / 1180 - 205 / 1100)


def test_features_never_use_next_year():
    rows = panel_rows(CF)
    base = build_features(pd.DataFrame(rows))
    tampered = [dict(r) for r in rows]
    for k in ("v_revenue", "v_operating_income", "m_ebitda"):  # change the LAST year only
        tampered[2][k] = (tampered[2][k] or 0) * 10
    after = build_features(pd.DataFrame(tampered))
    pd.testing.assert_frame_equal(base.iloc[:2][FEATURES], after.iloc[:2][FEATURES])


def _toy():
    return pd.DataFrame({
        "cik": ["a"] * 5,
        "as_of_date": ["2017-03-01", "2018-03-01", "2019-03-01", "2020-03-01", "2021-03-01"],
        "label_available_date": ["2018-03-01", "2019-03-01", "2020-03-01", "2021-03-01", "2022-03-01"],
        "label_next_fy": [0, 1, 0, 1, 0]})


def test_purge_drops_rows_whose_label_crosses_the_boundary():
    s = assign_splits(_toy(), SplitSpec("2019-01-01", "2021-01-01", "2026-01-01"))
    # 2018 features have a label published 2019-03 (after val start) -> purged from train
    assert list(s) == ["train", "excluded", "val", "excluded", "test"]


def test_no_train_label_is_public_after_validation_starts():
    df = _toy()
    s = assign_splits(df, SplitSpec("2019-01-01", "2021-01-01", "2026-01-01"))
    assert (pd.to_datetime(df.loc[s == "train", "label_available_date"]) < "2019-01-01").all()


def test_preprocessor_fits_on_train_only_and_masks_missing():
    train = pd.DataFrame({"x": [1.0, 2.0, 3.0, np.nan, 100.0]})
    test = pd.DataFrame({"x": [1e6, np.nan]})
    pre = Preprocessor(["x"], 0.0, 0.75).fit(train)
    before = (pre.hi["x"], pre.median["x"], pre.mean["x"])
    out = pre.transform(test)
    assert (pre.hi["x"], pre.median["x"], pre.mean["x"]) == before   # transform never refits
    assert out["x__missing"].tolist() == [0.0, 1.0]
    assert out["x"].iloc[0] == pytest.approx((pre.hi["x"] - pre.mean["x"]) / pre.std["x"])   # clipped to train bound


def test_preprocessor_roundtrips_json():
    pre = Preprocessor(["x"]).fit(pd.DataFrame({"x": [1.0, 2.0, 3.0]}))
    again = Preprocessor.from_json(pre.to_json())
    df = pd.DataFrame({"x": [2.5, np.nan]})
    pd.testing.assert_frame_equal(pre.transform(df), again.transform(df))
