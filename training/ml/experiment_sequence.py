"""Experiment (NOT deployed): a recurrent network over three years of accounts.

    python -m training.ml.experiment_sequence

Instead of hand-made lag inputs, each company-year becomes a sequence of three yearly input vectors (t-2, t-1, t),
each the same 31 standardized measures + 31 missing flags the deployed network uses, plus a "year present" flag.
A GRU reads the sequence; its last state feeds a small head. Prior years follow the point-in-time rule of
experiment_history (consecutive fiscal years, already public when year t was filed); missing years are zeros with
the presence flag off. Protocol identical to mlp_v1: same rows, split, train-only preprocessing, 8 configurations x
5 seeds chosen on 2019-20 validation PR-AUC, Platt calibration, one paired test on the same 1,086 rows.
"""
from __future__ import annotations

import copy
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
from sklearn.metrics import average_precision_score
from torch import nn

from backend.app.features.feature_set import FEATURES, build_features
from backend.app.features.preprocess import Preprocessor
from training.ml.evaluate import calibration_table, cluster_bootstrap, max_f1_threshold, point_metrics, threshold_metrics
from training.ml.mlp import set_seed
from training.ml.run_baselines import load_dataset
from training.ml.splits import SplitSpec, assign_splits
from training.ml.train_mlp import grouped_holdout, paired_bootstrap, sigmoid

OUT = Path("training/experiments/gru_history_v1")
TARGET = "label_next_fy"
YEARS = 3


class StressGRU(nn.Module):
    def __init__(self, n_in: int, hidden: int = 64):
        super().__init__()
        self.gru = nn.GRU(n_in, hidden, batch_first=True)
        self.head = nn.Sequential(nn.LayerNorm(hidden), nn.Dropout(0.25), nn.Linear(hidden, 32), nn.ReLU(), nn.Linear(32, 1))

    def forward(self, x):                       # x: (batch, years, features), oldest year first
        _, h = self.gru(x)
        return self.head(h[-1]).squeeze(-1)


def seq_logits(model, X):
    model.eval()
    with torch.no_grad():
        return model(torch.tensor(X, dtype=torch.float32)).numpy().astype(np.float64)


def train_seq(X, y, Xh, yh, *, lr, weight_decay, pos_weight, seed, batch_size, max_epochs, patience):
    set_seed(seed)
    model = StressGRU(X.shape[2])
    pw = torch.tensor((len(y) - y.sum()) / max(y.sum(), 1), dtype=torch.float32) if pos_weight == "balanced" else None
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=pw)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    Xt, yt = torch.tensor(X, dtype=torch.float32), torch.tensor(y, dtype=torch.float32)
    gen = torch.Generator().manual_seed(seed)
    best = (-1.0, 0, copy.deepcopy(model.state_dict()))
    for epoch in range(1, max_epochs + 1):
        model.train()
        perm = torch.randperm(len(Xt), generator=gen)
        for i in range(0, len(Xt), batch_size):
            idx = perm[i:i + batch_size]
            opt.zero_grad()
            loss_fn(model(Xt[idx]), yt[idx]).backward()
            opt.step()
        ap = average_precision_score(yh, seq_logits(model, Xh))
        if ap > best[0] + 1e-6:
            best = (ap, epoch, copy.deepcopy(model.state_dict()))
        elif epoch - best[1] >= patience:
            break
    model.load_state_dict(best[2])
    model.eval()
    return model


def sequences(rows: pd.DataFrame, all_feats: pd.DataFrame, pre: Preprocessor) -> np.ndarray:
    """(n, YEARS, 2F+1): standardized features + missing flags + presence flag, oldest year first."""
    allf = all_feats.copy()
    allf["_fye"], allf["_asof"] = pd.to_datetime(allf["fiscal_year_end"]), pd.to_datetime(allf["as_of_date"])
    by_cik = {c: g.sort_values("_fye") for c, g in allf.groupby("cik")}
    Z = pre.transform(allf).to_numpy()
    zpos = {i: k for k, i in enumerate(allf.index)}
    width = Z.shape[1] + 1
    out = np.zeros((len(rows), YEARS, width))
    for r, (_, row) in enumerate(rows.iterrows()):
        g = by_cik[row["cik"]]
        fye, asof = pd.Timestamp(row["fiscal_year_end"]), pd.Timestamp(row["as_of_date"])
        cur = g[g["_fye"] == fye].index[0]
        out[r, -1, :-1], out[r, -1, -1] = Z[zpos[cur]], 1.0
        for n in (1, 2):
            prev = g[(g["_fye"] < fye) & ((fye - g["_fye"]).dt.days.between(330 * n, 400 * n)) & (g["_asof"] <= asof)]
            if len(prev):
                out[r, -1 - n, :-1], out[r, -1 - n, -1] = Z[zpos[prev.index[-1]]], 1.0
    return out


def main():
    t0 = time.time()
    torch.set_num_threads(4)
    base_cfg = yaml.safe_load(Path("configs/experiment_baselines_v1.yaml").read_text())
    tcfg = yaml.safe_load(Path("configs/experiment_mlp_v1.yaml").read_text())["training"]
    df = load_dataset(base_cfg)
    all_feats = build_features(pd.read_csv(base_cfg["panel"], dtype={"cik": str}))   # history may come from any year
    split = assign_splits(df, SplitSpec(**base_cfg["split"]))
    sub = df[df[TARGET].notna()]
    sp = split.loc[sub.index]
    tr, va, te = sub[sp == "train"], sub[sp == "val"], sub[sp == "test"]
    ytr, yva, yte = (d[TARGET].astype(int).to_numpy() for d in (tr, va, te))
    pre = Preprocessor(FEATURES, base_cfg["preprocessing"]["winsor_lower_q"], base_cfg["preprocessing"]["winsor_upper_q"]).fit(tr)
    Str, Sva, Ste = (sequences(d, all_feats, pre) for d in (tr, va, te))
    hold = grouped_holdout(tr, tcfg["early_stop_holdout"])

    v1 = pd.read_csv("training/experiments/mlp_v1/test_predictions_label_next_fy.csv", dtype={"cik": str})
    key = te[["cik", "fiscal_year_end"]].reset_index(drop=True).merge(v1, on=["cik", "fiscal_year_end"], how="left")
    assert key["mlp"].notna().all() and (key["y"].to_numpy() == yte).all(), "test rows differ: not a paired comparison"

    search, models = [], {}
    for lr, wd, pw in itertools.product(tcfg["search"]["lr"], tcfg["search"]["weight_decay"], tcfg["search"]["pos_weight"]):
        ms = [train_seq(Str[~hold], ytr[~hold], Str[hold], ytr[hold], lr=lr, weight_decay=wd, pos_weight=pw, seed=s,
                        batch_size=tcfg["batch_size"], max_epochs=tcfg["max_epochs"], patience=tcfg["patience"])
              for s in tcfg["seeds"]]
        aps = [average_precision_score(yva, seq_logits(m, Sva)) for m in ms]
        k = f"lr={lr},wd={wd},pos_weight={pw}"
        search.append({"config": k, "val_pr_auc_mean": float(np.mean(aps))})
        models[k] = ms
        print(f"  {k}: val PR-AUC {np.mean(aps):.3f}", flush=True)
    best = max(search, key=lambda r: r["val_pr_auc_mean"])
    chosen = models[best["config"]]
    z_va = np.mean([seq_logits(m, Sva) for m in chosen], axis=0)
    z_te = np.mean([seq_logits(m, Ste) for m in chosen], axis=0)
    platt = LogisticRegression(C=1e6, max_iter=1000).fit(z_va.reshape(-1, 1), yva)
    a, b = float(platt.coef_[0, 0]), float(platt.intercept_[0])
    p_va, p_te, p_v1 = sigmoid(a * z_va + b), sigmoid(a * z_te + b), key["mlp"].to_numpy()
    groups = te["cik"].to_numpy()
    thr = max_f1_threshold(yva, p_va)
    thr_v1 = json.loads(Path("backend/models/stress_mlp_v1/xray.json").read_text())["threshold_test"]["threshold"]
    # canonical populations (label_onset): confirmed healthy in t / already stressed in t / status undeterminable.
    # Until v1.4 "onset" was stress_conditions_t.fillna(0) < 2, which also counted the undeterminable years.
    onset = te["label_onset"].notna().to_numpy()
    undetermined = te["stress_t"].isna().to_numpy()

    def subset(mask):
        y = yte[mask]
        return {"rows": int(mask.sum()), "stressed": int(y.sum()),
                "v1_pr_auc": float(average_precision_score(y, p_v1[mask])),
                "gru_pr_auc": float(average_precision_score(y, p_te[mask])),
                "v1_caught": int(((p_v1 >= thr_v1) & mask & (yte == 1)).sum()),
                "gru_caught": int(((p_te >= thr) & mask & (yte == 1)).sum())}

    present = Ste[:, :, -1].sum(axis=1)
    res = {
        "experiment": "gru_history_v1", "status": "experiment only; not deployed",
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "minutes": round((time.time() - t0) / 60, 1),
        "architecture": "GRU(63 -> 64) over t-2, t-1, t; LayerNorm, dropout 0.25, Linear(64,32), ReLU, Linear(32,1)",
        "years_present_test": {str(k): int((present == k).sum()) for k in (1, 2, 3)},
        "selected_config": best["config"], "search": search,
        "test": {"v1": point_metrics(yte, p_v1), "gru": point_metrics(yte, p_te)},
        "test_ci95": {"gru": cluster_bootstrap(yte, p_te, groups, 1000, 7)},
        "paired_gru_minus_v1": paired_bootstrap(yte, p_te, p_v1, groups, 1000, 7),
        "at_validation_threshold": {"v1": threshold_metrics(yte, p_v1, thr_v1), "gru": threshold_metrics(yte, p_te, thr)},
        "onset": subset(onset), "persistent": subset((te["stress_t"] == 1).to_numpy()),
        "status_undetermined_in_t": subset(undetermined), "onset_definition": "label_onset (canonical)",
        "paired_on_onsets": paired_bootstrap(yte[onset], p_te[onset], p_v1[onset], groups[onset], 1000, 7),
        "calibration_test": calibration_table(yte, p_te).to_dict(orient="records"),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(res, indent=1, default=float) + "\n")
    pd.DataFrame({"cik": te["cik"].to_numpy(), "fiscal_year_end": te["fiscal_year_end"].to_numpy(), "y": yte,
                  "v1": p_v1, "gru": p_te}).to_csv(OUT / "test_predictions.csv", index=False, float_format="%.10g")
    t, d = res["test"], res["paired_gru_minus_v1"]
    print(f"PR-AUC v1 {t['v1']['pr_auc']:.3f} | GRU {t['gru']['pr_auc']:.3f} | diff {d['mean_diff']:+.3f} "
          f"CI {d['ci95'][0]:+.3f} to {d['ci95'][1]:+.3f} | onsets caught v1 {res['onset']['v1_caught']} vs GRU "
          f"{res['onset']['gru_caught']} of {res['onset']['stressed']} | {res['minutes']} min")


if __name__ == "__main__":
    main()
