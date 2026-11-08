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

const ord = (n: number) => `${n}${n % 100 >= 11 && n % 100 <= 13 ? "th" : ["th", "st", "nd", "rd"][n % 10] ?? "th"}`;

type Band = { percentile: number; peers: number; group: string; years: string; p25: number; median: number; p75: number; stronger: "lower" | "higher" };

/** v1.6: where the company sits among peers (finance/peers.py). The bar shows the percentile; the text says which way is stronger. */
function PeerBand({ b, label, unit }: { b?: Band; label: string; unit: RowDef["unit"] }) {
  if (!b) return <td className="na peer">–</td>;
  const stronger = b.stronger === "lower" ? 100 - b.percentile : b.percentile;
  const sentence = `${label}: ${ord(b.percentile)} percentile of ${b.peers} peers (${b.group}, ${b.years}); ${b.stronger} is stronger, so it is stronger than about ${stronger}% of them. Peer quartiles ${fmt(b.p25, unit)}, ${fmt(b.median, unit)}, ${fmt(b.p75, unit)}.`;
  return (
    <td className="peer" title={sentence}>
      <span className="sr-only">{sentence}</span>
      <span aria-hidden="true" className="peer-cell">
        <span className="peer-bar">
          <span className="peer-mark" style={{ left: `${b.percentile}%` }} />
        </span>
        <span className="peer-pct">{ord(b.percentile)}</span>
      </span>
    </td>
  );
}

export default function CreditProfile({ analysis, history, selected, onSelect }: Props) {
  const upto = history.filter((h) => h.fiscal_year_end <= analysis.fiscal_year_end).slice(-4);
  const latest = analysis.fiscal_year_end;
  const bands: Record<string, Band> = (analysis.peers?.bands ?? {}) as Record<string, Band>;
  const anyBand = Object.values(bands)[0];
  return (
    <div className="sheet scroll-x" tabIndex={0} role="region" aria-label="Credit profile table">
      <table className="ledger num">
        <caption style={{ textAlign: "left", padding: "10px 12px 0", fontSize: 12.5, color: "var(--slate)" }}>
          {analysis.currency} millions, annual 10-K data. Select a row to see its formula and source filing.
          {anyBand ? " Peers: percentile among comparable companies in the training panel (hover for the group and quartiles)." : ""}
        </caption>
        <thead>
          <tr>
            <th scope="col">Metric</th>
            {upto.map((h) => (
              <th scope="col" key={h.fiscal_year_end}>
                {fyLabel(h.fiscal_year_end)}
              </th>
            ))}
            {anyBand && <th scope="col" className="peer">Peers</th>}
          </tr>
        </thead>
        <tbody>
          {ROWS.map((g) => (
            <Group key={g.group} group={g.group} cols={upto.length + 1 + (anyBand ? 1 : 0)}>
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
                    {anyBand && <PeerBand b={bands[r.key]} label={r.label} unit={r.unit} />}
                  </tr>
                );
              })}
            </Group>
          ))}
        </tbody>
      </table>
      {anyBand && (
        <p className="fine peer-note">
          Peers: {anyBand.group}, {anyBand.years}, {anyBand.peers} companies (rows may use a wider group when fewer than{" "}
          {analysis.peers?.min_peers} peers report the ratio). Each peer counts once; ratios on the training-panel basis, before the
          credit adjustments R5–R7, so a few values can differ slightly from the column above. Descriptive only.
        </p>
      )}
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
