"use client";

import Link from "next/link";
import type { ClassicScore, PeerBandT } from "@/lib/api";

const ord = (n: number) => `${n}${n % 100 >= 11 && n % 100 <= 13 ? "th" : ["th", "st", "nd", "rd"][n % 10] ?? "th"}`;
const NAMES: Record<string, string> = {
  total_assets: "total assets", current_assets: "current assets", current_liabilities: "current liabilities",
  retained_earnings: "retained earnings", operating_income: "operating income", stockholders_equity: "equity",
  total_liabilities: "total liabilities", net_income: "net income", net_income_prior_year: "prior-year net income",
  operating_cash_flow: "operating cash flow",
};

function Missing({ s }: { s?: ClassicScore }) {
  return (
    <span className="fine">
      Not available: {s?.reason ?? `not reported in XBRL: ${(s?.missing ?? []).map((m) => NAMES[m] ?? m).join(", ")}`}.
    </span>
  );
}

/** v1.6: Altman Z'' and Ohlson O beside the neural screen. Textbook references, not CreditLens predictions. */
export default function ClassicScores({ z, o, bands }: { z?: ClassicScore; o?: ClassicScore; bands?: Record<string, PeerBandT> }) {
  const pz = bands?.altman_z2;
  const po = bands?.ohlson_o;
  return (
    <div className="sheet classic">
      <h3 className="sub">Textbook scores for comparison</h3>
      <p className="fine" style={{ marginTop: 0 }}>
        Classic bankruptcy scores with their original coefficients, computed from the same 10-K facts. They are references, not CreditLens
        predictions. On the held-out years they rank next-year stress less well than the network (
        <Link href="/model#research">Model X-Ray</Link>).
      </p>
      <div className="classic-grid">
        <div>
          <div className="classic-name">Altman Z″ <span className="fine">(1995, non-manufacturers)</span></div>
          {z?.available ? (
            <>
              <div className="classic-val">
                <b>{z.value!.toFixed(2)}</b> <span className={`zone ${z.zone}`}>{z.zone === "safe" ? "safe zone" : z.zone === "grey" ? "grey zone" : "distress zone"}</span>
              </div>
              <div className="fine">Safe above 2.60, distress below 1.10. Lower is riskier.</div>
              {pz && <div className="fine">{ord(pz.percentile)} percentile of {pz.peers} peers ({pz.group}, {pz.years}).</div>}
            </>
          ) : (
            <Missing s={z} />
          )}
        </div>
        <div>
          <div className="classic-name">Ohlson O <span className="fine">(1980)</span></div>
          {o?.available ? (
            <>
              <div className="classic-val"><b>{o.value!.toFixed(2)}</b></div>
              <div className="fine">Higher is riskier. Only its rank is shown: the 1970s probability calibration does not carry over.</div>
              {po && <div className="fine">{ord(po.percentile)} percentile of {po.peers} peers ({po.group}, {po.years}).</div>}
            </>
          ) : (
            <Missing s={o} />
          )}
        </div>
      </div>
    </div>
  );
}
