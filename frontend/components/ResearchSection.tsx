"use client";

/**
 * Model X-Ray, section 4: neural-network research that is NOT used in the app. Overall-stress and onset-only results
 * sit in separate tables: different populations and base rates, so their PR-AUCs must not be compared across tables.
 * Data: GET /model -> research (backend/data/research/research_v1.json, built by training/ml/export_research.py).
 */

type Diff = { mean_diff: number; ci95?: [number, number]; share_a_better?: number } | null;
type Row = { model: string; kind: "deployed" | "experiment" | "benchmark" | "reference"; inputs: string; trained_on: string;
  pr_auc: number; pr_auc_ci95: [number, number] | null; vs_deployed: Diff; source: string };
type WRow = { rule: string; threshold: number; flagged: number; flag_rate: number; caught: number; missed: number;
  false_alarms: number; precision: number | null; recall: number; recall_ci95: [number, number] | null;
  precision_ci95: [number, number] | null };

const f3 = (v: number) => v.toFixed(3);
const pc = (v: number | null) => (v == null ? "–" : `${Math.round(v * 100)}%`);
const sgn = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(3)}`;
const KIND: Record<Row["kind"], string> = { deployed: "Deployed", experiment: "Experiment", benchmark: "Benchmark", reference: "Reference" };

function Table({ rows, caption, label }: { rows: Row[]; caption: string; label: string }) {
  return (
    <div className="sheet scroll-x" tabIndex={0} role="region" aria-label={label}>
      <table className="ledger research-table">
        <caption className="fine">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Model</th>
            <th scope="col">Status</th>
            <th scope="col">Inputs</th>
            <th scope="col">Trained on</th>
            <th scope="col" className="num">PR-AUC (95% CI)</th>
            <th scope="col" className="num">Versus deployed</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.model} className={r.kind === "deployed" ? "is-deployed" : undefined}>
              <th scope="row">{r.model}</th>
              <td><span className={`kind ${r.kind}`}>{KIND[r.kind]}</span></td>
              <td>{r.inputs}</td>
              <td>{r.trained_on}</td>
              <td className="num">
                <b>{f3(r.pr_auc)}</b>
                {r.pr_auc_ci95 ? <span className="fine"> ({f3(r.pr_auc_ci95[0])}–{f3(r.pr_auc_ci95[1])})</span> : null}
              </td>
              <td className="num">
                {r.kind === "deployed" || r.kind === "reference" || !r.vs_deployed ? "–" : (
                  <>
                    {sgn(r.vs_deployed.mean_diff)}
                    {r.vs_deployed.ci95 ? (
                      <span className="fine"> ({sgn(r.vs_deployed.ci95[0])} to {sgn(r.vs_deployed.ci95[1])})</span>
                    ) : null}
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function ResearchSection({ r }: { r: any }) {
  const pop = r.populations;
  const rec = r.reconciliation;
  const wl: WRow[] = r.watchlist.rows;
  const name = (k: string) => (k === "original" ? `Original threshold (${f3(wl[0].threshold)})` : `${k.replace("budget_", "")}% budget (${f3(wl.find((w) => w.rule === k)!.threshold)})`);
  return (
    <section className="block" id="research" aria-labelledby="h-research">
      <h2 id="h-research">4. Experimental research</h2>
      <div className="notice research-note" role="note">
        <strong>Not used in the app.</strong> Only the deployed network produces the neural screen. The models and thresholds below are
        experiments, compared on the same held-out rows. The 2021–25 test window had already been inspected, so these comparisons are
        exploratory.
      </div>

      <h3 className="sub">Next-year stress, all borrowers</h3>
      <Table
        rows={r.overall}
        label="Overall stress results table"
        caption={`${pop.overall.rows.toLocaleString()} held-out company-years, ${pop.overall.positives} stressed the next year (base rate ${pc(pop.overall.positives / pop.overall.rows)}).`}
      />

      <h3 className="sub">New stress only: borrowers healthy in the filing year</h3>
      <Table
        rows={r.onset}
        label="Onset-only results table"
        caption={`${pop.onset.rows} company-years confirmed not stressed in the filing year, ${pop.onset.positives} of which became stressed (base rate ${pc(pop.onset.positives / pop.onset.rows)}). Onset-specific models had ${pop.onset.training_onsets} onsets to learn from. Do not compare these PR-AUCs with the table above.`}
      />
      <p className="fine">
        Each row's “versus deployed” is a paired difference on the same rows; an interval is shown where it was bootstrapped by company.
        Sources: {Object.values(r.sources).join(", ")}.
      </p>

      <h3 className="sub">Research: a watch-list threshold for healthy borrowers</h3>
      <p className="fine" style={{ marginTop: 0 }}>
        The deployed network&apos;s unchanged scores on the same {pop.onset.rows} healthy borrowers. Budgets are fixed on 2019–20 validation
        scores, then applied once to the test window.
      </p>
      <div className="sheet scroll-x" tabIndex={0} role="region" aria-label="Watch-list threshold research table">
        <table className="ledger num research-wl">
          <thead>
            <tr>
              <th scope="col">Threshold</th>
              <th scope="col">Flagged</th>
              <th scope="col">Onsets caught (of {pop.onset.positives})</th>
              <th scope="col">Missed</th>
              <th scope="col">False alarms</th>
              <th scope="col">Precision</th>
              <th scope="col">Recall (95% CI)</th>
            </tr>
          </thead>
          <tbody>
            {wl.map((w) => (
              <tr key={w.rule} className={w.rule === "original" ? "is-deployed" : undefined}>
                <th scope="row">{name(w.rule)}{w.rule === "original" ? " · deployed" : ""}</th>
                <td>{w.flagged} ({pc(w.flag_rate)})</td>
                <td><b>{w.caught}</b></td>
                <td>{w.missed}</td>
                <td>{w.false_alarms}</td>
                <td>{pc(w.precision)}</td>
                <td>
                  {pc(w.recall)}
                  {w.recall_ci95 ? <span className="fine"> ({pc(w.recall_ci95[0])}–{pc(w.recall_ci95[1])})</span> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="fine"><b>Recommendation (not deployed):</b> {r.watchlist.recommendation}</p>

      <div className="fail-grid">
        <div className="sheet">
          <h3 className="sub">Key findings</h3>
          <ul className="plain-list">
            {r.findings.map((f: string) => <li key={f}>{f}</li>)}
          </ul>
        </div>
        <div className="sheet">
          <h3 className="sub">Limitations</h3>
          <ul className="warn-list">
            {r.limitations.map((f: string) => <li key={f}>{f}</li>)}
          </ul>
          <p className="fine">
            {rec.explanation}
          </p>
        </div>
      </div>
    </section>
  );
}
