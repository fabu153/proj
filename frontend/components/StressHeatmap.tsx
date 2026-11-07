"use client";

import { useEffect, useState } from "react";
import type { Covenants, Facility, Grid, GridCell } from "@/lib/api";
import { api } from "@/lib/api";

type MetricKey = "net_leverage" | "ebitda_interest_cover" | "headroom_lev" | "headroom_cov";
const METRICS: { key: MetricKey; label: string; needs?: keyof Covenants }[] = [
  { key: "net_leverage", label: "Net debt / EBITDA" },
  { key: "ebitda_interest_cover", label: "EBITDA / interest" },
  { key: "headroom_lev", label: "Headroom: max net debt / EBITDA", needs: "max_net_leverage" },
  { key: "headroom_cov", label: "Headroom: min EBITDA / interest", needs: "min_ebitda_interest_cover" },
];

type Props = {
  companyId: string;
  fiscalYear: string;
  facility: Facility;
  covenants: Covenants;
  floatShare: number;
  disabled: boolean;
  current: { ebitda: number; bps: number };
  onPick: (ebitdaShock: number, rateBps: number) => void;
};

/** Stage F: a grid of EBITDA and rate shocks. Every cell is computed by the Python scenario engine (/scenarios/grid). */
export default function StressHeatmap({ companyId, fiscalYear, facility, covenants, floatShare, disabled, current, onPick }: Props) {
  const [grid, setGrid] = useState<Grid | null>(null);
  const [metric, setMetric] = useState<MetricKey>("net_leverage");
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (disabled) return;
    let live = true;
    setState("loading");
    const t = setTimeout(() => {
      api
        .grid({ company_id: companyId, fiscal_year_end: fiscalYear, facility, covenants, existing_floating_share: floatShare })
        .then((g) => {
          if (!live) return;
          setGrid(g);
          setState("ready");
        })
        .catch((e) => {
          if (!live) return;
          setError((e as Error).message);
          setState("error");
        });
    }, 300);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [companyId, fiscalYear, facility, covenants, floatShare, disabled]);

  if (disabled) return null;
  const available = METRICS.filter((m) => !m.needs || covenants[m.needs] !== null);
  const shown = available.some((m) => m.key === metric) ? metric : "net_leverage";
  const fmt = (c: GridCell) => {
    if (c.error) return "n/a";
    const v = c[shown];
    if (v === null || v === undefined) return "N/A";
    if (shown.startsWith("headroom")) return v < 0 ? `−${Math.abs(v).toFixed(2)}x` : `+${v.toFixed(2)}x`;
    return `${v.toFixed(2)}x`;
  };
  // colouring is the engine's covenant assessment for the covenant behind the displayed metric (Fix 3)
  const covKey = shown === "ebitda_interest_cover" || shown === "headroom_cov" ? "state_cov" : "state_lev";
  const cellState = (c: GridCell) => (c.error ? "err" : c[covKey] ?? (shown.startsWith("headroom") ? null : c.breach ? "breach" : null));
  const breached = (c: GridCell) => cellState(c) === "breach";
  const untestable = (c: GridCell) => cellState(c) === "not_testable";
  const tight = (c: GridCell) => {
    const h = covKey === "state_cov" ? c.headroom_cov : c.headroom_lev;
    return cellState(c) === "pass" && h != null && h < 0.5;
  };

  return (
    <section className="heatmap" aria-labelledby="h-heatmap">
      <div className="heatmap-head">
        <h4 id="h-heatmap">Stress heatmap</h4>
        <div role="radiogroup" aria-label="Metric shown in the heatmap" className="seg">
          {available.map((m) => (
            <button key={m.key} type="button" role="radio" aria-checked={shown === m.key} className={shown === m.key ? "on" : ""} onClick={() => setMetric(m.key)}>
              {m.label}
            </button>
          ))}
        </div>
      </div>
      <p className="fine" style={{ margin: "0 0 6px" }}>
        Your facility under every combination of EBITDA change and floating-rate shock. Each cell is one run of the same Python scenario
        engine as the table above. Click a cell to load it into your case.
      </p>
      {state === "error" && <div className="notice error" role="alert">The heatmap could not be calculated: {error}</div>}
      {grid && (
        <div className={`scroll-x ${state === "loading" ? "stale-results" : ""}`} tabIndex={0} role="region" aria-label="Stress heatmap" aria-busy={state === "loading"}>
          <table className="heat num">
            <caption className="sr-only">
              {available.find((m) => m.key === shown)?.label} by EBITDA change (columns) and rate shock (rows)
            </caption>
            <thead>
              <tr>
                <th scope="col"><span className="sr-only">Rate shock by EBITDA change</span><span aria-hidden="true">bp \ EBITDA</span></th>
                {grid.ebitda_shocks.map((e) => (
                  <th scope="col" key={e}>{e > 0 ? "+" : ""}{Math.round(e * 100)}%</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {grid.cells.map((row, i) => (
                <tr key={grid.rate_shocks_bps[i]}>
                  <th scope="row">+{grid.rate_shocks_bps[i]}</th>
                  {row.map((c) => {
                    const active = Math.abs(c.ebitda_shock - current.ebitda) < 1e-9 && c.rate_shock_bps === current.bps;
                    const cls = c.error ? "err" : breached(c) ? "breach" : untestable(c) ? "untestable" : tight(c) ? "tight" : "ok";
                    const why = c.reasons?.[covKey === "state_cov" ? "min_ebitda_interest_cover" : "max_net_leverage"];
                    return (
                      <td key={c.ebitda_shock}>
                        <button
                          type="button"
                          className={`cell ${cls} ${active ? "active" : ""}`}
                          aria-pressed={active}
                          title={c.error ?? `EBITDA ${Math.round(c.ebitda_shock * 100)}%, rates +${c.rate_shock_bps} bp${breached(c) ? ": covenant breached" : untestable(c) ? `: not testable (${why})` : ""}`}
                          onClick={() => onPick(c.ebitda_shock, c.rate_shock_bps)}
                        >
                          {fmt(c)}
                          {breached(c) && <span className="sr-only"> (covenant breached)</span>}
                          {untestable(c) && <span className="sr-only"> (covenant not testable)</span>}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {state === "loading" && !grid && <p className="fine" role="status"><span className="spinner" aria-hidden="true" />Calculating 42 scenarios…</p>}
      <p className="fine heat-legend">
        <span className="item"><span className="key breach" /> breach</span>
        <span className="item"><span className="key tight" /> passes, within 0.5x of the limit</span>
        <span className="item"><span className="key ok" /> passes</span>
        <span className="item"><span className="key untestable" /> not testable (ratio undefined; not a breach)</span>
        {grid ? <span className="item">loan engine v{grid.engine_version}</span> : null}
      </p>
    </section>
  );
}
