"""Week 3 — baseline experiment runner (Blueprint p.11 step 05).

    python -m training.ml.run_baselines --config configs/experiment_baselines_v1.yaml

Fits no-skill, rule score, logistic regression and XGBoost on TRAIN, chooses hyperparameters
and an operating threshold on VALIDATION, and evaluates TEST once. Writes everything under
training/experiments/<experiment>/: config snapshot, split audit, preprocessor, results JSON,
plots and a markdown report. The same seeds + panel reproduce identical numbers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
import xgboost as xgb
import yaml
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score

from training.features.feature_set import FEATURE_VERSION, FEATURES, build_features
from training.ml.evaluate import (cluster_bootstrap, max_f1_threshold, plot_pr_and_calibration, point_metrics,
                                  threshold_metrics)
from training.ml.preprocess import Preprocessor
from training.ml.splits import SplitSpec, assign_splits, audit_splits


def sha256_file(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_dataset(cfg: dict) -> pd.DataFrame:
    panel = pd.read_csv(cfg["panel"], dtype={"cik": str})
    rf = cfg["row_filters"]
    feats = build_features(panel)    # built on the full panel so t-1 trends see the prior year
    if rf.get("min_revenue_usd_m") is not None:
        rev = panel.set_index(panel.index)["v_revenue"]
        feats = feats[rev.loc[feats.index] >= rf["min_revenue_usd_m"]]
    if rf.get("require_scorable"):
        feats = feats[feats["scorable"] == 1]
    feats = feats[feats["critical_coverage"] >= rf.get("min_critical_coverage", 0)]
    return feats.reset_index(drop=True)


# ----------------------------------------------------------------------------- models
def fit_rule(train: pd.DataFrame, target: str):
    key = lambda d: d["stress_conditions_t"].fillna(-1)  # noqa: E731  (-1 = unknown)
    table = train.groupby(key(train))[target].mean()
    prior = train[target].mean()
    return lambda d: key(d).map(table).fillna(prior).to_numpy(), {str(k): float(v) for k, v in table.items()}


def fit_logistic(Xtr, ytr, Xva, yva, grid):
    best = None
    for C in grid:
        m = LogisticRegression(C=C, max_iter=5000).fit(Xtr, ytr)
        ap = average_precision_score(yva, m.predict_proba(Xva)[:, 1])
        if best is None or ap > best[0]:
            best = (ap, C, m)
    return best[2], {"C": best[1], "val_pr_auc": best[0]}


def fit_xgb(Xtr, ytr, Xva, yva, mcfg):
    best = None
    for depth in mcfg["max_depth_grid"]:
        for mcw in mcfg["min_child_weight_grid"]:
            m = xgb.XGBClassifier(n_estimators=mcfg["n_estimators_max"], learning_rate=mcfg["learning_rate"],
                                  max_depth=depth, min_child_weight=mcw, subsample=mcfg["subsample"],
                                  colsample_bytree=mcfg["colsample_bytree"], eval_metric="aucpr",
                                  early_stopping_rounds=mcfg["early_stopping_rounds"], random_state=mcfg["seed"],
                                  n_jobs=4, tree_method="hist")
            m.fit(Xtr, ytr, eval_set=[(Xva, yva)], verbose=False)
            ap = average_precision_score(yva, m.predict_proba(Xva)[:, 1])
            if best is None or ap > best[0]:
                best = (ap, {"max_depth": depth, "min_child_weight": mcw, "best_iteration": int(m.best_iteration)}, m)
    return best[2], {**best[1], "val_pr_auc": best[0]}


# ----------------------------------------------------------------------------- one target
def run_target(df: pd.DataFrame, split: pd.Series, target: str, cfg: dict, out: Path) -> dict:
    sub = df[df[target].notna()]
    sp = split.loc[sub.index]
    tr, va, te = sub[sp == "train"], sub[sp == "val"], sub[sp == "test"]
    ytr, yva, yte = (d[target].astype(int).to_numpy() for d in (tr, va, te))

    pre = Preprocessor(FEATURES, cfg["preprocessing"]["winsor_lower_q"], cfg["preprocessing"]["winsor_upper_q"])
    pre.fit(tr)
    Xtr, Xva, Xte = pre.transform(tr), pre.transform(va), pre.transform(te)
    (out / f"preprocessor_{target}.json").write_text(pre.to_json())

    preds_va, preds_te, meta = {}, {}, {}
    base = float(ytr.mean())
    preds_va["no_skill"], preds_te["no_skill"] = np.full(len(va), base), np.full(len(te), base)
    meta["no_skill"] = {"train_base_rate": base}

    rule, table = fit_rule(tr, target)
    preds_va["rule_score"], preds_te["rule_score"] = rule(va), rule(te)
    meta["rule_score"] = {"P(label | conditions met in t; -1=unknown)": table}

    lr, lr_meta = fit_logistic(Xtr, ytr, Xva, yva, cfg["models"]["logistic"]["C_grid"])
    preds_va["logistic"], preds_te["logistic"] = lr.predict_proba(Xva)[:, 1], lr.predict_proba(Xte)[:, 1]
    coefs = pd.Series(lr.coef_[0], index=pre.output_columns())
    lr_meta["top_coefficients"] = {k: float(v) for k, v in coefs.reindex(coefs.abs().sort_values(ascending=False)
                                                                         .index).head(12).items()}
    meta["logistic"] = lr_meta

    xg, xg_meta = fit_xgb(Xtr, ytr, Xva, yva, cfg["models"]["xgboost"])
    preds_va["xgboost"], preds_te["xgboost"] = xg.predict_proba(Xva)[:, 1], xg.predict_proba(Xte)[:, 1]
    gain = pd.Series(xg.get_booster().get_score(importance_type="gain"))
    gain.index = [pre.output_columns()[int(i[1:])] if i.startswith("f") and i[1:].isdigit() else i
                  for i in gain.index]
    xg_meta["top_gain"] = {k: float(v) for k, v in gain.sort_values(ascending=False).head(12).items()}
    meta["xgboost"] = xg_meta

    bcfg = cfg["bootstrap"]
    results = {}
    for name in preds_te:
        thr = max_f1_threshold(yva, preds_va[name]) if name != "no_skill" else base
        r = {"val": point_metrics(yva, preds_va[name]), "test": point_metrics(yte, preds_te[name]),
             "test_at_val_threshold": threshold_metrics(yte, preds_te[name], thr), "fit": meta[name]}
        if name != "no_skill":
            r["test_bootstrap"] = cluster_bootstrap(yte, preds_te[name], te["cik"].to_numpy(),
                                                    bcfg["resamples"], bcfg["seed"])
        results[name] = r

    # segment stability for the strongest learned model on validation
    best = max(("logistic", "xgboost"), key=lambda n: results[n]["val"]["pr_auc"])
    seg = te.assign(p=preds_te[best], y=yte, year=te["as_of_date"].str[:4])
    stab = {}
    for col in ("year", "size_quintile"):
        rows = []
        for k, g in seg.groupby(col):
            if 0 < g["y"].sum() < len(g):
                rows.append({col: str(k), "n": len(g), "positives": int(g["y"].sum()),
                             "pr_auc": float(average_precision_score(g["y"], g["p"]))})
        stab[col] = rows
    results["_segment_stability"] = {"model": best, **stab}

    plot_pr_and_calibration({n: (yte, preds_te[n]) for n in preds_te}, f"{target} (test)", str(out / f"{target}"))
    pd.DataFrame({"cik": te["cik"], "fiscal_year_end": te["fiscal_year_end"], "y": yte,
                  **{n: preds_te[n] for n in preds_te}}).to_csv(out / f"test_predictions_{target}.csv", index=False)
    return results


def write_report(cfg, audit, all_results, out: Path, provenance: dict):
    L = [f"# Baseline experiment `{cfg['experiment']}`",
         f"_Run {provenance['run_at']} · panel sha256 `{provenance['panel_sha256'][:12]}` · "
         f"{FEATURE_VERSION} · python {provenance['python']} · sklearn {provenance['sklearn']} · "
         f"xgboost {provenance['xgboost']}_", "",
         "Outcome is a **next-fiscal-year accounting-stress proxy**, not a probability of default. "
         "Hyperparameters and thresholds were chosen on validation; test was evaluated once.", "",
         "## Splits (chronological by filing date, purged)",
         "| split | rows | companies | positives | prevalence | features filed | latest label public |",
         "|---|---|---|---|---|---|---|"]
    for s in ("train", "val", "test"):
        a = audit[s]
        L.append(f"| {s} | {a['rows']} | {a['companies']} | {a['positives']} | {a['prevalence']:.2%} | "
                 f"{a['as_of_min']} → {a['as_of_max']} | {a['label_available_max']} |")
    L.append(f"\nRows excluded by purge or outside windows: {audit['excluded_rows']}.\n")
    for target, res in all_results.items():
        L += [f"## Target: `{target}`", "",
              "| model | val PR-AUC | test PR-AUC (95% CI, company bootstrap) | test ROC-AUC (95% CI) | "
              "test Brier | test log loss | precision @val thr | recall @val thr |",
              "|---|---|---|---|---|---|---|---|"]
        for name in ("no_skill", "rule_score", "logistic", "xgboost"):
            r = res[name]
            t, b, th = r["test"], r.get("test_bootstrap"), r["test_at_val_threshold"]
            ci = lambda k: f" ({b[k][0]:.3f}–{b[k][1]:.3f})" if b else ""  # noqa: E731
            L.append(f"| {name} | {r['val']['pr_auc']:.3f} | {t['pr_auc']:.3f}{ci('pr_auc_ci95')} | "
                     f"{t['roc_auc']:.3f}{ci('roc_auc_ci95')} | {t['brier']:.4f} | {t['log_loss']:.4f} | "
                     f"{th['precision']:.2f} | {th['recall_sensitivity']:.2f} |")
        test_prev = res["no_skill"]["test"]["prevalence"]
        L += [f"\nTest prevalence {test_prev:.2%} (no-skill PR-AUC ≈ prevalence). "
              f"Plots: `{target}_pr.png`, `{target}_calibration.png`.", "",
              f"**Logistic C** = {res['logistic']['fit']['C']}; **XGBoost** depth "
              f"{res['xgboost']['fit']['max_depth']}, min_child_weight {res['xgboost']['fit']['min_child_weight']}, "
              f"{res['xgboost']['fit']['best_iteration']} trees.", "",
              "Top XGBoost drivers (gain): " + ", ".join(list(res["xgboost"]["fit"]["top_gain"])[:8]) + ".", ""]
        seg = res["_segment_stability"]
        L.append(f"Segment stability ({seg['model']}, test PR-AUC): by year " +
                 ", ".join(f"{r['year']}: {r['pr_auc']:.3f} (n={r['n']})" for r in seg["year"]) +
                 "; by size quintile " +
                 ", ".join(f"Q{r['size_quintile']}: {r['pr_auc']:.3f}" for r in seg["size_quintile"]) + ".\n")
    L += ["## Reading these results honestly",
          "- The rule score uses year-t stress conditions; stress is persistent, so it is a strong, cheap baseline. "
          "Any neural model in Week 4 must beat it, logistic and XGBoost on validation before claims are made.",
          "- Probabilities are uncalibrated here; Week 4 fits a calibration layer on held-out data.",
          "- Correlated rows of one company are handled by clustering the bootstrap on company.", ""]
    (out / "report.md").write_text("\n".join(L))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/experiment_baselines_v1.yaml")
    args = ap.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text())
    out = Path("training/experiments") / cfg["experiment"]
    out.mkdir(parents=True, exist_ok=True)

    df = load_dataset(cfg)
    split = assign_splits(df, SplitSpec(**cfg["split"]))
    audit = audit_splits(df, split)
    provenance = {"run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                  "panel_sha256": sha256_file(cfg["panel"]), "python": platform.python_version(),
                  "sklearn": sklearn.__version__, "xgboost": xgb.__version__, "features": FEATURES}
    all_results = {t: run_target(df, split, t, cfg, out) for t in (cfg["targets"]["primary"],
                                                                     cfg["targets"]["secondary"])}
    (out / "config_snapshot.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
    (out / "split_audit.json").write_text(json.dumps(audit, indent=1))
    (out / "results.json").write_text(json.dumps({"provenance": provenance, "results": all_results}, indent=1))
    write_report(cfg, audit, all_results, out, provenance)
    for t, res in all_results.items():
        print(t, {n: round(res[n]["test"]["pr_auc"], 3) for n in ("no_skill", "rule_score", "logistic", "xgboost")})


if __name__ == "__main__":
    main()
