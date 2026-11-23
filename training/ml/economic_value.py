"""Economic value of the screen for a capacity-constrained credit team (configs/economic_value_v1.yaml).

    python -m training.ml.economic_value

Each filing year the team reviews the top b% of borrowers by model score. For every model and budget this reports:
stressed borrowers caught (true positives), false alarms, missed, precision, recall, lift over random review, the
share of next-year-stressed DEBT (USD, from the 10-Ks) that was flagged, and the net value
    value = loss avoided per caught borrower x caught - review cost x reviews      (USD m per year)
against reviewing nobody, plus the value ADDED over random review and over the simpler models at equal budget.
Run on the walk-forward out-of-sample predictions (2016-25, primary) and on the frozen 2021-25 test (deployed model).
Textbook scores rank only the rows where they exist; unscored borrowers are never reviewed by them.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from training.ml.results_data import TARGET, frozen_test, risk, walk_forward

CONFIG = Path("configs/economic_value_v1.yaml")
OUT = Path("training/experiments/economic_value_v1")


def flags(df: pd.DataFrame, model: str, budget: float, population: pd.Series | None = None) -> np.ndarray:
    """Top `budget` share of each filing year's (population) rows by risk score; ties broken by row order."""
    f = np.zeros(len(df), dtype=bool)
    s = risk(df, model).to_numpy()
    pop = np.ones(len(df), dtype=bool) if population is None else population.to_numpy()
    for _, idx in df.groupby("year").indices.items():
        idx = idx[pop[idx]]
        k = int(round(budget * len(idx)))
        ok = idx[~np.isnan(s[idx])]
        order = ok[np.argsort(-s[ok], kind="stable")]
        f[order[:k]] = True
    return f


def evaluate(df: pd.DataFrame, cfg: dict, population: pd.Series | None = None) -> dict:
    lm = cfg["loss_model"]
    loss_avoided = lm["exposure_usd_m"] * lm["pd_given_stress"] * lm["lgd"] * lm["share_avoided_by_early_action"]
    c = cfg["review_cost_usd_m"]
    pop = np.ones(len(df), dtype=bool) if population is None else population.to_numpy()
    y = df[TARGET].to_numpy().astype(int)
    debt = df["gross_debt"].fillna(0).clip(lower=0).to_numpy()
    years = df["year"].nunique()
    stressed_debt = float(debt[pop & (y == 1)].sum())
    out = {"rows": int(pop.sum()), "stressed": int(y[pop].sum()), "years": int(years),
           "prevalence": float(y[pop].mean()), "stressed_debt_usd_bn": stressed_debt / 1000,
           "loss_avoided_per_catch_usd_m": loss_avoided, "review_cost_usd_m": c, "budgets": {}}
    for b in cfg["budgets"]:
        row = {}
        n_rev = None
        for m in cfg["models"]:
            f = flags(df, m, b, population)
            tp, fp = int((f & (y == 1)).sum()), int((f & (y == 0)).sum())
            n_rev = int(f.sum())
            rand_tp = n_rev * out["prevalence"]
            row[m] = {"reviews": n_rev, "caught": tp, "false_alarms": fp, "missed": out["stressed"] - tp,
                      "precision": tp / n_rev if n_rev else 0.0, "recall": tp / out["stressed"],
                      "lift_vs_random": (tp / n_rev) / out["prevalence"] if n_rev else 0.0,
                      "debt_flagged_share": float(debt[f & (y == 1)].sum()) / stressed_debt if stressed_debt else None,
                      "net_value_usd_m_per_year": (loss_avoided * tp - c * n_rev) / years,
                      "value_over_random_usd_m_per_year": loss_avoided * (tp - rand_tp) / years}
        row["_random_expected_caught"] = n_rev * out["prevalence"]
        out["budgets"][f"{int(b * 100)}%"] = row
    return out


def paired_catch_diff(df, a, b, budget, n, seed, population=None) -> dict:
    """Extra stressed borrowers caught by model a over model b at one budget, company-clustered bootstrap."""
    y = df[TARGET].to_numpy().astype(int)
    d = ((flags(df, a, budget, population) & (y == 1)).astype(int)
         - (flags(df, b, budget, population) & (y == 1)).astype(int))
    g = df["cik"].to_numpy()
    by = pd.Series(d).groupby(g).sum()
    rng = np.random.default_rng(seed)
    vals = by.to_numpy()
    boots = [vals[rng.integers(0, len(vals), len(vals))].sum() for _ in range(n)]
    return {"extra_caught": int(d.sum()), "ci95": [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))]}


def sensitivity(df, cfg, model="mlp") -> list[dict]:
    rows = []
    for pd_s in cfg["sensitivity"]["pd_given_stress"]:
        for share in cfg["sensitivity"]["share_avoided_by_early_action"]:
            c2 = json.loads(json.dumps(cfg))
            c2["loss_model"].update(pd_given_stress=pd_s, share_avoided_by_early_action=share)
            c2["budgets"] = [cfg["headline_budget"]]
            r = evaluate(df, c2)["budgets"][f"{int(cfg['headline_budget'] * 100)}%"]
            rows.append({"pd_given_stress": pd_s, "share_avoided": share,
                         "loss_avoided_per_catch_usd_m": c2["loss_model"]["exposure_usd_m"] * pd_s * c2["loss_model"]["lgd"] * share,
                         "mlp_net_value_usd_m_per_year": r[model]["net_value_usd_m_per_year"],
                         "mlp_over_random_usd_m_per_year": r[model]["value_over_random_usd_m_per_year"],
                         "altman_net_value_usd_m_per_year": r["altman_z2"]["net_value_usd_m_per_year"]})
    return rows


def main():
    cfg = yaml.safe_load(CONFIG.read_text())
    bs = cfg["bootstrap"]
    hb = cfg["headline_budget"]
    res = {"experiment": cfg["experiment"], "assumptions": cfg}
    for name, df in (("walk_forward_2016_2025", walk_forward()), ("frozen_test_2021_2025", frozen_test())):
        healthy = df["status_t"] == "healthy"
        res[name] = {
            "all_borrowers": evaluate(df, cfg),
            "healthy_borrowers_only": evaluate(df, cfg, healthy),
            "paired_at_headline_budget": {f"{a}_minus_{b}": paired_catch_diff(df, a, b, hb, bs["resamples"], bs["seed"])
                                          for a, b in (("mlp", "logistic"), ("mlp", "xgboost"), ("mlp", "rule_score"),
                                                       ("mlp", "altman_z2"), ("mlp", "ohlson_o"),
                                                       ("ensemble_equal", "logistic"))},
            "sensitivity_headline_budget": sensitivity(df, cfg),
        }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(res, indent=1) + "\n")
    (OUT / "config_snapshot.yaml").write_text(CONFIG.read_text())
    for name in ("walk_forward_2016_2025", "frozen_test_2021_2025"):
        r = res[name]["all_borrowers"]
        h = r["budgets"][f"{int(hb * 100)}%"]
        print(name, f"stressed {r['stressed']} of {r['rows']}", " | ".join(
            f"{m} {h[m]['caught']} ({h[m]['net_value_usd_m_per_year']:.1f}m/yr)" for m in cfg["models"]))


if __name__ == "__main__":
    main()
