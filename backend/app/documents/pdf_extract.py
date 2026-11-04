"""Annual-report PDF -> candidate canonical facts with page citations and confidence (Blueprint p.12).

Pipeline: validate bytes -> extract text per page -> classify statement pages -> detect scale,
currency and year columns -> parse "label  v1  v2 [v3]" lines -> map labels to canonical fields
-> score confidence -> cross-check identities. Extraction PROPOSES facts; nothing low-confidence
reaches the engines without an analyst decision (review step in store.py / the API).

Scope (stated in the UI): text-based PDFs of U.S.-style primary statements. Scanned images
(no text layer) are rejected with a clear message rather than OCR'd silently.
"""
from __future__ import annotations

import io
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Optional

import pdfplumber

MAX_BYTES = 15 * 1024 * 1024
MAX_PAGES = 400
CRITICAL = ["revenue", "operating_income", "interest_expense", "depreciation_amortization",
            "operating_cash_flow", "long_term_debt", "total_assets"]

STATEMENTS = {
    "income": [r"statements? of (consolidated )?(earnings|operations|income)", r"income statements?"],
    "balance": [r"balance sheets?", r"statements? of financial position"],
    "cashflow": [r"statements? of cash flows?", r"cash flow statements?"],
}

# canonical field -> (statement, [(pattern, strength)]) ; patterns run on the normalized label
SYNONYMS: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "revenue": ("income", [(r"^(net sales|net revenues?|total revenues?|revenues?|total net sales|sales)$", "exact"),
                           (r"^(net sales|revenues?|net revenues?)\b", "partial")]),
    "operating_income": ("income", [(r"^(operating income|income from operations|operating (income|profit) \(loss\)|"
                                     r"operating income \(loss\)|operating profit)$", "exact"),
                                    (r"^operating (income|profit)", "partial")]),
    "interest_expense": ("income", [(r"^interest expense$", "exact"),
                                    (r"^interest expense,? net$", "net"),
                                    (r"^interest expense", "partial")]),
    "net_income": ("income", [(r"^(net (earnings|income|loss)|net income \(loss\)|net earnings \(loss\))$", "exact")]),
    "depreciation_amortization": ("cashflow", [(r"^depreciation and amortization$", "exact"),
                                               (r"^depreciation,? (depletion )?and amortization", "partial")]),
    "operating_cash_flow": ("cashflow", [(r"^(net cash provided by (\(used in\) )?operating activities|"
                                          r"total operating activities|net cash from operating activities)$", "exact"),
                                         (r"operating activities$", "partial")]),
    "capital_expenditures": ("cashflow", [(r"^(capital expenditures|purchases? of property,? plant and equipment|"
                                           r"additions to property,? plant and equipment)$", "exact")]),
    "cash": ("balance", [(r"^cash and (cash )?equivalents$", "exact")]),
    "short_term_borrowings": ("balance", [(r"^(short-term borrowings|short-term debt|commercial paper|notes payable)$", "exact")]),
    "current_maturities_ltd": ("balance", [(r"^(current portion of long-term debt|current maturities of long-term debt|"
                                            r"long-term debt, current portion)$", "exact"),
                                           (r"^(debt due within one year|current debt)$", "combined")]),
    "long_term_debt": ("balance", [(r"^(long-term debt|long-term debt, net of current portion|long-term debt, "
                                    r"less current (portion|maturities)|long-term debt, net)$", "exact")]),
    "total_assets": ("balance", [(r"^total assets$", "exact")]),
    "total_liabilities": ("balance", [(r"^total liabilities$", "exact")]),
    "stockholders_equity": ("balance", [(r"^total (stockholders|shareholders)'? equity$", "exact")]),
    "current_assets": ("balance", [(r"^total current assets$", "exact")]),
    "current_liabilities": ("balance", [(r"^total current liabilities$", "exact")]),
}

NUM = r"\(?-?\$?\s?\d[\d,]*(?:\.\d+)?\)?|—|–"
NUM_RE = re.compile(NUM)
YEAR_ROW = re.compile(r"^(?:note\s+)?((?:(?:19|20)\d\d\s*){2,4})$", re.I)
MONTHS = "january february march april may june july august september october november december".split()


class ExtractionError(ValueError):
    """Raised for files we refuse to process; message is shown to the user."""


@dataclass
class Candidate:
    field: str
    period: str                 # "t" (latest year) or "t-1"
    value: float                # in currency units (scale applied)
    page: int                   # 1-based
    label: str
    snippet: str
    statement: str
    confidence: str             # high | medium | low
    reasons: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return self.confidence != "high"


@dataclass
class Extraction:
    pages: int
    statement_pages: dict[str, list[int]]
    scale: Optional[float]
    scale_label: Optional[str]
    currency: Optional[str]
    years: list[int]
    fiscal_year_end: Optional[str]
    fiscal_year_end_inferred: bool
    candidates: list[Candidate]
    issues: list[str]

    def to_dict(self) -> dict:
        d = asdict(self)
        for c, src in zip(d["candidates"], self.candidates):
            c["needs_review"] = src.needs_review
        return d


# ------------------------------------------------------------------ helpers
def validate_pdf_bytes(data: bytes) -> None:
    if len(data) == 0:
        raise ExtractionError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise ExtractionError(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    if not data[:1024].lstrip().startswith(b"%PDF-"):
        raise ExtractionError("This is not a PDF file.")


def parse_number(tok: str) -> Optional[float]:
    t = tok.strip()
    if t in ("—", "–", "-"):
        return 0.0
    neg = t.startswith("(") and t.endswith(")") or t.startswith("-")
    t = t.strip("()").replace("$", "").replace(",", "").replace("-", "").strip()
    if not t:
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def normalize_label(s: str) -> str:
    s = s.lower().replace("’", "'").replace("$", "")
    s = re.sub(r"\s+\d{1,2}$", "", s.strip())        # trailing note reference ("Net sales 3")
    s = re.sub(r"\s+\(note \d+\)$", "", s)
    s = re.sub(r"\s+", " ", s).strip(" :.")
    return s


def detect_scale(text: str) -> tuple[Optional[float], Optional[str]]:
    t = text.lower()
    for word, mult in (("billions", 1e9), ("millions", 1e6), ("thousands", 1e3)):
        if re.search(rf"in {word}|amounts in {word}|\({word}\)|{word} of", t):
            return mult, word
    return None, None


def detect_currency(text: str) -> Optional[str]:
    t = text.lower()
    if "€" in text or re.search(r"\beur\b|in euros?", t):
        return "EUR"
    if re.search(r"\bchf\b|swiss francs?", t):
        return "CHF"
    if "$" in text or re.search(r"u\.s\. dollars|\busd\b", t):
        return "USD"
    return None


def detect_year_end(text: str, latest_year: int) -> tuple[Optional[str], bool]:
    m = re.search(r"(?:years?|fiscal years?|periods?) ended (" + "|".join(MONTHS) + r")\s+(\d{1,2})(?:,\s*(\d{4}))?",
                  text, re.I)
    if not m:
        m2 = re.search(r"as of (" + "|".join(MONTHS) + r")\s+(\d{1,2})", text, re.I)
        if not m2:
            return f"{latest_year}-12-31", True
        m = m2
    month = MONTHS.index(m.group(1).lower()) + 1
    year = int(m.group(3)) if m.lastindex and m.lastindex >= 3 and m.group(3) else latest_year
    try:
        return date(year, month, int(m.group(2))).isoformat(), False
    except ValueError:            # e.g. "June 31": not a calendar date -> the analyst must confirm it
        return None, True


def classify_page(text: str) -> Optional[str]:
    head = "\n".join(text.lower().split("\n")[:6])
    for kind, pats in STATEMENTS.items():
        if any(re.search(p, head) for p in pats):
            return kind
    return None


def split_line(line: str, n_cols: int) -> Optional[tuple[str, list[float], list[str]]]:
    toks = list(NUM_RE.finditer(line))
    if len(toks) < n_cols:
        return None
    last = toks[-n_cols:]
    label = line[: last[0].start()].strip()
    if not re.search(r"[A-Za-z]", label):
        return None
    vals = [parse_number(t.group()) for t in last]
    if any(v is None for v in vals):
        return None
    return label, vals, [t.group() for t in last]


# ------------------------------------------------------------------ main
def extract(data: bytes) -> Extraction:
    validate_pdf_bytes(data)
    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except Exception as e:  # noqa: BLE001 — corrupted / encrypted PDFs
        raise ExtractionError(f"The PDF could not be opened ({type(e).__name__}).") from e
    with pdf:
        if len(pdf.pages) > MAX_PAGES:
            raise ExtractionError(f"The PDF has more than {MAX_PAGES} pages.")
        texts = [(p.extract_text() or "") for p in pdf.pages]
    if sum(len(t.strip()) for t in texts) < 200:
        raise ExtractionError("No text layer found (scanned document?). Upload a text-based PDF; OCR is not supported.")

    statement_pages: dict[str, list[int]] = {k: [] for k in STATEMENTS}
    for i, t in enumerate(texts):
        kind = classify_page(t)
        if kind:
            statement_pages[kind].append(i)
    issues: list[str] = []
    for kind, pages in statement_pages.items():
        if not pages:
            issues.append(f"No {kind.replace('cashflow', 'cash flow')} statement page found")

    stmt_text = "\n".join(texts[i] for pages in statement_pages.values() for i in pages)
    scale, scale_label = detect_scale(stmt_text)
    if scale is None:
        # values are kept in the units as printed; the analyst must confirm the scale before analysis
        issues.append("Unit scale (thousands/millions) not stated on the statement pages; confirm it in review")
        scale, scale_label = 1.0, None
    currency = detect_currency(stmt_text)
    if currency is None:
        issues.append("Reporting currency not stated on the statement pages; confirm it in review")

    raw: dict[str, list[Candidate]] = {}
    years: list[int] = []
    for kind, pages in statement_pages.items():
        for pi in pages:
            lines = texts[pi].split("\n")
            n_cols, page_years = 0, []
            for line in lines:
                m = YEAR_ROW.match(line.strip())
                if m:
                    page_years = [int(y) for y in m.group(1).split()]
                    n_cols = len(page_years)
                    years = years or page_years
                    continue
                if not n_cols:
                    continue
                parsed = split_line(line, n_cols)
                if not parsed:
                    continue
                label, vals, toks = parsed
                norm = normalize_label(label)
                for fld, (stmt, pats) in SYNONYMS.items():
                    for pat, strength in pats:
                        if re.search(pat, norm):
                            break
                    else:
                        continue
                    for col, period in ((0, "t"), (1, "t-1")):
                        if col >= len(vals):
                            continue
                        reasons, conf = [], "high"
                        if strength == "partial":
                            conf = "medium"
                            reasons.append(f"label '{label}' only partly matches")
                        if strength == "net":
                            conf = "medium"
                            reasons.append("interest shown net of interest income")
                        if stmt != kind:
                            conf = "low"
                            reasons.append(f"found on the {kind} statement, expected {stmt}")
                        v = vals[col] * scale
                        if fld == "capital_expenditures":
                            v = abs(v)
                        raw.setdefault(f"{fld}|{period}", []).append(Candidate(
                            fld, period, v, pi + 1, label, line.strip(), kind, conf, reasons))
                    if strength == "combined":
                        for c in raw[f"{fld}|t"][-1:] + raw.get(f"{fld}|t-1", [])[-1:]:
                            c.reasons.append("total debt due within one year (includes short-term borrowings)")
                    break

    # resolve duplicates: keep the first high-confidence candidate; conflicting duplicates lower confidence
    candidates: list[Candidate] = []
    for key, cands in raw.items():
        cands.sort(key=lambda c: {"high": 0, "medium": 1, "low": 2}[c.confidence])
        best = cands[0]
        distinct = {round(c.value, 2) for c in cands if c.statement == best.statement}
        if len(distinct) > 1:
            best.confidence = "low"
            best.reasons.append(f"{len(distinct)} different values found for this line")
        candidates.append(best)

    latest = max(years) if years else 0
    fye, inferred = detect_year_end(stmt_text, latest) if latest else (None, True)
    if inferred:
        issues.append("Fiscal year-end date not stated or not a valid date; confirm it in review")
    _cross_checks(candidates, scale, issues)
    found = {c.field for c in candidates if c.period == "t"}
    for f in CRITICAL:
        if f not in found:
            issues.append(f"Critical item not found: {f.replace('_', ' ')}")
    candidates.sort(key=lambda c: (c.period != "t", list(SYNONYMS).index(c.field)))
    return Extraction(len(texts), {k: [p + 1 for p in v] for k, v in statement_pages.items()}, scale, scale_label,
                      currency, years, fye, inferred, candidates, issues)


def _cross_checks(cands: list[Candidate], scale: float, issues: list[str]) -> None:
    """Statement identities. A failing identity downgrades the facts involved to low confidence."""
    tol = 1.0 * scale + 1e-9
    for period in ("t", "t-1"):
        g = {c.field: c for c in cands if c.period == period}
        a, l, e = g.get("total_assets"), g.get("total_liabilities"), g.get("stockholders_equity")
        if a and l and e and abs(a.value - (l.value + e.value)) > max(tol, 0.005 * abs(a.value)):
            # many filers show mezzanine/NCI lines between liabilities and equity; flag, don't block
            for c in (a, l, e):
                c.confidence = "low" if c.confidence != "high" else "medium"
                c.reasons.append("assets ≠ liabilities + equity on this page (check mezzanine/NCI lines)")
            issues.append(f"Balance sheet does not tie for {period}")
        ca, ta = g.get("current_assets"), g.get("total_assets")
        if ca and ta and ca.value > ta.value:
            ca.confidence = "low"
            ca.reasons.append("current assets exceed total assets")
