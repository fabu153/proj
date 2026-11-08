"""Research only (NOT deployed): a three-year GRU trained for stress ONSET.

    python -m training.ml.experiment_onset_gru          # ~10-20 min on 4 CPU threads

Population: label_onset rows (year-t status determinable and not stressed; t+1 status determinable). Inputs: the
same 31 measures + 31 missing flags as the deployed network for t, t-1 and t-2. Prior years follow the point-in-time
rule of experiment_history; a missing prior year is SKIPPED (variable-length packed sequence), never fed as zeros.
Protocol: baselines_v1 rows, split and purge; train-only preprocessing; the mlp_v1 grid (8 configs x 5 seeds) chosen
on validation PR-AUC; Platt calibration on validation; one evaluation on the already-inspected 2021-25 test window.
Configuration: configs/experiment_gru_onset_v1.yaml. Output: training/experiments/gru_onset_v1/. Nothing here
touches backend/models, the release manifest or the replay.
"""
from __future__ import annotations

import copy
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
import yaml
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from torch import nn
from torch.nn.utils.rnn import pack_padded_sequence

from backend.app.features.feature_set import FEATURES, build_features
from backend.app.features.preprocess import Preprocessor
from training.ml.onset_data import TARGET, YEARS, history_index, onset_cohort, sequences  # noqa: F401
from training.ml.evaluate import calibration_table, cluster_bootstrap, max_f1_threshold, point_metrics, threshold_metrics
from training.ml.mlp import logits, set_seed, train_one
from training.ml.run_baselines import load_dataset, sha256_file
from training.ml.splits import SplitSpec, assign_splits
from training.ml.train_mlp import grouped_holdout, sigmoid

CONFIG = Path("configs/experiment_gru_onset_v1.yaml")
OUT = Path("training/experiments/gru_onset_v1")
PUBLISHED_ONSET_MLP_TEST_PR_AUC = 0.30006116166558094      # training/experiments/mlp_v1/results.json


# ------------------------------------------------------------------ model
class OnsetGRU(nn.Module):
    def __init__(self, n_in: int, hidden: int = 64):
        super().__init__()
        self.gru = nn.GRU(n_in, hidden, batch_first=True)
        self.head = nn.Sequential(nn.LayerNorm(hidden), nn.Dropout(0.25), nn.Linear(hidden, 32), nn.ReLU(), nn.Linear(32, 1))

    def forward(self, x, lengths):
        packed = pack_padded_sequence(x, lengths.cpu(), batch_first=True, enforce_sorted=False)
        _, h = self.gru(packed)                 # state after each sequence's own last step (year t)
        return self.head(h[-1]).squeeze(-1)


def seq_logits(model, X, L):
    model.eval()
    with torch.no_grad():
        return model(torch.tensor(X), torch.tensor(L)).numpy().astype(np.float64)


def train_seq(X, L, y, Xh, Lh, yh, *, lr, weight_decay, pos_weight, seed, batch_size, max_epochs, patience):
    set_seed(seed)
    model = OnsetGRU(X.shape[2])
    pw = torch.tensor((len(y) - y.sum()) / max(y.sum(), 1), dtype=torch.float32) if pos_weight == "balanced" else None
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=pw)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    Xt, Lt, yt = torch.tensor(X), torch.tensor(L), torch.tensor(y, dtype=torch.float32)
    gen = torch.Generator().manual_seed(seed)
    best = (-1.0, 0, copy.deepcopy(model.state_dict()))
    for epoch in range(1, max_epochs + 1):
        model.train()
        perm = torch.randperm(len(Xt), generator=gen)
        for i in range(0, len(Xt), batch_size):
            idx = perm[i:i + batch_size]
            opt.zero_grad()
            loss_fn(model(Xt[idx], Lt[idx]), yt[idx]).backward()
            opt.step()
        ap = average_precision_score(yh, seq_logits(model, Xh, Lh))
        if ap > best[0] + 1e-6:
            best = (ap, epoch, copy.deepcopy(model.state_dict()))
        elif epoch - best[1] >= patience:
            break
    model.load_state_dict(best[2])
    model.eval()
    return model, best[1]


# ------------------------------------------------------------------ evaluation helpers
def paired_diff(y, p_a, p_b, groups, n, seed):
    """Company-clustered paired bootstrap of PR-AUC(a)-PR-AUC(b) and ROC-AUC(a)-ROC-AUC(b)."""
    rng = np.random.default_rng(seed)
    uniq = np.unique(groups)
    idx_by = {g: np.flatnonzero(groups == g) for g in uniq}
    dpr, droc = [], []
    for _ in range(n):
        take = np.concatenate([idx_by[g] for g in rng.choice(uniq, size=len(uniq), replace=True)])
        yy = y[take]
        if 0 < yy.sum() < len(yy):
            dpr.append(average_precision_score(yy, p_a[take]) - average_precision_score(yy, p_b[take]))
            droc.append(roc_auc_score(yy, p_a[take]) - roc_auc_score(yy, p_b[take]))
    q = lambda a: [float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5))]  # noqa: E731
    return {"pr_auc_diff": float(average_precision_score(y, p_a) - average_precision_score(y, p_b)),
            "pr_auc_diff_ci95": q(dpr), "share_a_better_pr": float(np.mean(np.array(dpr) > 0)),
            "roc_auc_diff": float(roc_auc_score(y, p_a) - roc_auc_score(y, p_b)), "roc_auc_diff_ci95": q(droc),
            "resamples_used": len(dpr)}


def at_budget(y, p, share):
    """Flag the top `share` of rows by score (ties broken by row order): what an analyst with a fixed review
    capacity would see."""
    k = int(round(share * len(y)))
    order = np.argsort(-p, kind="stable")
    flag = np.zeros(len(y), dtype=bool)
    flag[order[:k]] = True
    tp, fp = int((flag & (y == 1)).sum()), int((flag & (y == 0)).sum())
    fn = int(y.sum()) - tp
    return {"flagged": k, "tp": tp, "fp": fp, "fn": fn, "precision": tp / k if k else 0.0,
            "recall": tp / y.sum() if y.sum() else 0.0}


def main():
    t0 = time.time()
    torch.set_num_threads(4)
    cfg = yaml.safe_load(CONFIG.read_text())
    base_cfg = yaml.safe_load(Path(cfg["base_config"]).read_text())
    mcfg = yaml.safe_load(Path(cfg["mlp_config"]).read_text())
    tcfg = mcfg["training"]
    bs = cfg["bootstrap"]

    df = load_dataset(base_cfg)
    split = assign_splits(df, SplitSpec(**base_cfg["split"]))
    sub = onset_cohort(df)
    sp = split.loc[sub.index]
    tr, va, te = sub[sp == "train"], sub[sp == "val"], sub[sp == "test"]
    ytr, yva, yte = (d[TARGET].astype(int).to_numpy() for d in (tr, va, te))
    groups = te["cik"].to_numpy()
    print(f"onset rows train {len(tr)} ({ytr.sum()} onsets) | val {len(va)} ({yva.sum()}) | test {len(te)} ({yte.sum()})")

    pre = Preprocessor(FEATURES, base_cfg["preprocessing"]["winsor_lower_q"],
                       base_cfg["preprocessing"]["winsor_upper_q"]).fit(tr)          # train onset rows only
    hold = grouped_holdout(tr, tcfg["early_stop_holdout"])

    # ---- 1. onset MLP, reproduced (mlp_v1 kept no per-row onset predictions)
    Xtr, Xva, Xte = (pre.transform(d).to_numpy() for d in (tr, va, te))
    mlp_search, mlp_models = [], {}
    for lr, wd, pw in itertools.product(tcfg["search"]["lr"], tcfg["search"]["weight_decay"], tcfg["search"]["pos_weight"]):
        rs = [train_one(Xtr[~hold], ytr[~hold], Xtr[hold], ytr[hold], lr=lr, weight_decay=wd, pos_weight=pw, seed=s,
                        batch_size=tcfg["batch_size"], max_epochs=tcfg["max_epochs"], patience=tcfg["patience"])
              for s in tcfg["seeds"]]
        k = f"lr={lr},wd={wd},pos_weight={pw}"
        mlp_search.append({"config": k, "val_pr_auc_mean": float(np.mean([average_precision_score(yva, logits(r.model, Xva)) for r in rs]))})
        mlp_models[k] = rs
    mlp_best = max(mlp_search, key=lambda r: r["val_pr_auc_mean"])
    zm_va = np.mean([logits(r.model, Xva) for r in mlp_models[mlp_best["config"]]], axis=0)
    zm_te = np.mean([logits(r.model, Xte) for r in mlp_models[mlp_best["config"]]], axis=0)
    pl = LogisticRegression(C=1e6, max_iter=1000).fit(zm_va.reshape(-1, 1), yva)
    pm_va = sigmoid(pl.coef_[0, 0] * zm_va + pl.intercept_[0])
    pm_te = sigmoid(pl.coef_[0, 0] * zm_te + pl.intercept_[0])
    mlp_repro = float(average_precision_score(yte, pm_te))
    print(f"onset MLP reproduced: test PR-AUC {mlp_repro:.4f} (published {PUBLISHED_ONSET_MLP_TEST_PR_AUC:.4f})")

    # ---- 2. onset GRU
    all_feats = build_features(pd.read_csv(base_cfg["panel"], dtype={"cik": str}))   # history may come from any year
    Z = pre.transform(all_feats).to_numpy().astype(np.float32)
    zpos = {i: k for k, i in enumerate(all_feats.index)}
    keyed = lambda d: d.reset_index(drop=True).merge(  # noqa: E731
        all_feats.reset_index()[["index", "cik", "fiscal_year_end"]], on=["cik", "fiscal_year_end"], how="left")
    for d in (tr, va, te):
        assert keyed(d)["index"].notna().all(), "every onset row must exist in the full feature table"
    H = {name: history_index(d, all_feats) for name, d in (("tr", tr), ("va", va), ("te", te))}
    (Str, Ltr), (Sva, Lva), (Ste, Lte) = (sequences(H[k], Z, zpos) for k in ("tr", "va", "te"))
    gru_search, gru_models = [], {}
    for lr, wd, pw in itertools.product(tcfg["search"]["lr"], tcfg["search"]["weight_decay"], tcfg["search"]["pos_weight"]):
        ms = [train_seq(Str[~hold], Ltr[~hold], ytr[~hold], Str[hold], Ltr[hold], ytr[hold], lr=lr, weight_decay=wd,
                        pos_weight=pw, seed=s, batch_size=tcfg["batch_size"], max_epochs=tcfg["max_epochs"],
                        patience=tcfg["patience"]) for s in tcfg["seeds"]]
        aps = [average_precision_score(yva, seq_logits(m, Sva, Lva)) for m, _ in ms]
        k = f"lr={lr},wd={wd},pos_weight={pw}"
        gru_search.append({"config": k, "val_pr_auc_mean": float(np.mean(aps)), "val_pr_auc_min": float(np.min(aps)),
                           "val_pr_auc_max": float(np.max(aps)), "best_epochs": [e for _, e in ms]})
        gru_models[k] = [m for m, _ in ms]
        print(f"  GRU {k}: val PR-AUC {np.mean(aps):.3f} [{np.min(aps):.3f}-{np.max(aps):.3f}]", flush=True)
    gru_best = max(gru_search, key=lambda r: r["val_pr_auc_mean"])
    chosen = gru_models[gru_best["config"]]
    zg_va = np.mean([seq_logits(m, Sva, Lva) for m in chosen], axis=0)
    zg_te = np.mean([seq_logits(m, Ste, Lte) for m in chosen], axis=0)
    pg = LogisticRegression(C=1e6, max_iter=1000).fit(zg_va.reshape(-1, 1), yva)
    a, b = float(pg.coef_[0, 0]), float(pg.intercept_[0])
    pg_va, pg_te = sigmoid(a * zg_va + b), sigmoid(a * zg_te + b)
    per_seed = [float(average_precision_score(yte, seq_logits(m, Ste, Lte))) for m in chosen]

    # ---- 3. comparators on exactly the same test rows
    key = te[["cik", "fiscal_year_end"]].reset_index(drop=True)
    base = key.merge(pd.read_csv(f"training/experiments/{cfg['baseline_experiment']}/test_predictions_label_onset.csv",
                                 dtype={"cik": str}), on=["cik", "fiscal_year_end"], how="left")
    gen_mlp = key.merge(pd.read_csv(cfg["general_models"]["mlp_v1"], dtype={"cik": str}), on=["cik", "fiscal_year_end"], how="left")
    gen_gru = key.merge(pd.read_csv(cfg["general_models"]["gru_history_v1"], dtype={"cik": str}), on=["cik", "fiscal_year_end"], how="left")
    for name, m, col in (("baselines", base, "xgboost"), ("mlp_v1", gen_mlp, "mlp"), ("gru_history_v1", gen_gru, "gru")):
        assert m[col].notna().all() and (m["y"].to_numpy() == yte).all(), f"{name}: test rows differ — not paired"
    preds = {
        "gru_onset": pg_te,
        "mlp_onset": pm_te,
        "xgboost_onset": base["xgboost"].to_numpy(),
        "logistic_onset": base["logistic"].to_numpy(),
        "rule_score_onset": base["rule_score"].to_numpy(),
        "no_skill": base["no_skill"].to_numpy(),
        "general_mlp_v1": gen_mlp["mlp"].to_numpy(),
        "general_gru_history_v1": gen_gru["gru"].to_numpy(),
    }
    years_avail = Lte
    base_res = json.loads(Path(f"training/experiments/{cfg['baseline_experiment']}/results.json").read_text())["results"][TARGET]
    thr_g, thr_m = max_f1_threshold(yva, pg_va), max_f1_threshold(yva, pm_va)

    res = {
        "experiment": cfg["experiment"], "status": "research only; not deployed",
        "test_set_status": cfg["test_set_status"].strip(),
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "provenance": {"panel_sha256": sha256_file(base_cfg["panel"]), "config_sha256": sha256_file(str(CONFIG)),
                       "git_commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                                                    text=True).stdout.strip(),
                       "python": platform.python_version(), "torch": torch.__version__,
                       "minutes": round((time.time() - t0) / 60, 1)},
        "cohort": {s: {"rows": int(len(d)), "onsets": int(d[TARGET].sum()), "companies": int(d["cik"].nunique()),
                       "prevalence": float(d[TARGET].mean())} for s, d in (("train", tr), ("val", va), ("test", te))},
        "history_years_available": {s: {str(k): int((L == k).sum()) for k in (1, 2, 3)}
                                    for s, L in (("train", Ltr), ("val", Lva), ("test", Lte))},
        "onset_mlp_reproduction": {"published_test_pr_auc": PUBLISHED_ONSET_MLP_TEST_PR_AUC,
                                   "reproduced_test_pr_auc": mlp_repro, "selected_config": mlp_best["config"],
                                   "identical": abs(mlp_repro - PUBLISHED_ONSET_MLP_TEST_PR_AUC) < 1e-9},
        "gru": {"selected_config": gru_best["config"], "search": gru_search, "per_seed_test_pr_auc": per_seed,
                "platt": {"a": a, "b": b}, "val_calibrated": point_metrics(yva, pg_va)},
        "test": {k: point_metrics(yte, np.asarray(p, dtype=float)) for k, p in preds.items()},
        "test_ci95": {k: cluster_bootstrap(yte, np.asarray(p, dtype=float), groups, bs["resamples"], bs["seed"])
                      for k, p in preds.items() if k != "no_skill"},
        "paired_gru_onset_minus": {k: paired_diff(yte, pg_te, np.asarray(p, dtype=float), groups, bs["resamples"], bs["seed"])
                                   for k, p in preds.items() if k not in ("gru_onset", "no_skill")},
        "at_validation_threshold": {
            "gru_onset": threshold_metrics(yte, pg_te, thr_g),
            "mlp_onset": threshold_metrics(yte, pm_te, thr_m),
            "xgboost_onset": base_res["xgboost"]["test_at_val_threshold"],
            "logistic_onset": base_res["logistic"]["test_at_val_threshold"],
            "rule_score_onset": base_res["rule_score"]["test_at_val_threshold"],
        },
        "at_alert_budget": {f"{int(s * 100)}%": {k: at_budget(yte, np.asarray(p, dtype=float), s)
                                                 for k, p in preds.items() if k != "no_skill"}
                            for s in cfg["alert_budgets"]},
        "by_history_years": {},
        "calibration_test": {k: calibration_table(yte, np.asarray(preds[k], dtype=float), bins=5).to_dict(orient="records")
                             for k in ("gru_onset", "mlp_onset", "xgboost_onset", "general_mlp_v1")},
    }
    for k in (1, 2, 3):
        m = years_avail == k
        entry = {"rows": int(m.sum()), "onsets": int(yte[m].sum())}
        if 0 < yte[m].sum() < m.sum():
            entry["pr_auc"] = {name: float(average_precision_score(yte[m], np.asarray(p, dtype=float)[m]))
                               for name, p in preds.items() if name != "no_skill"}
        res["by_history_years"][str(k)] = entry

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(res, indent=1, default=float) + "\n")
    (OUT / "config_snapshot.yaml").write_text(CONFIG.read_text())
    pd.DataFrame({"cik": te["cik"].to_numpy(), "fiscal_year_end": te["fiscal_year_end"].to_numpy(), "y": yte,
                  "years_of_history": years_avail, **{k: np.asarray(p, dtype=float) for k, p in preds.items()}}
                 ).to_csv(OUT / "test_predictions.csv", index=False, float_format="%.10g")
    t = res["test"]
    print(" | ".join(f"{k} {t[k]['pr_auc']:.3f}" for k in preds), f"| {res['provenance']['minutes']} min")


if __name__ == "__main__":
    main()
