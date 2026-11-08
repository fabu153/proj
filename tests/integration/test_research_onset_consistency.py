"""v1.5: one canonical onset definition everywhere, the watch-list research, and the X-Ray research data.

Canonical onset population = label_onset: year-t status determinable and not stressed; t+1 determinable.
The frozen evaluation files (release manifest) keep their original numbers; these tests make sure every place that
reports onsets uses the canonical population, or labels the earlier figure as such.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).parents[2]
RESEARCH = ROOT / "backend/data/research/research_v1.json"
EXP = ROOT / "training/experiments"


@pytest.fixture(scope="module")
def research():
    return json.loads(RESEARCH.read_text())


@pytest.fixture(autouse=True)
def at_root(monkeypatch):
    monkeypatch.chdir(ROOT)


def test_reconciliation_of_96_and_73(research):
    rec = research["reconciliation"]
    g = rec["groups"]
    assert rec["test_rows"] == 1086 == sum(x["rows"] for x in g.values())
    assert (g["confirmed_healthy"]["rows"], g["confirmed_healthy"]["stressed_next_year"], g["confirmed_healthy"]["caught"]) == (727, 73, 6)
    assert (g["already_stressed"]["stressed_next_year"], g["already_stressed"]["caught"]) == (226, 214)
    assert (g["status_undetermined"]["rows"], g["status_undetermined"]["stressed_next_year"], g["status_undetermined"]["caught"]) == (60, 23, 9)
    legacy = rec["legacy_onset"]
    assert legacy["stressed_next_year"] == 96 == g["confirmed_healthy"]["stressed_next_year"] + g["status_undetermined"]["stressed_next_year"]
    assert legacy["caught"] == 15 == g["confirmed_healthy"]["caught"] + g["status_undetermined"]["caught"]
    assert sum(x["false_alarms"] for x in g.values()) == 84


def test_frozen_files_keep_their_original_numbers():
    """The replay file is frozen (release manifest): it still says 15 of 96, and the X-Ray labels that figure."""
    ea = json.loads((ROOT / "backend/data/replay/replay_v1.json").read_text())["error_analysis"]
    assert ea["stressed_next_year"]["new_stress_onset"] == {"n": 96, "caught": 15}
    assert ea["stressed_next_year"]["already_stressed_in_t"] == {"n": 226, "caught": 214}


def test_history_experiments_use_the_canonical_population():
    for name, caught in (("mlp_history_v1", ("v1_caught", 6)), ("gru_history_v1", ("v1_caught", 6))):
        r = json.loads((EXP / name / "results.json").read_text())
        assert r["onset_definition"] == "label_onset (canonical)"
        assert (r["onset"]["rows"], r["onset"]["stressed"]) == (727, 73) and r["onset"][caught[0]] == caught[1]
        assert (r["persistent"]["rows"], r["persistent"]["stressed"]) == (299, 226)
        assert (r["status_undetermined_in_t"]["rows"], r["status_undetermined_in_t"]["stressed"]) == (60, 23)


def test_research_file_matches_its_sources(research):
    on = json.loads((EXP / "gru_onset_v1/results.json").read_text())
    mlp = json.loads((EXP / "mlp_v1/results.json").read_text())["results"]["label_next_fy"]["ensemble"]
    o = {r["model"]: r for r in research["onset"]}
    assert o["Onset-specific GRU"]["pr_auc"] == on["test"]["gru_onset"]["pr_auc"]
    assert o["Onset-specific MLP"]["pr_auc"] == on["test"]["mlp_onset"]["pr_auc"]
    assert o["Deployed network (stress_mlp_v1)"]["pr_auc"] == on["test"]["general_mlp_v1"]["pr_auc"]
    v = {r["model"]: r for r in research["overall"]}
    assert v["Deployed network (stress_mlp_v1)"]["pr_auc"] == mlp["test_calibrated"]["pr_auc"]
    manifest = json.loads((ROOT / "release/manifest.json").read_text())
    assert v["Deployed network (stress_mlp_v1)"]["pr_auc"] == manifest["test_metrics"]["mlp_pr_auc"]
    assert v["XGBoost benchmark"]["pr_auc"] == manifest["test_metrics"]["xgboost_pr_auc"]
    # each table has exactly one deployed row, and the two populations are distinct and labelled
    for table in ("overall", "onset"):
        assert [r["kind"] for r in research[table]].count("deployed") == 1
    assert research["populations"]["overall"]["rows"] == 1086 and research["populations"]["onset"]["rows"] == 727
    assert "label_onset" in research["populations"]["onset"]["definition"]


def test_research_file_regenerates_identically(tmp_path, monkeypatch, research):
    from training.ml import export_research
    monkeypatch.setattr(export_research, "OUT", tmp_path / "r.json")
    export_research.main()
    assert json.loads((tmp_path / "r.json").read_text()) == research


def test_watchlist_thresholds_come_from_validation_scores_only():
    r = json.loads((EXP / "onset_watchlist_v1/results.json").read_text())
    pr = pd.read_csv(EXP / "onset_watchlist_v1/predictions.csv", dtype={"cik": str})
    va, te = pr[pr.split == "val"], pr[pr.split == "test"]
    assert (len(va), va.y.sum(), len(te), te.y.sum()) == (295, 18, 727, 73)
    for b in (5, 10, 15, 20):
        assert r["thresholds"][f"budget_{b}"] == pytest.approx(float(np.quantile(va.score, 1 - b / 100)), abs=1e-9)
    for k, t in r["thresholds"].items():
        flag = te.score >= t
        assert r["test"][k]["caught"] == int((flag & (te.y == 1)).sum())
        assert r["test"][k]["false_alarms"] == int((flag & (te.y == 0)).sum())
    assert r["test"]["original"]["caught"] == 6 and r["test"]["budget_10"]["caught"] == 33
    assert r["provenance"]["test_parity_max_abs_diff"] < 1e-9           # the frozen model, unchanged
    assert "not deployed" in r["status"]


def test_watchlist_is_not_in_the_app():
    src = (ROOT / "backend/app").rglob("*.py")
    assert not any("budget_10" in p.read_text() or "watchlist" in p.read_text().lower() for p in src)


def test_model_xray_serves_research_without_a_new_score():
    from backend.app.api.main import app
    body = TestClient(app).get("/model").json()
    r = body["research"]
    assert r["reconciliation"]["groups"]["confirmed_healthy"]["caught"] == 6
    assert "None of these" in r["status"]
    assert body["held_out"]["error_analysis"]["stressed_next_year"]["new_stress_onset"]["n"] == 96   # frozen, labelled in UI


def test_docs_no_longer_present_15_of_96_as_current():
    for p in ("docs/demo_script.md", "scripts/record_demo.py", "docs/defects.md"):
        assert "15 of 96 new" not in (ROOT / p).read_text(), p
    for p in ("README.md", "training/model_card/stress_mlp_v1.md", "training/experiments/HISTORY_EXPERIMENT.md"):
        for para in (ROOT / p).read_text().split("\n\n"):              # a mention must say it is the earlier figure
            if "of 96" in para:
                assert any(w in para.lower() for w in ("earlier", "before v1.5", "until v1.4")), (p, para[:120])
