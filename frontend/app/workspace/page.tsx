"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import ApiStatus from "@/components/ApiStatus";
import CreditProfile from "@/components/CreditProfile";
import EvidenceRail, { type Citation } from "@/components/EvidenceRail";
import LoanLab, { type LabState } from "@/components/LoanLab";
import MemoPanel from "@/components/MemoPanel";
import Progress, { type StepKey, type StepState } from "@/components/Progress";
import RiskScreen from "@/components/RiskScreen";
import TopBar from "@/components/TopBar";
import TrendCharts from "@/components/TrendCharts";
import Link from "next/link";
import type { Analysis, Company, HistoryPoint, Resolution } from "@/lib/api";
import { api } from "@/lib/api";
import { useApiReady } from "@/lib/useApi";

export default function Workspace() {
  const apiState = useApiReady();
  const [companies, setCompanies] = useState<Company[] | null>(null);
  const [companyId, setCompanyId] = useState<string>("");
  const [fiscalYear, setFiscalYear] = useState<string>("");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [selected, setSelected] = useState("net_leverage");
  const [error, setError] = useState<string | null>(null);
  const [lab, setLab] = useState<LabState | null>(null);
  const [memoSnapshot, setMemoSnapshot] = useState<string | null>(null);
  const [citation, setCitation] = useState<Citation | null>(null);
  const [reload, setReload] = useState(0);
  // Stage 2: a company opened from search (a CIK that is not a sample) is loaded from SEC through the API first
  const [resolution, setResolution] = useState<Resolution | null>(null);
  const [resolving, setResolving] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<{ cik: string; message: string } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const onLab = useCallback((s: LabState) => setLab(s), []);

  useEffect(() => {
    if (apiState.phase !== "ready") return;
    // ?company=<id> opens a specific company; an uploaded report is listed only for the holder of its id; a CIK from
    // search is fetched from SEC by the server (never by the browser) before the credit file opens
    const wanted = new URLSearchParams(window.location.search).get("company");
    const cik = wanted && /^\d{10}$/.test(wanted) ? wanted : null;
    let live = true;
    (async () => {
      setLoadError(null);
      let include: string | null = wanted?.startsWith("doc") ? wanted : null;
      if (cik) {
        const samples = await api.companies();
        if (!samples.some((c) => c.company_id === cik)) {
          setResolving(cik);
          try {
            const r = await api.resolveCompany(cik);
            if (!live) return;
            setResolution(r);
            if (r.outcome === "no_supported_statements" || !r.company) return;   // nothing to open; say why
            include = cik;
          } catch (e) {
            if (live) setLoadError({ cik, message: (e as Error).message });
            return;
          } finally {
            if (live) setResolving(null);
          }
        }
      }
      const cs = await api.companies(include);
      if (!live) return;
      const real = cs.filter((c) => !c.synthetic);
      const list = real.length ? real : cs;
      if (!list.length) throw new Error("No companies are available.");
      setCompanies(list);
      const first = list.find((c) => c.company_id === wanted) ?? list[0];
      if (wanted && first.company_id !== wanted) {
        setError("That uploaded report is no longer available (uploads are deleted after 24 hours). Showing a sample company instead.");
      }
      setCompanyId(first.company_id);
      setFiscalYear(first.fiscal_years[first.fiscal_years.length - 1]);
    })().catch((e) => live && setError(`Could not load the company list: ${(e as Error).message}`));
    return () => {
      live = false;
    };
  }, [apiState.phase, attempt]);

  useEffect(() => {
    if (!companyId || !fiscalYear) return;
    let live = true;
    setAnalysis(null);
    setCitation(null);
    setLab(null);
    setMemoSnapshot(null);
    Promise.all([api.analysis(companyId, fiscalYear), api.history(companyId)])
      .then(([a, h]) => {
        if (!live) return;
        setAnalysis(a);
        setHistory(h);
        setError(null);
      })
      .catch((e) => live && setError(`Could not load the credit file: ${(e as Error).message}`));
    return () => {
      live = false;
    };
  }, [companyId, fiscalYear, reload]);

  const changeCompany = (id: string) => {
    const c = companies?.find((x) => x.company_id === id);
    if (resolution?.company?.company_id !== id) setResolution(null);
    setCompanyId(id);
    if (c) setFiscalYear(c.fiscal_years[c.fiscal_years.length - 1]);
    const url = new URL(window.location.href);
    url.searchParams.set("company", id);
    window.history.replaceState(null, "", url);
  };

  const steps = useMemo(() => {
    const s: Record<StepKey, StepState> = { company: "todo", financials: "todo", screen: "todo", lab: "todo", memo: "todo" };
    if (companyId) s.company = "done";
    if (analysis) {
      s.financials = "done";
      s.screen = analysis.risk_model.status === "scored" ? "done" : "blocked";
      if (!analysis.scorable) {
        s.lab = "blocked";
        s.memo = "blocked";
      } else if (lab?.status === "current") s.lab = "done";
      if (memoSnapshot) s.memo = lab?.snapshotId && memoSnapshot === lab.snapshotId ? "done" : "stale";
    }
    const first = (Object.keys(s) as StepKey[]).find((k) => s[k] === "todo");
    if (first) s[first] = "current";
    return s;
  }, [companyId, analysis, lab, memoSnapshot]);

  const ev = analysis?.evidence.revenue;
  const uploaded = analysis?.source === "Uploaded annual report";
  return (
    <>
      <TopBar
        active="workspace"
        companies={companies ?? undefined}
        companyId={companyId}
        onCompany={changeCompany}
        fiscalYear={fiscalYear}
        onFiscalYear={setFiscalYear}
      />
      <main className="page" id="top">
        <ApiStatus state={apiState} onRetry={apiState.retry} />
        {error && (
          <div className="notice error" role="alert" style={{ marginBottom: 16 }}>
            {error}{" "}
            <button type="button" className="link" onClick={() => (companies ? setReload((r) => r + 1) : apiState.retry())}>
              Try again
            </button>
          </div>
        )}
        {resolving && (
          <p className="skeleton" role="status">
            <span className="spinner" aria-hidden="true" />
            Loading CIK {resolving} from SEC EDGAR (filings, XBRL financial data and identity record)…
          </p>
        )}
        {loadError && (
          <div className="sheet start-card sec-outcome" role="alert">
            <h1>This company could not be loaded</h1>
            <p>{loadError.message}</p>
            <p className="fine">Nothing has been estimated or substituted. The sample companies and upload keep working.</p>
            <div className="row-actions">
              <button type="button" className="btn" onClick={() => setAttempt((a) => a + 1)}>Try again</button>
              <Link className="btn ghost" href="/">Back to search</Link>
            </div>
          </div>
        )}
        {resolution?.outcome === "no_supported_statements" && (
          <div className="sheet start-card sec-outcome" role="status" data-outcome="no_supported_statements">
            <h1>No supported financial statements</h1>
            <p>{resolution.message}</p>
            {resolution.sic_description && <p className="fine">SEC industry: {resolution.sic_description} (SIC {resolution.sic}).</p>}
            <div className="row-actions">
              <Link className="btn" href="/">Search another company</Link>
              <Link className="btn ghost" href="/upload">Upload an annual report</Link>
            </div>
          </div>
        )}
        {apiState.phase === "ready" && !analysis && !error && !resolving && !loadError && resolution?.outcome !== "no_supported_statements" && (
          <p className="skeleton" role="status">
            <span className="spinner" aria-hidden="true" />
            Loading the credit file…
          </p>
        )}
        {analysis && (
          <>
            <div className="workspace-progress">
              <Progress states={steps} />
            </div>
            <div className="file-head">
              <h1>{analysis.company_name}</h1>
              <p className="num">
                Fiscal year ending {analysis.fiscal_year_end} · {analysis.currency} millions ·{" "}
                {uploaded
                  ? `uploaded annual report reviewed ${ev?.filed ?? ""}`
                  : `SEC XBRL${ev ? `, ${ev.form} filed ${ev.filed}` : ""}`}
                {uploaded && analysis.sec_check ? ` · ${analysis.sec_check}` : ""}
              </p>
            </div>
            {resolution?.company?.company_id === analysis.company_id && (
              <div className={`notice sec-banner ${resolution.outcome}`} role="status" data-outcome={resolution.outcome}>
                <strong>
                  {resolution.outcome === "full"
                    ? "Loaded from SEC EDGAR"
                    : resolution.outcome === "partial"
                      ? "Loaded from SEC EDGAR · some metrics unavailable"
                      : "Loaded from SEC EDGAR · neural stress screen withheld"}
                </strong>{" "}
                {resolution.message}
                {resolution.retrieved_at ? ` Retrieved ${resolution.retrieved_at}.` : ""}
              </div>
            )}
            {(analysis.unavailable_inputs?.length ?? 0) > 0 && (
              <div className="notice" style={{ marginBottom: 20 }}>
                Marked unavailable during review and not used in any calculation: {analysis.unavailable_inputs!.join(", ")}.
              </div>
            )}
            <div className="workspace">
              <div>
                <section className="block" aria-labelledby="h-profile">
                  <h2 id="h-profile">Financials</h2>
                  <p className="lede">
                    Every figure comes from {uploaded ? "the reviewed annual report" : "the company's 10-K filings"} and a versioned formula.
                    Grey dots mark ratios that are undefined, amber dots mark approximations or qualified values.
                  </p>
                  <CreditProfile analysis={analysis} history={history} selected={selected} onSelect={setSelected} />
                </section>

                <section className="block" aria-labelledby="h-trends">
                  <h2 id="h-trends">Trends</h2>
                  <TrendCharts history={history} upto={analysis.fiscal_year_end} currency={analysis.currency} />
                </section>

                <section className="block" aria-labelledby="h-risk">
                  <h2 id="h-risk">Neural screen</h2>
                  <p className="lede">
                    A next-FY accounting-stress screen: a trained network estimates the chance that next year&apos;s accounts show at least
                    two of EBIT / interest below 1.5x, debt / EBITDA above 5x, or negative operating cash flow. It is not a probability of
                    default.
                  </p>
                  <RiskScreen risk={analysis.risk_model} fiscalYearEnd={analysis.fiscal_year_end} />
                </section>

                <section className="block" aria-labelledby="h-lab">
                  <h2 id="h-lab">Loan lab</h2>
                  <p className="lede">
                    Add the proposed facility, then stress it. Base, downside and severe cases are fixed for comparability; your case
                    follows the sliders. These are deterministic calculations, separate from the neural screen above, which the sliders
                    never change. Each set of inputs gets a snapshot id that the memo and its PDF carry.
                  </p>
                  <LoanLab
                    key={`${analysis.company_id}|${analysis.fiscal_year_end}`}
                    companyId={analysis.company_id}
                    fiscalYear={analysis.fiscal_year_end}
                    reportingCurrency={analysis.currency}
                    blocked={!analysis.scorable}
                    onState={onLab}
                  />
                </section>

                <section className="block" aria-labelledby="h-memo">
                  <h2 id="h-memo">Committee memo</h2>
                  <p className="lede">
                    A draft for the credit committee built from everything above, using the current loan lab snapshot. Each number is
                    inserted by the engines and cited; select a citation to see its source, or edit a sentence and it is checked again.
                  </p>
                  <MemoPanel
                    key={`${analysis.company_id}|${analysis.fiscal_year_end}`}
                    companyId={analysis.company_id}
                    fiscalYear={analysis.fiscal_year_end}
                    lab={lab}
                    blocked={!analysis.scorable}
                    onCite={setCitation}
                    onMemo={setMemoSnapshot}
                  />
                </section>
              </div>
              <EvidenceRail analysis={analysis} selected={selected} citation={citation} />
            </div>
          </>
        )}
      </main>
    </>
  );
}
