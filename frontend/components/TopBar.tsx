"use client";

import Link from "next/link";
import type { Company } from "@/lib/api";

type Props = {
  active: "start" | "workspace" | "model" | "upload";
  companies?: Company[];
  companyId?: string;
  onCompany?: (id: string) => void;
  fiscalYear?: string;
  onFiscalYear?: (fye: string) => void;
};

export default function TopBar({ active, companies, companyId, onCompany, fiscalYear, onFiscalYear }: Props) {
  const company = companies?.find((c) => c.company_id === companyId);
  return (
    <header className="topbar">
      <Link href="/" className="brand">
        Credit<span>Lens</span>
      </Link>
      <nav aria-label="Main">
        <Link href="/" aria-current={active === "start" ? "page" : undefined}>
          Start
        </Link>
        <Link href="/workspace" aria-current={active === "workspace" ? "page" : undefined}>
          Workspace
        </Link>
        <Link href="/upload" aria-current={active === "upload" ? "page" : undefined}>
          Upload report
        </Link>
        <Link href="/model" aria-current={active === "model" ? "page" : undefined}>
          Model X-Ray
        </Link>
      </nav>
      {companies && onCompany && (
        <label>
          <span className="sr-only">Company</span>
          <select value={companyId} onChange={(e) => onCompany(e.target.value)}>
            {companies.map((c) => (
              <option key={c.company_id} value={c.company_id}>
                {c.name}
                {c.synthetic ? " (synthetic)" : ""}
              </option>
            ))}
          </select>
        </label>
      )}
      {company && onFiscalYear && (
        <label>
          <span className="sr-only">Fiscal year</span>
          <select value={fiscalYear} onChange={(e) => onFiscalYear(e.target.value)}>
            {[...company.fiscal_years].reverse().map((fy) => (
              <option key={fy} value={fy}>
                FY ending {fy}
              </option>
            ))}
          </select>
        </label>
      )}
      <span className="review-tag">Analyst review required</span>
    </header>
  );
}
