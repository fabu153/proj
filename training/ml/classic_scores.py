"""Textbook benchmarks: Altman Z'' (1995) and Ohlson O (1980) on the same held-out rows as the network.

    SEC_USER_AGENT="Name email" python -m training.ml.classic_scores        # fetch once (549 small requests), then evaluate
    python -m training.ml.classic_scores --offline                           # evaluate from the saved inputs only

The panel (panel_v1.csv, frozen) already holds every input except retained earnings. Retained earnings come from
SEC's companyconcept API (RetainedEarningsAccumulatedDeficit) and follow the panel's point-in-time rule: the value
for fiscal year t is the one in the first 10-K that reported it, and only if it was filed by year t's as-of date.
Scores use the original, unrefitted coefficients (backend/app/finance/credit_extras.py — the same code the app runs).
A missing input leaves the score missing; comparisons are made on the rows where the score exists, against the
deployed network on exactly those rows. Output: training/experiments/classic_scores_v1/ and
training/data/classic_inputs_v1.csv. Research only; nothing here is a model artifact.
"""
from __future__ import annotations

import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sklearn.metrics import average_precision_score, roc_auc_score

from backend.app.finance.credit_extras import altman_z2, ohlson_o
from training.ml.evaluate import cluster_bootstrap
from training.ml.run_baselines import load_dataset, sha256_file
from training.ml.splits import SplitSpec, assign_splits

OUT = Path("training/experiments/classic_scores_v1")
INPUTS = Path("training/data/classic_inputs_v1.csv")
CACHE = Path("training/data/raw/sec_concepts")
TAG = "RetainedEarningsAccumulatedDeficit"


def fetch_retained_earnings(ciks: list[str]) -> None:
    from backend.app.documents.sec_client import SECClient, SECError
    client = SECClient(cache_dir=CACHE)
    keep = lambda d: {"cik": d.get("cik"), "tag": d.get("tag"), "units": {"USD": d.get("units", {}).get("USD", [])}}  # noqa: E731
    for i, cik in enumerate(ciks, 1):
        try:
            client._cached(f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{TAG}.json",
                           f"{TAG}_{cik}", False, keep)
        except SECError as e:
            if e.kind != "not_found":
                raise
            (CACHE / f"{TAG}_{cik}.json.gz").write_bytes(gzip.compress(b'{"units": {"USD": []}}'))
        if i % 50 == 0:
            print(f"  {i}/{len(ciks)}", flush=True)


def build_inputs(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for cik, g in panel.groupby("cik"):
        p = CACHE / f"{TAG}_{cik}.json.gz"
        facts = json.loads(gzip.decompress(p.read_bytes())).get("units", {}).get("USD", []) if p.exists() else []
        facts = [f for f in facts if str(f.get("form", "")).startswith("10-K")]
        for _, r in g.iterrows():
            cands = sorted((f for f in facts if f["end"] == r["fiscal_year_end"] and f["filed"] <= r["as_of_date"]),
                           key=lambda f: (f["filed"], f["accn"]))
            f = cands[0] if cands else None                     # original vintage, already public at as-of
            rows.append({"cik": cik, "fiscal_year_end": r["fiscal_year_end"],
                         "retained_earnings": f["val"] / 1e6 if f else None,
                         "re_accession": f["accn"] if f else None, "re_filed": f["filed"] if f else None})
    return pd.DataFrame(rows)


def scores(panel: pd.DataFrame, inputs: pd.DataFrame) -> pd.DataFrame:
    """Z'' and O for every panel row, from the panel's own (model-basis) inputs in USD millions."""
    p = panel.merge(inputs, on=["cik", "fiscal_year_end"], how="left")
    p["_fye"], p["_asof"] = pd.to_datetime(p["fiscal_year_end"]), pd.to_datetime(p["as_of_date"])
    p = p.sort_values(["cik", "_fye"])
    prev_ni = []
    for cik, g in p.groupby("cik", sort=False):
        for _, r in g.iterrows():
            prev = g[(g["_fye"] < r["_fye"]) & ((r["_fye"] - g["_fye"]).dt.days.between(330, 400)) & (g["_asof"] <= r["_asof"])]
            prev_ni.append(prev["v_net_income"].iloc[-1] if len(prev) else None)
    p["net_income_prior"] = prev_ni
    out = []
    for _, r in p.iterrows():
        v = {k: (None if pd.isna(r.get(f"v_{k}")) else float(r[f"v_{k}"])) for k in
             ("total_assets", "current_assets", "current_liabilities", "operating_income", "stockholders_equity",
              "total_liabilities", "net_income", "operating_cash_flow")}
        v["retained_earnings"] = None if pd.isna(r["retained_earnings"]) else float(r["retained_earnings"])
        prior = {"net_income": None if r["net_income_prior"] is None or pd.isna(r["net_income_prior"]) else float(r["net_income_prior"])}
        z, o = altman_z2(v), ohlson_o(v, prior, r["fiscal_year_end"])
        out.append({"cik": r["cik"], "fiscal_year_end": r["fiscal_year_end"],
                    "altman_z2": z["value"] if z["available"] else np.nan,
                    "ohlson_o": o["value"] if o["available"] else np.nan})
    return pd.DataFrame(out)


def paired(y, a, b, groups, n=1000, seed=7):
    rng = np.random.default_rng(seed)
    uniq = np.unique(groups)
    idx = {g: np.flatnonzero(groups == g) for g in uniq}
    d = []
    for _ in range(n):
        t = np.concatenate([idx[g] for g in rng.choice(uniq, size=len(uniq), replace=True)])
        if 0 < y[t].sum() < len(t):
            d.append(average_precision_score(y[t], a[t]) - average_precision_score(y[t], b[t]))
    return {"mean_diff": float(average_precision_score(y, a) - average_precision_score(y, b)),
            "ci95": [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))], "share_a_better": float(np.mean(np.array(d) > 0))}


def evaluate(y, groups, risk: dict, mlp) -> dict:
    """risk: name -> riskier-is-higher score (NaN where unavailable)."""
    res = {}
    for name, s in risk.items():
        m = ~np.isnan(s)
        yy, ss, gg, mm = y[m], s[m], groups[m], mlp[m]
        res[name] = {"rows": int(m.sum()), "coverage": float(m.mean()), "positives": int(yy.sum()),
                     "pr_auc": float(average_precision_score(yy, ss)), "roc_auc": float(roc_auc_score(yy, ss)),
                     # ranks only: a logistic squash keeps the score in [0, 1] for the shared bootstrap helper
                     "pr_auc_ci95": cluster_bootstrap(yy, 1 / (1 + np.exp(-(ss - np.median(ss)))), gg, 1000, 7)["pr_auc_ci95"],
                     "deployed_on_same_rows": {"pr_auc": float(average_precision_score(yy, mm)),
                                               "roc_auc": float(roc_auc_score(yy, mm))},
                     "minus_deployed": paired(yy, ss, mm, gg),
                     "no_skill": float(yy.mean())}
    return res


def main(offline: bool):
    base = yaml.safe_load(Path("configs/experiment_baselines_v1.yaml").read_text())
    panel = pd.read_csv(base["panel"], dtype={"cik": str})
    if not offline:
        fetch_retained_earnings(sorted(panel["cik"].unique()))
        build_inputs(panel).to_csv(INPUTS, index=False)
    inputs = pd.read_csv(INPUTS, dtype={"cik": str})
    sc = scores(panel, inputs)
    OUT.mkdir(parents=True, exist_ok=True)
    sc.to_csv(OUT / "panel_scores.csv", index=False, float_format="%.8g")      # also feeds the app's percentiles

    df = load_dataset(base)
    split = assign_splits(df, SplitSpec(**base["split"]))
    pred = pd.read_csv("training/experiments/mlp_v1/test_predictions_label_next_fy.csv", dtype={"cik": str})
    te = df[(split == "test") & df["label_next_fy"].notna()][["cik", "fiscal_year_end", "label_next_fy", "label_onset"]]
    te = te.reset_index(drop=True).merge(pred[["cik", "fiscal_year_end", "mlp"]], how="left").merge(sc, how="left")
    assert len(te) == 1086 and te["mlp"].notna().all()
    risk = {"altman_z2": -te["altman_z2"].to_numpy(), "ohlson_o": te["ohlson_o"].to_numpy()}   # higher = riskier
    y, g = te["label_next_fy"].astype(int).to_numpy(), te["cik"].to_numpy()
    on = te["label_onset"].notna().to_numpy()
    res = {
        "experiment": "classic_scores_v1", "status": "textbook benchmarks; research only",
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "provenance": {"panel_sha256": sha256_file(base["panel"]), "inputs_sha256": sha256_file(str(INPUTS)),
                       "deflator": "backend/data/macro/gdp_deflator.json"},
        "conventions": {"altman_z2": "Altman (1995) Z'' four ratios, no constant; EBIT = operating income; lower = riskier",
                        "ohlson_o": "Ohlson (1980) model 1; total assets in USD millions; GDP deflator (1968 = 100) "
                                    "for the GNP index; FFO = operating cash flow; higher = riskier. Ranking metrics "
                                    "do not depend on the units of total assets."},
        "retained_earnings_coverage_panel": float(inputs["retained_earnings"].notna().mean()),
        "overall": evaluate(y, g, risk, te["mlp"].to_numpy()),
        "onset": evaluate(y[on], g[on], {k: v[on] for k, v in risk.items()}, te["mlp"].to_numpy()[on]),
        "test_set_status": "2021-25 test window, already inspected in earlier experiments: exploratory",
    }
    (OUT / "results.json").write_text(json.dumps(res, indent=1) + "\n")
    te[["cik", "fiscal_year_end", "label_next_fy", "label_onset", "mlp", "altman_z2", "ohlson_o"]].to_csv(
        OUT / "test_predictions.csv", index=False, float_format="%.10g")
    for k in ("overall", "onset"):
        for n, r in res[k].items():
            print(f"{k:8s} {n:10s} rows {r['rows']} PR-AUC {r['pr_auc']:.3f} (deployed same rows {r['deployed_on_same_rows']['pr_auc']:.3f}) "
                  f"diff {r['minus_deployed']['mean_diff']:+.3f} {r['minus_deployed']['ci95']}")


if __name__ == "__main__":
    main("--offline" in sys.argv)
