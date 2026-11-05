"""Historical Model Replay dataset (Stage D) and held-out error analysis (Stage C).

    python -m training.ml.export_replay

1. Re-scores the frozen held-out test rows (features filed 2021-2025) with the frozen artifact
   `backend/models/stress_mlp_v1` and checks the result reproduces the frozen evaluation EXACTLY
   (PR-AUC and ROC-AUC to 1e-12, Brier to 1e-8, the validation-threshold confusion matrix count for count).
   Training never wrote per-row MLP predictions, so this is how they are recovered without retraining; if the
   check fails the script stops and writes nothing.
2. Saves those predictions next to the baselines' saved predictions:
   training/experiments/mlp_v1/test_predictions_label_next_fy.csv
3. Writes the read-only replay file served by the API: backend/data/replay/replay_v1.json, with
   - error analysis for the Model X-Ray (confusion matrix, outcomes by screening band, onset vs persistence),
   - curated held-out cases, each split into what was KNOWN when the 10-K was filed and the LATER OUTCOME.

Case selection is a fixed rule, not hand-picking:
  * held-out test rows only (split == "test"), revenue >= USD 1bn (recognisable issuers), one row per company;
  * date-consistent: the year-t 10-K was filed 20-130 days after year-end (the original annual report, not a later
    comparative column) and the outcome came from the next annual report 300-430 days later;
  * correct warning = stressed next year, score >= 40% (high band), at most one stress condition in year t;
    false alarm = not stressed, score >= 40%; missed = stressed, score < 15% (low band);
    correct all-clear = not stressed, score < 15%;
  * within each category the most confident cases come first (highest score; lowest for missed / all-clear);
    the first three categories' top cases are the three predefined examples.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from backend.app.features.feature_set import FEATURE_DICTIONARY
from backend.app.labels.stress_label import EBIT_COVER_MAX, LEVERAGE_MAX, stress_label
from backend.app.models.inference import ARTIFACT_DIR, StressModel
from training.ml.run_baselines import load_dataset
from training.ml.splits import SplitSpec, assign_splits

TARGET = "label_next_fy"
PRED_CSV = Path("training/experiments/mlp_v1/test_predictions_label_next_fy.csv")
BASELINE_CSV = Path("training/experiments/baselines_v1/test_predictions_label_next_fy.csv")
REPLAY = Path("backend/data/replay/replay_v1.json")
HIGH, LOW = 0.40, 0.15
PER_CATEGORY = 3
CATEGORIES = {
    "correct_warning": "Correct warning",
    "false_alarm": "False alarm",
    "missed": "Missed case",
    "correct_all_clear": "Correct all-clear",
}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def days(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def fnum(x):
    return None if x is None or pd.isna(x) else float(x)


def ratio(a, b):
    a, b = fnum(a), fnum(b)
    return None if a is None or b is None or b == 0 else a / b


def score_test(model: StressModel, base_cfg: dict) -> pd.DataFrame:
    df = load_dataset(base_cfg)
    split = assign_splits(df, SplitSpec(**base_cfg["split"]))
    sub = df[df[TARGET].notna()]
    te = sub[split.loc[sub.index] == "test"].copy()
    te["logit"] = model.logit_from_matrix(model.pre.transform(te).to_numpy())
    te["mlp"] = model.calibrate(te["logit"].to_numpy())
    te["split"] = "test"
    return te


def verify(te: pd.DataFrame, meta: dict, xray: dict) -> dict:
    y, p = te[TARGET].astype(int).to_numpy(), te["mlp"].to_numpy()
    got = {"n": int(len(te)), "positives": int(y.sum()), "pr_auc": float(average_precision_score(y, p)),
           "roc_auc": float(roc_auc_score(y, p)), "brier": float(brier_score_loss(y, p))}
    ref = meta["test_metrics_calibrated"]
    thr = xray["threshold_test"]
    flag = p >= thr["threshold"]
    conf = {"tp": int((flag & (y == 1)).sum()), "fp": int((flag & (y == 0)).sum()),
            "fn": int((~flag & (y == 1)).sum()), "tn": int((~flag & (y == 0)).sum())}
    checks = {
        "rows": got["n"] == ref["n"] and got["positives"] == ref["positives"],
        "pr_auc": abs(got["pr_auc"] - ref["pr_auc"]) < 1e-12,
        "roc_auc": abs(got["roc_auc"] - ref["roc_auc"]) < 1e-12,
        "brier": abs(got["brier"] - ref["brier"]) < 1e-8,
        "confusion_at_val_threshold": all(conf[k] == thr[k] for k in conf),
    }
    if not all(checks.values()):
        raise SystemExit(f"re-scored predictions do not reproduce the frozen evaluation: {checks} {got} {conf}")
    return {"recomputed": got, "frozen": {k: ref[k] for k in ("n", "positives", "pr_auc", "roc_auc", "brier")},
            "confusion_at_val_threshold": conf, "checks": checks}


def error_analysis(te: pd.DataFrame, xray: dict, bands: dict) -> dict:
    y, p = te[TARGET].astype(int), te["mlp"]
    thr = xray["threshold_test"]["threshold"]
    flag = p >= thr
    onset = te["stress_conditions_t"].fillna(0) < 2          # not already stressed in year t
    out = {"threshold": thr, "threshold_rule": "maximises F1 on 2019-20 validation data; fixed before the test",
           "confusion": {"tp": int((flag & (y == 1)).sum()), "fp": int((flag & (y == 0)).sum()),
                         "fn": int((~flag & (y == 1)).sum()), "tn": int((~flag & (y == 0)).sum())}}
    out["by_band"] = []
    for name, (lo, hi) in bands.items():
        m = (p >= lo) & ((p < hi) | (hi == 1.0))
        out["by_band"].append({"band": name, "from": lo, "to": hi, "n": int(m.sum()), "stressed": int(y[m].sum()),
                               "observed_rate": float(y[m].mean()) if m.any() else None,
                               "mean_prediction": float(p[m].mean()) if m.any() else None})
    stressed = y == 1
    out["stressed_next_year"] = {
        "already_stressed_in_t": {"n": int((stressed & ~onset).sum()),
                                  "caught": int((stressed & ~onset & flag).sum())},
        "new_stress_onset": {"n": int((stressed & onset).sum()), "caught": int((stressed & onset & flag).sum())},
    }
    fa = flag & (y == 0)
    out["false_alarms"] = {"n": int(fa.sum()), "already_stressed_in_t": int((fa & ~onset).sum())}
    return out


def decile_context(te: pd.DataFrame) -> list[dict]:
    q = np.quantile(te["mlp"], np.linspace(0, 1, 11))
    out = []
    for i in range(10):
        lo, hi = q[i], q[i + 1]
        m = (te["mlp"] >= lo) & ((te["mlp"] < hi) if i < 9 else (te["mlp"] <= hi))
        out.append({"from": float(lo), "to": float(hi), "n": int(m.sum()), "observed_rate": float(te.loc[m, TARGET].mean())})
    return out


def find_next(panel: pd.DataFrame, cik: str, fye: str) -> pd.Series | None:
    rows = panel[(panel["cik"] == cik) & (panel["fiscal_year_end"] > fye)].sort_values("fiscal_year_end")
    if rows.empty:
        return None
    nxt = rows.iloc[0]
    return nxt if 300 <= days(fye, nxt["fiscal_year_end"]) <= 430 else None


def snapshot(r: pd.Series) -> dict:
    ebitda = fnum(r["m_ebitda"])
    return {
        "revenue": fnum(r["v_revenue"]), "ebitda": ebitda, "ebitda_margin": fnum(r["m_ebitda_margin"]),
        "operating_income": fnum(r["v_operating_income"]), "interest_expense": fnum(r["v_interest_expense"]),
        "gross_debt": fnum(r["m_gross_debt"]), "cash": fnum(r["v_cash"]),
        "operating_cash_flow": fnum(r["v_operating_cash_flow"]),
        "ebit_interest_cover": ratio(r["v_operating_income"], r["v_interest_expense"]),
        "gross_debt_to_ebitda": ratio(r["m_gross_debt"], ebitda) if ebitda and ebitda > 0 else None,
        "revenue_growth": fnum(r["m_revenue_growth"]),
    }


def conditions(r: pd.Series) -> dict:
    """The three label conditions, evaluated on one panel row (with the values they were tested on)."""
    ebit, intr, debt, ebitda, cfo = (fnum(r[c]) for c in ("v_operating_income", "v_interest_expense", "m_gross_debt",
                                                          "m_ebitda", "v_operating_cash_flow"))
    lab = stress_label({"operating_income": ebit, "interest_expense": intr, "gross_debt": debt, "ebitda": ebitda,
                        "operating_cash_flow": cfo})
    return {
        "label": lab.label,
        "coverage_weak": {"met": lab.coverage_weak, "value": ratio(ebit, intr), "rule": f"EBIT / interest < {EBIT_COVER_MAX}x"},
        "leverage_high": {"met": lab.leverage_high, "value": ratio(debt, ebitda) if ebitda and ebitda > 0 else None,
                          "ebitda_nonpositive": ebitda is not None and ebitda <= 0,
                          "rule": f"gross debt / EBITDA > {LEVERAGE_MAX}x (or debt with EBITDA <= 0)"},
        "cash_flow_weak": {"met": lab.cash_flow_weak, "value": cfo, "rule": "operating cash flow < 0"},
    }


def categorise(p: float, y: int, stress_t: float) -> str | None:
    if y == 1 and p >= HIGH and (pd.isna(stress_t) or stress_t <= 1):
        return "correct_warning"
    if y == 0 and p >= HIGH:
        return "false_alarm"
    if y == 1 and p < LOW:
        return "missed"
    if y == 0 and p < LOW:
        return "correct_all_clear"
    return None


ASSESSMENT = {"correct_warning": "Well-calibrated warning", "false_alarm": "Overconfident: false alarm",
              "missed": "Miss", "correct_all_clear": "Well-calibrated all-clear"}


def verdict(cat: str, p: float, observed: float, stress_t) -> str:
    obs = f"{observed:.0%}"
    already = not pd.isna(stress_t) and stress_t >= 2
    return {
        "correct_warning": f"The network gave {p:.0%} and stress followed. Among held-out companies scored in the same "
                           f"range, {obs} became stressed, so a score this high was borne out.",
        "false_alarm": f"The network gave {p:.0%}, but the company did not meet two stress conditions the next year. "
                       f"Among held-out companies scored in the same range, {obs} did become stressed, so about "
                       f"{1 - observed:.0%} of such scores are false alarms; this was one of them."
                       + (" It already met two or more conditions in the filing year and recovered, the network's most "
                          "common kind of false alarm." if already else ""),
        "missed": f"The network gave only {p:.0%}, yet stress followed. Among held-out companies scored in the same "
                  f"range, {obs} became stressed. Stress that starts from healthy accounts in the filing year is the network's "
                  "main blind spot.",
        "correct_all_clear": f"The network gave {p:.0%} and no stress followed. Among held-out companies scored in the "
                             f"same range, {obs} became stressed.",
    }[cat]


def main():
    base_cfg = yaml.safe_load(Path("configs/experiment_baselines_v1.yaml").read_text())
    model = StressModel.load()
    meta = model.meta
    xray = json.loads((ARTIFACT_DIR / "xray.json").read_text())
    te = score_test(model, base_cfg)
    check = verify(te, meta, xray)

    base = pd.read_csv(BASELINE_CSV, dtype={"cik": str})
    te = te.merge(base[["cik", "fiscal_year_end", "xgboost", "logistic", "rule_score"]], on=["cik", "fiscal_year_end"],
                  how="left", validate="one_to_one")
    assert te["xgboost"].notna().all(), "baseline predictions missing for some test rows"

    PRED_CSV.write_text(te[["cik", "company_name", "fiscal_year_end", "as_of_date", "label_available_date", "split",
                            TARGET, "logit", "mlp", "xgboost", "logistic", "rule_score"]]
                        .rename(columns={TARGET: "y"}).to_csv(index=False, float_format="%.17g"))

    panel = pd.read_csv(base_cfg["panel"], dtype={"cik": str})
    pidx = panel.set_index(["cik", "fiscal_year_end"])
    deciles = decile_context(te)
    training_ciks = set(json.loads((ARTIFACT_DIR / "training_ciks.json").read_text()))

    picked: dict[str, list] = {c: [] for c in CATEGORIES}
    used: set[tuple[str, str]] = set()
    te = te.assign(cat=[categorise(p, int(y), s) for p, y, s in zip(te["mlp"], te[TARGET], te["stress_conditions_t"])])
    for cat in CATEGORIES:
        cand = te[te["cat"] == cat].copy()
        cand["rev"] = [pidx.loc[(c, f), "v_revenue"] for c, f in zip(cand["cik"], cand["fiscal_year_end"])]
        cand = cand[cand["rev"] >= 1000]
        cand = cand.sort_values("mlp", ascending=cat in ("missed", "correct_all_clear"))
        for _, r in cand.iterrows():
            if len(picked[cat]) == PER_CATEGORY:
                break
            if (cat, r["cik"]) in used:
                continue
            filed_after = days(r["fiscal_year_end"], r["as_of_date"])
            nxt = find_next(panel, r["cik"], r["fiscal_year_end"])
            if not (20 <= filed_after <= 130) or nxt is None:
                continue
            out_after = days(r["as_of_date"], r["label_available_date"])
            if not 300 <= out_after <= 430:
                continue
            outcome = conditions(nxt)
            if outcome["label"] != int(r[TARGET]):
                raise SystemExit(f"label rebuilt from t+1 row disagrees with the panel for {r['cik']} {r['fiscal_year_end']}")
            picked[cat].append((r, nxt, outcome))
            used.add((cat, r["cik"]))

    cases = []
    for cat, rows in picked.items():
        for rank, (r, nxt, outcome) in enumerate(rows):
            row_t = pidx.loc[(r["cik"], r["fiscal_year_end"])]
            feats = te[(te["cik"] == r["cik"]) & (te["fiscal_year_end"] == r["fiscal_year_end"])]
            drivers = model.drivers(feats[list(FEATURE_DICTIONARY)], top_k=4)
            p = float(r["mlp"])
            dec = next(d for d in deciles if d["from"] <= p <= d["to"])
            cases.append({
                "id": f"{r['cik']}-{r['fiscal_year_end']}",
                "category": cat,
                "rank_in_category": rank + 1,
                "known": {
                    "split": "test",
                    "company_name": r["company_name"], "cik": r["cik"], "fiscal_year_end": r["fiscal_year_end"],
                    "features_as_of": r["as_of_date"], "filed_days_after_year_end": days(r["fiscal_year_end"], r["as_of_date"]),
                    "next_fiscal_year_end": nxt["fiscal_year_end"],
                    "company_in_training_data": r["cik"] in training_ciks,
                    "metrics_usd_m": snapshot(row_t),
                    "stress_conditions_in_t": {("stressed_in_t" if k == "label" else k): v
                                               for k, v in conditions(row_t).items()},
                    "prediction": {"probability": p, "logit": float(r["logit"]), "band": model.band(p),
                                   "xgboost_probability": float(r["xgboost"])},
                    "drivers": [{k: d[k] for k in ("feature", "description", "unit", "value", "logit_contribution")}
                                for d in drivers],
                },
                "outcome": {
                    "label": int(r[TARGET]),
                    "label_available_date": r["label_available_date"],
                    "fiscal_year_end": nxt["fiscal_year_end"],
                    "metrics_usd_m": snapshot(nxt),
                    "conditions": {k: v for k, v in outcome.items() if k != "label"},
                    "assessment": ASSESSMENT[cat],
                    "verdict": verdict(cat, p, dec["observed_rate"], r["stress_conditions_t"]),
                    "same_range_observed_rate": dec["observed_rate"],
                    "same_range": {"from": dec["from"], "to": dec["to"], "n": dec["n"]},
                },
            })
    # examples 1-3: top correct warning, false alarm, missed case, in alphabetical order so the order gives nothing away
    featured = sorted([c for c in cases if c["rank_in_category"] == 1 and c["category"] != "correct_all_clear"],
                      key=lambda c: c["known"]["company_name"].lower())
    for i, c in enumerate(featured, 1):
        c["example"] = i
    for c in cases:
        c.setdefault("example", None)

    replay = {
        "version": "replay_v1",
        "model": meta["model"], "target": meta["target"], "label_version": meta["label_version"],
        "split": "test",
        "test_window": meta["data_windows"]["test_features_filed"],
        "selection_rule": __doc__.split("Case selection is a fixed rule, not hand-picking:")[1].strip(),
        "provenance": {"panel_sha256": sha(Path(base_cfg["panel"])),
                       "weights_sha256": sha(ARTIFACT_DIR / "weights.npz"),
                       "calibrator_sha256": sha(ARTIFACT_DIR / "calibrator.json"),
                       "predictions_csv": str(PRED_CSV)},
        "verification": check,
        "error_analysis": error_analysis(te, xray, meta["risk_bands"]),
        "score_deciles": deciles,
        "cases": sorted(cases, key=lambda c: c["known"]["company_name"].lower()),
    }
    REPLAY.parent.mkdir(parents=True, exist_ok=True)
    REPLAY.write_text(json.dumps(replay, indent=1, default=float) + "\n")
    print(f"verified {check['recomputed']['n']} held-out predictions; wrote {PRED_CSV} and {REPLAY} "
          f"({len(cases)} cases; examples: {[c['known']['company_name'] for c in featured]})")


if __name__ == "__main__":
    main()
