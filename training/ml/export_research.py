"""Collect the neural-network research into one file for the Model X-Ray "Experimental research" section.

    python -m training.ml.export_research        # after the experiments; reads their saved results only

Writes backend/data/research/research_v1.json. This file is NOT a model artifact and NOT in the release manifest:
it reports experiments, none of which produces a score in the app. Overall-stress and onset-only results are kept
in separate tables because their populations and base rates differ (1,086 rows with a 30% base rate versus 727
rows with a 10% base rate), so their PR-AUCs cannot be compared with each other.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from training.ml.run_baselines import load_dataset
from training.ml.splits import SplitSpec, assign_splits

OUT = Path("backend/data/research/research_v1.json")
EXP = Path("training/experiments")


def _j(p):
    return json.loads(Path(p).read_text())


def paired(y, p_a, p_b, groups, n=1000, seed=7) -> dict:
    """PR-AUC(a) - PR-AUC(b) with a company-clustered paired bootstrap (same draws as the experiments)."""
    from sklearn.metrics import average_precision_score as ap
    rng = np.random.default_rng(seed)
    uniq = np.unique(groups)
    idx_by = {g: np.flatnonzero(groups == g) for g in uniq}
    d = []
    for _ in range(n):
        take = np.concatenate([idx_by[g] for g in rng.choice(uniq, size=len(uniq), replace=True)])
        if 0 < y[take].sum() < len(take):
            d.append(ap(y[take], p_a[take]) - ap(y[take], p_b[take]))
    return {"mean_diff": float(ap(y, p_a) - ap(y, p_b)),
            "ci95": [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))],
            "share_a_better": float(np.mean(np.array(d) > 0))}


def reconciliation() -> dict:
    """How the 1,086 held-out rows split by year-t status, and how the earlier 96-onset figure arises."""
    base = yaml.safe_load(Path("configs/experiment_baselines_v1.yaml").read_text())
    df = load_dataset(base)
    split = assign_splits(df, SplitSpec(**base["split"]))
    te = df[(split == "test") & df["label_next_fy"].notna()].reset_index(drop=True)
    pred = pd.read_csv(EXP / "mlp_v1/test_predictions_label_next_fy.csv", dtype={"cik": str})
    te = te.merge(pred[["cik", "fiscal_year_end", "mlp"]], on=["cik", "fiscal_year_end"], how="left")
    assert te["mlp"].notna().all()
    thr = _j("backend/models/stress_mlp_v1/xray.json")["threshold_test"]["threshold"]
    y, flag = te["label_next_fy"] == 1, te["mlp"] >= thr
    groups = {"already_stressed": te["stress_t"] == 1, "confirmed_healthy": te["stress_t"] == 0,
              "status_undetermined": te["stress_t"].isna()}
    assert (groups["confirmed_healthy"] == te["label_onset"].notna()).all()
    legacy = te["stress_conditions_t"].fillna(0) < 2

    def g(m):
        return {"rows": int(m.sum()), "stressed_next_year": int((m & y).sum()), "caught": int((m & y & flag).sum()),
                "false_alarms": int((m & ~y & flag).sum())}
    return {
        "test_rows": int(len(te)), "threshold": thr,
        "groups": {k: g(m) for k, m in groups.items()},
        "legacy_onset": {**g(legacy), "definition": "fewer than two stress conditions met in year t, counting a "
                                                    "condition that could not be checked as not met"},
        "explanation": "The earlier '15 of 96' counted 60 company-years whose year-t status could not be determined "
                       "(one condition met, others unreported) as healthy. Canonical onset = confirmed healthy only: "
                       "96 = 73 confirmed-healthy onsets + 23 undetermined; 15 caught = 6 + 9.",
    }


def main():
    mlp = _j(EXP / "mlp_v1/results.json")["results"]
    base = _j(EXP / "baselines_v1/results.json")["results"]
    hist = _j(EXP / "mlp_history_v1/results.json")
    gru = _j(EXP / "gru_history_v1/results.json")
    on = _j(EXP / "gru_onset_v1/results.json")
    wl = _j(EXP / "onset_watchlist_v1/results.json")
    m_nf, b_nf = mlp["label_next_fy"]["ensemble"], base["label_next_fy"]
    overall_n = {"rows": m_nf["test_calibrated"]["n"], "positives": m_nf["test_calibrated"]["positives"]}
    for r in (hist["test"]["history"], gru["test"]["gru"]):
        assert r["n"] == overall_n["rows"] and r["positives"] == overall_n["positives"], "overall rows differ"

    def row(model, kind, inputs, trained_on, pr, ci=None, diff=None, source="", note=None):
        return {"model": model, "kind": kind, "inputs": inputs, "trained_on": trained_on, "pr_auc": pr,
                "pr_auc_ci95": ci, "vs_deployed": diff, "source": source, "note": note}

    cl = _j(EXP / "classic_scores_v1/results.json")

    def classic_rows(pop):
        out_ = []
        for k, name, inputs in (("altman_z2", "Altman Z'' (1995)", "4 balance-sheet and profit ratios"),
                                ("ohlson_o", "Ohlson O (1980)", "9 ratios and indicators")):
            r = cl[pop][k]
            out_.append(row(name, "textbook", inputs, "original coefficients (not refitted)", r["pr_auc"],
                            r["pr_auc_ci95"], r["minus_deployed"], "classic_scores_v1",
                            note=f"{r['rows']:,} rows with all inputs ({r['coverage']:.0%}); network on them: "
                                 f"{r['deployed_on_same_rows']['pr_auc']:.3f}"))
        return out_

    overall = [
        row("Deployed network (stress_mlp_v1)", "deployed", "year t: 31 measures + missing flags", "all borrowers",
            m_nf["test_calibrated"]["pr_auc"], m_nf["test_bootstrap"]["pr_auc_ci95"], None, "mlp_v1"),
        row("Network + two prior years (MLP)", "experiment", "year t + lagged ratios for t-1, t-2", "all borrowers",
            hist["test"]["history"]["pr_auc"], hist["test_ci95"]["history"]["pr_auc_ci95"],
            hist["paired_history_minus_v1"], "mlp_history_v1"),
        row("General three-year GRU", "experiment", "sequence t-2, t-1, t", "all borrowers",
            gru["test"]["gru"]["pr_auc"], gru["test_ci95"]["gru"]["pr_auc_ci95"], gru["paired_gru_minus_v1"],
            "gru_history_v1"),
        row("XGBoost benchmark", "benchmark", "year t", "all borrowers", b_nf["xgboost"]["test"]["pr_auc"],
            b_nf["xgboost"]["test_bootstrap"]["pr_auc_ci95"],
            {k: -v if k == "mean_diff" else ([-v[1], -v[0]] if k == "ci95" else 1 - v)
             for k, v in mlp["label_next_fy"]["paired_vs_baselines"]["mlp_minus_xgboost"].items()}, "baselines_v1"),
        *classic_rows("overall"),
        row("No skill (base rate)", "reference", "-", "-", b_nf["no_skill"]["test"]["pr_auc"], None, None, "baselines_v1"),
    ]
    t, ci, pd_ = on["test"], on["test_ci95"], on["paired_gru_onset_minus"]
    onset = [
        row("Deployed network (stress_mlp_v1)", "deployed", "year t", "all borrowers", t["general_mlp_v1"]["pr_auc"],
            ci["general_mlp_v1"]["pr_auc_ci95"], None, "gru_onset_v1"),
        row("General three-year GRU", "experiment", "sequence t-2, t-1, t", "all borrowers",
            t["general_gru_history_v1"]["pr_auc"], ci["general_gru_history_v1"]["pr_auc_ci95"], None, "gru_onset_v1"),
        row("Onset-specific MLP", "experiment", "year t", "healthy borrowers only", t["mlp_onset"]["pr_auc"],
            ci["mlp_onset"]["pr_auc_ci95"], None, "mlp_v1 (reproduced in gru_onset_v1)"),
        row("Onset-specific GRU", "experiment", "sequence t-2, t-1, t (missing years skipped)", "healthy borrowers only",
            t["gru_onset"]["pr_auc"], ci["gru_onset"]["pr_auc_ci95"],
            {"mean_diff": pd_["general_mlp_v1"]["pr_auc_diff"], "ci95": pd_["general_mlp_v1"]["pr_auc_diff_ci95"],
             "share_a_better": pd_["general_mlp_v1"]["share_a_better_pr"]},               # GRU minus deployed
            "gru_onset_v1"),
        row("Onset XGBoost benchmark", "benchmark", "year t", "healthy borrowers only", t["xgboost_onset"]["pr_auc"],
            ci["xgboost_onset"]["pr_auc_ci95"], None, "baselines_v1"),
        *classic_rows("onset"),
        row("No skill (base rate)", "reference", "-", "-", t["no_skill"]["pr_auc"], None, None, "baselines_v1"),
    ]
    # paired difference against the deployed network on the same 727 rows, company-clustered (seed 7, 1,000 draws)
    tp = pd.read_csv(EXP / "gru_onset_v1/test_predictions.csv", dtype={"cik": str})
    cols = {"General three-year GRU": "general_gru_history_v1", "Onset-specific MLP": "mlp_onset",
            "Onset-specific GRU": "gru_onset", "Onset XGBoost benchmark": "xgboost_onset"}
    for r in onset:
        if r["model"] in cols:
            r["vs_deployed"] = paired(tp["y"].to_numpy(), tp[cols[r["model"]]].to_numpy(),
                                      tp["general_mlp_v1"].to_numpy(), tp["cik"].to_numpy())

    wl_rows = [{"rule": k, "threshold": wl["thresholds"][k], **{m: wl["test"][k][m] for m in
               ("flagged", "flag_rate", "caught", "missed", "false_alarms", "precision", "recall")},
                "recall_ci95": wl["test_ci95"][k]["recall"], "precision_ci95": wl["test_ci95"][k]["precision"]}
               for k in wl["thresholds"]]
    out = {
        "version": "research_v1",
        "status": "Experimental results. None of these models or thresholds produces a score in the app.",
        "test_window": "filed 2021-2025; already inspected in earlier experiments, so all comparisons are exploratory",
        "populations": {
            "overall": {"definition": "label_next_fy: at least two of three stress conditions in the next fiscal "
                                      "year; every held-out row", **overall_n},
            "onset": {"definition": "label_onset: confirmed not stressed in the filing year (status determinable) "
                                    "and next-year status determinable", "rows": on["cohort"]["test"]["rows"],
                      "positives": on["cohort"]["test"]["onsets"], "training_onsets": on["cohort"]["train"]["onsets"]},
        },
        "reconciliation": reconciliation(),
        "overall": overall,
        "onset": onset,
        "watchlist": {"population": wl["population"], "rows": wl_rows,
                      "recommendation": "Most promising onset improvement so far: a threshold flagging ~10% of healthy "
                                        "borrowers (set on validation) catches 33 of 73 onsets instead of 6, with "
                                        "precision 34%. Not deployed: validation had only 18 onsets and the test "
                                        "window was inspected before; confirm on fiscal-2026 outcomes first."},
        "findings": [
            "No experimental network beats the deployed one by a statistically clear margin on overall stress; the "
            "three-year GRU is +0.015 PR-AUC with an interval that includes zero.",
            "Training only on healthy borrowers made the networks worse, not better: 65 training onsets are too few.",
            "The deployed network already ranks new onsets about as well as the specialist models; its low onset recall "
            "comes from a single alert threshold set for a population where most stress is persistent.",
            "A separate watch-list threshold for healthy borrowers is the most promising next step (research only).",
            "The textbook scores (Altman Z'', Ohlson O) rank next-year stress clearly worse than the network: about "
            "0.18 lower PR-AUC on the same rows, with intervals well below zero.",
        ],
        "limitations": [
            "One held-out window (2021-25), inspected several times; no later outcomes yet.",
            "Accounting-stress proxy, not default; U.S. non-financial SEC filers with revenue of USD 50m or more.",
            "Onset results rest on 73 test onsets (65 in training, 18 in validation), so intervals are wide.",
        ],
        "sources": {k: f"training/experiments/{k}/" for k in
                    ("mlp_v1", "baselines_v1", "mlp_history_v1", "gru_history_v1", "gru_onset_v1", "onset_watchlist_v1",
                     "classic_scores_v1")},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, default=lambda x: float(x) if isinstance(x, np.floating) else x) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
