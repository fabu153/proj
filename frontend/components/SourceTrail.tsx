"use client";

/** Stage E2: filing -> normalized fact -> calculation -> memo statement, for a headline memo figure. */
export type Trail = {
  metric: string;
  facts: {
    field: string;
    label: string;
    as_filed: { value: number; unit: string } | null;
    normalized: number | null;
    unit: string;
    rule: string | null;
    note: string | null;
    basis: "reported" | "credit" | "derived";
    source: { kind: "sec" | "upload" | "none"; tag?: string | null; accession?: string; form?: string; filed?: string; url?: string; page?: number; method?: string; derived?: boolean };
  }[];
  steps: { metric: string; label: string; formula: string; version: string; expression: string; status: string; note: string | null }[];
};

const n1 = (v: number | null) => (v === null ? "not reported" : v.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 }));
const raw = (v: number) => v.toLocaleString("en-US", { maximumFractionDigits: 0 });

export default function SourceTrail({ trail, statement }: { trail: Trail; statement?: string | null }) {
  return (
    <ol className="trail">
      <li>
        <span className="trail-step">1 · Filing</span>
        <ul>
          {trail.facts.map((f) => (
            <li key={f.field}>
              <strong>{f.label}</strong>{" "}
              {f.source.kind === "sec" && !f.source.derived && f.as_filed && (
                <>
                  {raw(f.as_filed.value)} {f.as_filed.unit} as tagged <code>{f.source.tag}</code>, {f.source.form} filed {f.source.filed},{" "}
                  <a href={f.source.url} target="_blank" rel="noreferrer">accession {f.source.accession}</a>
                </>
              )}
              {f.source.kind === "sec" && f.source.derived && (
                <>
                  not tagged directly; derived by rule from the same {f.source.form} (
                  <a href={f.source.url} target="_blank" rel="noreferrer">accession {f.source.accession}</a>)
                </>
              )}
              {f.source.kind === "upload" && f.as_filed && (
                <>
                  {raw(f.as_filed.value)} {f.as_filed.unit} from the uploaded report, page {f.source.page} ({f.source.method})
                </>
              )}
              {f.source.kind === "none" && <>not reported in this filing</>}
            </li>
          ))}
        </ul>
      </li>
      <li>
        <span className="trail-step">2 · Normalized fact ({trail.facts[0]?.unit})</span>
        <ul>
          {trail.facts.map((f) => (
            <li key={f.field}>
              {f.label}: <b className="num">{n1(f.normalized)}</b>
              {f.rule && <span className="fine"> · rule {f.rule.replace(/_/g, " ")}</span>}
              {f.note && <span className="fine"> · {f.note}</span>}
            </li>
          ))}
        </ul>
      </li>
      <li>
        <span className="trail-step">3 · Calculation</span>
        <ul>
          {trail.steps.map((s) => (
            <li key={s.metric}>
              {s.label} = <code>{s.formula}</code>
              <div className="num calc">{s.expression}</div>
              {s.note && <span className="fine">{s.note}</span>}
            </li>
          ))}
        </ul>
      </li>
      {statement && (
        <li>
          <span className="trail-step">4 · Memo statement</span>
          <blockquote>{statement}</blockquote>
        </li>
      )}
    </ol>
  );
}
