"use client";

import { useEffect, useMemo, useState } from "react";
import type { Covenants, Facility, ScenarioResponse, ScenarioResult, Shock, UseOfProceeds } from "@/lib/api";
import { api } from "@/lib/api";
import Ruler from "./Ruler";

const FIXED: Shock[] = [
  { name: "Base", ebitda_shock: 0, rate_shock_bps: 0 },
  { name: "Downside", ebitda_shock: -0.2, rate_shock_bps: 200 },
  { name: "Severe", ebitda_shock: -0.35, rate_shock_bps: 400 },
];
const CASE_COLORS: Record<string, string> = {
  "Before loan": "#8c9aab",
  Base: "#0f7c7a",
  Downside: "#a4650a",
  Severe: "#b3262e",
  "Your case": "#0e1b2c",
};
const USES: { value: UseOfProceeds; label: string }[] = [
  { value: "capex", label: "Capex, spent at closing" },
  { value: "acquisition", label: "Acquisition, spent at closing" },
  { value: "refinancing", label: "Refinance existing debt" },
  { value: "retained_cash", label: "Held as cash" },
];

const m1 = new Intl.NumberFormat("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const x2 = (v: number | null) => (v === null ? "n/a" : `${v.toFixed(2)}x`);
const amt = (v: number) => (v < 0 ? `(${m1.format(-v)})` : m1.format(v));

type Props = {
  companyId: string;
  fiscalYear: string;
  reportingCurrency: string;
  blocked: boolean;
  onParams?: (p: { facility: Facility; covenants: Covenants; existing_floating_share: number }) => void;
};

export default function LoanLab({ companyId, fiscalYear, reportingCurrency, blocked, onParams }: Props) {
  const [fac, setFac] = useState<Facility>({
    amount: 100,
    currency: reportingCurrency,
    coupon: 0.06,
    floating: true,
    tenor_years: 5,
    annual_amortization: 0,
    use_of_proceeds: "capex",
    fx_rate_to_reporting: null,
    fx_rate_date: null,
    refinanced_debt_rate: null,
  });
  const [floatShare, setFloatShare] = useState(0);
  const [ebitdaShock, setEbitdaShock] = useState(-0.1);
  const [rateBps, setRateBps] = useState(100);
  const [cov, setCov] = useState<Covenants>({ max_net_leverage: 3.5, min_ebitda_interest_cover: 3.0 });
  const [res, setRes] = useState<ScenarioResponse | null>(null);
  const [before, setBefore] = useState<ScenarioResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const fxNeeded = fac.currency !== reportingCurrency;
  const body = useMemo(
    () => ({
      company_id: companyId,
      fiscal_year_end: fiscalYear,
      facility: { ...fac, fx_rate_to_reporting: fxNeeded ? fac.fx_rate_to_reporting : null },
      shocks: [...FIXED, { name: "Your case", ebitda_shock: ebitdaShock, rate_shock_bps: rateBps }],
      covenants: cov,
      existing_floating_share: floatShare,
    }),
    [companyId, fiscalYear, fac, fxNeeded, ebitdaShock, rateBps, cov, floatShare],
  );

  useEffect(() => {
    onParams?.({ facility: body.facility, covenants: body.covenants, existing_floating_share: body.existing_floating_share });
  }, [body, onParams]);

  useEffect(() => {
    if (blocked) return;
    let live = true;
    const t = setTimeout(async () => {
      setBusy(true);
      try {
        const [withLoan, statusQuo] = await Promise.all([
          api.scenarios(body),
          api.scenarios({ ...body, facility: null as unknown as Facility, shocks: [{ name: "Before loan", ebitda_shock: 0, rate_shock_bps: 0 }] }),
        ]);
        if (!live) return;
        setRes(withLoan);
        setBefore(statusQuo.results[0]);
        setError(null);
      } catch (e) {
        if (live) setError((e as Error).message);
      } finally {
        if (live) setBusy(false);
      }
    }, 250);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [body, blocked]);

  if (blocked) {
    return <div className="notice error">Loan scenarios are blocked until the data-check failures on the right are resolved.</div>;
  }

  const set = <K extends keyof Facility>(k: K, v: Facility[K]) => setFac((f) => ({ ...f, [k]: v }));
  const cases = res ? [before, ...res.results].filter(Boolean) as ScenarioResult[] : [];
  const yours = res?.results.find((r) => r.name === "Your case");

  return (
    <div className="sheet lab">
      <form className="controls" onSubmit={(e) => e.preventDefault()} aria-label="Loan and stress assumptions">
        <fieldset>
          <legend>Proposed facility</legend>
          <div className="inline">
            <Field label="Amount (m)">
              <input type="number" min={1} step={5} value={fac.amount} onChange={(e) => set("amount", Math.max(1, +e.target.value))} />
            </Field>
            <Field label="Currency">
              <select value={fac.currency} onChange={(e) => set("currency", e.target.value)}>
                {Array.from(new Set([reportingCurrency, "EUR", "USD", "CHF"])).map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </Field>
          </div>
          {fxNeeded && (
            <div className="inline">
              <Field label={`${reportingCurrency} per 1 ${fac.currency}`}>
                <input
                  type="number"
                  step={0.0001}
                  min={0}
                  placeholder="e.g. spot rate"
                  value={fac.fx_rate_to_reporting ?? ""}
                  onChange={(e) => set("fx_rate_to_reporting", e.target.value ? +e.target.value : null)}
                />
              </Field>
              <Field label="Rate date">
                <input type="text" placeholder="YYYY-MM-DD" value={fac.fx_rate_date ?? ""} onChange={(e) => set("fx_rate_date", e.target.value || null)} />
              </Field>
            </div>
          )}
          <Field label="Use of proceeds">
            <select value={fac.use_of_proceeds} onChange={(e) => set("use_of_proceeds", e.target.value as UseOfProceeds)}>
              {USES.map((u) => (
                <option key={u.value} value={u.value}>
                  {u.label}
                </option>
              ))}
            </select>
          </Field>
          <div className="inline">
            <Field label="All-in coupon (%)">
              <input type="number" step={0.25} min={0} value={+(fac.coupon * 100).toFixed(2)} onChange={(e) => set("coupon", +e.target.value / 100)} />
            </Field>
            <Field label="Tenor (years)">
              <input type="number" min={1} max={30} value={fac.tenor_years} onChange={(e) => set("tenor_years", Math.max(1, +e.target.value))} />
            </Field>
          </div>
          <Field label="Annual repayment (m, 0 = bullet)">
            <input type="number" min={0} step={5} value={fac.annual_amortization} onChange={(e) => set("annual_amortization", Math.max(0, +e.target.value))} />
          </Field>
          <label className="toggle">
            <input type="checkbox" checked={fac.floating} onChange={(e) => set("floating", e.target.checked)} /> Floating rate (reprices with rate shock)
          </label>
        </fieldset>

        <fieldset>
          <legend>Your stress case</legend>
          <Field label={<>EBITDA change <span className="value num">{Math.round(ebitdaShock * 100)}%</span></>}>
            <input type="range" min={-50} max={20} step={5} value={Math.round(ebitdaShock * 100)} onChange={(e) => setEbitdaShock(+e.target.value / 100)} />
          </Field>
          <Field label={<>Rate shock <span className="value num">+{rateBps} bp</span></>}>
            <input type="range" min={0} max={500} step={25} value={rateBps} onChange={(e) => setRateBps(+e.target.value)} />
          </Field>
          <Field label={<>Existing debt at floating rate <span className="value num">{Math.round(floatShare * 100)}%</span></>}>
            <input type="range" min={0} max={100} step={10} value={floatShare * 100} onChange={(e) => setFloatShare(+e.target.value / 100)} />
          </Field>
        </fieldset>

        <fieldset>
          <legend>Covenants to test</legend>
          <div className="inline">
            <Field label="Max net leverage (x)">
              <input type="number" step={0.25} min={0} value={cov.max_net_leverage ?? ""} onChange={(e) => setCov((c) => ({ ...c, max_net_leverage: e.target.value ? +e.target.value : null }))} />
            </Field>
            <Field label="Min EBITDA cover (x)">
              <input type="number" step={0.25} min={0} value={cov.min_ebitda_interest_cover ?? ""} onChange={(e) => setCov((c) => ({ ...c, min_ebitda_interest_cover: e.target.value ? +e.target.value : null }))} />
            </Field>
          </div>
        </fieldset>
      </form>

      <div className="results" aria-live="polite" aria-busy={busy}>
        {error ? (
          <div className="notice">
            {fxNeeded && !fac.fx_rate_to_reporting
              ? `Enter a ${reportingCurrency} per ${fac.currency} rate and its date, or switch the facility to ${reportingCurrency}. Currencies are never mixed silently.`
              : error}
          </div>
        ) : !res ? (
          <p className="skeleton">Calculating scenarios…</p>
        ) : (
          <>
            <h4>Covenant headroom</h4>
            {cov.max_net_leverage !== null && (
              <CovenantRuler cases={cases} limit={cov.max_net_leverage} kind="max" />
            )}
            {cov.min_ebitda_interest_cover !== null && (
              <CovenantRuler cases={cases} limit={cov.min_ebitda_interest_cover} kind="min" />
            )}

            <h4>Pro forma credit metrics ({reportingCurrency} millions)</h4>
            <div style={{ overflowX: "auto" }}>
              <table className="ledger num">
                <thead>
                  <tr>
                    <th scope="col">Metric</th>
                    {cases.map((c) => (
                      <th scope="col" key={c.name} style={{ color: CASE_COLORS[c.name] }}>
                        {c.name}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  <Row label="EBITDA" cases={cases} f={(c) => amt(c.ebitda)} />
                  <Row label="Gross debt" cases={cases} f={(c) => amt(c.gross_debt)} />
                  <Row label="Cash" cases={cases} f={(c) => amt(c.cash)} />
                  <Row label="Net debt" cases={cases} f={(c) => amt(c.net_debt)} />
                  <Row label="Interest expense" cases={cases} f={(c) => amt(c.interest_expense)} />
                  <Row
                    label="Net debt / EBITDA"
                    cases={cases}
                    f={(c) => x2(c.net_leverage)}
                    breach={(c) => cov.max_net_leverage !== null && (c.net_leverage === null || c.net_leverage > cov.max_net_leverage)}
                  />
                  <Row
                    label="EBITDA / interest"
                    cases={cases}
                    f={(c) => x2(c.ebitda_interest_cover)}
                    breach={(c) =>
                      cov.min_ebitda_interest_cover !== null &&
                      c.ebitda_interest_cover !== null &&
                      c.ebitda_interest_cover < cov.min_ebitda_interest_cover
                    }
                  />
                </tbody>
              </table>
            </div>

            {yours && (
              <>
                <h4>How your case was calculated</h4>
                <ol className="steps">
                  {yours.steps.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ol>
                {yours.flags.length > 0 && (
                  <p className="fine">
                    Flags: <span className="cell-breach">{yours.flags.join(", ").replace(/_/g, " ").toLowerCase()}</span>
                  </p>
                )}
              </>
            )}

            <details style={{ marginTop: 14 }}>
              <summary style={{ cursor: "pointer", fontSize: 14, fontWeight: 600 }}>Facility repayment schedule ({fac.currency} millions)</summary>
              <table className="ledger num" style={{ marginTop: 8 }}>
                <thead>
                  <tr>
                    <th scope="col">Year</th>
                    <th scope="col">Opening</th>
                    <th scope="col">Interest</th>
                    <th scope="col">Repayment</th>
                    <th scope="col">Closing</th>
                  </tr>
                </thead>
                <tbody>
                  {res.facility_schedule.map((r) => (
                    <tr key={r.year}>
                      <td>{r.year}</td>
                      <td>{amt(r.opening)}</td>
                      <td>{amt(r.interest)}</td>
                      <td>{amt(r.repayment)}</td>
                      <td>{amt(r.closing)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
            <p className="fine">{res.disclaimer} Proceeds spent on capex or acquisitions are assumed to add no EBITDA.</p>
          </>
        )}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="field">
      <label>
        {label}
        {children}
      </label>
    </div>
  );
}

function Row({ label, cases, f, breach }: { label: string; cases: ScenarioResult[]; f: (c: ScenarioResult) => string; breach?: (c: ScenarioResult) => boolean }) {
  return (
    <tr>
      <td>{label}</td>
      {cases.map((c) => (
        <td key={c.name} className={breach && breach(c) ? "cell-breach" : ""}>
          {f(c)}
        </td>
      ))}
    </tr>
  );
}

function CovenantRuler({ cases, limit, kind }: { cases: ScenarioResult[]; limit: number; kind: "max" | "min" }) {
  const vals = cases.map((c) => (kind === "max" ? c.net_leverage : c.ebitda_interest_cover));
  const hi = Math.max(limit * 1.6, ...vals.filter((v): v is number => v !== null).map((v) => v * 1.1));
  const max = Math.ceil(hi);
  const ok = "#cfe6e4";
  const bad = "#efc6c8";
  return (
    <div style={{ marginBottom: 6 }}>
      <div className="fine" style={{ color: "var(--text)" }}>
        {kind === "max" ? `Net debt / EBITDA must stay at or below ${limit.toFixed(2)}x` : `EBITDA / interest must stay at or above ${limit.toFixed(2)}x`}
      </div>
      <Ruler
        min={0}
        max={max}
        ariaLabel={kind === "max" ? "Net leverage by case against covenant" : "Interest cover by case against covenant"}
        segments={kind === "max" ? [{ to: limit, color: ok }, { to: max, color: bad }] : [{ to: limit, color: bad }, { to: max, color: ok }]}
        threshold={{ value: limit, label: `limit ${limit.toFixed(2)}x` }}
        marks={cases.map((c, i) => ({ label: c.name, value: vals[i], color: CASE_COLORS[c.name] ?? "#0e1b2c" }))}
        format={(v) => `${v.toFixed(2)}x`}
      />
    </div>
  );
}
