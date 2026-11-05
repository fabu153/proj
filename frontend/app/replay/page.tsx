"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import ApiStatus from "@/components/ApiStatus";
import { featureValue } from "@/components/RiskScreen";
import Ruler from "@/components/Ruler";
import TopBar from "@/components/TopBar";
import type { Condition, Conditions, ReplayForecast, ReplayMetrics, ReplayOutcome, ReplayOverview } from "@/lib/api";
import { fyLabel, replayApi } from "@/lib/api";
import { featureLabel } from "@/lib/labels";
import { useApiReady } from "@/lib/useApi";

const pct0 = (v: number) => `${(v * 100).toFixed(v < 0.1 ? 1 : 0)}%`;
const m1 = (v: number | null) => (v === null ? "n/a" : v < 0 ? `(${Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 0 })})` : v.toLocaleString("en-US", { maximumFractionDigits: 0 }));
const xx = (v: number | null) => (v === null ? "n/a" : `${v.toFixed(2)}x`);
const pp = (v: number | null) => (v === null ? "n/a" : `${(v * 100).toFixed(1)}%`);
const BAND = { low: "Low", elevated: "Elevated", high: "High" } as const;
const edgar = (cik: string) => `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${cik}&type=10-K&dateb=&owner=include&count=40`;

export default function Replay() {
  const apiState = useApiReady();
  const [ov, setOv] = useState<ReplayOverview | null>(null);
  const [id, setId] = useState<string | null>(null);
  const [fc, setFc] = useState<ReplayForecast | null>(null);
  const [out, setOut] = useState<ReplayOutcome | null>(null);
  const [busy, setBusy] = useState<"case" | "outcome" | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (apiState.phase !== "ready") return;
    replayApi
      .overview()
      .then((o) => {
        setOv(o);
        const wanted = new URLSearchParams(window.location.search).get("case");
        setId(o.cases.find((c) => c.id === wanted)?.id ?? o.cases.find((c) => c.example === 1)?.id ?? o.cases[0].id);
      })
      .catch((e) => setError(`Could not load the replay cases: ${(e as Error).message}`));
  }, [apiState.phase]);

  useEffect(() => {
    if (!id) return;
    let live = true;
    setFc(null);
    setOut(null);                       // the outcome is hidden again whenever the case changes
    setBusy("case");
    replayApi
      .forecast(id)
      .then((f) => live && setFc(f))
      .catch((e) => live && setError((e as Error).message))
      .finally(() => live && setBusy(null));
    const url = new URL(window.location.href);
    url.searchParams.set("case", id);
    window.history.replaceState(null, "", url);
    return () => {
      live = false;
    };
  }, [id]);

  const reveal = async () => {
    if (!fc) return;
    setBusy("outcome");
    try {
      setOut(await replayApi.outcome(fc.id));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const examples = ov?.cases.filter((c) => c.example).sort((a, b) => (a.example ?? 0) - (b.example ?? 0)) ?? [];
  const more = ov?.cases.filter((c) => !c.example) ?? [];

  return (
    <>
      <TopBar active="replay" />
      <main className="page">
        <div className="file-head">
          <h1>Historical model replay</h1>
          <p>What could the network infer when the annual report was first available, and what happened one fiscal year later?</p>
        </div>
        <ApiStatus state={apiState} onRetry={apiState.retry} />
        {error && <div className="notice error" role="alert">{error}</div>}
        {ov && (
          <>
            <p className="lede replay-lede">
              Every case is a held-out company-year: its 10-K was filed between {ov.test_window[0]} and {ov.test_window[1]}, after the
              network was trained and selected on earlier filings. The forecast shown is the frozen saved prediction, exactly as the
              model scored it in the test. This is a demonstration of genuine out-of-sample performance, including its mistakes.
            </p>
            <div className="replay-picker">
              <div role="group" aria-label="Example cases">
                <span className="fine">Three examples: one correct warning, one false alarm and one missed case, in alphabetical order.</span>
                <div className="example-row">
                  {examples.map((c) => (
                    <button key={c.id} type="button" className={`example ${c.id === id ? "active" : ""}`} aria-pressed={c.id === id} onClick={() => setId(c.id)}>
                      <span className="fine">Example {c.example}</span>
                      <strong>{c.company_name}</strong>
                      <span className="fine num">{fyLabel(c.fiscal_year_end)} · filed {c.features_as_of}</span>
                    </button>
                  ))}
                </div>
              </div>
              <label className="field more-cases">
                More held-out cases
                <select value={examples.some((c) => c.id === id) ? "" : id ?? ""} onChange={(e) => e.target.value && setId(e.target.value)}>
                  <option value="">Choose a company-year…</option>
                  {more.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.company_name}, {fyLabel(c.fiscal_year_end)}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </>
        )}

        {busy === "case" && <p className="skeleton" role="status"><span className="spinner" aria-hidden="true" />Loading the case…</p>}
        {fc && (
          <>
            <Timeline fc={fc} out={out} />
            <div className="replay-split">
              <section className="sheet replay-panel" aria-labelledby="h-forecast">
                <h2 id="h-forecast">Forecast <span className="fine">known on {fc.features_as_of}</span></h2>
                <p className="fine" style={{ marginTop: 0 }}>
                  {fc.company_name}, fiscal year ending {fc.fiscal_year_end}. 10-K filed {fc.filed_days_after_year_end} days after year-end.
                  {fc.company_in_training_data ? " The network saw this company's earlier years (filed before 2019) in training, never this one." : " The network never saw this company in training."}
                </p>
                <MetricsTable m={fc.metrics_usd_m} />
                <ConditionList c={fc.stress_conditions_in_t} title={`Stress conditions in ${fyLabel(fc.fiscal_year_end)}`} />
                <div className="replay-score">
                  <div className="risk-head">
                    <span className="pct num">{pct0(fc.prediction.probability)}</span>
                    <span className={`band ${fc.prediction.band}`}>{BAND[fc.prediction.band]} screening risk</span>
                  </div>
                  <p className="fine" style={{ margin: "2px 0 0" }}>
                    Neural network&apos;s estimated chance of next-FY accounting stress. XGBoost benchmark on the same row:{" "}
                    {pct0(fc.prediction.xgboost_probability)}.
                  </p>
                  <Ruler
                    min={0}
                    max={1}
                    ariaLabel="Frozen forecast against screening bands"
                    segments={[{ to: 0.15, color: "#cfe6e4" }, { to: 0.4, color: "#f0dcb7" }, { to: 1, color: "#efc6c8" }]}
                    marks={[{ label: "Forecast", value: fc.prediction.probability, color: "#0e1b2c" }]}
                    format={(v) => `${Math.round(v * 100)}%`}
                  />
                </div>
                <h3 className="sub">What moved the forecast</h3>
                <ul className="drivers">
                  {fc.drivers.map((d) => (
                    <li key={d.feature}>
                      <span>
                        {featureLabel(d.feature)}
                        <br />
                        <span className="fine num">{featureValue(d)}</span>
                      </span>
                      <span className="num" style={{ textAlign: "right", color: d.logit_contribution > 0 ? "var(--red)" : "var(--teal)" }}>
                        {d.logit_contribution > 0 ? "raises" : "lowers"} {Math.abs(d.logit_contribution).toFixed(2)}
                      </span>
                      <span className="fine">log-odds</span>
                    </li>
                  ))}
                </ul>
                <p className="fine">
                  Change in log-odds when the input is set to its training median: associations, not causes, and not percentage points.{" "}
                  <Link href="/model#where-it-fails">How to read these</Link>.
                </p>
              </section>

              <section className="sheet replay-panel outcome" aria-labelledby="h-outcome" aria-live="polite">
                <h2 id="h-outcome">Outcome <span className="fine">fiscal year ending {fc.next_fiscal_year_end}</span></h2>
                {!out ? (
                  <div className="outcome-hidden">
                    <p>
                      Hidden. When the forecast was made, this year had not happened yet; the result was published in the next annual report.
                    </p>
                    <button className="btn" type="button" onClick={reveal} disabled={busy === "outcome"}>
                      {busy === "outcome" ? "Loading…" : "Reveal next-year outcome"}
                    </button>
                  </div>
                ) : (
                  <Outcome fc={fc} out={out} onHide={() => setOut(null)} />
                )}
              </section>
            </div>
          </>
        )}
        {ov && (
          <details className="replay-method">
            <summary>How these cases were chosen and checked</summary>
            <p className="fine">
              The saved forecasts were re-scored from the frozen model and reproduce the frozen test evaluation exactly
              ({ov.verification.rows.toLocaleString()} held-out rows, PR-AUC {ov.verification.pr_auc_recomputed.toFixed(4)} against{" "}
              {ov.verification.pr_auc_frozen.toFixed(4)} recorded at training). Figures are USD millions as the model read them from the
              original 10-K data.
            </p>
            <pre className="fine rule-text">{ov.selection_rule}</pre>
            <p className="fine">
              Full error analysis: <Link href="/model#where-it-fails">Model X-Ray, where the network fails</Link>.
            </p>
          </details>
        )}
      </main>
    </>
  );
}

function Timeline({ fc, out }: { fc: ReplayForecast; out: ReplayOutcome | null }) {
  const steps = [
    { date: fc.fiscal_year_end, label: `${fyLabel(fc.fiscal_year_end)} ends` },
    { date: fc.features_as_of, label: "10-K filed: forecast made", now: true },
    { date: fc.next_fiscal_year_end, label: `${fyLabel(fc.next_fiscal_year_end)} ends` },
    { date: out ? out.label_available_date : null, label: "Next 10-K filed: outcome known" },
  ];
  return (
    <ol className="timeline" aria-label="Timeline">
      {steps.map((s, i) => (
        <li key={i} className={s.now ? "now" : s.date ? "" : "hidden"}>
          <span className="dot" aria-hidden="true" />
          <span className="num">{s.date ?? "hidden"}</span>
          <span className="fine">{s.label}</span>
        </li>
      ))}
    </ol>
  );
}

function MetricsTable({ m, title }: { m: ReplayMetrics; title?: string }) {
  return (
    <table className="ledger num replay-metrics" aria-label={title ?? "Financial snapshot, USD millions"}>
      <tbody>
        <tr><td>Revenue</td><td>{m1(m.revenue)}</td></tr>
        <tr><td>EBITDA (margin)</td><td>{m1(m.ebitda)} ({pp(m.ebitda_margin)})</td></tr>
        <tr><td>Gross debt / EBITDA</td><td>{m.ebitda !== null && m.ebitda <= 0 ? "EBITDA ≤ 0" : xx(m.gross_debt_to_ebitda)}</td></tr>
        <tr><td>EBIT / interest</td><td>{xx(m.ebit_interest_cover)}</td></tr>
        <tr><td>Operating cash flow</td><td>{m1(m.operating_cash_flow)}</td></tr>
      </tbody>
    </table>
  );
}

const COND_LABEL: Record<keyof Conditions, string> = {
  coverage_weak: "EBIT / interest below 1.5x",
  leverage_high: "Gross debt / EBITDA above 5x",
  cash_flow_weak: "Negative operating cash flow",
};

function condValue(k: keyof Conditions, c: Condition) {
  if (k === "cash_flow_weak") return c.value === null ? "n/a" : `${m1(c.value)}m`;
  if (k === "leverage_high" && c.ebitda_nonpositive) return "EBITDA ≤ 0 with debt";
  return xx(c.value);
}

function ConditionList({ c, title }: { c: Conditions; title: string }) {
  const keys = ["coverage_weak", "leverage_high", "cash_flow_weak"] as const;
  const met = keys.filter((k) => c[k].met).length;
  return (
    <div className="conditions">
      <h3 className="sub">
        {title}: {met} of 3
      </h3>
      <ul>
        {keys.map((k) => (
          <li key={k} className={c[k].met ? "met" : c[k].met === null ? "unknown" : ""}>
            <span aria-hidden="true">{c[k].met ? "●" : c[k].met === null ? "?" : "○"}</span>
            <span>{COND_LABEL[k]}</span>
            <span className="num">{condValue(k, c[k])}</span>
            <span className="sr-only">{c[k].met ? "met" : c[k].met === null ? "unknown" : "not met"}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Outcome({ fc, out, onHide }: { fc: ReplayForecast; out: ReplayOutcome; onHide: () => void }) {
  const stressed = out.label === 1;
  const tone = out.category === "correct_warning" || out.category === "correct_all_clear" ? "good" : "bad";
  return (
    <div>
      <p className={`outcome-head ${stressed ? "stressed" : "clear"}`}>
        {stressed ? "Accounting stress followed" : "No accounting stress"}
        <span className="fine"> published {out.label_available_date}</span>
      </p>
      <MetricsTable m={out.metrics_usd_m} title="Next-year financial snapshot, USD millions" />
      <ConditionList c={out.conditions} title={`Stress conditions in ${fyLabel(out.fiscal_year_end)}`} />
      <p className="fine">Stress means at least two of the three conditions.</p>
      <div className={`assessment ${tone}`}>
        <strong>{out.assessment}</strong>
        <p>{out.verdict}</p>
        <p className="fine">
          Same score range: {pct0(out.same_range.from)} to {pct0(out.same_range.to)}, {out.same_range.n} held-out company-years.
        </p>
      </div>
      <p className="fine">
        Sources: the company&apos;s 10-K filings on{" "}
        <a href={edgar(fc.cik)} target="_blank" rel="noreferrer">SEC EDGAR</a> (CIK {fc.cik.replace(/^0+/, "")}). How the network performs
        overall: <Link href="/model">Model X-Ray</Link>.{" "}
        <button type="button" className="link" onClick={onHide}>Hide the outcome again</button>
      </p>
    </div>
  );
}
