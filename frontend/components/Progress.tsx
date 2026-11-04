"use client";

export type StepState = "done" | "current" | "todo" | "blocked" | "stale";
export const STEPS = [
  { key: "company", label: "Company", anchor: "top" },
  { key: "financials", label: "Financials", anchor: "h-profile" },
  { key: "screen", label: "Neural screen", anchor: "h-risk" },
  { key: "lab", label: "Loan lab", anchor: "h-lab" },
  { key: "memo", label: "Committee memo", anchor: "h-memo" },
] as const;
export type StepKey = (typeof STEPS)[number]["key"];

const WORD: Record<StepState, string> = { done: "done", current: "current step", todo: "not started", blocked: "not available", stale: "outdated" };

/** Where the analyst is in the credit file: Company → Financials → Neural screen → Loan lab → Committee memo. */
export default function Progress({ states }: { states: Record<StepKey, StepState> }) {
  return (
    <nav className="progress" aria-label="Analysis progress">
      <ol>
        {STEPS.map((s, i) => (
          <li key={s.key} className={states[s.key]} aria-current={states[s.key] === "current" ? "step" : undefined}>
            <a href={`#${s.anchor}`}>
              <span className="n" aria-hidden="true">{states[s.key] === "done" ? "✓" : i + 1}</span>
              {s.label}
              <span className="sr-only"> ({WORD[states[s.key]]})</span>
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
}
