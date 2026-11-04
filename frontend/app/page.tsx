"use client";

import { useEffect, useState } from "react";
import CreditProfile from "@/components/CreditProfile";
import EvidenceRail from "@/components/EvidenceRail";
import LoanLab from "@/components/LoanLab";
import RiskScreen from "@/components/RiskScreen";
import TopBar from "@/components/TopBar";
import TrendCharts from "@/components/TrendCharts";
import type { Analysis, Company, HistoryPoint } from "@/lib/api";
import { API_URL, api } from "@/lib/api";

export default function Workspace() {
  const [companies, setCompanies] = useState<Company[] | null>(null);
  const [companyId, setCompanyId] = useState<string>("");
  const [fiscalYear, setFiscalYear] = useState<string>("");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [selected, setSelected] = useState("net_leverage");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .companies()
      .then((cs) => {
        const real = cs.filter((c) => !c.synthetic);
        const list = real.length ? real : cs;
        setCompanies(list);
        const first = list[0];
        setCompanyId(first.company_id);
        setFiscalYear(first.fiscal_years[first.fiscal_years.length - 1]);
      })
      .catch((e) => setError(`Could not reach the CreditLens API at ${API_URL}: ${e.message}. It may be waking up; reload in a minute.`));
  }, []);

  useEffect(() => {
    if (!companyId || !fiscalYear) return;
    setAnalysis(null);
    Promise.all([api.analysis(companyId, fiscalYear), api.history(companyId)])
      .then(([a, h]) => {
        setAnalysis(a);
        setHistory(h);
        setError(null);
      })
      .catch((e) => setError(e.message));
  }, [companyId, fiscalYear]);

  const changeCompany = (id: string) => {
    const c = companies?.find((x) => x.company_id === id);
    setCompanyId(id);
    if (c) setFiscalYear(c.fiscal_years[c.fiscal_years.length - 1]);
  };

  const ev = analysis?.evidence.revenue;
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
      <main className="page">
        {error && <div className="notice error">{error}</div>}
        {!analysis && !error && <p className="skeleton">Loading the credit file…</p>}
        {analysis && (
          <>
            <div className="file-head">
              <h1>{analysis.company_name}</h1>
              <p className="num">
                Fiscal year ending {analysis.fiscal_year_end}
                {ev ? `, from the ${ev.form} filed ${ev.filed}` : ""}. SEC XBRL data, {analysis.currency} millions.
              </p>
            </div>
            <div className="workspace">
              <div>
                <section className="block" aria-labelledby="h-profile">
                  <h2 id="h-profile">Credit profile</h2>
                  <p className="lede">
                    Every figure comes from the company&apos;s 10-K filings and a versioned formula. Grey dots mark ratios that are
                    undefined, amber dots mark approximations.
                  </p>
                  <CreditProfile analysis={analysis} history={history} selected={selected} onSelect={setSelected} />
                </section>

                <section className="block" aria-labelledby="h-trends">
                  <h2 id="h-trends">Trends</h2>
                  <TrendCharts history={history} upto={analysis.fiscal_year_end} />
                </section>

                <section className="block" aria-labelledby="h-risk">
                  <h2 id="h-risk">Neural stress screen</h2>
                  <p className="lede">
                    A trained network estimates the chance that next year&apos;s accounts show financial stress: at least two of EBIT
                    below 1.5x interest, debt above 5x EBITDA, or negative operating cash flow.
                  </p>
                  <RiskScreen risk={analysis.risk_model} />
                </section>

                <section className="block" aria-labelledby="h-lab">
                  <h2 id="h-lab">Loan lab</h2>
                  <p className="lede">
                    Add the proposed facility, then stress it. Base, downside and severe cases are fixed for comparability; your case
                    follows the sliders. Every number is recalculated by the API.
                  </p>
                  <LoanLab
                    key={analysis.company_id}
                    companyId={analysis.company_id}
                    fiscalYear={analysis.fiscal_year_end}
                    reportingCurrency={analysis.currency}
                    blocked={!analysis.scorable}
                  />
                </section>
              </div>
              <EvidenceRail analysis={analysis} selected={selected} />
            </div>
          </>
        )}
      </main>
    </>
  );
}
