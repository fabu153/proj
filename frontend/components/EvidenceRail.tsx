"use client";

import { useEffect, useRef } from "react";
import type { Analysis, PackageItem } from "@/lib/api";
import { fmt } from "@/lib/api";
import { ROWS } from "./CreditProfile";
import SourceTrail from "./SourceTrail";

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

function describeSource(src: Record<string, any>): string {
  switch (src.kind) {
    case "filing":
      if (src.page) return `Uploaded report, page ${src.page} (${src.method ?? "PDF"})`;
      return src.accession ? `10-K XBRL tag ${src.tag}, filed ${src.filed}, accession ${src.accession}` : "Not reported";
    case "formula":
      return `Formula ${src.formula} (v${src.version})${src.note ? `; note: ${String(src.note).replace(/_/g, " ")}` : ""}`;
    case "model":
      return `Neural stress model${src.name ? ` ${src.name}` : ""}${src.features_as_of ? `, inputs as of ${src.features_as_of}` : ""}`;
    case "model_evaluation":
      return "Frozen test-window evaluation (Model X-Ray)";
    case "scenario":
      return `Loan engine v${src.engine_version}, ${src.case} case: EBITDA ${Math.round(src.ebitda_shock * 100)}%, rates ${src.rate_shock_bps >= 0 ? "+" : ""}${src.rate_shock_bps} bp${src.snapshot ? `, snapshot ${src.snapshot}` : ""}`;
    case "assumption":
      return "Your input in the loan lab";
    case "data_checks":
      return src.rules ? `Data-quality rules: ${Object.values(src.rules).join("; ")}` : src.detail ?? "Data-quality checks for this fiscal year";
    case "snapshot":
      return src.detail ?? "Analysis snapshot";
    default:
      return src.detail ?? "";
  }
}

export type Citation = { item: PackageItem; statement: string | null };

export default function EvidenceRail({ analysis, selected, citation: cite }: { analysis: Analysis; selected: string; citation?: Citation | null }) {
  const citation = cite?.item;
  const rail = useRef<HTMLElement>(null);
  // a newly opened citation or row always starts at the top of the panel, fully visible
  useEffect(() => {
    rail.current?.scrollTo({ top: 0, behavior: "smooth" });
  }, [cite, selected]);
  const row = ROWS.flatMap((g) => g.rows).find((r) => r.key === selected);
  const metric = analysis.metrics[selected];
  const facts = Array.from(new Set(row?.facts ?? []));
  return (
    <aside className="rail" aria-label="Source evidence" ref={rail} tabIndex={0}>
      {citation && (
        <div className="sheet evidence cite-card" aria-live="polite">
          <h3>{citation.source.trail ? "Source trail" : "Memo citation"}</h3>
          <p style={{ margin: "0 0 4px", fontSize: 14 }}>{citation.label}</p>
          <div className="formula num">{citation.display}</div>
          {citation.source.trail ? (
            <SourceTrail trail={citation.source.trail} statement={cite?.statement} />
          ) : (
            <>
              <p className="fine" style={{ margin: 0 }}>{describeSource(citation.source)}</p>
              {cite?.statement && <blockquote className="fine">{cite.statement}</blockquote>}
            </>
          )}
          {citation.source.kind === "scenario" && Array.isArray(citation.source.steps) && (
            <ol className="steps">
              {citation.source.steps.map((st: string, i: number) => (
                <li key={i}>{st}</li>
              ))}
            </ol>
          )}
        </div>
      )}
      <div className="sheet evidence">
        <h3>Why this value?</h3>
        {analysis.industry?.financial && (
          <p className="fine sector-rail" role="note">
            As reported, not a credit measure: industrial ratios do not apply to this financial-sector filer.
          </p>
        )}
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
              {der ? (
                <div className="num">
                  {fmt(der.value, "amount")} used in the ratios, by rule {der.rule}
                  {ev && (
                    <div className="fine">
                      As {ev.page ? `extracted from page ${ev.page}` : <>tagged in XBRL (<code>{ev.tag}</code>)</>}: {fmt(ev.value, "amount")}
                      {der.basis === "credit" ? ". The neural screen keeps the as-tagged value, which is what it was trained on." : "."}
                    </div>
                  )}
                </div>
              ) : ev && ev.page ? (
                <div className="num">
                  {fmt(ev.value, "amount")} from the uploaded report, page {ev.page}
                  <br />
                  <span className="fine">{ev.extraction_method}</span>
                </div>
              ) : ev ? (
                <div className="num">
                  {fmt(ev.value, "amount")} from XBRL tag <code>{ev.tag}</code>
                  <br />
                  {ev.form} filed {ev.filed},{" "}
                  <a href={filingUrl(analysis.company_id, ev.accession)} target="_blank" rel="noreferrer">
                    accession {ev.accession}
                  </a>
                </div>
              ) : (
                <div className="na">Not reported in this filing</div>
              )}
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
