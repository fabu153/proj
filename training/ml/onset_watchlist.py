"""Research only: would a separate watch-list threshold for currently healthy borrowers catch more new stress?

    python -m training.ml.onset_watchlist        # seconds; torch not needed

The deployed network is NOT retrained: its frozen weights are run through the app's own numpy inference (which
reproduces the published test predictions to 1e-15). On the canonical onset cohort (label_onset: confirmed not
stressed in t, t+1 determinable) the original threshold is compared with thresholds that flag 5/10/15/20% of
healthy borrowers. Each threshold is fixed on VALIDATION scores (2019-20 filings) and applied once to the test
window. Config: configs/experiment_onset_watchlist_v1.yaml. Output: training/experiments/onset_watchlist_v1/.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from backend.app.models.inference import ARTIFACT_DIR, StressModel
from training.ml.onset_data import onset_cohort
from training.ml.run_baselines import load_dataset, sha256_file
from training.ml.splits import SplitSpec, assign_splits

CONFIG = Path("configs/experiment_onset_watchlist_v1.yaml")
OUT = Path("training/experiments/onset_watchlist_v1")


def counts(y: np.ndarray, flag: np.ndarray) -> dict:
    tp, fp = int((flag & (y == 1)).sum()), int((flag & (y == 0)).sum())
    fn, tn = int((~flag & (y == 1)).sum()), int((~flag & (y == 0)).sum())
    return {"flagged": tp + fp, "flag_rate": (tp + fp) / len(y), "caught": tp, "false_alarms": fp, "missed": fn,
            "correct_all_clear": tn, "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None}


def bootstrap(y, p, groups, thresholds: dict, base_key: str, n: int, seed: int) -> dict:
    """Company-clustered 95% intervals for recall, precision and false alarms per 100 healthy borrowers, plus the
    paired change against the original threshold (same resampled companies for both)."""
    rng = np.random.default_rng(seed)
    uniq = np.unique(groups)
    idx_by = {g: np.flatnonzero(groups == g) for g in uniq}
    draws = {k: {"recall": [], "precision": [], "fa_per_100": [], "d_recall": [], "d_caught": [], "d_false_alarms": []}
             for k in thresholds}
    for _ in range(n):
        take = np.concatenate([idx_by[g] for g in rng.choice(uniq, size=len(uniq), replace=True)])
        yy, pp = y[take], p[take]
        if yy.sum() == 0:
            continue
        b = counts(yy, pp >= thresholds[base_key])
        for k, t in thresholds.items():
            c = counts(yy, pp >= t)
            d = draws[k]
            d["recall"].append(c["recall"])
            if c["precision"] is not None:
                d["precision"].append(c["precision"])
            d["fa_per_100"].append(100 * c["false_alarms"] / max((yy == 0).sum(), 1))
            d["d_recall"].append(c["recall"] - b["recall"])
            d["d_caught"].append(c["caught"] - b["caught"])
            d["d_false_alarms"].append(c["false_alarms"] - b["false_alarms"])
    q = lambda a: [float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5))] if len(a) else None  # noqa: E731
    return {k: {m: q(v) for m, v in d.items()} for k, d in draws.items()}


def main():
    cfg = yaml.safe_load(CONFIG.read_text())
    base = yaml.safe_load(Path(cfg["base_config"]).read_text())
    df = load_dataset(base)
    split = assign_splits(df, SplitSpec(**base["split"]))
    sub = onset_cohort(df)
    sp = split.loc[sub.index]
    va, te = sub[sp == "val"], sub[sp == "test"]
    model = StressModel.load(ARTIFACT_DIR)
    p_va, p_te = model.predict_proba(va), model.predict_proba(te)

    # the frozen test predictions must be reproduced exactly: same model, same rows
    ref = pd.read_csv("training/experiments/mlp_v1/test_predictions_label_next_fy.csv", dtype={"cik": str})
    k = te[["cik", "fiscal_year_end"]].reset_index(drop=True).merge(ref, on=["cik", "fiscal_year_end"], how="left")
    parity = float(np.abs(k["mlp"].to_numpy() - p_te).max())
    assert parity < 1e-9, f"deployed scores do not reproduce the frozen predictions ({parity})"

    xray = json.loads((ARTIFACT_DIR / "xray.json").read_text())
    thresholds = {"original": float(xray["threshold_test"]["threshold"])}
    for b in cfg["alert_budgets"]:
        thresholds[f"budget_{int(b * 100)}"] = float(np.quantile(p_va, 1 - b))
    yva, yte = va["label_onset"].astype(int).to_numpy(), te["label_onset"].astype(int).to_numpy()
    bs = cfg["bootstrap"]
    res = {
        "experiment": cfg["experiment"], "status": "research only; threshold not deployed",
        "test_set_status": cfg["test_set_status"].strip(),
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "provenance": {"panel_sha256": sha256_file(base["panel"]), "config_sha256": sha256_file(str(CONFIG)),
                       "weights_sha256": sha256_file(str(ARTIFACT_DIR / "weights.npz")),
                       "test_parity_max_abs_diff": parity},
        "population": {"definition": "label_onset: year-t status determinable and not stressed; t+1 determinable",
                       "validation": {"rows": int(len(va)), "onsets": int(yva.sum()), "companies": int(va["cik"].nunique())},
                       "test": {"rows": int(len(te)), "onsets": int(yte.sum()), "companies": int(te["cik"].nunique())}},
        "thresholds": thresholds,
        "validation": {k: counts(yva, p_va >= t) for k, t in thresholds.items()},
        "test": {k: counts(yte, p_te >= t) for k, t in thresholds.items()},
        "test_ci95": bootstrap(yte, p_te, te["cik"].to_numpy(), thresholds, "original", bs["resamples"], bs["seed"]),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(res, indent=1) + "\n")
    (OUT / "config_snapshot.yaml").write_text(CONFIG.read_text())
    pd.concat([pd.DataFrame({"split": "val", "cik": va["cik"].to_numpy(), "fiscal_year_end": va["fiscal_year_end"].to_numpy(),
                             "y": yva, "score": p_va}),
               pd.DataFrame({"split": "test", "cik": te["cik"].to_numpy(), "fiscal_year_end": te["fiscal_year_end"].to_numpy(),
                             "y": yte, "score": p_te})]).to_csv(OUT / "predictions.csv", index=False, float_format="%.10g")
    for k, t in thresholds.items():
        c = res["test"][k]
        print(f"{k:10s} thr {t:.3f} | test flagged {c['flagged']:3d} ({c['flag_rate']:.0%}) caught {c['caught']}/{yte.sum()} "
              f"false alarms {c['false_alarms']} precision {c['precision'] or 0:.0%}")


if __name__ == "__main__":
    main()
