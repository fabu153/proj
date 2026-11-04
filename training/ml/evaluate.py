"""Metrics, company-clustered bootstrap CIs and plots (Blueprint p.11 exhibit list)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import (average_precision_score, brier_score_loss, confusion_matrix, log_loss,
                             precision_recall_curve, roc_auc_score)


def point_metrics(y: np.ndarray, p: np.ndarray) -> dict:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return {"n": int(len(y)), "positives": int(y.sum()), "prevalence": float(y.mean()),
            "pr_auc": float(average_precision_score(y, p)), "roc_auc": float(roc_auc_score(y, p)),
            "brier": float(brier_score_loss(y, p)), "log_loss": float(log_loss(y, p, labels=[0, 1]))}


def max_f1_threshold(y: np.ndarray, p: np.ndarray) -> float:
    prec, rec, thr = precision_recall_curve(y, p)
    f1 = 2 * prec * rec / np.clip(prec + rec, 1e-12, None)
    return float(thr[np.nanargmax(f1[:-1])]) if len(thr) else 0.5


def threshold_metrics(y: np.ndarray, p: np.ndarray, thr: float) -> dict:
    pred = (p >= thr).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {"threshold": thr, "tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn),
            "precision": float(tp / (tp + fp)) if tp + fp else 0.0,
            "recall_sensitivity": float(tp / (tp + fn)) if tp + fn else 0.0,
            "flag_rate": float(pred.mean())}


def cluster_bootstrap(y: np.ndarray, p: np.ndarray, groups: np.ndarray, n: int, seed: int) -> dict:
    """95% CI for PR-AUC and ROC-AUC, resampling companies with replacement."""
    rng = np.random.default_rng(seed)
    uniq = np.unique(groups)
    idx_by = {g: np.flatnonzero(groups == g) for g in uniq}
    pr, roc = [], []
    for _ in range(n):
        take = np.concatenate([idx_by[g] for g in rng.choice(uniq, size=len(uniq), replace=True)])
        yy, pp = y[take], p[take]
        if 0 < yy.sum() < len(yy):
            pr.append(average_precision_score(yy, pp))
            roc.append(roc_auc_score(yy, pp))
    q = lambda a: [float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5))]  # noqa: E731
    return {"pr_auc_ci95": q(pr), "roc_auc_ci95": q(roc), "resamples_used": len(pr)}


def calibration_table(y: np.ndarray, p: np.ndarray, bins: int = 10) -> pd.DataFrame:
    """Quantile bins of predicted risk vs observed frequency."""
    d = pd.DataFrame({"y": y, "p": p})
    d["bin"] = pd.qcut(d["p"].rank(method="first"), q=min(bins, len(d)), labels=False)
    return d.groupby("bin").agg(mean_pred=("p", "mean"), observed=("y", "mean"), n=("y", "size")).reset_index()


def plot_pr_and_calibration(curves: dict[str, tuple[np.ndarray, np.ndarray]], title: str, path_prefix: str):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.4, 4.8))
    for name, (y, p) in curves.items():
        prec, rec, _ = precision_recall_curve(y, p)
        ax.plot(rec, prec, label=f"{name} (AP {average_precision_score(y, p):.3f})", lw=1.6)
    y0 = next(iter(curves.values()))[0]
    ax.axhline(y0.mean(), color="grey", ls=":", lw=1, label=f"base rate {y0.mean():.3f}")
    ax.set(xlabel="Recall", ylabel="Precision", title=f"Precision-recall — {title}", xlim=(0, 1), ylim=(0, 1))
    ax.legend(fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(f"{path_prefix}_pr.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(6.4, 4.8))
    hi = 0.0
    for name, (y, p) in curves.items():
        if name == "no_skill":
            continue
        t = calibration_table(y, p)
        ax.plot(t["mean_pred"], t["observed"], marker="o", ms=3, lw=1.4, label=name)
        hi = max(hi, t["mean_pred"].max(), t["observed"].max())
    ax.plot([0, hi], [0, hi], color="grey", ls=":", lw=1, label="perfect calibration")
    ax.set(xlabel="Mean predicted probability (decile)", ylabel="Observed frequency",
           title=f"Reliability — {title}")
    ax.legend(fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(f"{path_prefix}_calibration.png", dpi=150)
    plt.close(fig)
