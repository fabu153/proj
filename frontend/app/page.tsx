"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import ApiStatus from "@/components/ApiStatus";
import CompanySearch from "@/components/CompanySearch";
import Progress from "@/components/Progress";
import TopBar from "@/components/TopBar";
import type { Company } from "@/lib/api";
import { api, fyLabel } from "@/lib/api";
import { useApiReady } from "@/lib/useApi";

const SHORT: Record<string, string> = { "0000080424": "Procter & Gamble", "0001067701": "United Rentals", "0001278027": "B&G Foods" };

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
            Find any U.S. public company or upload a report, check where every figure comes from, read a trained next-FY accounting-stress screen, stress a proposed
            loan, and draft a cited memo for the credit committee.
          </p>
        </div>
        <Progress states={{ company: "current", financials: "todo", screen: "todo", lab: "todo", memo: "todo" }} />

        <ApiStatus state={apiState} onRetry={apiState.retry} />
        <div className="start-grid">
          <section className="sheet start-card" aria-labelledby="h-search">
            <h2 id="h-search">Search a U.S. public company</h2>
            <p className="fine">
              Any SEC registrant that files U.S. GAAP financial statements in XBRL. Figures, filing dates and accession numbers come
              straight from its 10-K data at SEC EDGAR; nothing missing is estimated.
            </p>
            <CompanySearch disabled={apiState.phase !== "ready"} />
          </section>

          <section className="sheet start-card" aria-labelledby="h-upload">
            <h2 id="h-upload">Upload an annual report</h2>
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

        <section className="quick-demo" aria-labelledby="h-sample">
          <h2 id="h-sample">Quick demo</h2>
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
                    <strong>{SHORT[c.company_id] ?? c.name}</strong>
                    <span className="fine">
                      {c.fiscal_years.length} fiscal years, latest {fyLabel(c.fiscal_years[c.fiscal_years.length - 1])}
                      {c.last_filed ? `, filed ${c.last_filed}` : ""}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
          <p className="fine">Three curated issuers kept offline, including a stressed borrower: they open even if SEC is unreachable.</p>
        </section>
        <section className="sheet start-card replay-card" aria-labelledby="h-replay">
          <div>
            <h2 id="h-replay">Replay the model on held-out years</h2>
            <p className="fine">
              What could the network infer when an annual report was first published, and what happened a year later? Real 2021–25 cases
              it never saw: a correct warning, a false alarm and a miss.
            </p>
          </div>
          <Link className="btn ghost" href="/replay">Open the replay</Link>
        </section>
      </main>
    </>
  );
}
