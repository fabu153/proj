"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import ApiStatus from "@/components/ApiStatus";
import CreditProfile from "@/components/CreditProfile";
import EvidenceRail from "@/components/EvidenceRail";
import LoanLab, { type LabState } from "@/components/LoanLab";
import MemoPanel from "@/components/MemoPanel";
import Progress, { type StepKey, type StepState } from "@/components/Progress";
import RiskScreen from "@/components/RiskScreen";
import TopBar from "@/components/TopBar";
import TrendCharts from "@/components/TrendCharts";
import type { Analysis, Company, HistoryPoint, PackageItem } from "@/lib/api";
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
  const [citation, setCitation] = useState<PackageItem | null>(null);
  const [reload, setReload] = useState(0);
  const onLab = useCallback((s: LabState) => setLab(s), []);

  useEffect(() => {
    if (apiState.phase !== "ready") return;
    // ?company=<id> opens a specific company; an uploaded report is listed only for the holder of its id
    const wanted = new URLSearchParams(window.location.search).get("company");
    api
      .companies(wanted?.startsWith("doc") ? wanted : null)
      .then((cs) => {
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
      })
      .catch((e) => setError(`Could not load the company list: ${(e as Error).message}`));
  }, [apiState.phase]);

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
        {apiState.phase === "ready" && !analysis && !error && (
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
                  <RiskScreen risk={analysis.risk_model} />
                </section>

                <section className="block" aria-labelledby="h-lab">
                  <h2 id="h-lab">Loan lab</h2>
                  <p className="lede">
                    Add the proposed facility, then stress it. Base, downside and severe cases are fixed for comparability; your case
                    follows the sliders. Every number is recalculated by the API, and each set of inputs gets a snapshot id that the memo
                    and its PDF carry.
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
