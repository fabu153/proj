"use client";

import type { MaturityWall as Wall } from "@/lib/api";
import { fmt } from "@/lib/api";

const accUrl = (cik: string, acc: string) => `https://www.sec.gov/Archives/edgar/data/${parseInt(cik, 10)}/${acc.replace(/-/g, "")}/`;

/** v1.6: principal of long-term debt falling due by year (XBRL maturity schedule) and how far liquidity reaches. */
export default function MaturityWall({ wall, cik, currency }: { wall: Wall; cik: string; currency: string }) {
  if (!wall.available) {
    return (
      <div className="sheet maturity">
        <p className="fine" style={{ margin: 0 }}>{wall.reason}</p>
      </div>
    );
  }
  const vals = wall.buckets.map((b) => b.value ?? 0);
  const max = Math.max(...vals, wall.cash ?? 0, 1);
  const H = 180;
  const SHORT: Record<string, string> = { debt_maturity_y1: "≤ 1 yr", debt_maturity_y2: "2 yrs", debt_maturity_y3: "3 yrs",
    debt_maturity_y4: "4 yrs", debt_maturity_y5: "5 yrs", debt_maturity_after5: "> 5 yrs" };
  const room = H - 22;                                    // leave space for the value labels above the tallest bar
  const accessions = Array.from(new Set(wall.buckets.filter((b) => b.evidence).map((b) => `${b.evidence!.accession}|${b.evidence!.filed}`)));
  const cov = wall.coverage_12m;
  const through = wall.runway_through == null ? "n/a" : wall.runway_through === 0 ? "Not year 1" : `Year ${Math.min(wall.runway_through, 5)}`;
  const tone = cov == null ? "" : cov < 1 ? "weak" : cov < 1.5 ? "tight" : "ok";
  return (
    <div className="sheet maturity">
      <div className="maturity-kpis">
        <div className="kpi">
          <span className="kpi-label">Due within 12 months</span>
          <span className="kpi-value">{wall.due_12m != null ? fmt(wall.due_12m, "amount") : "n/a"}</span>
          <span className="kpi-sub">
            {fmt(wall.buckets[0].value, "amount")} scheduled + {fmt(wall.short_term_borrowings ?? 0, "amount")} short-term borrowings
          </span>
        </div>
        <div className={`kpi ${tone}`}>
          <span className="kpi-label">Liquidity runway</span>
          <span className="kpi-value">{cov == null ? "n/a" : `${cov.toFixed(2)}x`}</span>
          <span className="kpi-sub">
            cash {fmt(wall.cash, "amount")} + FCF {wall.fcf == null ? "n/a" : fmt(Math.max(wall.fcf, 0), "amount")}, over 12-month dues
          </span>
        </div>
        <div className="kpi">
          <span className="kpi-label">Covered through</span>
          <span className="kpi-value">{through}</span>
          <span className="kpi-sub">if free cash flow holds and nothing is refinanced</span>
        </div>
        <div className="kpi">
          <span className="kpi-label">Due within 2 years</span>
          <span className="kpi-value">{wall.within_two_years_share == null ? "n/a" : `${Math.round(wall.within_two_years_share * 100)}%`}</span>
          <span className="kpi-sub">of the scheduled principal</span>
        </div>
      </div>
      <div className="maturity-body">
        <figure className="maturity-chart" aria-label={`Debt maturities, ${currency} millions`}>
          <div className="bars" style={{ height: H }}>
            {wall.cash != null && (
              <div className="cash-line" style={{ bottom: (wall.cash / max) * room }} aria-hidden="true" />
            )}
            {wall.buckets.map((b) => (
              <div key={b.key} className="bar-col" title={b.evidence ? `${b.label}: ${fmt(b.value, "amount")} (${b.evidence.tag}, 10-K filed ${b.evidence.filed})` : `${b.label}: not tagged in XBRL`}>
                <span className="bar-val">{b.value == null ? "n/r" : fmt(b.value, "amount")}</span>
                <div className={`bar ${b.value == null ? "missing" : ""} ${b.key === "debt_maturity_y1" ? "first" : ""}`} style={{ height: b.value == null ? 2 : Math.max(2, ((b.value ?? 0) / max) * room) }} />
              </div>
            ))}
          </div>
          <div className="bar-labels">
            {wall.buckets.map((b) => <span key={b.key}>{SHORT[b.key]}</span>)}
          </div>
          <figcaption>
            <span className="legend"><i className="sw first" />due in the next 12 months</span>
            <span className="legend"><i className="sw later" />later years</span>
            {wall.cash != null && <span className="legend"><i className="sw cash" />cash {fmt(wall.cash, "amount")}</span>}
            <span className="legend fine">Long-term debt principal, {currency} millions, from the 10-K schedule · n/r = not tagged</span>
          </figcaption>
          <table className="sr-only">
            <caption>Debt maturities</caption>
            <tbody>
              {wall.buckets.map((b) => (
                <tr key={b.key}><th scope="row">{b.label}</th><td>{b.value == null ? "not reported" : fmt(b.value, "amount")}</td></tr>
              ))}
            </tbody>
          </table>
        </figure>
      </div>
      <div className="maturity-foot">
        <p>
          <span className="foot-label">Schedule vs balance sheet</span>
          <span>
            {fmt(wall.schedule_total, "amount")} scheduled vs {fmt(wall.long_term_debt_balance, "amount")} long-term debt on the balance
            sheet; differences come from discounts, issuance costs and finance leases.
          </span>
        </p>
        {wall.notes.map((n) => (
          <p key={n}><span className="foot-label">Note</span><span>{n}</span></p>
        ))}
        <p>
          <span className="foot-label">Source</span>
          <span>
          {accessions.map((a, i) => {
            const [acc, filed] = a.split("|");
            return (
              <span key={a}>
                {i ? ", " : ""}
                <a href={accUrl(cik, acc)} target="_blank" rel="noreferrer">10-K filed {filed}</a>
              </span>
            );
          })}
          . Runway formula v{wall.version}: {wall.formula}.
          </span>
        </p>
      </div>
    </div>
  );
}
