// Typed client for the CreditLens API. All numbers are computed server-side;
// the UI only formats them.

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

export type Company = {
  company_id: string;
  name: string;
  source: string;
  fiscal_years: string[];
  last_filed: string | null;
  synthetic: boolean;
};

export type Metric = {
  metric: string;
  value: number | null;
  status: "ok" | "ok_with_warning" | "not_available" | "undefined";
  unit: string;
  formula: string;
  formula_version: string;
  inputs: Record<string, number | null>;
  reason: string | null;
};

export type Evidence = {
  field: string;
  value: number;
  unit: string;
  tag: string;
  accession: string;
  form: string;
  filed: string;
  period_end: string;
  extraction_method: string;
  page?: number | null;
};

export type Driver = {
  feature: string;
  description: string;
  unit: string;
  value: number | null;
  train_median: number;
  logit_contribution: number;
};

export type RiskModel = {
  status: "scored" | "withheld" | "model_unavailable";
  probability?: number;
  band?: "low" | "elevated" | "high";
  label?: string;
  drivers?: Driver[];
  gate_reasons?: string[];
  features_missing?: number;
  features_as_of?: string;
  sample_period?: string;
  in_training_universe?: boolean;
  disclaimer?: string;
  model?: {
    name: string;
    target: string;
    trained_at: string;
    test_pr_auc: number;
    test_pr_auc_ci95: [number, number];
    xgboost_benchmark_test_pr_auc: number;
  };
};

export type Analysis = {
  company_id: string;
  company_name: string;
  fiscal_year_end: string;
  currency: string;
  scale: string;
  scorable: boolean;
  source: string;
  metrics: Record<string, Metric>;
  evidence: Record<string, Evidence | null>;
  derived: Record<string, { value: number; rule: string }>;
  warnings: string[];
  hard_failures: string[];
  risk_model: RiskModel;
};

export type HistoryPoint = {
  fiscal_year_end: string;
  filed: string | null;
  scorable: boolean;
  values: Record<string, number | null>;
  metrics: Record<string, number | null>;
};

export type UseOfProceeds = "capex" | "acquisition" | "refinancing" | "retained_cash";

export type Facility = {
  amount: number;
  currency: string;
  coupon: number;
  floating: boolean;
  tenor_years: number;
  annual_amortization: number;
  use_of_proceeds: UseOfProceeds;
  fx_rate_to_reporting: number | null;
  fx_rate_date: string | null;
  refinanced_debt_rate: number | null;
};

export type Shock = { name: string; ebitda_shock: number; rate_shock_bps: number };
export type Covenants = { max_net_leverage: number | null; min_ebitda_interest_cover: number | null };

export type ScenarioResult = {
  name: string;
  currency: string;
  ebitda: number;
  gross_debt: number;
  cash: number;
  net_debt: number;
  interest_expense: number;
  net_leverage: number | null;
  gross_leverage: number | null;
  ebitda_interest_cover: number | null;
  covenant_headroom: Record<string, number | null>;
  flags: string[];
  steps: string[];
};

export type ScenarioResponse = {
  baseline: Record<string, number | string>;
  results: ScenarioResult[];
  facility_schedule: { year: number; opening: number; interest: number; repayment: number; closing: number }[];
  disclaimer: string;
};

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep status text */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  companies: () => call<Company[]>("/companies"),
  analysis: (company_id: string, fiscal_year_end?: string) =>
    call<Analysis>("/analyses", { method: "POST", body: JSON.stringify({ company_id, fiscal_year_end }) }),
  history: (company_id: string) => call<HistoryPoint[]>(`/companies/${company_id}/history`),
  scenarios: (body: {
    company_id: string;
    fiscal_year_end?: string;
    facility: Facility;
    shocks: Shock[];
    covenants: Covenants;
    existing_floating_share: number;
  }) => call<ScenarioResponse>("/scenarios", { method: "POST", body: JSON.stringify(body) }),
  model: () => call<{ metadata: any; xray: any }>("/model"),
};

// ---------------------------------------------------------------- formatting
const nf = (d: number) => new Intl.NumberFormat("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

export function fmt(v: number | null | undefined, unit: string): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "n/a";
  switch (unit) {
    case "pct":
      return `${nf(1).format(v * 100)}%`;
    case "x":
      return `${nf(2).format(v)}x`;
    case "amount":
      return v < 0 ? `(${nf(0).format(-v)})` : nf(0).format(v);
    default:
      return nf(2).format(v);
  }
}

// 52/53-week years that end in the first days of January belong to the prior fiscal year.
export const fyLabel = (fye: string) => {
  const y = +fye.slice(0, 4);
  return fye.slice(5, 7) === "01" && +fye.slice(8, 10) <= 7 ? `FY${y - 1}` : `FY${y}`;
};

// ---------------------------------------------------------------- Week 6: documents and memos
export type Fact = {
  id: string;
  field: string;
  period: "t" | "t-1";
  value: number;
  page: number;
  label: string;
  snippet: string;
  statement: string;
  confidence: "high" | "medium" | "low";
  reasons: string[];
  status: "auto_accepted" | "needs_review" | "accepted" | "corrected" | "rejected";
  reviewed_value: number | null;
  reviewer_note: string | null;
};

export type DocumentView = {
  id: string;
  company_id: string;
  filename: string;
  pages: number;
  company_name: string;
  currency: string;
  scale_label: string;
  fiscal_year_end: string | null;
  fye_inferred: boolean;
  statement_pages: Record<string, number[]>;
  issues: string[];
  status: "in_review" | "finalized";
  facts: Fact[];
  blocking: string[];
  can_finalize: boolean;
};

export type PackageItem = { id: string; label: string; value: unknown; unit: string; display: string; source: Record<string, any> };
export type Sentence = {
  id: string;
  template: string;
  text: string;
  refs: string[];
  kind: "claim" | "framing" | "question";
  status: "ok" | "flagged";
  issues: string[];
  edited: boolean;
};
export type Memo = {
  id: string;
  company_id: string;
  fiscal_year_end: string;
  created_at: string;
  writer: string;
  writer_note: string | null;
  package_sha256: string;
  currency: string;
  package: Record<string, PackageItem>;
  sections: { key: string; title: string; sentences: Sentence[] }[];
  summary: { sentences: number; flagged: number; cited_items: number };
};

async function send<T>(path: string, method: string, body?: unknown): Promise<T> {
  return call<T>(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });
}

export const docs = {
  upload: async (file: File, company_name: string, cik: string): Promise<DocumentView> => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("company_name", company_name);
    fd.append("cik", cik);
    const res = await fetch(`${API_URL}/documents/upload`, { method: "POST", body: fd });
    if (!res.ok) {
      const b = await res.json().catch(() => ({}));
      throw new Error(typeof b?.detail === "string" ? b.detail : `${res.status} ${res.statusText}`);
    }
    return res.json();
  },
  get: (id: string) => call<DocumentView>(`/documents/${id}`),
  review: (factId: string, decision: "accept" | "correct" | "reject", value?: number, note?: string) =>
    send<{ id: string; status: string }>(`/facts/${factId}/review`, "PATCH", { decision, value, note }),
  update: (id: string, meta: { fiscal_year_end?: string; company_name?: string }) => send<DocumentView>(`/documents/${id}`, "PATCH", meta),
  finalize: (id: string) => send<DocumentView>(`/documents/${id}/finalize`, "POST"),
  remove: (id: string) => send<{ deleted: string }>(`/documents/${id}`, "DELETE"),
};

export const memos = {
  config: () => call<{ writer: string; llm_configured: boolean }>("/memos/config"),
  create: (body: {
    company_id: string;
    fiscal_year_end?: string;
    facility: Facility;
    covenants: Covenants;
    existing_floating_share: number;
  }) => send<Memo>("/memos", "POST", body),
  edit: (id: string, sentenceId: string, text: string) => send<Memo>(`/memos/${id}/sentences/${sentenceId}`, "PATCH", { text }),
  pdfUrl: (id: string) => `${API_URL}/memos/${id}/pdf`,
};
