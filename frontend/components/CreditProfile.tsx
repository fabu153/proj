"use client";

import type { Analysis, HistoryPoint } from "@/lib/api";
import { fmt, fyLabel } from "@/lib/api";

export type RowDef = {
  key: string;
  label: string;
  unit: "amount" | "pct" | "x";
  source: "values" | "metrics";
  facts: string[]; // canonical facts behind it, for the evidence rail
};

export const ROWS: { group: string; rows: RowDef[] }[] = [
  {
    group: "Scale and profitability",
    rows: [
      { key: "revenue", label: "Revenue", unit: "amount", source: "values", facts: ["revenue"] },
      { key: "revenue_growth", label: "Revenue growth", unit: "pct", source: "metrics", facts: ["revenue"] },
      { key: "ebitda", label: "EBITDA (approx.)", unit: "amount", source: "metrics", facts: ["operating_income", "depreciation_amortization"] },
      { key: "ebitda_margin", label: "EBITDA margin", unit: "pct", source: "metrics", facts: ["operating_income", "depreciation_amortization", "revenue"] },
    ],
  },
  {
    group: "Leverage",
    rows: [
      { key: "gross_debt", label: "Gross debt", unit: "amount", source: "metrics", facts: ["short_term_borrowings", "current_maturities_ltd", "long_term_debt"] },
      { key: "net_debt", label: "Net debt", unit: "amount", source: "metrics", facts: ["short_term_borrowings", "current_maturities_ltd", "long_term_debt", "cash"] },
      { key: "gross_leverage", label: "Gross debt / EBITDA", unit: "x", source: "metrics", facts: ["long_term_debt", "operating_income", "depreciation_amortization"] },
      { key: "net_leverage", label: "Net debt / EBITDA", unit: "x", source: "metrics", facts: ["long_term_debt", "cash", "operating_income", "depreciation_amortization"] },
    ],
  },
  {
    group: "Coverage",
    rows: [
      { key: "ebit_interest_cover", label: "EBIT / interest", unit: "x", source: "metrics", facts: ["operating_income", "interest_expense"] },
      { key: "ebitda_interest_cover", label: "EBITDA / interest", unit: "x", source: "metrics", facts: ["operating_income", "depreciation_amortization", "interest_expense"] },
    ],
  },
  {
    group: "Cash and liquidity",
    rows: [
      { key: "fcf_simple", label: "Free cash flow (CFO − capex)", unit: "amount", source: "metrics", facts: ["operating_cash_flow", "capital_expenditures"] },
      { key: "current_ratio", label: "Current ratio", unit: "x", source: "metrics", facts: ["current_assets", "current_liabilities"] },
    ],
  },
];

type Props = {
  analysis: Analysis;
  history: HistoryPoint[];
  selected: string;
  onSelect: (key: string) => void;
};

export default function CreditProfile({ analysis, history, selected, onSelect }: Props) {
  const upto = history.filter((h) => h.fiscal_year_end <= analysis.fiscal_year_end).slice(-4);
  const latest = analysis.fiscal_year_end;
  return (
    <div className="sheet" style={{ overflowX: "auto" }}>
      <table className="ledger num">
        <caption style={{ textAlign: "left", padding: "10px 12px 0", fontSize: 12.5, color: "var(--slate)" }}>
          {analysis.currency} millions, annual 10-K data. Select a row to see its formula and source filing.
        </caption>
        <thead>
          <tr>
            <th scope="col">Metric</th>
            {upto.map((h) => (
              <th scope="col" key={h.fiscal_year_end}>
                {fyLabel(h.fiscal_year_end)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ROWS.map((g) => (
            <Group key={g.group} group={g.group} cols={upto.length + 1}>
              {g.rows.map((r) => {
                const m = analysis.metrics[r.key];
                return (
                  <tr
                    key={r.key}
                    className="row"
                    tabIndex={0}
                    aria-selected={selected === r.key}
                    onClick={() => onSelect(r.key)}
                    onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect(r.key))}
                  >
                    <td>
                      {r.label}
                      {m && m.status === "ok_with_warning" && <span className="status-dot warn" title={m.reason ?? ""} />}
                      {m && (m.status === "undefined" || m.status === "not_available") && (
                        <span className="status-dot undef" title={m.reason ?? ""} />
                      )}
                    </td>
                    {upto.map((h) => {
                      const v = r.source === "values" ? h.values[r.key] : h.metrics[r.key];
                      return (
                        <td key={h.fiscal_year_end} className={`${h.fiscal_year_end === latest ? "latest" : ""} ${v == null ? "na" : ""}`}>
                          {fmt(v, r.unit)}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </Group>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Group({ group, cols, children }: { group: string; cols: number; children: React.ReactNode }) {
  return (
    <>
      <tr className="group">
        <td colSpan={cols}>{group}</td>
      </tr>
      {children}
    </>
  );
}
