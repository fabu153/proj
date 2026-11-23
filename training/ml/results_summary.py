"""Results summary: every headline number, table and figure, computed from the saved experiment results.

    python -m training.ml.results_summary          # ~1 min, CPU only

Inputs (all committed): training/data/panel_v1.csv and training/experiments/* (written by the scripts that
`make experiments` runs). Outputs in training/experiments/results_summary_v1/:
    numbers.json      every headline number (PR-AUCs with company-clustered intervals, paired differences,
                      walk-forward, economic value, robustness), formatted as reported
    tables/*.md       results tables (frozen test, walk-forward, economic value, sensitivity, robustness, calibration)
    figures/*.png     pipeline, walk-forward by year, capture curves, robustness by size and sector
CI re-runs this and fails if numbers.json changes.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import yaml
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from training.ml.evaluate import cluster_bootstrap  # noqa: E402
from training.ml.results_data import LABELS, TARGET, frozen_test, risk, walk_forward  # noqa: E402
from training.ml.run_baselines import load_dataset  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "training/experiments"
OUT = EXP / "results_summary_v1"
FIG = OUT / "figures"
COLORS = {"mlp": "#0f766e", "logistic": "#1d4ed8", "xgboost": "#b45309", "ensemble_equal": "#7c3aed",
          "rule_score": "#6b7280", "altman_z2": "#be123c", "ohlson_o": "#db2777", "no_skill": "#9ca3af"}
N: dict[str, str] = {}
T: dict[str, str] = {}


def j(p):
    return json.loads(Path(p).read_text())


def put(name, value, fmt="{:.3f}"):
    N[name] = fmt.format(value) if not isinstance(value, str) else value


def pct(x, d=0):
    return f"{100 * x:.{d}f}%"


def ci(a, b, f="{:.3f}"):
    return f"{f.format(a)}–{f.format(b)}"


def sgn(x, f="{:.3f}"):
    return ("+" if x >= 0 else "−") + f.format(abs(x))


def table(head: list[str], rows: list[list], align: str | None = None) -> str:
    align = align or "l" + "r" * (len(head) - 1)
    # dash counts set pandoc's relative column widths: proportional to the longest cell (or longest header word)
    width = [max([len(str(r[i]).replace("*", "")) for r in rows] + [max(len(w) for w in head[i].split())] + [3])
             for i in range(len(head))]
    sep = ["-" * min(w, 34) + ":" if a == "r" else ":" + "-" * min(w, 34) for a, w in zip(align, width)]
    lines = ["| " + " | ".join(head) + " |", "| " + " | ".join(sep) + " |"]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def paired_pr(y, a, b, g, n=1000, seed=7):
    rng = np.random.default_rng(seed)
    uniq = np.unique(g)
    idx = {k: np.flatnonzero(g == k) for k in uniq}
    d = []
    for _ in range(n):
        t = np.concatenate([idx[k] for k in rng.choice(uniq, size=len(uniq), replace=True)])
        if 0 < y[t].sum() < len(t):
            d.append(average_precision_score(y[t], a[t]) - average_precision_score(y[t], b[t]))
    return float(average_precision_score(y, a) - average_precision_score(y, b)), np.percentile(d, [2.5, 97.5])


# ------------------------------------------------------------------ data and design
def data_numbers():
    base = yaml.safe_load((ROOT / "configs/experiment_baselines_v1.yaml").read_text())
    panel = pd.read_csv(ROOT / base["panel"], dtype={"cik": str})
    uni = pd.read_csv(ROOT / "training/data/universe_v1.csv")
    df = load_dataset(base)
    lab = df[df[TARGET].notna()]
    audit = j(EXP / "baselines_v1/split_audit.json")
    put("universe_companies", f"{len(uni):,}")
    put("panel_rows", f"{len(panel):,}")
    put("panel_companies", f"{panel['cik'].nunique():,}")
    put("panel_fy_min", panel["fiscal_year_end"].min()[:4])
    put("panel_fy_max", panel["fiscal_year_end"].max()[:4])
    put("lending_rows", f"{len(df):,}")
    put("labelled_rows", f"{len(lab):,}")
    put("labelled_companies", f"{lab['cik'].nunique():,}")
    put("prevalence_all", pct(lab[TARGET].mean(), 1))
    # labelled rows per split (the audit counts every row in the window, labelled or not)
    from training.ml.splits import SplitSpec, assign_splits
    sp = assign_splits(df, SplitSpec(**base["split"])).loc[lab.index]
    rows = []
    for s, name in (("train", "Training"), ("val", "Validation"), ("test", "Test")):
        d = lab[sp == s]
        put(f"{s}_rows", f"{len(d):,}")
        put(f"{s}_companies", f"{d['cik'].nunique():,}")
        put(f"{s}_prev", pct(d[TARGET].mean(), 1))
        rows.append([name, f"{d['as_of_date'].min()[:7]} to {d['as_of_date'].max()[:7]}", f"{len(d):,}",
                     f"{d['cik'].nunique():,}", f"{int(d[TARGET].sum()):,}", pct(d[TARGET].mean(), 1)])
    put("excluded_purge", f"{int((sp == 'excluded').sum()):,}")
    put("excluded_rows_all", f"{audit['excluded_rows']:,}")
    T["splits"] = table(["Window", "Accounts filed", "Company-years", "Companies", "Stressed next year", "Rate"], rows,
                        "llrrrr")


# ------------------------------------------------------------------ frozen test (Table 2)
def frozen_numbers():
    te = frozen_test()
    y, g = te[TARGET].to_numpy().astype(int), te["cik"].to_numpy()
    mlp = te["mlp"].to_numpy()
    rows = []
    for m in ["no_skill", "rule_score", "altman_z2", "ohlson_o", "logistic", "xgboost", "mlp", "ensemble_equal"]:
        s = risk(te, m).to_numpy()
        ok = ~np.isnan(s)
        ap, roc = average_precision_score(y[ok], s[ok]), roc_auc_score(y[ok], s[ok]) if m != "no_skill" else 0.5
        if m in ("altman_z2", "ohlson_o"):
            sq = 1 / (1 + np.exp(-(s[ok] - np.median(s[ok]))))
            c = cluster_bootstrap(y[ok], sq, g[ok], 1000, 7)["pr_auc_ci95"]
            brier = "–"
        elif m == "no_skill":
            c, brier = None, f"{brier_score_loss(y, s):.3f}"
        else:
            c = cluster_bootstrap(y, s, g, 1000, 7)["pr_auc_ci95"]
            brier = f"{brier_score_loss(y, s):.3f}"
        if m in ("no_skill", "mlp"):
            diff = "–"
        else:
            dd, dci = paired_pr(y[ok], s[ok], mlp[ok], g[ok])
            diff = f"{sgn(dd)} ({sgn(dci[0])} to {sgn(dci[1])})"
            put(f"ft_{m}_minus_mlp", sgn(dd))
            put(f"ft_{m}_minus_mlp_ci", f"{sgn(dci[0])} to {sgn(dci[1])}")
        put(f"ft_{m}_pr", ap)
        put(f"ft_{m}_roc", roc)
        if c is not None:
            put(f"ft_{m}_pr_ci", ci(*c))
        name = LABELS[m] + (" †" if m in ("altman_z2", "ohlson_o") else "") + (" (deployed)" if m == "mlp" else "")
        rows.append([name, f"{ap:.3f}" + (f" ({ci(*c)})" if c is not None else ""), f"{roc:.3f}", brier, diff,
                     f"{int(ok.sum()):,}"])
    T["frozen"] = table(["Model", "PR-AUC (95% CI)", "ROC-AUC", "Brier", "Minus network (95% CI)", "Rows"], rows,
                        "lrrrrr")
    put("ft_prev", pct(y.mean(), 1))
    put("ft_rows", f"{len(te):,}")
    put("ft_companies", f"{te['cik'].nunique():,}")
    put("ft_mlp_brier", brier_score_loss(y, mlp))
    # deployed threshold behaviour
    mres = j(EXP / "mlp_v1/results.json")["results"][TARGET]
    th = mres["ensemble"]["test_at_val_threshold"]
    put("thr", th["threshold"])
    put("thr_precision", pct(th["precision"]))
    put("thr_recall", pct(th["recall_sensitivity"]))
    put("thr_tp", str(th["tp"]))
    put("thr_fp", str(th["fp"]))
    put("thr_fn", str(th["fn"]))
    pi = mres["permutation_importance_val"]
    top = list(pi)[:5]
    nice = {"stress_conditions_t": "stress conditions already met", "operating_margin": "operating margin",
            "net_margin": "net margin", "ebitda_nonpositive": "non-positive EBITDA", "roa": "return on assets",
            "cfo_to_assets": "operating cash flow / assets"}
    put("top_drivers", ", ".join(nice.get(k, k.replace("_", " ")) for k in top))
    # calibration table for the annex
    from training.ml.evaluate import calibration_table
    cal = calibration_table(y, mlp, bins=10)
    put("cal_max_gap", float((cal["mean_pred"] - cal["observed"]).abs().max()))
    T["calibration"] = table(["Decile of predicted risk", "Mean predicted", "Observed rate", "Rows"],
                             [[int(r.bin) + 1, pct(r.mean_pred, 1), pct(r.observed, 1), int(r.n)] for r in cal.itertuples()])
    # onset / watch-list research
    wl = j(EXP / "onset_watchlist_v1/results.json")
    put("wl_orig_caught", str(wl["test"]["original"]["caught"]))
    put("wl_onsets", str(wl["population"]["test"]["onsets"]))
    put("wl_healthy_rows", str(wl["population"]["test"]["rows"]))
    put("wl10_caught", str(wl["test"]["budget_10"]["caught"]))
    put("wl10_fp", str(wl["test"]["budget_10"]["false_alarms"]))
    put("wl10_precision", pct(wl["test"]["budget_10"]["precision"]))
    put("wl_val_onsets", str(wl["population"]["validation"]["onsets"]))
    return te


# ------------------------------------------------------------------ walk-forward (Table 3, Figure 2)
def walk_forward_numbers():
    r = j(EXP / "walk_forward_v1/results.json")
    w = walk_forward()
    y, g = w[TARGET].to_numpy().astype(int), w["cik"].to_numpy()
    pool = r["pooled_oos"]
    put("wf_rows", f"{pool['rows']:,}")
    put("wf_pos", f"{pool['positives']:,}")
    put("wf_companies", f"{pool['companies']:,}")
    put("wf_minutes", f"{r['provenance']['minutes']:.0f}")
    pr = pd.DataFrame([f["test_pr_auc"] for f in r["folds"]], index=[f["test_year"] for f in r["folds"]])
    rows = []
    for m in ["rule_score", "logistic", "xgboost", "mlp", "ensemble_equal", "altman_z2", "ohlson_o"]:
        s = risk(w, m).to_numpy()
        ok = ~np.isnan(s)
        ap = average_precision_score(y[ok], s[ok])
        put(f"wf_{m}_pr", ap)
        if m in pr:
            fold = f"{pr[m].mean():.3f} ± {pr[m].std():.3f}"
            put(f"wf_{m}_mean", pr[m].mean())
            put(f"wf_{m}_sd", pr[m].std())
        else:
            per = [average_precision_score(d[TARGET], risk(d, m).dropna().reindex(d.index).fillna(-1e9))
                   for _, d in w.groupby("year")]
            fold = f"{np.mean(per):.3f} ± {np.std(per, ddof=1):.3f}"
        if m == "mlp":
            diff = "–"
        else:
            dd, dci = paired_pr(y[ok], s[ok], w["mlp"].to_numpy()[ok], g[ok])
            diff = f"{sgn(dd)} ({sgn(dci[0])} to {sgn(dci[1])})"
            put(f"wf_{m}_minus_mlp", sgn(dd))
            put(f"wf_{m}_minus_mlp_ci", f"{sgn(dci[0])} to {sgn(dci[1])}")
        wins = int((pr["mlp"] > pr[m]).sum()) if m in pr and m != "mlp" else "–"
        rows.append([LABELS[m] + (" †" if m in ("altman_z2", "ohlson_o") else ""), f"{ap:.3f}", fold, diff, wins])
    T["walk_forward"] = table(["Model", "Pooled PR-AUC", "Mean ± s.d. across 10 years", "Minus network (95% CI)",
                               "Years network better"], rows, "lrrrr")
    pp = r["paired_pooled"]
    put("wf_mlp_minus_logistic", sgn(pp["mlp_minus_logistic"]["mean_diff"]))
    put("wf_mlp_minus_logistic_ci", f"{sgn(pp['mlp_minus_logistic']['ci95'][0])} to {sgn(pp['mlp_minus_logistic']['ci95'][1])}")
    put("wf_mlp_minus_xgb", sgn(pp["mlp_minus_xgboost"]["mean_diff"]))
    put("wf_mlp_minus_xgb_ci", f"{sgn(pp['mlp_minus_xgboost']['ci95'][0])} to {sgn(pp['mlp_minus_xgboost']['ci95'][1])}")
    put("wf_mlp_beats_logistic_years", str(r["years_mlp_beats"]["logistic"]))
    put("wf_mlp_beats_xgb_years", str(r["years_mlp_beats"]["xgboost"]))
    put("wf_ml_min", pr[["logistic", "xgboost", "mlp"]].min().min())
    put("wf_ml_max", pr[["logistic", "xgboost", "mlp"]].max().max())
    for yr in (2020, 2022):
        put(f"wf_{yr}_mlp", pr.loc[yr, "mlp"])
        put(f"wf_{yr}_prev", pct(r["folds"][[f["test_year"] for f in r["folds"]].index(yr)]["positives"]["test"]
                                 / r["folds"][[f["test_year"] for f in r["folds"]].index(yr)]["rows"]["test"]))
    # onset rows inside the walk-forward (healthy in t)
    h = (w["status_t"] == "healthy").to_numpy()
    put("wf_healthy_rows", f"{int(h.sum()):,}")
    put("wf_healthy_onsets", str(int(y[h].sum())))
    for m in ("mlp", "logistic", "xgboost", "ensemble_equal"):
        put(f"wf_healthy_{m}", average_precision_score(y[h], w[m].to_numpy()[h]))
    dd, dci = paired_pr(y[h], w["mlp"].to_numpy()[h], w["logistic"].to_numpy()[h], g[h])
    put("wf_healthy_mlp_minus_logistic", sgn(dd))
    put("wf_healthy_mlp_minus_logistic_ci", f"{sgn(dci[0])} to {sgn(dci[1])}")
    put("wf_healthy_prev", pct(y[h].mean(), 1))
    # selected hyperparameters per fold (annex)
    T["wf_folds"] = table(["Test year", "Train / val / test rows", "Logistic C", "XGBoost depth, min child, trees",
                           "Network configuration"],
                          [[f["test_year"], f"{f['rows']['train']:,} / {f['rows']['val']} / {f['rows']['test']}",
                            f["selected"]["logistic_C"],
                            f"{f['selected']['xgboost']['max_depth']}, {f['selected']['xgboost']['min_child_weight']}, "
                            f"{f['selected']['xgboost']['best_iteration']}",
                            f["selected"]["mlp"]["config"].replace("pos_weight=", "weights=")] for f in r["folds"]],
                          "lrrll")
    # Figure 2
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    yrs = pr.index.to_numpy()
    for m in ["logistic", "xgboost", "mlp", "rule_score"]:
        ax.plot(yrs, pr[m], marker="o", ms=4, lw=1.8 if m == "mlp" else 1.2, color=COLORS[m], label=LABELS[m])
    az = [average_precision_score(d[TARGET], -d["altman_z2"].fillna(1e9)) for _, d in w.groupby("year")]
    ax.plot(yrs, az, marker="s", ms=3, lw=1, ls="--", color=COLORS["altman_z2"], label="Altman Z″ (textbook)")
    ax.plot(yrs, pr["no_skill"], lw=1, ls=":", color=COLORS["no_skill"], label="Base rate (no skill)")
    for yr, txt in ((2020, "COVID-19"), (2022, "rate shock")):
        ax.axvspan(yr - 0.4, yr + 0.4, color="#f3f4f6", zorder=0)
        ax.text(yr, 0.12, txt, ha="center", fontsize=7, color="#6b7280")
    ax.set_xticks(yrs)
    ax.set_ylim(0, 1)
    ax.set_ylabel("PR-AUC (test year)")
    ax.set_xlabel("Year the accounts were filed (each year predicted by models trained only on earlier data)")
    ax.legend(fontsize=7, ncol=3, loc="lower center", frameon=False, bbox_to_anchor=(0.5, 1.0))
    ax.grid(axis="y", color="#e5e7eb", lw=0.6)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(FIG / "fig2_walk_forward.png", dpi=200)
    plt.close(fig)
    return w


# ------------------------------------------------------------------ economic value (Table 4, Figure 3)
def economic_numbers():
    r = j(EXP / "economic_value_v1/results.json")
    a = r["assumptions"]
    lm = a["loss_model"]
    put("ev_exposure", f"{lm['exposure_usd_m']:.0f}")
    put("ev_pd", pct(lm["pd_given_stress"]))
    put("ev_lgd", pct(lm["lgd"]))
    put("ev_share", pct(lm["share_avoided_by_early_action"]))
    put("ev_cost_k", f"{a['review_cost_usd_m'] * 1000:.0f}")
    wf = r["walk_forward_2016_2025"]
    al = wf["all_borrowers"]
    put("ev_loss_avoided_k", f"{al['loss_avoided_per_catch_usd_m'] * 1000:.0f}")
    put("ev_years", str(al["years"]))
    put("ev_stressed", f"{al['stressed']:,}")
    put("ev_stressed_debt_bn", f"{al['stressed_debt_usd_bn']:.0f}")
    put("ev_book_bn", f"{al['rows'] / al['years'] * lm['exposure_usd_m'] / 1000:.1f}")
    put("ev_borrowers_per_year", f"{al['rows'] / al['years']:.0f}")
    b10 = al["budgets"]["10%"]
    put("ev10_random", f"{b10['_random_expected_caught']:.0f}")
    for m in ("mlp", "logistic", "xgboost", "rule_score", "altman_z2", "ohlson_o", "ensemble_equal"):
        put(f"ev10_{m}_caught", str(b10[m]["caught"]))
        put(f"ev10_{m}_precision", pct(b10[m]["precision"]))
        put(f"ev10_{m}_lift", f"{b10[m]['lift_vs_random']:.1f}")
        put(f"ev10_{m}_value", f"{b10[m]['net_value_usd_m_per_year']:.1f}")
        put(f"ev10_{m}_over_random", f"{b10[m]['value_over_random_usd_m_per_year']:.1f}")
        put(f"ev10_{m}_debt", pct(b10[m]["debt_flagged_share"]))
    put("ev10_reviews", str(b10["mlp"]["reviews"]))
    pa = wf["paired_at_headline_budget"]
    for k, v in pa.items():
        put(f"evp_{k}", f"{v['extra_caught']:+d}".replace("-", "−"))
        put(f"evp_{k}_ci", f"{v['ci95'][0]:+.0f} to {v['ci95'][1]:+.0f}".replace("-", "−"))
    lac = al["loss_avoided_per_catch_usd_m"]
    put("ev_mlp_vs_altman_usd_m", f"{pa['mlp_minus_altman_z2']['extra_caught'] * lac / al['years']:.1f}")
    put("ev_mlp_vs_logistic_usd_m", f"{pa['mlp_minus_logistic']['extra_caught'] * lac / al['years']:+.1f}")
    rows, rows10 = [], []
    order = ["rule_score", "altman_z2", "ohlson_o", "logistic", "xgboost", "mlp", "ensemble_equal"]
    for b in ("5%", "10%", "20%"):
        row = al["budgets"][b]
        for m in order:
            v = row[m]
            rows.append([b if m == order[0] else "", LABELS[m], v["caught"], v["false_alarms"],
                         pct(v["precision"]), f"{v['lift_vs_random']:.1f}x", pct(v["debt_flagged_share"]),
                         f"{v['net_value_usd_m_per_year']:.1f}"])
        rows.append(["", "*Random review (expected)*", f"{row['_random_expected_caught']:.0f}",
                     f"{row['mlp']['reviews'] - row['_random_expected_caught']:.0f}", pct(al["prevalence"]), "1.0x",
                     "–", f"{(row['_random_expected_caught'] * lac - a['review_cost_usd_m'] * row['mlp']['reviews']) / al['years']:.1f}"])
        if b == "10%":
            rows10 = [r[1:] for r in rows[-len(order) - 1:]]
    T["economic_all"] = table(["Budget", "Ranking used", "Stressed caught", "False alarms", "Precision", "Lift",
                               "Stressed debt flagged", "Net value, USD m / yr"], rows, "llrrrrrr")
    T["economic"] = table(["Ranking used", "Stressed caught", "False alarms", "Precision", "Lift",
                           "Stressed debt flagged", "Net value, USD m / yr"], rows10, "lrrrrrr")
    # healthy borrowers
    h = wf["healthy_borrowers_only"]
    hb = h["budgets"]["10%"]
    put("evh_rows", f"{h['rows']:,}")
    put("evh_onsets", str(h["stressed"]))
    for m in ("mlp", "logistic", "xgboost", "altman_z2"):
        put(f"evh10_{m}", str(hb[m]["caught"]))
    put("evh10_random", f"{hb['_random_expected_caught']:.0f}")
    # sensitivity (annex)
    T["sensitivity"] = table(["PD of a stressed borrower", "Loss avoided by early action", "Loss avoided per catch, USD k",
                              "Network net value, USD m / yr", "Network value over random review, USD m / yr",
                              "Altman Z″ net value, USD m / yr"],
                             [[pct(s["pd_given_stress"]), pct(s["share_avoided"]), f"{s['loss_avoided_per_catch_usd_m'] * 1000:.0f}",
                               f"{s['mlp_net_value_usd_m_per_year']:.1f}", f"{s['mlp_over_random_usd_m_per_year']:.1f}",
                               f"{s['altman_net_value_usd_m_per_year']:.1f}"] for s in wf["sensitivity_headline_budget"]])
    sens = wf["sensitivity_headline_budget"]
    put("sens_min", f"{min(s['mlp_net_value_usd_m_per_year'] for s in sens):.1f}")
    put("sens_max", f"{max(s['mlp_net_value_usd_m_per_year'] for s in sens):.1f}")
    # Figure 3: capture curve on walk-forward OOS
    from training.ml.economic_value import flags
    w = walk_forward()
    y = w[TARGET].to_numpy().astype(int)
    budgets = np.linspace(0.01, 0.5, 50)
    fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.2))
    for m in ["mlp", "logistic", "xgboost", "rule_score", "altman_z2"]:
        caught = [(flags(w, m, b) & (y == 1)).sum() / y.sum() for b in budgets]
        debt = w["gross_debt"].fillna(0).clip(lower=0).to_numpy()
        dcap = [debt[flags(w, m, b) & (y == 1)].sum() / debt[y == 1].sum() for b in budgets]
        kw = dict(color=COLORS[m], lw=1.8 if m == "mlp" else 1.1, ls="--" if m == "altman_z2" else "-",
                  label=LABELS[m] + (" (textbook)" if m == "altman_z2" else ""))
        axes[0].plot(budgets * 100, np.array(caught) * 100, **kw)
        axes[1].plot(budgets * 100, np.array(dcap) * 100, **kw)
    axes[0].plot(budgets * 100, budgets * 100, color=COLORS["no_skill"], ls=":", lw=1, label="Random review")
    axes[1].plot(budgets * 100, budgets * 100, color=COLORS["no_skill"], ls=":", lw=1)
    axes[0].set_title("Stressed borrowers caught", fontsize=9)
    axes[1].set_title("Stressed borrowers' debt (USD) caught", fontsize=9)
    for ax in axes:
        ax.set_xlabel("Review budget: % of borrowers reviewed each year", fontsize=8)
        ax.set_ylim(0, 100)
        ax.axvline(10, color="#d1d5db", lw=0.8)
        ax.grid(color="#f3f4f6", lw=0.6)
        ax.tick_params(labelsize=7)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    axes[0].set_ylabel("% captured", fontsize=8)
    axes[0].legend(fontsize=6.5, frameon=False, loc="lower right")
    fig.tight_layout()
    fig.savefig(FIG / "fig3_capture.png", dpi=200)
    plt.close(fig)


# ------------------------------------------------------------------ robustness (Table 5, Figure 4)
def robustness_numbers():
    r = j(EXP / "robustness_v1/results.json")["walk_forward_2016_2025"]
    rows = []
    for key, title in (("by_size", "Size (revenue tercile)"), ("by_sector", "Sector"), ("by_status_in_t", "Status in the filing year")):
        first = True
        for g in r[key]:
            if "mlp" not in g:
                continue
            label = g["group"].split(" ", 1)[1] if key == "by_size" else g["group"]
            rows.append([title if first else "", label, f"{g['rows']:,}", pct(g["prevalence"]),
                         f"{g['logistic']['pr_auc']:.2f}", f"{g['xgboost']['pr_auc']:.2f}", f"{g['mlp']['pr_auc']:.2f}",
                         f"{g['altman_z2']['pr_auc']:.2f}" if "altman_z2" in g else "–", f"{g['mlp']['lift']:.1f}x"])
            first = False
    T["robustness"] = table(["Cut", "Group", "Rows", "Stressed", "Logistic", "XGBoost", "Network", "Altman Z″",
                             "Network lift"], rows, "llrrrrrrr")
    size = {g["group"]: g for g in r["by_size"]}
    put("size_cut_small", f"{r['size_cutoffs_revenue_usd_m'][0]:,.0f}")
    put("size_cut_large", f"{r['size_cutoffs_revenue_usd_m'][1]:,.0f}")
    put("rb_small_mlp", size["1 small"]["mlp"]["pr_auc"], "{:.2f}")
    put("rb_large_mlp", size["3 large"]["mlp"]["pr_auc"], "{:.2f}")
    put("rb_small_prev", pct(size["1 small"]["prevalence"]))
    put("rb_large_prev", pct(size["3 large"]["prevalence"]))
    put("rb_small_lift", f"{size['1 small']['mlp']['lift']:.1f}")
    put("rb_large_lift", f"{size['3 large']['mlp']['lift']:.1f}")
    sec = {g["group"]: g for g in r["by_sector"]}
    put("rb_mining_mlp", sec["mining"]["mlp"]["pr_auc"], "{:.2f}")
    put("rb_wholesale_mlp", sec["wholesale trade"]["mlp"]["pr_auc"], "{:.2f}")
    put("rb_manuf_mlp", sec["manufacturing"]["mlp"]["pr_auc"], "{:.2f}")
    st = {g["group"]: g for g in r["by_status_in_t"]}
    put("rb_stressed_mlp", st["already stressed"]["mlp"]["pr_auc"], "{:.2f}")
    put("rb_healthy_mlp", st["healthy"]["mlp"]["pr_auc"], "{:.2f}")
    cal = pd.DataFrame(r["calibration_by_year"])
    T["calibration_years"] = table(["Year", "Observed stress rate", "Network mean predicted", "Logistic", "XGBoost"],
                                   [[int(c.year), pct(c.observed, 1), pct(c.mlp_mean_predicted, 1),
                                     pct(c.logistic_mean_predicted, 1), pct(c.xgboost_mean_predicted, 1)] for c in cal.itertuples()])
    under = cal[(cal["observed"] - cal["mlp_mean_predicted"]) > 0.03]["year"].astype(int).tolist()
    put("underpredicted_years", " and ".join([", ".join(str(x) for x in under[:-1]), str(under[-1])]) if len(under) > 1
        else ", ".join(str(x) for x in under))
    # Figure 4: lift by size and sector
    groups = [("Small", size["1 small"]), ("Mid", size["2 mid"]), ("Large", size["3 large"])] + \
        [(g["group"].replace("transportation, communications and utilities", "transport & utilities").capitalize(), g)
         for g in r["by_sector"] if "mlp" in g]
    fig, ax = plt.subplots(figsize=(7.4, 3.0))
    xs = np.arange(len(groups))
    wdt = 0.2
    for i, m in enumerate(["logistic", "xgboost", "mlp", "altman_z2"]):
        ax.bar(xs + (i - 1.5) * wdt, [g[m]["pr_auc"] if m in g else np.nan for _, g in groups], wdt,
               color=COLORS[m], label=LABELS[m])
    ax.scatter(xs, [g["prevalence"] for _, g in groups], marker="_", s=180, color="#111827", zorder=3,
               label="Base rate", linewidths=1.6)
    ax.axvline(2.5, color="#d1d5db", lw=0.8)
    ax.set_xticks(xs)
    ax.set_xticklabels([n for n, _ in groups], fontsize=7, rotation=20, ha="right")
    ax.set_ylabel("PR-AUC", fontsize=8)
    ax.set_ylim(0, 1)
    ax.tick_params(labelsize=7)
    ax.legend(fontsize=6.5, ncol=5, frameon=False, loc="lower center", bbox_to_anchor=(0.5, 1.0))
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(FIG / "fig4_robustness.png", dpi=200)
    plt.close(fig)


# ------------------------------------------------------------------ Figure 1: system
def figure_pipeline():
    fig, ax = plt.subplots(figsize=(7.4, 2.5))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 34)
    ax.axis("off")
    boxes = [
        (1, "SEC EDGAR\nXBRL facts", "549 firms, FY2007-26\noriginal vintages", "#e0f2fe"),
        (21, "Point-in-time\npanel", "as-of = filing date\nlabel from t+1 only", "#e0f2fe"),
        (41, "Features &\nlabel", "31 ratios + 31 missing\nflags; 2-of-3 stress", "#ecfdf5"),
        (61, "Models", "rule, Altman, Ohlson,\nlogit, XGBoost, MLP", "#ecfdf5"),
        (81, "Analyst app", "score, drivers, loan\nstress, sourced memo", "#fef3c7"),
    ]
    for x, title, sub, col in boxes:
        ax.add_patch(matplotlib.patches.FancyBboxPatch((x, 9), 17, 20, boxstyle="round,pad=0.4,rounding_size=1.5",
                                                       fc=col, ec="#374151", lw=0.8))
        ax.text(x + 8.5, 23.5, title, ha="center", va="center", fontsize=8, weight="bold")
        ax.text(x + 8.5, 14, sub, ha="center", va="center", fontsize=6.4, color="#374151")
    for x in (18.6, 38.6, 58.6, 78.6):
        ax.annotate("", xy=(x + 2.2, 19), xytext=(x, 19), arrowprops=dict(arrowstyle="-|>", color="#374151", lw=0.9))
    ax.text(50, 3, "Validation: chronological split with label purge (train <2019, validation 2019-20, test 2021-25) "
            "and walk-forward re-fitting 2016-25", ha="center", fontsize=6.6, color="#374151", style="italic")
    fig.savefig(FIG / "fig1_pipeline.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------------ render
def main():
    (OUT / "tables").mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)
    data_numbers()
    frozen_numbers()
    walk_forward_numbers()
    economic_numbers()
    robustness_numbers()
    figure_pipeline()
    research = j(ROOT / "backend/data/research/research_v1.json")
    put("onset_gru_pr", next(r["pr_auc"] for r in research["onset"] if r["model"] == "Onset-specific GRU"))
    put("general_gru_pr", next(r["pr_auc"] for r in research["overall"] if r["model"] == "General three-year GRU"))
    put("manifest_version", j(ROOT / "release/manifest.json").get("version", "1.2.0"))
    (OUT / "numbers.json").write_text(json.dumps(N, indent=1, ensure_ascii=False) + "\n")
    for k, v in T.items():
        (OUT / "tables" / f"{k}.md").write_text(v + "\n")
    print(f"{len(N)} numbers, {len(T)} tables, 4 figures -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
