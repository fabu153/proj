"use client";

import { useEffect, useState } from "react";
import type { LabState } from "./LoanLab";
import type { Memo, PackageItem, Sentence } from "@/lib/api";
import { memos } from "@/lib/api";

type Props = {
  companyId: string;
  fiscalYear: string;
  lab: LabState | null;
  blocked: boolean;
  onCite: (item: PackageItem) => void;
  onMemo?: (snapshotId: string | null) => void;
};

export default function MemoPanel({ companyId, fiscalYear, lab, blocked, onCite, onMemo }: Props) {
  const [memo, setMemo] = useState<Memo | null>(null);
  const [writer, setWriter] = useState<{ writer: string; llm_configured: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    memos.config().then(setWriter).catch(() => setWriter(null));
  }, []);
  useEffect(() => onMemo?.(memo?.snapshot?.id ?? null), [memo, onMemo]);

  const labReady = lab?.status === "current" && !!lab.snapshotId;
  const memoSnap = memo?.snapshot?.id ?? null;
  // a memo is current only when it was built from exactly the inputs the loan table now shows
  const outdated = !!memo && labReady && memoSnap !== lab!.snapshotId;

  const draft = async () => {
    if (!lab || !labReady) return;
    setBusy(true);
    setError(null);
    try {
      const m = await memos.create({ company_id: companyId, fiscal_year_end: fiscalYear, ...lab.params });
      if (m.snapshot?.id !== lab.snapshotId) {
        // the server rebuilt the case from the same inputs; a different id means the inputs drifted in transit
        setError(`The memo was built from snapshot ${m.snapshot?.id}, but the loan lab shows ${lab.snapshotId}. Regenerate.`);
      }
      setMemo(m);
    } catch (e) {
      setError(`The memo could not be drafted: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  if (blocked) {
    return <div className="notice error">The memo is blocked until the data-check failures on the right are resolved.</div>;
  }

  // citation numbers in order of first appearance, as in the PDF appendix
  const order: string[] = [];
  memo?.sections.forEach((s) => s.sentences.forEach((x) => x.refs.forEach((r) => !order.includes(r) && order.push(r))));

  const waiting = !labReady
    ? lab?.status === "error"
      ? "Fix the loan lab inputs first: the memo is built from the loan lab's current case."
      : "Waiting for the loan lab to finish calculating…"
    : null;

  return (
    <div className="sheet memo">
      <div className="memo-bar">
        <button className="btn" type="button" onClick={draft} disabled={busy || !labReady}>
          {busy ? "Drafting…" : memo ? (outdated ? "Regenerate with the current loan lab inputs" : "Redraft") : "Draft credit memo"}
        </button>
        {memo && !outdated && (
          <a className="btn ghost" href={memos.pdfUrl(memo.id)} target="_blank" rel="noreferrer">
            Download PDF
          </a>
        )}
        <span className="fine">
          {writer?.llm_configured ? `Written by ${writer.writer}; ` : "Written from templates (no language model configured); "}
          every number is inserted from the engines.
        </span>
      </div>
      {busy && (
        <p className="fine" role="status">
          <span className="spinner" aria-hidden="true" />
          Drafting from snapshot <code className="snap">{lab?.snapshotId}</code>…
        </p>
      )}
      {!memo && waiting && <p className="fine" role="status">{waiting}</p>}
      {error && <div className="notice error" role="alert">{error}</div>}
      {outdated && (
        <div className="notice outdated" role="status">
          <strong>Outdated — regenerate.</strong>
          <span>
            This memo describes snapshot <code className="snap">{memoSnap}</code>; the loan lab now shows{" "}
            <code className="snap">{lab!.snapshotId}</code>. Its numbers and PDF no longer match the table.
          </span>
          <button type="button" className="link" onClick={draft} disabled={busy}>
            Regenerate now
          </button>
        </div>
      )}
      {memo && lab?.status === "calculating" && <p className="fine" role="status">Loan lab recalculating; checking whether this memo is still current…</p>}
      {memo && (
        <div className={outdated ? "stale-results" : undefined} aria-hidden={outdated || undefined}>
          <p className="fine" style={{ margin: "4px 0 12px" }}>
            {memo.summary.sentences} sentences citing {memo.summary.cited_items} sourced items.{" "}
            {memo.summary.flagged
              ? `${memo.summary.flagged} sentence${memo.summary.flagged > 1 ? "s" : ""} failed the checks and will be left out of the PDF until fixed.`
              : "All sentences passed the evidence checks."}
            {memo.writer_note ? ` ${memo.writer_note}.` : ""}
          </p>
          {memo.sections.map((sec) =>
            sec.sentences.length ? (
              <section key={sec.key} className="memo-section">
                <h3>{sec.title}</h3>
                <p>
                  {sec.sentences.map((s, i) => (
                    <SentenceView
                      first={i === 0}
                      key={s.id}
                      s={s}
                      order={order}
                      memo={memo}
                      onCite={onCite}
                      onSave={async (text) => setMemo(await memos.edit(memo.id, s.id, text))}
                    />
                  ))}
                </p>
              </section>
            ) : null,
          )}
          <p className="fine">
            Snapshot <code className="snap">{memoSnap ?? "n/a"}</code> · memo {memo.id.slice(0, 12)} · package{" "}
            {memo.package_sha256.slice(0, 12)} · generated {memo.created_at}. The PDF prints the full assumptions of this snapshot.
            Select a citation number to see its source.
          </p>
        </div>
      )}
    </div>
  );
}

function SentenceView({
  first, s, order, memo, onCite, onSave,
}: {
  first: boolean;
  s: Sentence;
  order: string[];
  memo: Memo;
  onCite: (i: PackageItem) => void;
  onSave: (t: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(s.text);
  const [saving, setSaving] = useState(false);
  if (editing) {
    return (
      <span className="sentence-edit">
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} aria-label="Edit sentence" />
        <span className="row-actions">
          <button
            type="button"
            className="link"
            disabled={saving}
            onClick={async () => {
              setSaving(true);
              await onSave(text);
              setSaving(false);
              setEditing(false);
            }}
          >
            Save and check
          </button>
          <button type="button" className="link" onClick={() => { setText(s.text); setEditing(false); }}>Cancel</button>
          <span className="fine">Clear the text to remove the sentence.</span>
        </span>
      </span>
    );
  }
  return (
    <span className={`sentence ${s.status === "flagged" ? "flagged" : ""}`}>
      {!first && " "}
      <span className="sentence-text" onDoubleClick={() => setEditing(true)}>{s.text}</span>
      {s.refs.map((r) => (
        <button key={r} type="button" className="cite" onClick={() => onCite(memo.package[r])} title={memo.package[r]?.label}>
          {order.indexOf(r) + 1}
        </button>
      ))}
      {s.edited && <span className="fine"> (edited)</span>}
      <button type="button" className="link edit-link" onClick={() => setEditing(true)} aria-label="Edit this sentence">
        edit
      </button>
      {s.status === "flagged" && <span className="issue">{s.issues.join("; ")}</span>}
    </span>
  );
}
