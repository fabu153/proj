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
  critical_inputs_unavailable?: string[];
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
  derived: Record<string, { value: number; rule: string; basis?: string }>;
  supplemental?: Record<string, Evidence>;
  cash_basis?: "unrestricted" | "unrestricted_derived" | "combined_not_separable" | "missing";
  unavailable_inputs?: string[];
  sec_check?: string | null;
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

export type Snapshot = { id: string; inputs: Record<string, any> };

export type ScenarioResponse = {
  baseline: Record<string, number | string>;
  results: ScenarioResult[];
  snapshot?: Snapshot | null;
  facility_schedule: { year: number; opening: number; interest: number; repayment: number; closing: number }[];
  disclaimer: string;
};

export class ApiError extends Error {
  constructor(message: string, readonly status: number | null) {
    super(message);
  }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * One request with a timeout. Idempotent requests (GET, and the pure calculation POSTs) are retried when the
 * network fails or the host answers 502/503/504, which is what a sleeping free-tier server does while it wakes.
 * Requests never hang: each attempt is aborted after `timeoutMs`.
 */
async function call<T>(path: string, init?: RequestInit & { retries?: number; timeoutMs?: number }): Promise<T> {
  const retries = init?.retries ?? (init?.method && init.method !== "GET" ? 0 : 2);
  const timeoutMs = init?.timeoutMs ?? 45000;
  let last: unknown;
  for (let attempt = 0; attempt <= retries; attempt++) {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), timeoutMs);
    try {
      const res = await fetch(`${API_URL}${path}`, {
        ...init,
        signal: ctl.signal,
        headers: { "content-type": "application/json", ...(init?.headers || {}) },
        cache: "no-store",
      });
      if (!res.ok) {
        let detail = `${res.status} ${res.statusText}`;
        try {
          const body = await res.json();
          if (body?.detail) detail = typeof body.detail === "string" ? body.detail : formatValidation(body.detail);
        } catch {
          /* keep status text */
        }
        if ([502, 503, 504].includes(res.status) && attempt < retries) {
          last = new ApiError(detail, res.status);
          await sleep(1500 * (attempt + 1));
          continue;
        }
        throw new ApiError(detail, res.status);
      }
      return (await res.json()) as T;
    } catch (e) {
      if (e instanceof ApiError) throw e;
      last = (e as Error).name === "AbortError" ? new ApiError(`The analysis service did not answer within ${timeoutMs / 1000} seconds.`, null) : e;
      if (attempt < retries) await sleep(1500 * (attempt + 1));
    } finally {
      clearTimeout(timer);
    }
  }
  throw last instanceof Error ? last : new ApiError("Request failed", null);
}

function formatValidation(detail: unknown): string {
  if (Array.isArray(detail)) {
    return detail.map((d: any) => (d?.msg ? String(d.msg).replace(/^Value error, /, "") : JSON.stringify(d))).join("; ");
  }
  return JSON.stringify(detail);
}

/**
 * Wake the API (free hosting sleeps when idle; the first request can take up to about a minute).
 * Polls /health until it answers or `budgetMs` runs out; reports progress so the page can say what is happening.
 */
export async function waitForApi(onProgress?: (elapsedS: number, attempt: number) => void, budgetMs = 90000): Promise<void> {
  const start = Date.now();
  for (let attempt = 1; ; attempt++) {
    onProgress?.(Math.round((Date.now() - start) / 1000), attempt);
    try {
      await call<{ status: string }>("/health", { retries: 0, timeoutMs: 20000 });
      return;
    } catch (e) {
      if (Date.now() - start > budgetMs) {
        throw new ApiError(`The analysis service at ${API_URL} did not wake up within ${Math.round(budgetMs / 1000)} seconds (${(e as Error).message}).`, null);
      }
      await sleep(3000);
    }
  }
}

export const api = {
  companies: (include?: string | null) => call<Company[]>(`/companies${include ? `?include=${encodeURIComponent(include)}` : ""}`),
  analysis: (company_id: string, fiscal_year_end?: string) =>
    call<Analysis>("/analyses", { method: "POST", body: JSON.stringify({ company_id, fiscal_year_end }), retries: 1 }),
  history: (company_id: string) => call<HistoryPoint[]>(`/companies/${company_id}/history`),
  scenarios: (body: {
    company_id: string;
    fiscal_year_end?: string;
    facility: Facility;
    shocks: Shock[];
    covenants: Covenants;
    existing_floating_share: number;
  }) => call<ScenarioResponse>("/scenarios", { method: "POST", body: JSON.stringify(body), retries: 1 }),
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
  value: number | null;
  page: number;
  label: string;
  snippet: string;
  statement: string;
  confidence: "high" | "medium" | "low";
  reasons: string[];
  status: "auto_accepted" | "needs_review" | "accepted" | "corrected" | "rejected" | "manual" | "unavailable";
  reviewed_value: number | null;
  reviewer_note: string | null;
};

export type DocumentView = {
  id: string;
  company_id: string;
  filename: string;
  pages: number;
  company_name: string;
  currency: string | null;
  scale_label: string | null;
  fiscal_year_end: string | null;
  fye_inferred: boolean;
  statement_pages: Record<string, number[]>;
  issues: string[];
  status: "in_review" | "finalized";
  facts: Fact[];
  blocking: string[];
  can_finalize: boolean;
  unavailable_critical: string[];
  sec_check: string | null;
  currencies: string[];
  scales: string[];
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
  snapshot?: Snapshot | null;
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
  update: (id: string, meta: { fiscal_year_end?: string; company_name?: string; currency?: string; scale_label?: string }) =>
    send<DocumentView>(`/documents/${id}`, "PATCH", meta),
  addFact: (id: string, f: { field: string; period?: "t" | "t-1"; value: number | null; page?: number | null; note?: string }) =>
    send<DocumentView>(`/documents/${id}/facts`, "POST", f),
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
    shocks: Shock[];
  }) => send<Memo>("/memos", "POST", body),
  edit: (id: string, sentenceId: string, text: string) => send<Memo>(`/memos/${id}/sentences/${sentenceId}`, "PATCH", { text }),
  pdfUrl: (id: string) => `${API_URL}/memos/${id}/pdf`,
};
