"use client";

import Link from "next/link";
import type { Driver, RiskModel } from "@/lib/api";
import { fyLabel } from "@/lib/api";
import Ruler from "./Ruler";
import { featureLabel } from "@/lib/labels";

const pct = (v: number) => `${(v * 100).toFixed(v < 0.1 ? 1 : 0)}%`;

export function featureValue(d: Pick<Driver, "value" | "unit">) {
  if (d.value === null) return "not available";
  switch (d.unit) {
    case "pct":
      return `${(d.value * 100).toFixed(1)}%`;
    case "pp":
      return `${(d.value * 100).toFixed(1)} pp`;
    case "x":
      return `${d.value.toFixed(2)}x`;
    case "log":
      return `$${Math.round(Math.exp(d.value)).toLocaleString("en-US")}m assets`;
    case "flag":
      return d.value ? "yes" : "no";
    case "count":
      return `${d.value.toFixed(0)} of 3`;
    default:
      return d.value.toFixed(0);
  }
}

export default function RiskScreen({ risk, fiscalYearEnd }: { risk: RiskModel; fiscalYearEnd?: string }) {
  if (risk.status === "model_unavailable") {
    return <div className="notice">No trained model is deployed, so no risk estimate is shown.</div>;
  }
  if (risk.status === "withheld") {
    return (
      <div className="sheet risk">
        <div className="notice">
          <strong>Score withheld.</strong> The network only scores company-years like those it was trained on:{" "}
          {(risk.gate_reasons ?? []).join("; ")}.
        </div>
        <ModelMeta risk={risk} />
      </div>
    );
  }
  const p = risk.probability ?? 0;
  const maxAbs = Math.max(...(risk.drivers ?? []).map((d) => Math.abs(d.logit_contribution)), 0.01);
  return (
    <div className="sheet risk">
      <div className="risk-head">
        <span className="pct num">{pct(p)}</span>
        <span className={`band ${risk.band}`}>{risk.band === "elevated" ? "Elevated" : risk.band === "high" ? "High" : "Low"} screening risk</span>
        <span className="fine">{risk.label}</span>
      </div>
      {(risk.critical_inputs_unavailable?.length ?? 0) > 0 && (
        <div className="notice" style={{ margin: "10px 0" }}>
          Scored with {risk.critical_inputs_unavailable!.join(", ")} not available. The network treats missing inputs as it did in
          training, which makes this score less reliable.
        </div>
      )}
      <Ruler
        min={0}
        max={1}
        ariaLabel="Next-FY accounting-stress screen against screening bands"
        segments={[
          { to: 0.15, color: "#cfe6e4" },
          { to: 0.4, color: "#f0dcb7" },
          { to: 1, color: "#efc6c8" },
        ]}
        marks={[{ label: "This company", value: p, color: "#0e1b2c" }]}
        format={(v) => `${Math.round(v * 100)}%`}
      />
      <p className="fine" style={{ margin: "2px 0 0" }}>
        Bands: low below 15%, elevated 15–40%, high from 40%. Fixed before training, for display only.
      </p>
      {risk.model && (
        <p className="score-sentence">
          The network reads only the {fiscalYearEnd ? `${fyLabel(fiscalYearEnd)} ` : ""}annual report and puts the chance of
          accounting stress in the following year at {pct(p)}; on 2021–25 filings it never saw, it reached a precision-recall AUC of{" "}
          {risk.model.test_pr_auc.toFixed(3)} against {risk.model.xgboost_benchmark_test_pr_auc.toFixed(3)} for XGBoost, a difference within the
          margin of error. <Link href="/model">Model X-Ray</Link> · <Link href="/replay">See it on held-out cases</Link>
        </p>
      )}
      <p className="fine" style={{ margin: "6px 0 0" }}>
        This score does not respond to the loan lab: the network predicts from the filed accounts, while the loan lab reworks financing
        mechanically.
      </p>

      <h4 style={{ margin: "18px 0 0", fontSize: 14 }}>What moved the score</h4>
      <p className="fine" style={{ margin: "2px 0 0" }}>
        Change in the network&apos;s log-odds when each input is replaced by its training median: not percentage points, and associations,
        not causes. <Link href="/model#where-it-fails">How to read these</Link>.
      </p>
      <ul className="drivers">
        {(risk.drivers ?? []).map((d) => {
          const w = (Math.abs(d.logit_contribution) / maxAbs) * 50;
          const up = d.logit_contribution > 0;
          return (
            <li key={d.feature}>
              <span title={d.description}>
                {featureLabel(d.feature)}
                <br />
                <span className="fine num">{featureValue(d)}</span>
              </span>
              <span className="num" style={{ textAlign: "right", color: up ? "var(--red)" : "var(--teal)" }}>
                {up ? "raises" : "lowers"} {Math.abs(d.logit_contribution).toFixed(2)}
              </span>
              <span className="bar" aria-hidden="true">
                <span
                  style={{
                    left: up ? "50%" : `${50 - w}%`,
                    width: `${w}%`,
                    background: up ? "var(--red)" : "var(--teal)",
                  }}
                />
              </span>
            </li>
          );
        })}
      </ul>
      <ModelMeta risk={risk} />
    </div>
  );
}

function ModelMeta({ risk }: { risk: RiskModel }) {
  const m = risk.model;
  return (
    <>
      <div className="meta-grid">
        <div>
          Inputs available from
          <strong className="num">{risk.features_as_of ?? "unknown"}</strong>
        </div>
        <div>
          Relative to model evaluation
          <strong>{risk.sample_period}</strong>
        </div>
        <div>
          Company in training data
          <strong>{risk.in_training_universe ? "Yes, earlier years" : "No"}</strong>
        </div>
        {m && (
          <div>
            Held-out precision-recall AUC
            <strong className="num">
              {m.test_pr_auc.toFixed(3)} (XGBoost benchmark {m.xgboost_benchmark_test_pr_auc.toFixed(3)})
            </strong>
          </div>
        )}
      </div>
      <p className="fine" style={{ marginBottom: 0 }}>
        {risk.disclaimer} <Link href="/model">See how the model was trained and tested.</Link>
      </p>
    </>
  );
}
