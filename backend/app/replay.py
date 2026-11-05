"""Historical Model Replay (Stage D): read-only, frozen held-out cases.

The data file is built by `python -m training.ml.export_replay` from the frozen test predictions. Each case is
split into what was KNOWN when the year-t 10-K was filed and the LATER OUTCOME. The forecast endpoints never
return outcome fields; the outcome has its own endpoint, so nothing about the future reaches the browser
until the analyst asks for it.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

REPLAY_FILE = Path(__file__).resolve().parents[1] / "data" / "replay" / "replay_v1.json"


@lru_cache
def data() -> dict:
    return json.loads(REPLAY_FILE.read_text())


def _case(case_id: str) -> dict:
    for c in data()["cases"]:
        if c["id"] == case_id:
            return c
    raise KeyError(case_id)


def overview() -> dict:
    d = data()
    v = d["verification"]
    return {
        "version": d["version"], "model": d["model"], "split": d["split"], "test_window": d["test_window"],
        "selection_rule": d["selection_rule"],
        "verification": {"rows": v["recomputed"]["n"], "pr_auc_recomputed": v["recomputed"]["pr_auc"],
                         "pr_auc_frozen": v["frozen"]["pr_auc"], "all_checks_passed": all(v["checks"].values())},
        # known-at-time fields only: no category, label, outcome date or verdict
        "cases": [{"id": c["id"], "example": c["example"], "company_name": c["known"]["company_name"],
                   "fiscal_year_end": c["known"]["fiscal_year_end"], "features_as_of": c["known"]["features_as_of"],
                   "probability": c["known"]["prediction"]["probability"], "band": c["known"]["prediction"]["band"]}
                  for c in d["cases"]],
    }


def forecast(case_id: str) -> dict:
    c = _case(case_id)
    return {"id": c["id"], "example": c["example"], **c["known"]}


def outcome(case_id: str) -> dict:
    c = _case(case_id)
    return {"id": c["id"], "category": c["category"], **c["outcome"]}


def model_evidence() -> dict:
    """Held-out error analysis for the Model X-Ray (aggregate only)."""
    d = data()
    return {"error_analysis": d["error_analysis"], "verification": d["verification"],
            "score_deciles": d["score_deciles"]}
