"use client";

import { useEffect, useState } from "react";
import type { Covenants, Facility, Memo, PackageItem, Sentence } from "@/lib/api";
import { memos } from "@/lib/api";

export type MemoParams = { facility: Facility; covenants: Covenants; existing_floating_share: number };

type Props = {
  companyId: string;
  fiscalYear: string;
  params: MemoParams | null;
  onCite: (item: PackageItem) => void;
};

export default function MemoPanel({ companyId, fiscalYear, params, onCite }: Props) {
  const [memo, setMemo] = useState<Memo | null>(null);
  const [writer, setWriter] = useState<{ writer: string; llm_configured: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    memos.config().then(setWriter).catch(() => setWriter(null));
  }, []);
  useEffect(() => setMemo(null), [companyId, fiscalYear]);

  const draft = async () => {
    if (!params) return;
    setBusy(true);
    setError(null);
    try {
      setMemo(await memos.create({ company_id: companyId, fiscal_year_end: fiscalYear, ...params }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  // citation numbers in order of first appearance, as in the PDF appendix
  const order: string[] = [];
  memo?.sections.forEach((s) => s.sentences.forEach((x) => x.refs.forEach((r) => !order.includes(r) && order.push(r))));

  return (
    <div className="sheet memo">
      <div className="memo-bar">
        <button className="btn" type="button" onClick={draft} disabled={busy || !params}>
          {busy ? "Drafting…" : memo ? "Redraft with current loan lab inputs" : "Draft credit memo"}
        </button>
        {memo && (
          <a className="btn ghost" href={memos.pdfUrl(memo.id)} target="_blank" rel="noreferrer">
            Download PDF
          </a>
        )}
        <span className="fine">
          {writer?.llm_configured ? `Written by ${writer.writer}; ` : "Written from templates (no language model configured); "}
          every number is inserted from the engines.
        </span>
      </div>
      {error && <div className="notice error">{error}</div>}
      {memo && (
        <>
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
            Memo {memo.id.slice(0, 12)}, package {memo.package_sha256.slice(0, 12)}, generated {memo.created_at}. Select a citation number to
            see its source.
          </p>
        </>
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
