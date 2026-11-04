"""M01 — panel builder: features from t, labels from t+1 only, last year right-censored."""
import json
from pathlib import Path

from backend.app.features.panel import panel_rows

CF = json.loads((Path(__file__).parents[1] / "fixtures" / "demo_companyfacts.json").read_text())


def test_panel_rows_are_point_in_time_and_censored():
    rows = panel_rows(CF, {"sic": "3531", "size_quintile": 3})
    assert len(rows) == 3 and rows[0]["sic"] == "3531"
    for r in rows[:-1]:
        assert r["label_next_fy"] is not None
        assert r["label_available_date"] > r["as_of_date"]       # outcome observable only after prediction date
    assert rows[-1]["label_next_fy"] is None and rows[-1]["label_reason"] == "no_consecutive_t+1"


def test_panel_values_in_millions_and_first_growth_missing():
    r0, r2 = panel_rows(CF)[0], panel_rows(CF)[2]
    assert r2["v_revenue"] == 1240 and r2["m_ebitda"] == 238
    assert r0["m_revenue_growth"] is None
