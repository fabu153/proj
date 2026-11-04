"use client";

import type { Analysis } from "@/lib/api";
import { fmt } from "@/lib/api";
import { ROWS } from "./CreditProfile";

const FACT_LABELS: Record<string, string> = {
  revenue: "Revenue",
  operating_income: "Operating income (EBIT proxy)",
  depreciation_amortization: "Depreciation and amortization",
  interest_expense: "Interest expense",
  short_term_borrowings: "Short-term borrowings",
  current_maturities_ltd: "Current portion of long-term debt",
  long_term_debt: "Long-term debt (non-current)",
  cash: "Cash and equivalents",
  operating_cash_flow: "Operating cash flow",
  capital_expenditures: "Capital expenditures",
  current_assets: "Current assets",
  current_liabilities: "Current liabilities",
};

function filingUrl(cik: string, accession: string) {
  return `https://www.sec.gov/Archives/edgar/data/${parseInt(cik, 10)}/${accession.replace(/-/g, "")}/`;
}

export default function EvidenceRail({ analysis, selected }: { analysis: Analysis; selected: string }) {
  const row = ROWS.flatMap((g) => g.rows).find((r) => r.key === selected);
  const metric = analysis.metrics[selected];
  const facts = Array.from(new Set(row?.facts ?? []));
  return (
    <aside className="rail" aria-label="Source evidence">
      <div className="sheet evidence">
        <h3>Why this value?</h3>
        {row && (
          <p className="fine" style={{ margin: 0 }}>
            {row.label}, fiscal year ending {analysis.fiscal_year_end}
          </p>
        )}
        {metric ? (
          <>
            <div className="formula num">
              {metric.formula}
              <div className="fine">formula v{metric.formula_version}</div>
            </div>
            <dl className="num">
              <dt>Result</dt>
              <dd>
                <strong>{fmt(metric.value, metric.unit === "amount" ? "amount" : metric.unit)}</strong>
              </dd>
              {Object.entries(metric.inputs).map(([k, v]) => (
                <Pair key={k} k={k.replace(/_/g, " ")} v={fmt(v, "amount")} />
              ))}
            </dl>
            {metric.reason && <p className="fine">Note: {metric.reason.replace(/_/g, " ")}</p>}
          </>
        ) : (
          <p className="fine">Reported directly in the filing; no calculation.</p>
        )}
        {facts.map((f) => {
          const ev = analysis.evidence[f];
          const der = analysis.derived[f];
          return (
            <div className="src" key={f}>
              <strong>{FACT_LABELS[f] ?? f}</strong>
              {ev ? (
                <div className="num">
                  {fmt(ev.value, "amount")} from XBRL tag <code>{ev.tag}</code>
                  <br />
                  {ev.form} filed {ev.filed},{" "}
                  <a href={filingUrl(analysis.company_id, ev.accession)} target="_blank" rel="noreferrer">
                    accession {ev.accession}
                  </a>
                </div>
              ) : der ? (
                <div className="num">
                  {fmt(der.value, "amount")} derived by rule {der.rule}
                </div>
              ) : (
                <div className="na">Not reported in this filing</div>
              )}
              {der && ev && <div className="fine">Overridden by derivation rule {der.rule}</div>}
            </div>
          );
        })}
      </div>
      <div className="sheet">
        <h3>Data checks</h3>
        {analysis.hard_failures.length > 0 && (
          <div className="notice error" style={{ marginBottom: 8 }}>
            Hard checks failed, so the risk score and loan scenarios are blocked: {analysis.hard_failures.join("; ")}
          </div>
        )}
        {analysis.warnings.length ? (
          <ul className="warn-list">
            {analysis.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        ) : (
          <p className="fine" style={{ margin: 0 }}>No warnings for this fiscal year.</p>
        )}
      </div>
    </aside>
  );
}

function Pair({ k, v }: { k: string; v: string }) {
  return (
    <>
      <dt>{k}</dt>
      <dd>{v}</dd>
    </>
  );
}
