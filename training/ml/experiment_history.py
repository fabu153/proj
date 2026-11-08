"""Experiment (NOT deployed): does adding the two prior years of accounts help the stress network?

    python -m training.ml.experiment_history

The deployed network (stress_mlp_v1) sees year t plus five one-year changes. This experiment adds, for eight key
ratios, their values in t-1 and t-2, plus four multi-year summaries. Everything else is identical to mlp_v1:
the same rows and row filters, the same chronological split and purge, train-only preprocessing, the same
8 configurations x 5 seeds chosen on 2019-20 validation PR-AUC, Platt calibration on validation, and one
evaluation on the same 1,086 held-out test rows, paired row-for-row with the frozen v1 predictions.

Point-in-time rule: a prior year is used only if it is the consecutive fiscal year of the same company AND its
features were already public when year t was filed (its as_of_date <= year t's as_of_date). Nothing here writes
to backend/models; results go to training/experiments/mlp_history_v1/.
"""
from __future__ import annotations

import itertools
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import yaml
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from backend.app.features.feature_set import FEATURES, build_features
from backend.app.features.preprocess import Preprocessor
from training.ml.evaluate import calibration_table, cluster_bootstrap, max_f1_threshold, point_metrics, threshold_metrics
from training.ml.mlp import logits, train_one
from training.ml.splits import SplitSpec, assign_splits
from training.ml.train_mlp import grouped_holdout, paired_bootstrap, sigmoid

OUT = Path("training/experiments/mlp_history_v1")
TARGET = "label_next_fy"
LAGGED = ["ebitda_margin", "operating_margin", "cfo_to_assets", "gross_leverage", "debt_to_assets",
          "ebit_interest_cover", "current_ratio", "stress_conditions_t"]
SUMMARIES = {
    "years_stressed_prior2": "number of the two prior years with 2+ stress conditions",
    "years_negative_cfo_3y": "years with negative operating cash flow in t, t-1, t-2",
    "ebitda_margin_slope_3y": "(EBITDA margin t - EBITDA margin t-2) / 2",
    "ebitda_margin_vol_3y": "standard deviation of EBITDA margin over t, t-1, t-2",
}
HISTORY_FEATURES = [f"{k}_lag{n}" for k in LAGGED for n in (1, 2)] + list(SUMMARIES)
ALL_FEATURES = FEATURES + HISTORY_FEATURES


def add_history(feats: pd.DataFrame) -> pd.DataFrame:
    """Lagged values from the same company's consecutive prior years, only if already public at year t."""
    f = feats.sort_values(["cik", "fiscal_year_end"]).copy()
    fye, asof = pd.to_datetime(f["fiscal_year_end"]), pd.to_datetime(f["as_of_date"])
    lagged = {}
    for n in (1, 2):
        same = f["cik"] == f["cik"].shift(n)
        gap = (fye - fye.shift(n)).dt.days
        ok = same & gap.between(330 * n, 400 * n) & (asof.shift(n) <= asof)
        lagged[n] = ok
        for k in LAGGED:
            f[f"{k}_lag{n}"] = f[k].shift(n).where(ok)
    stressed = lambda s: (s >= 2).astype(float).where(s.notna())  # noqa: E731
    f["years_stressed_prior2"] = pd.concat([stressed(f["stress_conditions_t_lag1"]),
                                            stressed(f["stress_conditions_t_lag2"])], axis=1).sum(axis=1, min_count=1)
    cfo_neg = lambda s: (s < 0).astype(float).where(s.notna())  # noqa: E731
    f["years_negative_cfo_3y"] = pd.concat([cfo_neg(f["cfo_to_assets"]), cfo_neg(f["cfo_to_assets_lag1"]),
                                            cfo_neg(f["cfo_to_assets_lag2"])], axis=1).sum(axis=1, min_count=1)
    f["ebitda_margin_slope_3y"] = (f["ebitda_margin"] - f["ebitda_margin_lag2"]) / 2
    f["ebitda_margin_vol_3y"] = f[["ebitda_margin", "ebitda_margin_lag1", "ebitda_margin_lag2"]].std(axis=1, skipna=False)
    return f            # keep build_features' row order: it decides mini-batches and the early-stopping holdout


def load(base_cfg: dict) -> pd.DataFrame:
    """Same row filters as training/ml/run_baselines.load_dataset; history added before filtering."""
    panel = pd.read_csv(base_cfg["panel"], dtype={"cik": str})
    rf = base_cfg["row_filters"]
    feats = add_history(build_features(panel))
    rev = panel["v_revenue"]
    feats = feats[rev.loc[feats.index] >= rf["min_revenue_usd_m"]]
    feats = feats[feats["scorable"] == 1]
    feats = feats[feats["critical_coverage"] >= rf.get("min_critical_coverage", 0)]
    return feats.reset_index(drop=True)


def main(features: list[str] | None = None, out: Path = OUT):
    """features=None: v1 inputs + history. features=FEATURES: control run that must reproduce the deployed model."""
    features = features or ALL_FEATURES
    t0 = time.time()
    torch.set_num_threads(4)
    base_cfg = yaml.safe_load(Path("configs/experiment_baselines_v1.yaml").read_text())
    cfg = yaml.safe_load(Path("configs/experiment_mlp_v1.yaml").read_text())
    tcfg = cfg["training"]
    df = load(base_cfg)
    split = assign_splits(df, SplitSpec(**base_cfg["split"]))
    sub = df[df[TARGET].notna()]
    sp = split.loc[sub.index]
    tr, va, te = sub[sp == "train"], sub[sp == "val"], sub[sp == "test"]
    yva, yte = va[TARGET].astype(int).to_numpy(), te[TARGET].astype(int).to_numpy()

    v1 = pd.read_csv("training/experiments/mlp_v1/test_predictions_label_next_fy.csv", dtype={"cik": str})
    key = te[["cik", "fiscal_year_end"]].reset_index(drop=True).merge(v1, on=["cik", "fiscal_year_end"], how="left")
    assert key["mlp"].notna().all() and len(key) == len(te) and (key["y"].to_numpy() == yte).all(), \
        "test rows differ from the deployed model's: not a paired comparison"

    coverage = {k: {"train": float(tr[k].notna().mean()), "test": float(te[k].notna().mean())}
                for k in ("ebitda_margin_lag1", "ebitda_margin_lag2", "stress_conditions_t_lag2")}

    pre = Preprocessor(features, base_cfg["preprocessing"]["winsor_lower_q"],
                       base_cfg["preprocessing"]["winsor_upper_q"]).fit(tr)
    Xtr_all, Xva, Xte = (pre.transform(d).to_numpy() for d in (tr, va, te))
    hold = grouped_holdout(tr, tcfg["early_stop_holdout"])
    ytr = tr[TARGET].astype(int).to_numpy()

    search, models = [], {}
    for lr, wd, pw in itertools.product(tcfg["search"]["lr"], tcfg["search"]["weight_decay"], tcfg["search"]["pos_weight"]):
        rs = [train_one(Xtr_all[~hold], ytr[~hold], Xtr_all[hold], ytr[hold], lr=lr, weight_decay=wd, pos_weight=pw,
                        seed=s, batch_size=tcfg["batch_size"], max_epochs=tcfg["max_epochs"], patience=tcfg["patience"])
              for s in tcfg["seeds"]]
        aps = [average_precision_score(yva, logits(r.model, Xva)) for r in rs]
        k = f"lr={lr},wd={wd},pos_weight={pw}"
        search.append({"config": k, "val_pr_auc_mean": float(np.mean(aps)), "val_pr_auc_min": float(np.min(aps)),
                       "val_pr_auc_max": float(np.max(aps))})
        models[k] = rs
        print(f"  {k}: val PR-AUC {np.mean(aps):.3f}", flush=True)
    best = max(search, key=lambda r: r["val_pr_auc_mean"])
    chosen = models[best["config"]]
    z_va = np.mean([logits(r.model, Xva) for r in chosen], axis=0)
    z_te = np.mean([logits(r.model, Xte) for r in chosen], axis=0)
    platt = LogisticRegression(C=1e6, max_iter=1000).fit(z_va.reshape(-1, 1), yva)
    a, b = float(platt.coef_[0, 0]), float(platt.intercept_[0])
    p_va, p_te = sigmoid(a * z_va + b), sigmoid(a * z_te + b)
    p_v1 = key["mlp"].to_numpy()
    groups = te["cik"].to_numpy()

    # matched comparison on identical rows
    thr_h = max_f1_threshold(yva, p_va)
    thr_v1 = json.loads(Path("backend/models/stress_mlp_v1/xray.json").read_text())["threshold_test"]["threshold"]
    # canonical populations (label_onset): confirmed healthy in t / already stressed in t / status undeterminable.
    # Until v1.4 "onset" was stress_conditions_t.fillna(0) < 2, which also counted the undeterminable years.
    onset = te["label_onset"].notna().to_numpy()
    undetermined = te["stress_t"].isna().to_numpy()
    persist = (te["stress_t"] == 1).to_numpy()

    def subset(mask):
        y = yte[mask]
        return {"rows": int(mask.sum()), "stressed": int(y.sum()),
                "v1_pr_auc": float(average_precision_score(y, p_v1[mask])),
                "history_pr_auc": float(average_precision_score(y, p_te[mask])),
                "v1_caught": int(((p_v1 >= thr_v1) & mask & (yte == 1)).sum()),
                "history_caught": int(((p_te >= thr_h) & mask & (yte == 1)).sum())}

    res = {
        "experiment": "mlp_history_v1", "status": "experiment only; not deployed",
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "minutes": round((time.time() - t0) / 60, 1),
        "inputs": {"v1": len(FEATURES), "this_run": len(features), "added": [f for f in features if f not in FEATURES],
                   "summaries": SUMMARIES},
        "history_coverage": coverage,
        "rows": {"train": int(len(tr)), "val": int(len(va)), "test": int(len(te))},
        "selected_config": best["config"], "search": search,
        "test": {"v1": point_metrics(yte, p_v1), "history": point_metrics(yte, p_te)},
        "test_ci95": {"v1": cluster_bootstrap(yte, p_v1, groups, 1000, 7), "history": cluster_bootstrap(yte, p_te, groups, 1000, 7)},
        "paired_history_minus_v1": paired_bootstrap(yte, p_te, p_v1, groups, 1000, 7),
        "at_validation_threshold": {"v1": threshold_metrics(yte, p_v1, thr_v1), "history": threshold_metrics(yte, p_te, thr_h)},
        "onset": subset(onset), "persistent": subset(persist), "status_undetermined_in_t": subset(undetermined),
        "onset_definition": "label_onset (canonical)",
        "paired_on_onsets": paired_bootstrap(yte[onset], p_te[onset], p_v1[onset], groups[onset], 1000, 7),
        "calibration_test": {"v1": calibration_table(yte, p_v1).to_dict(orient="records"),
                             "history": calibration_table(yte, p_te).to_dict(orient="records")},
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(res, indent=1, default=float) + "\n")
    pd.DataFrame({"cik": te["cik"].to_numpy(), "fiscal_year_end": te["fiscal_year_end"].to_numpy(), "y": yte,
                  "v1": p_v1, "history": p_te}).to_csv(out / "test_predictions.csv", index=False, float_format="%.10g")
    t, d = res["test"], res["paired_history_minus_v1"]
    print(f"PR-AUC v1 {t['v1']['pr_auc']:.3f} | history {t['history']['pr_auc']:.3f} | diff {d['mean_diff']:+.3f} "
          f"CI {d['ci95'][0]:+.3f} to {d['ci95'][1]:+.3f} | onsets caught v1 {res['onset']['v1_caught']} vs history "
          f"{res['onset']['history_caught']} of {res['onset']['stressed']} | {res['minutes']} min")


if __name__ == "__main__":
    import sys
    if "--control" in sys.argv:          # same pipeline, v1 inputs only: must reproduce the frozen test metrics
        main(FEATURES, OUT / "control_v1_inputs")
    else:
        main()
