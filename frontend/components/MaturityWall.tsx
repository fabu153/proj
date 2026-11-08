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
  const H = 150;
  const SHORT: Record<string, string> = { debt_maturity_y1: "≤ 1 yr", debt_maturity_y2: "2 yrs", debt_maturity_y3: "3 yrs",
    debt_maturity_y4: "4 yrs", debt_maturity_y5: "5 yrs", debt_maturity_after5: "> 5 yrs" };
  const room = H - 22;                                    // leave space for the value labels above the tallest bar
  const accessions = Array.from(new Set(wall.buckets.filter((b) => b.evidence).map((b) => `${b.evidence!.accession}|${b.evidence!.filed}`)));
  const cov = wall.coverage_12m;
  return (
    <div className="sheet maturity">
      <div className="maturity-grid">
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
          <figcaption className="fine">
            Long-term debt principal due by year from the balance-sheet date, {currency} millions, as tagged in the 10-K. The first
            bar is dark; the dashed line marks cash ({fmt(wall.cash, "amount")}). n/r = not reported in XBRL.
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
        <dl className="maturity-facts">
          <dt>Due within 12 months</dt>
          <dd>
            {wall.due_12m != null ? fmt(wall.due_12m, "amount") : "n/a"}
            <span className="fine"> scheduled {fmt(wall.buckets[0].value, "amount")} + short-term borrowings {fmt(wall.short_term_borrowings ?? 0, "amount")}</span>
          </dd>
          <dt>Liquidity runway</dt>
          <dd>
            <b>{cov == null ? "n/a" : `${cov.toFixed(2)}x`}</b>
            <span className="fine"> (cash {fmt(wall.cash, "amount")} + free cash flow {wall.fcf == null ? "n/a" : fmt(Math.max(wall.fcf, 0), "amount")}) / due within 12 months</span>
          </dd>
          <dt>Covers scheduled maturities</dt>
          <dd>
            {wall.runway_through == null ? "n/a" : wall.runway_through === 0 ? "not even year 1" : wall.runway_through >= 5 ? "through year 5" : `through year ${wall.runway_through}`}
            <span className="fine"> if free cash flow holds and nothing is refinanced</span>
          </dd>
          <dt>Due within 2 years</dt>
          <dd>{wall.within_two_years_share == null ? "n/a" : `${Math.round(wall.within_two_years_share * 100)}% of the schedule`}</dd>
          <dt>Schedule vs balance sheet</dt>
          <dd>
            {fmt(wall.schedule_total, "amount")} scheduled vs {fmt(wall.long_term_debt_balance, "amount")} long-term debt
            <span className="fine"> (differences: discounts, issuance costs, finance leases)</span>
          </dd>
        </dl>
      </div>
      {wall.notes.map((n) => <p key={n} className="fine" style={{ margin: "6px 0 0" }}>{n}</p>)}
      <p className="fine" style={{ margin: "6px 0 0" }}>
        Source:{" "}
        {accessions.map((a, i) => {
          const [acc, filed] = a.split("|");
          return (
            <span key={a}>
              {i ? ", " : ""}
              <a href={accUrl(cik, acc)} target="_blank" rel="noreferrer">10-K filed {filed}</a>
            </span>
          );
        })}
        . Formula v{wall.version}: {wall.formula}.
      </p>
    </div>
  );
}
