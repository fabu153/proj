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
  rejected: "Rejected by you",
  manual: "Entered by you",
  unavailable: "Marked unavailable",
};
const SCALE_FACTOR: Record<string, number> = { units: 1, thousands: 1e3, millions: 1e6, billions: 1e9 };
const n1 = (v: number) => v.toLocaleString("en-US", { maximumFractionDigits: 1 });
/** Stored values are in base currency units once the scale is confirmed, and as printed before that. */
const shownValue = (v: number | null, scaled: boolean) => (v === null ? "n/a" : scaled ? n1(v / 1e6) : v.toLocaleString("en-US"));
const effective = (f: Fact) => (f.status === "corrected" ? f.reviewed_value : f.status === "rejected" || f.status === "unavailable" ? null : f.value);
const isAccepted = (f: Fact) => ["auto_accepted", "accepted", "corrected", "manual"].includes(f.status);

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
          <p>Text-based PDF of a public company&apos;s financial statements. The file itself is not stored.</p>
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
              {busy && (
                <p className="fine" role="status">
                  <span className="spinner" aria-hidden="true" />
                  Reading the statements. If the service was asleep this can take up to a minute.
                </p>
              )}
              <p className="fine" style={{ marginBottom: 0 }}>
                The parser looks for the income statement, balance sheet and cash-flow statement, reads the latest two years, and
                cites the page of every figure. Scanned PDFs without a text layer are not supported. Use public filings only.
              </p>
            </form>
            {error && <div className="notice error" role="alert" style={{ marginTop: 12 }}>{error}</div>}
          </section>
        )}

        {doc && (
          <Review
            doc={doc}
            busy={busy}
            error={error}
            onReview={(f, decision, value) => run(async () => { await docs.review(f.id, decision, value); await refresh(doc.id); })}
            onMeta={(meta) => run(async () => setDoc(await docs.update(doc.id, meta)))}
            onAdd={(field, value, page) => run(async () => setDoc(await docs.addFact(doc.id, { field, value, page })))}
            onFinalize={() => run(async () => { const d = await docs.finalize(doc.id); router.push(`/workspace?company=${d.company_id}`); })}
            onDelete={() => run(async () => { await docs.remove(doc.id); setDoc(null); setFile(null); })}
          />
        )}
      </main>
    </>
  );
}

type Meta = { fiscal_year_end?: string; currency?: string; scale_label?: string };

function Review({
  doc, busy, error, onReview, onMeta, onAdd, onFinalize, onDelete,
}: {
  doc: DocumentView;
  busy: boolean;
  error: string | null;
  onReview: (f: Fact, d: "accept" | "correct" | "reject", value?: number) => void;
  onMeta: (m: Meta) => void;
  onAdd: (field: string, value: number | null, page: number | null) => void;
  onFinalize: () => void;
  onDelete: () => void;
}) {
  const final = doc.status === "finalized";
  const scaled = !!doc.scale_label;
  const ccy = doc.currency ?? "currency?";
  const order = Object.keys(FIELD_LABELS);
  const byField = (a: { field: string }, b: { field: string }) => order.indexOf(a.field) - order.indexOf(b.field);
  const latest = doc.facts.filter((f) => f.period === "t");
  const prior = doc.facts.filter((f) => f.period === "t-1");
  const present = new Set(latest.map((f) => f.field));
  const missing = [...CRITICAL].filter((k) => !present.has(k)).sort((a, b) => order.indexOf(a) - order.indexOf(b));
  const needs = latest.filter((f) => f.status === "needs_review").sort(byField);
  const excluded = latest.filter((f) => f.status === "rejected" || f.status === "unavailable").sort(byField);
  const accepted = latest.filter(isAccepted).sort(byField);
  const metaMissing = [!doc.currency, !doc.scale_label, doc.fye_inferred || !doc.fiscal_year_end].filter(Boolean).length;

  return (
    <div className="workspace">
      <div>
        <DocMeta doc={doc} busy={busy} final={final} onMeta={onMeta} />

        <section className="block">
          <h2>Check the extracted figures</h2>
          <div className="review-summary" role="status">
            <span className={missing.length + metaMissing ? "count bad" : "count"}><b>{missing.length + metaMissing}</b> missing</span>
            <span className={needs.length ? "count warn" : "count"}><b>{needs.length}</b> need review</span>
            <span className="count ok"><b>{accepted.length}</b> accepted</span>
            {excluded.length > 0 && <span className="count"><b>{excluded.length}</b> rejected or unavailable</span>}
          </div>
          <p className="lede">
            {doc.company_name}: {doc.pages} pages. Exceptions are listed first. Statements found on pages{" "}
            {Object.entries(doc.statement_pages).map(([k, v]) => `${v.join(", ") || "none"} (${k === "cashflow" ? "cash flow" : k})`).join(", ")}.
            {scaled ? ` Values in ${ccy} millions.` : " Values are shown as printed until you confirm the units."}
          </p>
          <div className="sheet scroll-x" tabIndex={0} role="region" aria-label="Extracted figures, exceptions first">
            <table className="ledger num review-table">
              <thead>
                <tr>
                  <th scope="col">Item</th>
                  <th scope="col">Latest year{scaled ? ` (${ccy} m)` : " (as printed)"}</th>
                  <th scope="col">Prior year{scaled ? "" : " (as printed)"}</th>
                  <th scope="col">Where it came from</th>
                  <th scope="col">Decision</th>
                </tr>
              </thead>
              <tbody>
                {missing.map((k) => (
                  <MissingRow key={k} field={k} ccy={ccy} scaled={scaled} final={final} busy={busy} onAdd={onAdd} />
                ))}
                {[...needs, ...excluded, ...accepted].map((f) => (
                  <FactRow
                    key={f.id}
                    f={f}
                    prior={prior.find((p) => p.field === f.field)}
                    ccy={ccy}
                    scaled={scaled}
                    final={final}
                    busy={busy}
                    onReview={onReview}
                    onAdd={onAdd}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <aside className="rail">
        <div className="sheet">
          <h3>Before analysis</h3>
          {doc.blocking.length ? (
            <ul className="warn-list">
              {doc.blocking.map((b) => (
                <li key={b}>{b}</li>
              ))}
            </ul>
          ) : (
            <p className="fine" style={{ marginTop: 0 }}>
              Currency, units and year-end are confirmed and every critical figure is accepted, entered or marked unavailable.
              {doc.unavailable_critical.length ? ` Analysed without: ${doc.unavailable_critical.join(", ")}.` : ""}
            </p>
          )}
          <button className="btn" type="button" disabled={!doc.can_finalize || busy} onClick={onFinalize} style={{ marginTop: 10 }}>
            Analyse reviewed figures
          </button>
          {error && <div className="notice error" role="alert" style={{ marginTop: 10 }}>{error}</div>}
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
            Only the extracted numbers, page references and one line of text per figure are kept, for at most 24 hours, and they are
            visible only through this upload&apos;s link. Deleting removes them now.
          </p>
          <button className="btn ghost" type="button" disabled={busy} onClick={onDelete}>
            Delete this upload
          </button>
        </div>
      </aside>
    </div>
  );
}

/** Always-visible currency, units, year-end and SEC status; anything not stated in the report must be confirmed here. */
function DocMeta({ doc, busy, final, onMeta }: { doc: DocumentView; busy: boolean; final: boolean; onMeta: (m: Meta) => void }) {
  const [fye, setFye] = useState(doc.fiscal_year_end ?? "");
  const fyeOk = !doc.fye_inferred && !!doc.fiscal_year_end;
  const secChecked = doc.sec_check?.startsWith("Checked");
  return (
    <div className="doc-meta sheet" aria-label="Report basis">
      <div className={doc.currency ? "meta-item" : "meta-item todo"}>
        <label>
          Currency {doc.currency ? <span className="ok-mark">confirmed</span> : <span className="todo-mark">not stated, choose</span>}
          <select value={doc.currency ?? ""} disabled={busy || final} onChange={(e) => e.target.value && onMeta({ currency: e.target.value })}>
            <option value="" disabled>
              Choose…
            </option>
            {doc.currencies.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
      </div>
      <div className={doc.scale_label ? "meta-item" : "meta-item todo"}>
        <label>
          Units as printed {doc.scale_label ? <span className="ok-mark">confirmed</span> : <span className="todo-mark">not stated, choose</span>}
          <select value={doc.scale_label ?? ""} disabled={busy || final} onChange={(e) => e.target.value && onMeta({ scale_label: e.target.value })}>
            <option value="" disabled>
              Choose…
            </option>
            {doc.scales.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <span className="fine">Changing this rescales every figure.</span>
      </div>
      <div className={fyeOk ? "meta-item" : "meta-item todo"}>
        <label>
          Fiscal year-end {fyeOk ? <span className="ok-mark">confirmed</span> : <span className="todo-mark">confirm</span>}
          <span className="inline-pair">
            <input type="date" value={fye} disabled={busy || final} onChange={(e) => setFye(e.target.value)} />
            {(!fyeOk || fye !== doc.fiscal_year_end) && (
              <button className="btn ghost" type="button" disabled={busy || final || !fye} onClick={() => onMeta({ fiscal_year_end: fye })}>
                Confirm
              </button>
            )}
          </span>
        </label>
      </div>
      <div className="meta-item">
        <span className="label-like">SEC cross-check</span>
        <span className={secChecked ? "ok-mark" : "todo-mark neutral"}>{doc.sec_check ?? "Not checked against SEC"}</span>
      </div>
    </div>
  );
}

function Provenance({ f, ccy, scaled }: { f: Fact; ccy: string; scaled: boolean }) {
  if (f.status === "manual") return <span className="fine">Entered by you{f.page ? `, from page ${f.page}` : ""}{f.reviewer_note ? `: ${f.reviewer_note}` : ""}</span>;
  if (f.status === "unavailable") return <span className="fine">Marked unavailable by you; it will not be used or zero-filled.</span>;
  return (
    <>
      <span className="fine">
        Extracted, page {f.page}: “{f.snippet.length > 70 ? f.snippet.slice(0, 70) + "…" : f.snippet}”
      </span>
      {f.status === "corrected" && f.value !== null && (
        <div className="fine">Corrected by you; extracted value was {shownValue(f.value, scaled)}{scaled ? ` ${ccy} m` : ""}.</div>
      )}
      {f.reasons.length > 0 && (
        <div className={f.confidence === "high" ? "fine" : "fine amber-text"}>{f.reasons.join("; ")}</div>
      )}
    </>
  );
}

/** Millions input with the explicit conversion to base units, so 1,828.7 is never stored as 1,828.7 dollars. */
function MillionsInput({ ccy, value, onChange, label }: { ccy: string; value: string; onChange: (v: string) => void; label: string }) {
  const n = parseFloat(value);
  return (
    <span className="millions">
      <input type="number" step="any" value={value} onChange={(e) => onChange(e.target.value)} aria-label={label} style={{ width: 110 }} />
      <span className="fine"> {ccy} m{!Number.isNaN(n) ? ` = ${(n * 1e6).toLocaleString("en-US", { maximumFractionDigits: 0 })} ${ccy}` : ""}</span>
    </span>
  );
}

function MissingRow({
  field, ccy, scaled, final, busy, onAdd,
}: {
  field: string;
  ccy: string;
  scaled: boolean;
  final: boolean;
  busy: boolean;
  onAdd: (field: string, value: number | null, page: number | null) => void;
}) {
  const [val, setVal] = useState("");
  const [page, setPage] = useState("");
  return (
    <tr className="missing">
      <td>
        {FIELD_LABELS[field]} <span className="fine">(critical)</span>
      </td>
      <td className="na">not found</td>
      <td className="na">n/a</td>
      <td style={{ textAlign: "left" }}>
        <span className="fine">The parser did not find this line. Enter it from the report or mark it unavailable.</span>
      </td>
      <td style={{ textAlign: "left", minWidth: 230 }}>
        {!final && (
          <form
            className="row-actions"
            onSubmit={(e) => {
              e.preventDefault();
              const n = parseFloat(val);
              if (!Number.isNaN(n)) onAdd(field, n * 1e6, page ? +page : null);
            }}
          >
            {scaled ? (
              <>
                <MillionsInput ccy={ccy} value={val} onChange={setVal} label={`${FIELD_LABELS[field]} in ${ccy} millions`} />
                <input type="number" min={1} value={page} onChange={(e) => setPage(e.target.value)} placeholder="page" aria-label="Page in the report" style={{ width: 64 }} />
                <button type="submit" className="link" disabled={busy || val === ""}>Enter</button>
              </>
            ) : (
              <span className="fine">Confirm the units above to enter a value.</span>
            )}
            <button type="button" className="link" disabled={busy} onClick={() => onAdd(field, null, null)}>Mark unavailable</button>
          </form>
        )}
      </td>
    </tr>
  );
}

function FactRow({
  f, prior, ccy, scaled, final, busy, onReview, onAdd,
}: {
  f: Fact;
  prior?: Fact;
  ccy: string;
  scaled: boolean;
  final: boolean;
  busy: boolean;
  onReview: (f: Fact, d: "accept" | "correct" | "reject", value?: number) => void;
  onAdd: (field: string, value: number | null, page: number | null) => void;
}) {
  const [editing, setEditing] = useState(false);
  const start = f.reviewed_value ?? f.value;
  const [val, setVal] = useState(start === null ? "" : String(start / 1e6));
  const shown = effective(f);
  const tone = f.status === "needs_review" ? "#7a4a06" : f.status === "rejected" || f.status === "unavailable" ? "var(--red)" : "var(--teal)";
  const manual = f.status === "manual" || f.status === "unavailable";
  return (
    <tr className={f.status === "needs_review" ? "needs-review" : f.status === "rejected" || f.status === "unavailable" ? "excluded" : ""}>
      <td>
        {FIELD_LABELS[f.field] ?? f.field}
        {CRITICAL.has(f.field) && <span className="fine"> (critical)</span>}
      </td>
      <td className={shown === null ? "na" : ""}>{shownValue(shown, scaled)}</td>
      <td>{prior ? shownValue(effective(prior), scaled) : "n/a"}</td>
      <td style={{ textAlign: "left", maxWidth: 320 }}>
        <Provenance f={f} ccy={ccy} scaled={scaled} />
      </td>
      <td style={{ textAlign: "left", minWidth: 200 }}>
        <div style={{ color: tone, fontWeight: 600, fontSize: 13 }}>{STATUS_TEXT[f.status]}</div>
        {!final && !editing && (
          <div className="row-actions">
            {!manual && f.status !== "accepted" && f.status !== "auto_accepted" && (
              <button type="button" className="link" disabled={busy} onClick={() => onReview(f, "accept")}>Accept</button>
            )}
            <button type="button" className="link" disabled={busy || !scaled} title={scaled ? undefined : "Confirm the units first"} onClick={() => setEditing(true)}>
              {manual ? "Change" : "Correct"}
            </button>
            {!manual && f.status !== "rejected" && (
              <button type="button" className="link" disabled={busy} onClick={() => onReview(f, "reject")}>Reject</button>
            )}
            {f.status === "manual" && (
              <button type="button" className="link" disabled={busy} onClick={() => onAdd(f.field, null, null)}>Mark unavailable</button>
            )}
          </div>
        )}
        {editing && (
          <form
            className="row-actions"
            onSubmit={(e) => {
              e.preventDefault();
              const n = parseFloat(val);
              if (Number.isNaN(n)) return;
              if (manual) onAdd(f.field, n * 1e6, f.page || null);
              else onReview(f, "correct", n * 1e6);
              setEditing(false);
            }}
          >
            <MillionsInput ccy={ccy} value={val} onChange={setVal} label={`Corrected ${FIELD_LABELS[f.field] ?? f.field} in ${ccy} millions`} />
            <button type="submit" className="link" disabled={busy || val === ""}>Save</button>
            <button type="button" className="link" onClick={() => setEditing(false)}>Cancel</button>
          </form>
        )}
      </td>
    </tr>
  );
}
