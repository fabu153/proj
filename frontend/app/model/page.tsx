"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import ApiStatus from "@/components/ApiStatus";
import NetworkDiagram from "@/components/NetworkDiagram";
import TopBar from "@/components/TopBar";
import { api } from "@/lib/api";
import { featureLabel } from "@/lib/labels";
import { useApiReady } from "@/lib/useApi";

const f3 = (v: number) => v.toFixed(3);
const pc = (v: number, d = 0) => `${(v * 100).toFixed(d)}%`;
const sig = (z: number) => 1 / (1 + Math.exp(-z));
const logit = (p: number) => Math.log(p / (1 - p));
const BAND = { low: "Low", elevated: "Elevated", high: "High" } as Record<string, string>;

export default function ModelXRay() {
  const [data, setData] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);
  const apiState = useApiReady();
  useEffect(() => {
    if (apiState.phase !== "ready") return;
    setError(null);
    api.model().then(setData).catch((e) => setError(e.message));
  }, [apiState.phase]);

  if (error || !data) {
    return (
      <>
        <TopBar active="model" />
        <main className="page">
          <ApiStatus state={apiState} onRetry={apiState.retry} />
          {error ? (
            <div className="notice error" role="alert">
              Could not load the model evidence: {error}{" "}
              <button type="button" className="link" onClick={apiState.retry}>Try again</button>
            </div>
          ) : apiState.phase === "ready" ? (
            <p className="skeleton" role="status"><span className="spinner" aria-hidden="true" />Loading model evidence…</p>
          ) : null}
        </main>
      </>
    );
  }
  const { metadata: m, xray: x, held_out: h, feature_groups: groups } = data;
  const tm = m.test_metrics_calibrated;
  const ci = m.test_bootstrap;
  const cal = (x.calibration_test as any[]).map((r) => ({ pred: +(r.mean_pred * 100).toFixed(1), obs: +(r.observed * 100).toFixed(1) }));
  const perm = Object.entries(x.permutation_importance_val as Record<string, number>).slice(0, 10);
  const permMax = Math.max(...perm.map(([, v]) => v), 0.001);
  const px = x.paired_vs_baselines;
  const board = x.leaderboard as any[];
  const xgb = board.find((r) => r.model === "XGBoost");
  const noSkill = board.find((r) => /no-skill/i.test(r.model));
  // one data array, so both lines span the whole axis (separate arrays made Recharts break the observed line)
  const calData = [{ pred: 0, ideal: 0 }, ...cal.map((r) => ({ ...r, ideal: r.pred })), { pred: 100, ideal: 100 }];
  const ea = h?.error_analysis;
  const c = ea?.confusion;
  const sn = ea?.stressed_next_year;
  const w = m.data_windows;

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
        <nav className="xray-toc" aria-label="On this page">
          <a href="#what-it-learned">1. What the network learned</a>
          <a href="#how-it-performed">2. How it performed</a>
          <a href="#where-it-fails">3. Where it fails</a>
          <a href="#how-chosen">How it was chosen</a>
        </nav>

        <div className="workspace">
          <div>
            {/* ------------------------------------------------------------ 1 */}
            <section className="block" id="what-it-learned" aria-labelledby="h-learned">
              <h2 id="h-learned">1. What the network learned</h2>
              <div className="target-box">
                <strong>What it predicts: next-fiscal-year accounting stress.</strong> A company-year counts as stressed when, in the fiscal
                year <em>after</em> the 10-K, at least two of these hold: EBIT / interest below 1.5x; gross debt / EBITDA above 5x (or debt
                with EBITDA at or below zero); negative operating cash flow. This is an accounting-stress screen. It is not a probability of
                default, not a credit rating and not a loan decision.
              </div>
              <h3 className="sub">Inputs: 31 measures from one annual report, in {groups.length} groups</h3>
              <div className="feature-groups">
                {groups.map((g: any) => (
                  <div key={g.group}>
                    <strong>
                      {g.group} <span className="fine">({g.features.length})</span>
                    </strong>
                    <span className="fine">{g.features.map((f: any) => featureLabel(f.name)).join(", ")}</span>
                  </div>
                ))}
              </div>
              <p className="fine">
                Each input also gets a flag saying whether it was missing, so the network sees 62 numbers. Inputs are standardised with
                statistics from the training years only.
              </p>
              <h3 className="sub">Architecture</h3>
              <div className="sheet" style={{ padding: "10px 12px" }}>
                <NetworkDiagram />
              </div>
              <h3 className="sub">Training, validation and test windows (by 10-K filing date)</h3>
              <div className="windows" role="table" aria-label="Data windows">
                {(
                  [
                    ["train", "Training", "Fits the weights", w.train_features_filed],
                    ["val", "Validation", "Chooses settings and calibration", w.val_features_filed],
                    ["test", "Test", "Scored once, after every choice was fixed", w.test_features_filed],
                  ] as const
                ).map(([k, name, role, win]) => (
                  <div key={k} className={`win ${k}`} role="row">
                    <strong role="cell">{name}</strong>
                    <span role="cell" className="num">
                      {win[0].slice(0, 4)}–{win[1].slice(0, 4)}
                    </span>
                    <span role="cell" className="num">
                      {m.rows[k].toLocaleString()} company-years, {pc(x.splits[k].prevalence, 1)} stressed
                    </span>
                    <span role="cell" className="fine">{role}</span>
                  </div>
                ))}
              </div>
              <p className="fine">
                Company-years after the population gate (revenue at least USD 50m, data checks passed). Training labels published after
                validation began were removed, so no window learns from outcomes that were not yet public.
              </p>
            </section>

            {/* ------------------------------------------------------------ 2 */}
            <section className="block" id="how-it-performed" aria-labelledby="h-performed">
              <h2 id="h-performed">2. How it performed on the held-out test</h2>
              <p className="lede">
                {tm.n.toLocaleString()} company-years whose 10-Ks were filed {w.test_features_filed[0]} to {w.test_features_filed[1]}, never used
                for training or for any choice. {pc(tm.prevalence, 1)} of them became stressed the next year.
              </p>
              <div className="metric-cards">
                <div className="sheet">
                  <span className="fine">Precision-recall AUC</span>
                  <strong className="num">{f3(tm.pr_auc)}</strong>
                  <span className="fine num">95% interval {f3(ci.pr_auc_ci95[0])}–{f3(ci.pr_auc_ci95[1])}; no-skill {f3(tm.prevalence)}</span>
                </div>
                <div className="sheet">
                  <span className="fine">ROC AUC</span>
                  <strong className="num">{f3(tm.roc_auc)}</strong>
                  <span className="fine num">95% interval {f3(ci.roc_auc_ci95[0])}–{f3(ci.roc_auc_ci95[1])}; no-skill 0.500</span>
                </div>
                <div className="sheet">
                  <span className="fine">Brier score (lower is better)</span>
                  <strong className="num">{tm.brier.toFixed(3)}</strong>
                  <span className="fine num">no-skill (training base rate): {noSkill ? noSkill.test_brier.toFixed(3) : "n/a"}</span>
                </div>
              </div>
              <details className="explain" open>
                <summary>Why precision-recall AUC is the headline</summary>
                <p>
                  Only {pc(tm.prevalence)} of company-years are stressed. ROC AUC asks how well the model ranks stressed above healthy
                  companies, and with many healthy companies it can look strong even when a large share of warnings are false. Precision-recall
                  AUC asks the lender&apos;s question: of the companies flagged, how many really became stressed, and how many stressed companies
                  were found? A model that guesses scores the prevalence, {f3(tm.prevalence)}, so {f3(tm.pr_auc)} is a large improvement over
                  chance; the Brier score checks that the probabilities themselves are accurate.
                </p>
              </details>
              <h3 className="sub">Matched comparison: every model scored on the identical {tm.n.toLocaleString()} rows</h3>
              <div className="sheet scroll-x" tabIndex={0} role="region" aria-label="Model comparison table">
                <table className="ledger num">
                  <thead>
                    <tr>
                      <th scope="col">Model</th>
                      <th scope="col">PR-AUC</th>
                      <th scope="col">95% interval</th>
                      <th scope="col">ROC AUC</th>
                      <th scope="col">Brier</th>
                    </tr>
                  </thead>
                  <tbody>
                    {board.map((r: any, i: number) => (
                      <tr key={r.model}>
                        <td style={{ fontWeight: i === 0 ? 600 : 400 }}>{r.model}</td>
                        <td>{f3(r.test_pr_auc)}</td>
                        <td>{r.ci95 ? `${f3(r.ci95[0])}–${f3(r.ci95[1])}` : "n/a"}</td>
                        <td>{f3(r.test_roc_auc)}</td>
                        <td>{r.test_brier.toFixed(3)}</td>
                      </tr>
                    ))}

                  </tbody>
                </table>
              </div>
              <div className="notice" style={{ marginTop: 12 }}>
                <strong>XGBoost has the higher point estimate</strong> ({f3(xgb.test_pr_auc)} against {f3(tm.pr_auc)}) and the lower Brier score.
                Paired on identical rows, resampling whole companies, the network&apos;s PR-AUC is {Math.abs(px.mlp_minus_xgboost.mean_diff).toFixed(3)}{" "}
                {px.mlp_minus_xgboost.mean_diff < 0 ? "lower" : "higher"} (95% interval {px.mlp_minus_xgboost.ci95[0].toFixed(3)} to{" "}
                {px.mlp_minus_xgboost.ci95[1].toFixed(3)}). The interval includes zero, so the two are not reliably different. The network is
                deployed to meet the course&apos;s deep-learning objective, with XGBoost kept beside it as the benchmark. It clearly beats the
                simple rule score (by {px.mlp_minus_rule_score.mean_diff.toFixed(3)}, interval {px.mlp_minus_rule_score.ci95[0].toFixed(3)} to{" "}
                {px.mlp_minus_rule_score.ci95[1].toFixed(3)}).
              </div>

              <h3 className="sub">Are the probabilities honest? Observed versus predicted</h3>
              <p className="fine" style={{ marginTop: 0 }}>
                Test companies in ten buckets by predicted risk; on the dashed line a 30% prediction comes true 30% of the time. Calibration
                was fitted on 2019–20; later years show more stress than predicted, so the network slightly understates risk.
              </p>
              <div className="sheet chart">
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart data={calData} margin={{ top: 8, right: 16, left: 0, bottom: 16 }}>
                    <CartesianGrid stroke="#e3e7ec" />
                    <XAxis type="number" dataKey="pred" domain={[0, 100]} unit="%" tick={{ fontSize: 12 }} label={{ value: "Predicted", position: "insideBottom", offset: -8, fontSize: 12 }} />
                    <YAxis type="number" domain={[0, 100]} unit="%" tick={{ fontSize: 12 }} width={48} label={{ value: "Observed", angle: -90, position: "insideLeft", fontSize: 12 }} />
                    <Tooltip formatter={(v) => `${v}%`} />
                    <Line dataKey="ideal" stroke="#8c9aab" strokeDasharray="4 4" dot={false} name="Perfect calibration" isAnimationActive={false} />
                    <Line dataKey="obs" stroke="#0f7c7a" strokeWidth={2} dot={{ r: 3 }} name="Observed" connectNulls isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              {ea && (
                <div className="sheet scroll-x" tabIndex={0} role="region" aria-label="Outcomes by screening band" style={{ marginTop: 12 }}>
                  <table className="ledger num">
                    <thead>
                      <tr>
                        <th scope="col">Screening band</th>
                        <th scope="col">Company-years</th>
                        <th scope="col">Average prediction</th>
                        <th scope="col">Actually stressed</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ea.by_band.map((b: any) => (
                        <tr key={b.band}>
                          <td>
                            {BAND[b.band]} ({pc(b.from)}–{b.to === 1 ? "100%" : pc(b.to)})
                          </td>
                          <td>{b.n}</td>
                          <td>{pc(b.mean_prediction, 1)}</td>
                          <td>
                            {pc(b.observed_rate, 1)} ({b.stressed})
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {/* ------------------------------------------------------------ 3 */}
            {ea && (
              <section className="block" id="where-it-fails" aria-labelledby="h-fails">
                <h2 id="h-fails">3. Where it fails</h2>
                <p className="lede">
                  To count errors, a company is flagged when its score is at least {pc(ea.threshold, 1)}, the cut-off that maximised F1 on
                  2019–20 validation data, fixed before the test.
                </p>
                <div className="confusion" role="table" aria-label="Errors on the held-out test">
                  <div role="row" className="hdr">
                    <span role="columnheader" />
                    <span role="columnheader">Stressed next year</span>
                    <span role="columnheader">Not stressed</span>
                  </div>
                  <div role="row">
                    <span role="rowheader">Flagged</span>
                    <span role="cell" className="ok"><b>{c.tp}</b> correct warnings</span>
                    <span role="cell" className="bad"><b>{c.fp}</b> false alarms</span>
                  </div>
                  <div role="row">
                    <span role="rowheader">Not flagged</span>
                    <span role="cell" className="bad"><b>{c.fn}</b> missed</span>
                    <span role="cell" className="ok"><b>{c.tn}</b> correct all-clears</span>
                  </div>
                </div>
                <p className="fine">
                  Precision {pc(c.tp / (c.tp + c.fp))}: about {Math.round((c.fp / (c.tp + c.fp)) * 10)} in 10 flags are false alarms. Recall{" "}
                  {pc(c.tp / (c.tp + c.fn))}: about {Math.round((c.fn / (c.tp + c.fn)) * 10)} in 10 stressed companies are missed.
                </p>
                <div className="fail-grid">
                  <div className="sheet">
                    <h3 className="sub">It mostly detects stress that persists</h3>
                    <p>
                      Of companies already meeting two conditions that stayed stressed, it caught{" "}
                      <b>{sn.already_stressed_in_t.caught} of {sn.already_stressed_in_t.n}</b>. Of companies that <em>became</em> stressed from
                      healthier accounts, it caught only <b>{sn.new_stress_onset.caught} of {sn.new_stress_onset.n}</b>. New stress usually
                      comes from events in the following year that one annual report does not show.
                    </p>
                  </div>
                  <div className="sheet">
                    <h3 className="sub">False alarms are mostly recoveries</h3>
                    <p>
                      <b>{ea.false_alarms.already_stressed_in_t} of {ea.false_alarms.n}</b> false alarms were companies already stressed in the
                      filing year that recovered the next year. The network leans heavily on the current year&apos;s stress conditions, so it
                      is slow to recognise a turnaround.
                    </p>
                  </div>
                </div>
                <p className="fine">
                  See one correct warning, one false alarm and one missed case, company by company, in the{" "}
                  <Link href="/replay">historical model replay</Link>.
                </p>

                <h3 className="sub">What it relies on</h3>
                <p className="fine" style={{ marginTop: 0 }}>
                  Drop in validation PR-AUC when each input is shuffled. Larger means the network leans on it more.
                </p>
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
                <div className="explain-box">
                  <strong>Reading the driver bars in the workspace.</strong> Each bar is the change in the network&apos;s <em>log-odds</em> when
                  that one input is replaced by its training median. It is not a change in percentage points, and it is not a cause. The same
                  bar moves the probability by different amounts depending on where the score starts: +0.50 log-odds takes 5% to{" "}
                  {pc(sig(logit(0.05) + 0.5), 1)}, 20% to {pc(sig(logit(0.2) + 0.5), 1)} and 50% to {pc(sig(logit(0.5) + 0.5), 1)}. Inputs
                  also interact, so the bars do not add up to the score.
                </div>

                <h3 className="sub">Where it does not apply</h3>
                <ul className="warn-list">
                  <li>U.S. SEC filers outside financial services with revenue of at least USD 50m, annual 10-K data 2009–2025.</li>
                  <li>Figures in another currency, or company-years missing more than {m.inference_gate.max_missing_features} of 31 inputs: the score is withheld.</li>
                  <li>It reads one annual report. It knows nothing about markets, management, covenants or events after the filing.</li>
                  <li>The loan lab&apos;s sliders do not change the score: they rework financing mechanically, and recomputing all 31 inputs for a hypothetical company has not been validated.</li>
                </ul>
              </section>
            )}

            <section className="block" id="how-chosen" aria-labelledby="h-chosen">
              <h2 id="h-chosen">How it was chosen</h2>
              <p className="lede">
                Eight configurations fixed before training, five random seeds each, ranked on 2019–20 validation data only. The deployed
                model averages the five seeds of {x.selected_config}.
              </p>
              <div className="sheet scroll-x" tabIndex={0} role="region" aria-label="Configuration search table">
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
              <p className="fine">
                Single seeds reach test PR-AUC {f3(x.per_seed_test_pr_auc.min)}–{f3(x.per_seed_test_pr_auc.max)}; averaging five gives{" "}
                {f3(tm.pr_auc)}.
              </p>
            </section>
          </div>

          <aside className="rail" tabIndex={0} aria-label="Model summary">
            <div className="sheet">
              <h3>In one sentence</h3>
              <p style={{ fontSize: 14, margin: 0 }}>
                On filings it never saw, the network ranks next-year accounting stress well (PR-AUC {f3(tm.pr_auc)} against a no-skill{" "}
                {f3(tm.prevalence)}), level with XGBoost ({f3(xgb.test_pr_auc)}) within the margin of error, and it is much better at spotting
                stress that persists than stress that starts.
              </p>
            </div>
            <div className="sheet">
              <h3>Intended use</h3>
              <p style={{ fontSize: 14, margin: 0 }}>{m.intended_use}</p>
              <p className="fine">Not for: {m.not_for.join(", ")}.</p>
            </div>
            {h?.verification && (
              <div className="sheet">
                <h3>Reproducibility</h3>
                <p className="fine" style={{ margin: 0 }}>
                  The frozen model was re-run on all {h.verification.recomputed.n.toLocaleString()} test rows: PR-AUC{" "}
                  {h.verification.recomputed.pr_auc.toFixed(6)} and the error counts above match the values recorded at training exactly.
                </p>
              </div>
            )}
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
