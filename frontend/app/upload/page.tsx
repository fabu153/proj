"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import TopBar from "@/components/TopBar";
import type { DocumentView, Fact } from "@/lib/api";
import { docs } from "@/lib/api";

const FIELD_LABELS: Record<string, string> = {
  revenue: "Revenue",
  operating_income: "Operating income",
  net_income: "Net income",
  interest_expense: "Interest expense",
  depreciation_amortization: "Depreciation and amortization",
  operating_cash_flow: "Operating cash flow",
  capital_expenditures: "Capital expenditures",
  cash: "Cash and equivalents",
  short_term_borrowings: "Short-term borrowings",
  current_maturities_ltd: "Current portion of debt",
  long_term_debt: "Long-term debt",
  total_assets: "Total assets",
  total_liabilities: "Total liabilities",
  stockholders_equity: "Shareholders' equity",
  current_assets: "Current assets",
  current_liabilities: "Current liabilities",
};
const CRITICAL = new Set(["revenue", "operating_income", "interest_expense", "depreciation_amortization", "operating_cash_flow", "long_term_debt", "total_assets"]);
const STATUS_TEXT: Record<Fact["status"], string> = {
  auto_accepted: "Accepted automatically",
  needs_review: "Needs your review",
  accepted: "Accepted by you",
  corrected: "Corrected by you",
  rejected: "Rejected",
};
const m = (v: number | null) => (v === null ? "n/a" : (v / 1e6).toLocaleString("en-US", { maximumFractionDigits: 1 }));

export default function UploadPage() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [cik, setCik] = useState("");
  const [doc, setDoc] = useState<DocumentView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const refresh = (id: string) => docs.get(id).then(setDoc);

  return (
    <>
      <TopBar active="upload" />
      <main className="page">
        <div className="file-head">
          <h1>Upload an annual report</h1>
          <p>Text-based PDF of the primary financial statements. The file itself is not stored.</p>
        </div>

        {!doc && (
          <section className="block" style={{ maxWidth: 640 }}>
            <form
              className="sheet"
              style={{ padding: 20 }}
              onSubmit={(e) => {
                e.preventDefault();
                if (file) run(async () => setDoc(await docs.upload(file, name, cik)));
              }}
            >
              <div className="field">
                <label>
                  Annual report (PDF, up to 15 MB)
                  <input type="file" accept="application/pdf,.pdf" required onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
                </label>
              </div>
              <div className="inline">
                <div className="field">
                  <label>
                    Company name
                    <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="As it should appear in the memo" />
                  </label>
                </div>
                <div className="field">
                  <label>
                    SEC CIK, optional
                    <input type="text" inputMode="numeric" value={cik} onChange={(e) => setCik(e.target.value.replace(/\D/g, ""))} placeholder="Cross-checks against XBRL" />
                  </label>
                </div>
              </div>
              <button className="btn" type="submit" disabled={!file || busy}>
                {busy ? "Reading the statements…" : "Extract figures"}
              </button>
              <p className="fine" style={{ marginBottom: 0 }}>
                The parser looks for the income statement, balance sheet and cash-flow statement, reads the latest two years, and
                cites the page of every figure. Scanned PDFs without a text layer are not supported.
              </p>
            </form>
            {error && <div className="notice error" style={{ marginTop: 12 }}>{error}</div>}
          </section>
        )}

        {doc && (
          <Review
            doc={doc}
            busy={busy}
            error={error}
            onReview={(f, decision, value) => run(async () => { await docs.review(f.id, decision, value); await refresh(doc.id); })}
            onFye={(fye) => run(async () => setDoc(await docs.update(doc.id, { fiscal_year_end: fye })))}
            onFinalize={() => run(async () => { const d = await docs.finalize(doc.id); router.push(`/?company=${d.company_id}`); })}
            onDelete={() => run(async () => { await docs.remove(doc.id); setDoc(null); setFile(null); })}
          />
        )}
      </main>
    </>
  );
}

function Review({
  doc, busy, error, onReview, onFye, onFinalize, onDelete,
}: {
  doc: DocumentView;
  busy: boolean;
  error: string | null;
  onReview: (f: Fact, d: "accept" | "correct" | "reject", value?: number) => void;
  onFye: (fye: string) => void;
  onFinalize: () => void;
  onDelete: () => void;
}) {
  const [fye, setFye] = useState(doc.fiscal_year_end ?? "");
  const order = Object.keys(FIELD_LABELS);
  const latest = doc.facts.filter((f) => f.period === "t").sort((a, b) => order.indexOf(a.field) - order.indexOf(b.field));
  const prior = doc.facts.filter((f) => f.period === "t-1");
  const pending = latest.filter((f) => f.status === "needs_review").length;
  return (
    <div className="workspace">
      <div>
        <section className="block">
          <h2>Check the extracted figures</h2>
          <p className="lede">
            {doc.company_name}: {doc.pages} pages, figures in {doc.currency} {doc.scale_label}, shown below in millions. Statements found on
            pages {Object.entries(doc.statement_pages).map(([k, v]) => `${v.join(", ") || "none"} (${k === "cashflow" ? "cash flow" : k})`).join(", ")}.
          </p>
          <div className="sheet scroll-x" tabIndex={0} role="region" aria-label="Extracted figures table">
            <table className="ledger num review-table">
              <thead>
                <tr>
                  <th scope="col">Item</th>
                  <th scope="col">Latest year</th>
                  <th scope="col">Prior year</th>
                  <th scope="col">Source line</th>
                  <th scope="col">Decision</th>
                </tr>
              </thead>
              <tbody>
                {latest.map((f) => (
                  <FactRow key={f.id} f={f} prior={prior.find((p) => p.field === f.field)} final={doc.status === "finalized"} busy={busy} onReview={onReview} />
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <aside className="rail">
        <div className="sheet">
          <h3>Before analysis</h3>
          {doc.fye_inferred && (
            <div className="field">
              <label>
                Fiscal year-end (not stated on the statements)
                <input type="text" value={fye} onChange={(e) => setFye(e.target.value)} placeholder="YYYY-MM-DD" />
              </label>
              <button className="btn ghost" type="button" disabled={busy || !/^\d{4}-\d{2}-\d{2}$/.test(fye)} onClick={() => onFye(fye)}>
                Confirm year-end
              </button>
            </div>
          )}
          {doc.blocking.length ? (
            <ul className="warn-list">
              {doc.blocking.map((b) => (
                <li key={b}>{b}</li>
              ))}
            </ul>
          ) : (
            <p className="fine" style={{ marginTop: 0 }}>All critical figures are accepted. {pending ? `${pending} other items still await review.` : ""}</p>
          )}
          <button className="btn" type="button" disabled={!doc.can_finalize || busy} onClick={onFinalize} style={{ marginTop: 10 }}>
            Analyse reviewed figures
          </button>
          {error && <div className="notice error" style={{ marginTop: 10 }}>{error}</div>}
        </div>
        {doc.issues.length > 0 && (
          <div className="sheet">
            <h3>Extraction notes</h3>
            <ul className="warn-list">
              {doc.issues.map((i) => (
                <li key={i}>{i}</li>
              ))}
            </ul>
          </div>
        )}
        <div className="sheet">
          <h3>Your data</h3>
          <p className="fine" style={{ marginTop: 0 }}>
            Only the extracted numbers, page references and one line of text per figure are kept, for at most 24 hours. Deleting removes
            them now.
          </p>
          <button className="btn ghost" type="button" disabled={busy} onClick={onDelete}>
            Delete this upload
          </button>
        </div>
      </aside>
    </div>
  );
}

function FactRow({
  f, prior, final, busy, onReview,
}: {
  f: Fact;
  prior?: Fact;
  final: boolean;
  busy: boolean;
  onReview: (f: Fact, d: "accept" | "correct" | "reject", value?: number) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(String((f.reviewed_value ?? f.value) / 1e6));
  const shown = f.status === "corrected" ? f.reviewed_value : f.status === "rejected" ? null : f.value;
  const tone = f.status === "needs_review" ? "var(--amber)" : f.status === "rejected" ? "var(--red)" : "var(--teal)";
  return (
    <tr className={f.status === "needs_review" ? "needs-review" : ""}>
      <td>
        {FIELD_LABELS[f.field] ?? f.field}
        {CRITICAL.has(f.field) && <span className="fine"> (critical)</span>}
      </td>
      <td className={shown === null ? "na" : ""}>{m(shown)}</td>
      <td>{prior ? m(prior.status === "corrected" ? prior.reviewed_value : prior.value) : "n/a"}</td>
      <td style={{ textAlign: "left", maxWidth: 300 }}>
        <span className="fine">
          Page {f.page}: “{f.snippet.length > 70 ? f.snippet.slice(0, 70) + "…" : f.snippet}”
        </span>
        {f.reasons.length > 0 && <div className="fine" style={{ color: f.confidence === "high" ? "var(--slate)" : "var(--amber)" }}>{f.reasons.join("; ")}</div>}
      </td>
      <td style={{ textAlign: "left", minWidth: 190 }}>
        <div style={{ color: tone, fontWeight: 600, fontSize: 13 }}>{STATUS_TEXT[f.status]}</div>
        {!final && !editing && (
          <div className="row-actions">
            {f.status !== "accepted" && f.status !== "auto_accepted" && (
              <button type="button" className="link" disabled={busy} onClick={() => onReview(f, "accept")}>Accept</button>
            )}
            <button type="button" className="link" disabled={busy} onClick={() => setEditing(true)}>Correct</button>
            {f.status !== "rejected" && (
              <button type="button" className="link" disabled={busy} onClick={() => onReview(f, "reject")}>Reject</button>
            )}
          </div>
        )}
        {editing && (
          <form
            className="row-actions"
            onSubmit={(e) => {
              e.preventDefault();
              const n = parseFloat(val);
              if (!Number.isNaN(n)) {
                onReview(f, "correct", n * 1e6);
                setEditing(false);
              }
            }}
          >
            <input type="number" step="any" value={val} onChange={(e) => setVal(e.target.value)} aria-label="Corrected value in millions" style={{ width: 110 }} />
            <button type="submit" className="link" disabled={busy}>Save</button>
            <button type="button" className="link" onClick={() => setEditing(false)}>Cancel</button>
          </form>
        )}
      </td>
    </tr>
  );
}
