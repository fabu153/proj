"""Week 4 — train, select, calibrate and export the stress MLP.

    python -m training.ml.train_mlp --config configs/experiment_mlp_v1.yaml

Protocol (configs/experiment_mlp_v1.yaml):
  * Same rows, split and train-only preprocessing as baselines_v1 (paired comparison).
  * Early stopping on a GROUPED holdout of training companies; the validation window is never
    seen during weight updates.
  * 8 predefined configurations x 5 seeds; the configuration with the best MEAN validation
    PR-AUC is selected. Deployed model = mean logit of its 5 seeds.
  * Platt calibration fitted on validation logits. Test evaluated once, afterwards.
"""
from __future__ import annotations

import argparse
import itertools
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import yaml
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score

from backend.app.features.feature_set import FEATURE_VERSION, FEATURES
from backend.app.features.preprocess import Preprocessor
from backend.app.labels.stress_label import LABEL_VERSION
from backend.app.models.inference import forward
from training.ml.evaluate import (calibration_table, cluster_bootstrap, max_f1_threshold, plot_pr_and_calibration,
                                  point_metrics, threshold_metrics)
from training.ml.mlp import export_weights, logits, train_one
from training.ml.run_baselines import load_dataset, sha256_file
from training.ml.splits import SplitSpec, assign_splits

ARTIFACT = Path("backend/models/stress_mlp_v1")


def sigmoid(z):
    return 1 / (1 + np.exp(-z))


def grouped_holdout(df: pd.DataFrame, share: float, seed: int = 0) -> np.ndarray:
    ciks = np.array(sorted(df["cik"].unique()))
    rng = np.random.default_rng(seed)
    held = set(rng.choice(ciks, size=max(1, int(round(share * len(ciks)))), replace=False))
    return df["cik"].isin(held).to_numpy()


def paired_bootstrap(y, p_a, p_b, groups, n, seed):
    """Distribution of PR-AUC(a) - PR-AUC(b), resampling companies."""
    rng = np.random.default_rng(seed)
    uniq = np.unique(groups)
    idx_by = {g: np.flatnonzero(groups == g) for g in uniq}
    d = []
    for _ in range(n):
        take = np.concatenate([idx_by[g] for g in rng.choice(uniq, size=len(uniq), replace=True)])
        if 0 < y[take].sum() < len(take):
            d.append(average_precision_score(y[take], p_a[take]) - average_precision_score(y[take], p_b[take]))
    d = np.array(d)
    return {"mean_diff": float(d.mean()), "ci95": [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))],
            "share_a_better": float((d > 0).mean())}


def permutation_importance(model_logit, pre, va, yva, repeats=5, seed=0):
    rng = np.random.default_rng(seed)
    base = average_precision_score(yva, model_logit(pre.transform(va).to_numpy()))
    out = {}
    for f in FEATURES:
        drops = []
        for _ in range(repeats):
            sh = va.copy()
            sh[f] = rng.permutation(sh[f].to_numpy())
            drops.append(base - average_precision_score(yva, model_logit(pre.transform(sh).to_numpy())))
        out[f] = float(np.mean(drops))
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def run_target(df, split, target, cfg, base_cfg, out: Path) -> dict:
    tcfg = cfg["training"]
    sub = df[df[target].notna()]
    sp = split.loc[sub.index]
    tr, va, te = sub[sp == "train"], sub[sp == "val"], sub[sp == "test"]
    yva, yte = va[target].astype(int).to_numpy(), te[target].astype(int).to_numpy()

    pre = Preprocessor(FEATURES, base_cfg["preprocessing"]["winsor_lower_q"],
                       base_cfg["preprocessing"]["winsor_upper_q"]).fit(tr)
    Xtr_all, Xva, Xte = (pre.transform(d).to_numpy() for d in (tr, va, te))
    hold = grouped_holdout(tr, tcfg["early_stop_holdout"])
    Xfit, yfit = Xtr_all[~hold], tr[target].astype(int).to_numpy()[~hold]
    Xh, yh = Xtr_all[hold], tr[target].astype(int).to_numpy()[hold]

    grid = list(itertools.product(tcfg["search"]["lr"], tcfg["search"]["weight_decay"], tcfg["search"]["pos_weight"]))
    search, models = [], {}
    for lr, wd, pw in grid:
        seed_aps, seed_models = [], []
        for s in tcfg["seeds"]:
            r = train_one(Xfit, yfit, Xh, yh, lr=lr, weight_decay=wd, pos_weight=pw, seed=s,
                          batch_size=tcfg["batch_size"], max_epochs=tcfg["max_epochs"], patience=tcfg["patience"])
            seed_aps.append(average_precision_score(yva, logits(r.model, Xva)))
            seed_models.append(r)
        key = f"lr={lr},wd={wd},pos_weight={pw}"
        search.append({"config": key, "val_pr_auc_mean": float(np.mean(seed_aps)),
                       "val_pr_auc_min": float(np.min(seed_aps)), "val_pr_auc_max": float(np.max(seed_aps)),
                       "best_epochs": [r.best_epoch for r in seed_models]})
        models[key] = seed_models
        print(f"  {target} {key}: val PR-AUC {np.mean(seed_aps):.3f} [{np.min(seed_aps):.3f}-{np.max(seed_aps):.3f}]")
    best = max(search, key=lambda r: r["val_pr_auc_mean"])
    chosen = models[best["config"]]

    z_va = np.mean([logits(r.model, Xva) for r in chosen], axis=0)
    z_te = np.mean([logits(r.model, Xte) for r in chosen], axis=0)
    platt = LogisticRegression(C=1e6, max_iter=1000).fit(z_va.reshape(-1, 1), yva)
    a, b = float(platt.coef_[0, 0]), float(platt.intercept_[0])
    p_va, p_te = sigmoid(a * z_va + b), sigmoid(a * z_te + b)

    per_seed_test = [point_metrics(yte, sigmoid(logits(r.model, Xte))) for r in chosen]
    thr = max_f1_threshold(yva, p_va)
    res = {
        "selected_config": best["config"], "search": search,
        "per_seed_test_pr_auc": {"mean": float(np.mean([m["pr_auc"] for m in per_seed_test])),
                                 "min": float(np.min([m["pr_auc"] for m in per_seed_test])),
                                 "max": float(np.max([m["pr_auc"] for m in per_seed_test]))},
        "ensemble": {"val": point_metrics(yva, sigmoid(z_va)), "test_uncalibrated": point_metrics(yte, sigmoid(z_te)),
                     "test_calibrated": point_metrics(yte, p_te), "val_calibrated": point_metrics(yva, p_va),
                     "test_at_val_threshold": threshold_metrics(yte, p_te, thr),
                     "test_bootstrap": cluster_bootstrap(yte, p_te, te["cik"].to_numpy(),
                                                         cfg["comparison"]["paired_bootstrap_resamples"],
                                                         cfg["comparison"]["seed"])},
        "platt": {"a": a, "b": b},
        "calibration_table_test": calibration_table(yte, p_te).to_dict(orient="records"),
    }

    # paired comparison with baselines on the identical test rows
    bp = pd.read_csv(Path("training/experiments") / cfg["baseline_experiment"] / f"test_predictions_{target}.csv",
                     dtype={"cik": str})
    key = te[["cik", "fiscal_year_end"]].reset_index(drop=True)
    merged = key.merge(bp, on=["cik", "fiscal_year_end"], how="left")
    assert len(merged) == len(te) and merged["y"].notna().all(), "baseline test rows differ — not a paired comparison"
    assert (merged["y"].to_numpy() == yte).all()
    comp = {}
    for other in ("xgboost", "logistic", "rule_score"):
        comp[f"mlp_minus_{other}"] = paired_bootstrap(yte, p_te, merged[other].to_numpy(), te["cik"].to_numpy(),
                                                      cfg["comparison"]["paired_bootstrap_resamples"],
                                                      cfg["comparison"]["seed"])
        comp[f"{other}_test_pr_auc"] = float(average_precision_score(yte, merged[other]))
    res["paired_vs_baselines"] = comp

    ens_logit = lambda X: np.mean([logits(r.model, X) for r in chosen], axis=0)  # noqa: E731
    res["permutation_importance_val"] = permutation_importance(ens_logit, pre, va, yva)

    plot_pr_and_calibration({"mlp (calibrated)": (yte, p_te), "xgboost": (yte, merged["xgboost"].to_numpy()),
                             "logistic": (yte, merged["logistic"].to_numpy()),
                             "rule_score": (yte, merged["rule_score"].to_numpy())},
                            f"{target} (test)", str(out / target))
    plot_pr_and_calibration({"mlp uncalibrated": (yte, sigmoid(z_te)), "mlp calibrated": (yte, p_te)},
                            f"{target} MLP calibration (test)", str(out / f"{target}_mlp_only"))

    if target == cfg["deploy_target"]:
        export_artifact(chosen, pre, a, b, cfg, res, Xte[:64], tr, va, te)
    return res


def export_artifact(chosen, pre, a, b, cfg, res, X_parity, tr, va, te):
    if ARTIFACT.exists():
        shutil.rmtree(ARTIFACT)
    ARTIFACT.mkdir(parents=True)
    weights = {"n_seeds": np.array(len(chosen))}
    for i, r in enumerate(chosen):
        for k, v in export_weights(r.model).items():
            weights[f"s{i}__{k}"] = v
    np.savez(ARTIFACT / "weights.npz", **weights)
    (ARTIFACT / "preprocessor.json").write_text(pre.to_json())
    (ARTIFACT / "calibrator.json").write_text(json.dumps({"method": "platt", "a": a, "b": b}))
    z = np.mean([logits(r.model, X_parity) for r in chosen], axis=0)
    np.savez(ARTIFACT / "parity.npz", X=X_parity, torch_logits=z)
    seeds_np = [{k.split("__", 1)[1]: v for k, v in weights.items() if k.startswith(f"s{i}__")}
                for i in range(len(chosen))]
    z_np = np.mean([forward(w, X_parity) for w in seeds_np], axis=0)
    assert np.allclose(z, z_np, atol=1e-6), f"numpy/torch parity failed: {np.abs(z - z_np).max()}"
    e = res["ensemble"]
    meta = {"model": "stress_mlp_v1", "target": cfg["deploy_target"], "label_version": LABEL_VERSION,
            "feature_version": FEATURE_VERSION, "features": FEATURES, "architecture": cfg["architecture"],
            "selected_config": res["selected_config"], "n_seeds": len(chosen),
            "trained_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "data_windows": {"train_features_filed": [tr["as_of_date"].min(), tr["as_of_date"].max()],
                             "val_features_filed": [va["as_of_date"].min(), va["as_of_date"].max()],
                             "test_features_filed": [te["as_of_date"].min(), te["as_of_date"].max()]},
            "rows": {"train": len(tr), "val": len(va), "test": len(te)},
            "test_metrics_calibrated": e["test_calibrated"], "test_bootstrap": e["test_bootstrap"],
            "xgboost_test_pr_auc": res["paired_vs_baselines"]["xgboost_test_pr_auc"],
            "paired_mlp_minus_xgboost": res["paired_vs_baselines"]["mlp_minus_xgboost"],
            "risk_bands": cfg["risk_bands"], "inference_gate": cfg["inference_gate"],
            "top_permutation_importance": dict(list(res["permutation_importance_val"].items())[:8]),
            "intended_use": "Screening indicator of next-fiscal-year accounting stress for U.S. non-financial issuers "
                            "with revenue >= USD 50m. Decision support only; analyst review required.",
            "not_for": ["probability of default", "credit rating", "regulatory capital", "automatic loan decisions"]}
    (ARTIFACT / "metadata.json").write_text(json.dumps(meta, indent=1, default=str))


def write_report(cfg, results, out: Path, prov):
    L = [f"# Neural experiment `{cfg['experiment']}`",
         f"_Run {prov['run_at']} · panel sha256 `{prov['panel_sha256'][:12]}` · torch {prov['torch']} · "
         f"paired with `{cfg['baseline_experiment']}` (identical rows and split)_", "",
         "Architecture: 62 → 128 (ReLU, LayerNorm, dropout 0.25) → 64 (ReLU, dropout 0.20) → 32 (ReLU) → 1. "
         "AdamW, BCE-with-logits, early stopping on a grouped 15% holdout of training companies. "
         "8 predefined configurations × 5 seeds; selection on mean validation PR-AUC; Platt calibration on "
         "validation. Test evaluated once.", ""]
    for t, r in results.items():
        e, pc = r["ensemble"], r["paired_vs_baselines"]
        bs = e["test_bootstrap"]
        L += [f"## Target `{t}`", "", f"Selected configuration: `{r['selected_config']}`.", "",
              "| configuration | val PR-AUC mean | min–max over seeds |", "|---|---|---|"]
        for s in sorted(r["search"], key=lambda s: -s["val_pr_auc_mean"]):
            L.append(f"| {s['config']} | {s['val_pr_auc_mean']:.3f} | {s['val_pr_auc_min']:.3f}–{s['val_pr_auc_max']:.3f} |")
        tc, tu = e["test_calibrated"], e["test_uncalibrated"]
        L += ["", "| test metric | MLP ensemble (calibrated) | uncalibrated |", "|---|---|---|",
              f"| PR-AUC | {tc['pr_auc']:.3f} (95% CI {bs['pr_auc_ci95'][0]:.3f}–{bs['pr_auc_ci95'][1]:.3f}) | {tu['pr_auc']:.3f} |",
              f"| ROC-AUC | {tc['roc_auc']:.3f} | {tu['roc_auc']:.3f} |",
              f"| Brier | {tc['brier']:.4f} | {tu['brier']:.4f} |", f"| log loss | {tc['log_loss']:.4f} | {tu['log_loss']:.4f} |",
              f"| precision / recall at validation-chosen threshold | {e['test_at_val_threshold']['precision']:.2f} / "
              f"{e['test_at_val_threshold']['recall_sensitivity']:.2f} | |", "",
              f"Single-seed test PR-AUC: mean {r['per_seed_test_pr_auc']['mean']:.3f}, range "
              f"{r['per_seed_test_pr_auc']['min']:.3f}–{r['per_seed_test_pr_auc']['max']:.3f}.", "",
              "**Paired comparison on identical test rows** (company-clustered bootstrap of the PR-AUC difference):", "",
              "| vs | baseline test PR-AUC | MLP − baseline | 95% CI | share of resamples MLP better |", "|---|---|---|---|---|"]
        for o in ("xgboost", "logistic", "rule_score"):
            d = pc[f"mlp_minus_{o}"]
            L.append(f"| {o} | {pc[f'{o}_test_pr_auc']:.3f} | {d['mean_diff']:+.3f} | "
                     f"{d['ci95'][0]:+.3f} to {d['ci95'][1]:+.3f} | {d['share_a_better']:.0%} |")
        L += ["", "Top validation permutation importance (PR-AUC drop): " +
              ", ".join(f"{k} ({v:.3f})" for k, v in list(r["permutation_importance_val"].items())[:8]) + ".", "",
              f"Plots: `{t}_pr.png`, `{t}_calibration.png`, `{t}_mlp_only_calibration.png`.", ""]
    (out / "report.md").write_text("\n".join(L))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/experiment_mlp_v1.yaml")
    args = ap.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text())
    base_cfg = yaml.safe_load(Path(cfg["base_config"]).read_text())
    cfg["risk_bands"] = {k: list(v) for k, v in cfg["risk_bands"].items()}
    out = Path("training/experiments") / cfg["experiment"]
    out.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(4)

    df = load_dataset(base_cfg)
    split = assign_splits(df, SplitSpec(**base_cfg["split"]))
    results = {t: run_target(df, split, t, cfg, base_cfg, out) for t in cfg["targets"]}
    prov = {"run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "panel_sha256": sha256_file(base_cfg["panel"]), "torch": torch.__version__}
    (out / "results.json").write_text(json.dumps({"provenance": prov, "results": results}, indent=1, default=float))
    (out / "config_snapshot.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
    write_report(cfg, results, out, prov)
    for t, r in results.items():
        print(t, "MLP test PR-AUC", round(r["ensemble"]["test_calibrated"]["pr_auc"], 3),
              "vs XGB", round(r["paired_vs_baselines"]["xgboost_test_pr_auc"], 3),
              "diff CI", [round(x, 3) for x in r["paired_vs_baselines"]["mlp_minus_xgboost"]["ci95"]])


if __name__ == "__main__":
    main()
