"use client";

import { useEffect, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import TopBar from "@/components/TopBar";
import { api } from "@/lib/api";
import { featureLabel } from "@/lib/labels";

const f3 = (v: number) => v.toFixed(3);

export default function ModelXRay() {
  const [data, setData] = useState<{ metadata: any; xray: any } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.model().then(setData).catch((e) => setError(e.message));
  }, []);

  if (error || !data) {
    return (
      <>
        <TopBar active="model" />
        <main className="page">{error ? <div className="notice error">{error}</div> : <p className="skeleton">Loading model evidence…</p>}</main>
      </>
    );
  }
  const { metadata: m, xray: x } = data;
  const cal = (x.calibration_test as any[]).map((r) => ({ pred: +(r.mean_pred * 100).toFixed(1), obs: +(r.observed * 100).toFixed(1) }));
  const perm = Object.entries(x.permutation_importance_val as Record<string, number>).slice(0, 10);
  const permMax = Math.max(...perm.map(([, v]) => v), 0.001);
  const px = x.paired_vs_baselines;

  return (
    <>
      <TopBar active="model" />
      <main className="page">
        <div className="file-head">
          <h1>Model X-Ray</h1>
          <p className="num">
            {m.model}, trained {m.trained_at}. Target {m.target} ({m.label_version}), features {m.feature_version}.
          </p>
        </div>

        <div className="workspace">
          <div>
            <section className="block">
              <h2>Does the network work?</h2>
              <p className="lede">
                All models were scored once on the same held-out company-years whose features were filed {x.splits.test.as_of_min} to{" "}
                {x.splits.test.as_of_max}, after every choice had been fixed on earlier data. Intervals resample whole companies.
              </p>
              <div className="sheet" style={{ overflowX: "auto" }}>
                <table className="ledger num">
                  <thead>
                    <tr>
                      <th scope="col">Model</th>
                      <th scope="col">Precision-recall AUC</th>
                      <th scope="col">95% interval</th>
                      <th scope="col">ROC AUC</th>
                      <th scope="col">Brier score</th>
                    </tr>
                  </thead>
                  <tbody>
                    {x.leaderboard.map((r: any, i: number) => (
                      <tr key={r.model}>
                        <td style={{ fontWeight: i === 0 ? 600 : 400 }}>{r.model}</td>
                        <td>{f3(r.test_pr_auc)}</td>
                        <td>{r.ci95 ? `${f3(r.ci95[0])} to ${f3(r.ci95[1])}` : "n/a"}</td>
                        <td>{f3(r.test_roc_auc)}</td>
                        <td>{r.test_brier.toFixed(4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="notice calm" style={{ marginTop: 12 }}>
                Paired on identical rows, the network scores {px.mlp_minus_xgboost.mean_diff > 0 ? "above" : "below"} XGBoost by{" "}
                {Math.abs(px.mlp_minus_xgboost.mean_diff).toFixed(3)} (interval {px.mlp_minus_xgboost.ci95[0].toFixed(3)} to{" "}
                {px.mlp_minus_xgboost.ci95[1].toFixed(3)}), so the two are not reliably different. It beats the simple rule score by{" "}
                {px.mlp_minus_rule_score.mean_diff.toFixed(3)} (interval {px.mlp_minus_rule_score.ci95[0].toFixed(3)} to{" "}
                {px.mlp_minus_rule_score.ci95[1].toFixed(3)}). Stress prevalence on the test window is {(x.splits.test.prevalence * 100).toFixed(1)}%.
              </div>
            </section>

            <section className="block">
              <h2>Are the probabilities honest?</h2>
              <p className="lede">
                Test companies grouped into ten buckets by predicted risk. On the diagonal, a 30% prediction comes true 30% of the time.
                Calibration was fitted on 2019–20 data; later years show more stress than the model expects.
              </p>
              <div className="sheet chart">
                <ResponsiveContainer width="100%" height={280}>
                  <LineChart data={cal} margin={{ top: 8, right: 16, left: 0, bottom: 16 }}>
                    <CartesianGrid stroke="#e3e7ec" />
                    <XAxis type="number" dataKey="pred" domain={[0, 100]} unit="%" tick={{ fontSize: 12 }} label={{ value: "Predicted", position: "insideBottom", offset: -8, fontSize: 12 }} />
                    <YAxis type="number" domain={[0, 100]} unit="%" tick={{ fontSize: 12 }} width={48} />
                    <Tooltip formatter={(v) => `${v}%`} />
                    <Line data={[{ pred: 0, obs: 0 }, { pred: 100, obs: 100 }]} dataKey="obs" stroke="#8c9aab" strokeDasharray="4 4" dot={false} name="Perfect calibration" />
                    <Line dataKey="obs" stroke="#0f7c7a" strokeWidth={2} dot={{ r: 3 }} name="Observed" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </section>

            <section className="block">
              <h2>What does it rely on?</h2>
              <p className="lede">Drop in validation precision-recall AUC when each input is shuffled. Larger means the model leans on it more.</p>
              <div className="sheet" style={{ padding: "8px 16px" }}>
                <ul className="drivers">
                  {perm.map(([k, v]) => (
                    <li key={k} style={{ gridTemplateColumns: "minmax(0,1.4fr) 70px minmax(0,1fr)" }}>
                      <span>{featureLabel(k)}</span>
                      <span className="num" style={{ textAlign: "right" }}>{v.toFixed(3)}</span>
                      <span className="bar" aria-hidden="true">
                        <span style={{ left: 0, width: `${Math.max(0, v / permMax) * 100}%`, background: "var(--ink)" }} />
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            </section>

            <section className="block">
              <h2>How was it chosen?</h2>
              <p className="lede">
                Eight configurations fixed before training, five random seeds each, ranked on 2019–20 validation data only. The deployed
                model averages the five seeds of {x.selected_config}.
              </p>
              <div className="sheet" style={{ overflowX: "auto" }}>
                <table className="ledger num">
                  <thead>
                    <tr>
                      <th scope="col">Configuration</th>
                      <th scope="col">Validation PR-AUC, mean</th>
                      <th scope="col">Range over seeds</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...x.search].sort((a: any, b: any) => b.val_pr_auc_mean - a.val_pr_auc_mean).map((s: any) => (
                      <tr key={s.config}>
                        <td style={{ fontWeight: s.config === x.selected_config ? 600 : 400 }}>{s.config.replace(/,/g, ", ")}</td>
                        <td>{f3(s.val_pr_auc_mean)}</td>
                        <td>
                          {f3(s.val_pr_auc_min)} to {f3(s.val_pr_auc_max)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </div>

          <aside className="rail">
            <div className="sheet">
              <h3>Intended use</h3>
              <p style={{ fontSize: 14, margin: 0 }}>{m.intended_use}</p>
              <p className="fine">Not for: {m.not_for.join(", ")}.</p>
            </div>
            <div className="sheet">
              <h3>Data windows</h3>
              <table className="ledger num" style={{ fontSize: 13 }}>
                <tbody>
                  {(["train", "val", "test"] as const).map((s) => (
                    <tr key={s}>
                      <td>{s === "val" ? "Validation" : s === "train" ? "Training" : "Test"}</td>
                      <td>{x.splits[s].rows} rows</td>
                      <td>{(x.splits[s].prevalence * 100).toFixed(1)}% stressed</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="fine">Split by filing date. Training labels published after validation began were removed.</p>
            </div>
            <div className="sheet">
              <h3>Limitations</h3>
              <ul className="warn-list">
                {x.limitations.map((l: string) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            </div>
          </aside>
        </div>
      </main>
    </>
  );
}
