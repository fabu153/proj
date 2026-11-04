"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import ApiStatus from "@/components/ApiStatus";
import Progress from "@/components/Progress";
import TopBar from "@/components/TopBar";
import type { Company } from "@/lib/api";
import { api, fyLabel } from "@/lib/api";
import { useApiReady } from "@/lib/useApi";

export default function Start() {
  const apiState = useApiReady();
  const [companies, setCompanies] = useState<Company[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (apiState.phase !== "ready") return;
    api
      .companies()
      .then((cs) => setCompanies(cs.filter((c) => !c.synthetic).length ? cs.filter((c) => !c.synthetic) : cs))
      .catch((e) => setError((e as Error).message));
  }, [apiState.phase]);

  return (
    <>
      <TopBar active="start" />
      <main className="page start">
        <div className="start-head">
          <h1>Evidence-linked credit analysis</h1>
          <p>
            Pick a company, check where every figure comes from, read a trained next-FY accounting-stress screen, stress a proposed
            loan, and draft a cited memo for the credit committee.
          </p>
        </div>
        <Progress states={{ company: "current", financials: "todo", screen: "todo", lab: "todo", memo: "todo" }} />

        <div className="start-grid">
          <section className="sheet start-card" aria-labelledby="h-sample">
            <h2 id="h-sample">Explore a sample company</h2>
            <p className="fine">Three U.S. issuers with figures taken from their SEC 10-K XBRL filings, including a stressed borrower.</p>
            <ApiStatus state={apiState} onRetry={apiState.retry} />
            {error && (
              <div className="notice error" role="alert">
                {error}{" "}
                <button type="button" className="link" onClick={apiState.retry}>
                  Try again
                </button>
              </div>
            )}
            {apiState.phase === "ready" && !companies && !error && <p className="fine" role="status">Loading the sample companies…</p>}
            {companies && (
              <ul className="company-list">
                {companies.map((c) => (
                  <li key={c.company_id}>
                    <Link href={`/workspace?company=${c.company_id}`}>
                      <strong>{c.name}</strong>
                      <span className="fine">
                        {c.fiscal_years.length} fiscal years, latest {fyLabel(c.fiscal_years[c.fiscal_years.length - 1])}
                        {c.last_filed ? `, filed ${c.last_filed}` : ""}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="sheet start-card" aria-labelledby="h-upload">
            <h2 id="h-upload">Upload a public annual report</h2>
            <p className="fine">
              A text-based PDF of a public company&apos;s financial statements. You confirm the currency, units and year-end and review
              each extracted figure before anything is analysed. The PDF itself is never stored, and the extracted figures are deleted
              after 24 hours.
            </p>
            <Link className="btn" href="/upload">
              Upload a report
            </Link>
            <p className="fine">Use public filings only. Do not upload confidential or client documents.</p>
          </section>
        </div>
      </main>
    </>
  );
}
