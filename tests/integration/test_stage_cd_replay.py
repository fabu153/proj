"""Stages C and D (v1.2): Model X-Ray evidence and Historical Model Replay.

ML-01  the Model X-Ray serves every headline claim from frozen artifacts, XGBoost's higher point estimate included
ML-02  the neural score is separate from the deterministic loan stress tests (sliders never change it)
OUT-01 the replay forecast reveals nothing about the future until the outcome is requested
OUT-02 replay forecasts equal the frozen held-out predictions; cases are genuinely held-out and date-consistent
"""
import gzip
import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from backend.app import replay
from backend.app.api import main
from backend.app.api.main import app
from backend.app.labels.stress_label import stress_label
from backend.app.models.inference import StressModel

ROOT = Path(__file__).parents[2]
client = TestClient(app)
META = json.loads((ROOT / "backend/models/stress_mlp_v1/metadata.json").read_text())
XRAY = json.loads((ROOT / "backend/models/stress_mlp_v1/xray.json").read_text())
PRED = pd.read_csv(ROOT / "training/experiments/mlp_v1/test_predictions_label_next_fy.csv", dtype={"cik": str})
DATA = replay.data()
FUTURE_KEYS = {"label", "outcome", "category", "verdict", "assessment", "label_available_date", "conditions",
               "same_range_observed_rate"}


def keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from keys(v)


# ------------------------------------------------------------------ OUT-02 frozen predictions
def test_out02_saved_predictions_reproduce_the_frozen_evaluation():
    ref = META["test_metrics_calibrated"]
    y, p = PRED["y"].astype(int), PRED["mlp"]
    assert len(PRED) == ref["n"] and int(y.sum()) == ref["positives"] and set(PRED["split"]) == {"test"}
    assert average_precision_score(y, p) == pytest.approx(ref["pr_auc"], abs=1e-12)
    assert roc_auc_score(y, p) == pytest.approx(ref["roc_auc"], abs=1e-12)
    assert brier_score_loss(y, p) == pytest.approx(ref["brier"], abs=1e-8)
    assert average_precision_score(y, PRED["xgboost"]) == pytest.approx(META["xgboost_test_pr_auc"], abs=1e-12)


def test_out02_replay_forecasts_equal_frozen_model_and_saved_predictions():
    from training.ml.run_baselines import load_dataset
    df = load_dataset(yaml.safe_load((ROOT / "configs/experiment_baselines_v1.yaml").read_text()))
    model = StressModel.load()
    for c in DATA["cases"]:
        k = c["known"]
        row = df[(df["cik"] == k["cik"]) & (df["fiscal_year_end"] == k["fiscal_year_end"])]
        assert len(row) == 1
        p_now = float(model.predict_proba(row)[0])
        saved = PRED[(PRED["cik"] == k["cik"]) & (PRED["fiscal_year_end"] == k["fiscal_year_end"])].iloc[0]
        assert k["prediction"]["probability"] == pytest.approx(p_now, abs=1e-12)
        assert k["prediction"]["probability"] == pytest.approx(saved["mlp"], abs=1e-15)
        assert k["prediction"]["xgboost_probability"] == pytest.approx(saved["xgboost"], abs=1e-7)
        assert c["outcome"]["label"] == int(saved["y"])


def test_out02_cases_are_held_out_and_date_consistent():
    lo, hi = (date.fromisoformat(x) for x in META["data_windows"]["test_features_filed"])
    panel = pd.read_csv(ROOT / "training/data/panel_v1.csv", dtype={"cik": str}).set_index(["cik", "fiscal_year_end"])
    for c in DATA["cases"]:
        k, o = c["known"], c["outcome"]
        fye, asof, nfye, lab = (date.fromisoformat(x) for x in (k["fiscal_year_end"], k["features_as_of"],
                                                                 k["next_fiscal_year_end"], o["label_available_date"]))
        assert k["split"] == "test" and lo <= asof <= hi
        assert fye < asof < nfye < lab <= date.today()
        assert 20 <= (asof - fye).days <= 130 and 300 <= (lab - asof).days <= 430
        nxt = panel.loc[(k["cik"], o["fiscal_year_end"])]
        f = lambda c: None if pd.isna(nxt[c]) else float(nxt[c])  # noqa: E731
        rebuilt = stress_label({"operating_income": f("v_operating_income"), "interest_expense": f("v_interest_expense"),
                                "gross_debt": f("m_gross_debt"), "ebitda": f("m_ebitda"),
                                "operating_cash_flow": f("v_operating_cash_flow")})
        assert rebuilt.label == o["label"] == int(panel.loc[(k["cik"], k["fiscal_year_end"]), "label_next_fy"])


def test_out02_three_examples_cover_warning_false_alarm_and_miss():
    ex = sorted((c for c in DATA["cases"] if c["example"]), key=lambda c: c["example"])
    assert [c["example"] for c in ex] == [1, 2, 3]
    assert {c["category"] for c in ex} == {"correct_warning", "false_alarm", "missed"}
    for c in ex:
        p, y = c["known"]["prediction"]["probability"], c["outcome"]["label"]
        assert {"correct_warning": p >= 0.4 and y == 1, "false_alarm": p >= 0.4 and y == 0,
                "missed": p < 0.15 and y == 1}[c["category"]]


def test_out02_replay_export_is_reproducible(tmp_path, monkeypatch):
    from training.ml import export_replay
    monkeypatch.setattr(export_replay, "PRED_CSV", tmp_path / "pred.csv")
    monkeypatch.setattr(export_replay, "REPLAY", tmp_path / "replay.json")
    monkeypatch.chdir(ROOT)
    export_replay.main()
    again = json.loads((tmp_path / "replay.json").read_text())
    again["provenance"].pop("predictions_csv")
    frozen = json.loads(replay.REPLAY_FILE.read_text())
    frozen["provenance"].pop("predictions_csv")
    assert again == frozen
    assert (tmp_path / "pred.csv").read_bytes() == (ROOT / "training/experiments/mlp_v1/test_predictions_label_next_fy.csv").read_bytes()


# ------------------------------------------------------------------ OUT-01 no future in the forecast
def test_out01_forecast_endpoints_carry_no_outcome():
    ov = client.get("/replay").json()
    assert ov["split"] == "test" and ov["verification"]["all_checks_passed"] and len(ov["cases"]) == len(DATA["cases"])
    assert not FUTURE_KEYS & set(keys(ov))
    for c in DATA["cases"]:
        f = client.get(f"/replay/cases/{c['id']}").json()
        assert not FUTURE_KEYS & set(keys(f)), c["id"]
        text = json.dumps(f)
        assert c["outcome"]["label_available_date"] not in text and c["outcome"]["verdict"] not in text
        o = client.get(f"/replay/cases/{c['id']}/outcome").json()
        assert o["label"] == c["outcome"]["label"] and o["category"] == c["category"]


def test_out01_list_order_does_not_reveal_outcomes():
    names = [c["company_name"].lower() for c in client.get("/replay").json()["cases"]]
    assert names == sorted(names)


def test_unknown_replay_case_is_404():
    assert client.get("/replay/cases/nope").status_code == 404
    assert client.get("/replay/cases/nope/outcome").status_code == 404


# ------------------------------------------------------------------ ML-01 Model X-Ray evidence
def test_ml01_model_xray_supports_headline_claims():
    m = client.get("/model").json()
    md, held = m["metadata"], m["held_out"]
    assert round(md["test_metrics_calibrated"]["pr_auc"], 3) == 0.805 and round(md["test_metrics_calibrated"]["roc_auc"], 3) == 0.904
    assert round(md["test_metrics_calibrated"]["brier"], 3) == 0.113
    board = {r["model"]: r for r in m["xray"]["leaderboard"]}
    assert board["XGBoost"]["test_pr_auc"] > board["MLP ensemble (deployed)"]["test_pr_auc"]      # never hidden
    lo, hi = md["paired_mlp_minus_xgboost"]["ci95"]
    assert lo < 0 < hi
    assert held["error_analysis"]["confusion"] == {k: XRAY["threshold_test"][k] for k in ("tp", "fp", "fn", "tn")}
    bands = held["error_analysis"]["by_band"]
    assert sum(b["n"] for b in bands) == META["test_metrics_calibrated"]["n"]
    on = held["error_analysis"]["stressed_next_year"]
    assert on["already_stressed_in_t"]["n"] + on["new_stress_onset"]["n"] == META["test_metrics_calibrated"]["positives"]


def test_ml01_feature_groups_cover_every_model_input_once():
    groups = client.get("/model").json()["feature_groups"]
    names = [f["name"] for g in groups for f in g["features"]]
    assert names == META["features"] and len(names) == 31


# ------------------------------------------------------------------ ML-02 neural score vs loan stress tests
@pytest.fixture
def real_issuers(monkeypatch):
    data = {}
    for p in (ROOT / "backend/data/curated").glob("companyfacts_*.json.gz"):
        with gzip.open(p, "rt") as fh:
            d = json.load(fh)
        data[str(d["cik"]).zfill(10)] = d
    monkeypatch.setattr(main, "_curated", lambda: data)


def test_ml02_loan_stress_never_changes_the_neural_score(real_issuers):
    before = client.post("/analyses", json={"company_id": "0001278027"}).json()["risk_model"]["probability"]
    s = client.post("/scenarios", json={"company_id": "0001278027",
                                        "facility": {"amount": 500, "currency": "USD"},
                                        "shocks": [{"name": "Your case", "ebitda_shock": -0.5, "rate_shock_bps": 500}]})
    assert s.status_code == 200
    assert not {"probability", "risk_model", "band"} & set(keys(s.json()))
    after = client.post("/analyses", json={"company_id": "0001278027"}).json()["risk_model"]["probability"]
    assert before == after == pytest.approx(0.808225, abs=5e-7)
