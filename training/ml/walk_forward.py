"""Walk-forward (rolling-origin) validation of the full modelling protocol, 2016-2025. Research only.

    python -m training.ml.walk_forward          # ~7 min on 2 CPU cores (the MLP grid dominates)

For each test year Y the logistic regression, XGBoost and the MLP are re-selected and re-fitted with exactly the
protocol of baselines_v1 / mlp_v1, using only accounts and labels that were public before Y (config:
configs/experiment_walk_forward_v1.yaml). Every company-year in 2016-2025 is therefore predicted once, out of
sample, by models that could have existed at the time. Altman Z'' and Ohlson O need no fitting.

Writes training/experiments/walk_forward_v1/: results.json (per-fold and pooled metrics, paired differences),
oos_predictions.csv (one row per company-year with every model's out-of-sample score) and config_snapshot.yaml.
Nothing in backend/models changes.
"""
from __future__ import annotations

import itertools
import json
import platform
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import xgboost as xgb
import yaml
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score

from backend.app.features.feature_set import FEATURES
from backend.app.features.preprocess import Preprocessor
from training.ml.evaluate import cluster_bootstrap, point_metrics
from training.ml.mlp import logits, train_one
from training.ml.run_baselines import fit_logistic, fit_rule, fit_xgb, load_dataset, sha256_file
from training.ml.splits import walk_forward_masks as fold_masks
from training.ml.train_mlp import grouped_holdout, sigmoid

CONFIG = Path("configs/experiment_walk_forward_v1.yaml")
OUT = Path("training/experiments/walk_forward_v1")


def fit_mlp(Xtr, ytr, tr, Xva, yva, tcfg, log):
    hold = grouped_holdout(tr, tcfg["early_stop_holdout"])
    best = None
    for lr, wd, pw in itertools.product(tcfg["search"]["lr"], tcfg["search"]["weight_decay"], tcfg["search"]["pos_weight"]):
        rs = [train_one(Xtr[~hold], ytr[~hold], Xtr[hold], ytr[hold], lr=lr, weight_decay=wd, pos_weight=pw, seed=s,
                        batch_size=tcfg["batch_size"], max_epochs=tcfg["max_epochs"], patience=tcfg["patience"])
              for s in tcfg["seeds"]]
        ap = float(np.mean([average_precision_score(yva, logits(r.model, Xva)) for r in rs]))
        if best is None or ap > best[0]:
            best = (ap, f"lr={lr},wd={wd},pos_weight={pw}", rs)
    z_va = np.mean([logits(r.model, Xva) for r in best[2]], axis=0)
    platt = LogisticRegression(C=1e6, max_iter=1000).fit(z_va.reshape(-1, 1), yva)
    a, b = float(platt.coef_[0, 0]), float(platt.intercept_[0])
    log(f"    mlp {best[1]} val PR-AUC {best[0]:.3f}")
    return (lambda X: sigmoid(a * np.mean([logits(r.model, X) for r in best[2]], axis=0) + b)), \
        {"config": best[1], "val_pr_auc_mean": best[0], "platt": {"a": a, "b": b}}


def paired(y, p_a, p_b, groups, n, seed):
    rng = np.random.default_rng(seed)
    uniq = np.unique(groups)
    idx = {g: np.flatnonzero(groups == g) for g in uniq}
    d = []
    for _ in range(n):
        t = np.concatenate([idx[g] for g in rng.choice(uniq, size=len(uniq), replace=True)])
        if 0 < y[t].sum() < len(t):
            d.append(average_precision_score(y[t], p_a[t]) - average_precision_score(y[t], p_b[t]))
    return {"mean_diff": float(average_precision_score(y, p_a) - average_precision_score(y, p_b)),
            "ci95": [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))],
            "share_a_better": float(np.mean(np.array(d) > 0))}


def main():
    t_start = time.time()
    torch.set_num_threads(2)
    cfg = yaml.safe_load(CONFIG.read_text())
    base = yaml.safe_load(Path(cfg["base_config"]).read_text())
    tcfg = yaml.safe_load(Path(cfg["mlp_config"]).read_text())["training"]
    target, bs = cfg["target"], cfg["bootstrap"]
    df = load_dataset(base)
    df = df[df[target].notna()]
    classic = pd.read_csv(cfg["textbook_scores"], dtype={"cik": str})
    OUT.mkdir(parents=True, exist_ok=True)
    log_lines = []

    def log(msg):
        print(msg, flush=True)
        log_lines.append(msg)

    folds, oos = [], []
    for year in cfg["test_years"]:
        trm, vam, tem = fold_masks(df, year, cfg["validation_years"])
        tr, va, te = df[trm], df[vam], df[tem]
        ytr, yva, yte = (d[target].astype(int).to_numpy() for d in (tr, va, te))
        log(f"fold {year}: train {len(tr)} ({ytr.sum()}) | val {len(va)} ({yva.sum()}) | test {len(te)} ({yte.sum()})")
        pre = Preprocessor(FEATURES, base["preprocessing"]["winsor_lower_q"], base["preprocessing"]["winsor_upper_q"]).fit(tr)
        Xtr, Xva, Xte = (pre.transform(d) for d in (tr, va, te))
        preds = {"no_skill": np.full(len(te), float(ytr.mean()))}
        rule, _ = fit_rule(tr, target)
        preds["rule_score"] = rule(te)
        lr_m, lr_meta = fit_logistic(Xtr, ytr, Xva, yva, base["models"]["logistic"]["C_grid"])
        preds["logistic"] = lr_m.predict_proba(Xte)[:, 1]
        xg_m, xg_meta = fit_xgb(Xtr, ytr, Xva, yva, base["models"]["xgboost"])
        preds["xgboost"] = xg_m.predict_proba(Xte)[:, 1]
        mlp_pred, mlp_meta = fit_mlp(Xtr.to_numpy(), ytr, tr, Xva.to_numpy(), yva, tcfg, log)
        preds["mlp"] = mlp_pred(Xte.to_numpy())
        rows = te[["cik", "fiscal_year_end", "as_of_date", "sic", target, "label_onset", "stress_t"]].copy()
        rows["test_year"] = year
        for k, v in preds.items():
            rows[k] = v
        rows = rows.merge(classic, on=["cik", "fiscal_year_end"], how="left")
        oos.append(rows)
        folds.append({"test_year": year, "rows": {"train": int(len(tr)), "val": int(len(va)), "test": int(len(te))},
                      "positives": {"train": int(ytr.sum()), "val": int(yva.sum()), "test": int(yte.sum())},
                      "selected": {"logistic_C": lr_meta["C"], "xgboost": {k: xg_meta[k] for k in ("max_depth", "min_child_weight", "best_iteration")},
                                   "mlp": mlp_meta},
                      "test_pr_auc": {k: float(average_precision_score(yte, v)) for k, v in preds.items()},
                      "test_roc_auc": {k: float(roc_auc_score(yte, v)) for k, v in preds.items() if k != "no_skill"}})
        log("    " + " ".join(f"{k} {v:.3f}" for k, v in folds[-1]["test_pr_auc"].items()))

    pooled = pd.concat(oos, ignore_index=True)
    y, g = pooled[target].astype(int).to_numpy(), pooled["cik"].to_numpy()
    fitted = ["rule_score", "logistic", "xgboost", "mlp"]
    res_pooled = {k: {**point_metrics(y, pooled[k].to_numpy()),
                      "pr_auc_ci95": cluster_bootstrap(y, pooled[k].to_numpy(), g, bs["resamples"], bs["seed"])["pr_auc_ci95"]}
                  for k in ["no_skill"] + fitted}
    # textbook scores: rank-only, on rows where they exist (riskier = higher)
    for k, sign in (("altman_z2", -1.0), ("ohlson_o", 1.0)):
        m = pooled[k].notna().to_numpy()
        s = sign * pooled[k].to_numpy()
        res_pooled[k] = {"rows": int(m.sum()), "pr_auc": float(average_precision_score(y[m], s[m])),
                         "roc_auc": float(roc_auc_score(y[m], s[m])),
                         "mlp_same_rows_pr_auc": float(average_precision_score(y[m], pooled["mlp"].to_numpy()[m]))}
    pr = pd.DataFrame([f["test_pr_auc"] for f in folds], index=[f["test_year"] for f in folds])
    ranks = pr.drop(columns="no_skill").rank(axis=1, ascending=False)
    res = {
        "experiment": cfg["experiment"], "status": "research only; deployed model unchanged",
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "provenance": {"panel_sha256": sha256_file(base["panel"]), "config_sha256": sha256_file(str(CONFIG)),
                       "git_commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip(),
                       "python": platform.python_version(), "torch": torch.__version__, "xgboost": xgb.__version__,
                       "minutes": round((time.time() - t_start) / 60, 1)},
        "folds": folds,
        "pooled_oos": {"rows": int(len(pooled)), "positives": int(y.sum()), "companies": int(pooled["cik"].nunique()),
                       "years": f"{min(cfg['test_years'])}-{max(cfg['test_years'])}", "metrics": res_pooled},
        "mean_fold_pr_auc": pr.mean().to_dict(), "sd_fold_pr_auc": pr.std().to_dict(),
        "mean_rank": ranks.mean().to_dict(),
        "years_mlp_beats": {k: int((pr["mlp"] > pr[k]).sum()) for k in ("logistic", "xgboost", "rule_score")},
        "paired_pooled": {f"mlp_minus_{k}": paired(y, pooled["mlp"].to_numpy(), pooled[k].to_numpy(), g, bs["resamples"], bs["seed"])
                          for k in ("logistic", "xgboost", "rule_score")}
        | {"xgboost_minus_logistic": paired(y, pooled["xgboost"].to_numpy(), pooled["logistic"].to_numpy(), g, bs["resamples"], bs["seed"])},
    }
    (OUT / "results.json").write_text(json.dumps(res, indent=1) + "\n")
    (OUT / "config_snapshot.yaml").write_text(CONFIG.read_text())
    pooled.to_csv(OUT / "oos_predictions.csv", index=False, float_format="%.10g")
    (OUT / "run_log.txt").write_text("\n".join(log_lines) + "\n")
    log(f"pooled {len(pooled)} rows: " + " ".join(f"{k} {v['pr_auc']:.3f}" for k, v in res_pooled.items()))


if __name__ == "__main__":
    main()
