"use client";

import Link from "next/link";
import type { ClassicScore, PeerBandT } from "@/lib/api";

const NAMES: Record<string, string> = {
  total_assets: "total assets", current_assets: "current assets", current_liabilities: "current liabilities",
  retained_earnings: "retained earnings", operating_income: "operating income", stockholders_equity: "equity",
  total_liabilities: "total liabilities", net_income: "net income", net_income_prior_year: "prior-year net income",
  operating_cash_flow: "operating cash flow",
};

/** Where the company sits among peers, always drawn with "safer" to the right (O is flipped: lower is safer). */
function PeerGauge({ b }: { b: PeerBandT }) {
  const safer = b.stronger === "higher" ? b.percentile : 100 - b.percentile;
  const text = `Safer than ${safer}% of ${b.peers} peers (${b.group}, ${b.years})`;
  return (
    <div className="gauge" role="img" aria-label={text}>
      <div className="gauge-track">
        <span className="gauge-q" style={{ left: "25%" }} />
        <span className="gauge-q" style={{ left: "50%" }} />
        <span className="gauge-q" style={{ left: "75%" }} />
        <span className="gauge-dot" style={{ left: `${safer}%` }} />
      </div>
      <div className="gauge-ends" aria-hidden="true"><span>riskier</span><span>peer median</span><span>safer</span></div>
      <div className="gauge-text">
        Safer than <b>{safer}%</b> of {b.peers} peers <span className="fine">· {b.group}, {b.years}</span>
      </div>
    </div>
  );
}

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
              {pz && <PeerGauge b={pz} />}
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
              {po && <PeerGauge b={po} />}
            </>
          ) : (
            <Missing s={o} />
          )}
        </div>
      </div>
    </div>
  );
}
