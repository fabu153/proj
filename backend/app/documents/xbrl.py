"""SEC XBRL companyfacts -> canonical, point-in-time company-year facts (Blueprint p.05-06).

Input: the JSON returned by https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json
  facts -> "us-gaap" -> <Tag> -> units -> "USD" -> [ {start?, end, val, accn, fy, fp, form, filed}, ... ]

Key rules implemented here (pipeline steps 02-06 on p.06):
  * Only 10-K / 10-K/A facts; never mix quarterly with full-year amounts.
  * Duration concepts must span ~one year (350-380 days); instant concepts have no `start`.
  * Periods are keyed by period END date (the `fy` field describes the filing, not the period).
  * Point-in-time: a fact is visible only if `filed <= as_of`.
  * Vintage: by default use the ORIGINAL report (earliest filing) of each period;
    restated values are kept in `restatements`, never silently overwrite history.
  * Each canonical field tries an ordered list of tags; the chosen tag is logged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Optional

ANNUAL_FORMS = {"10-K", "10-K/A", "10-KT"}
MIN_DAYS, MAX_DAYS = 350, 380

# canonical field -> (period type, ordered us-gaap tag candidates)
TAG_REGISTRY: dict[str, tuple[str, list[str]]] = {
    "revenue": ("duration", ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                             "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"]),
    "operating_income": ("duration", ["OperatingIncomeLoss"]),
    "net_income": ("duration", ["NetIncomeLoss", "ProfitLoss"]),
    "interest_expense": ("duration", ["InterestExpense", "InterestExpenseNonoperating",
                                      "InterestExpenseDebt", "InterestAndDebtExpense",
                                      "InterestPaidNet", "InterestPaid"]),   # last two: cash interest fallback
    "depreciation_amortization": ("duration", ["DepreciationDepletionAndAmortization",
                                               "DepreciationAndAmortization",
                                               "DepreciationAmortizationAndAccretionNet"]),
    "operating_cash_flow": ("duration", ["NetCashProvidedByUsedInOperatingActivities"]),
    "capital_expenditures": ("duration", ["PaymentsToAcquirePropertyPlantAndEquipment",
                                          "PaymentsToAcquireProductiveAssets"]),
    "cash": ("instant", ["CashAndCashEquivalentsAtCarryingValue",
                         "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"]),
    "short_term_borrowings": ("instant", ["ShortTermBorrowings", "CommercialPaper"]),
    "current_maturities_ltd": ("instant", ["LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"]),
    "long_term_debt": ("instant", ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations",
                                   "LongTermNotesPayable"]),
    # fallbacks used ONLY to resolve gross debt when the noncurrent tag is absent (see derive())
    "long_term_debt_total": ("instant", ["LongTermDebt", "DebtAndCapitalLeaseObligations",
                                         "DebtLongtermAndShorttermCombinedAmount"]),
    "debt_current_total": ("instant", ["DebtCurrent"]),
    "total_assets": ("instant", ["Assets"]),
    "total_liabilities": ("instant", ["Liabilities"]),
    "liabilities_and_equity": ("instant", ["LiabilitiesAndStockholdersEquity"]),
    "stockholders_equity": ("instant", ["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                                        "StockholdersEquity"]),
    "current_assets": ("instant", ["AssetsCurrent"]),
    "current_liabilities": ("instant", ["LiabilitiesCurrent"]),
}

# Debt buckets that are commonly absent because the company has none. Missing -> 0 with a soft flag.
ZERO_IF_ABSENT = {"short_term_borrowings", "current_maturities_ltd"}
# Tags that bundle finance leases into debt — accepted, but flagged (p.08 lease caveat).
LEASE_BUNDLED_TAGS = {"LongTermDebtAndCapitalLeaseObligations", "LongTermDebtAndCapitalLeaseObligationsCurrent",
                      "DebtAndCapitalLeaseObligations"}
CASH_INTEREST_TAGS = {"InterestPaidNet", "InterestPaid"}
# Fields that are inputs to derivations only, never passed to the finance engine directly.
HELPER_FIELDS = {"long_term_debt_total", "debt_current_total", "liabilities_and_equity"}
COMBINED_CASH_TAG = "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"

# Supplementary tags read ONLY for the credit basis (rules R5-R7 in credit_adjustments). They are kept apart from
# TAG_REGISTRY on purpose: the stress model v1 was trained on inputs built from TAG_REGISTRY alone, so the model
# basis must never see them (see engine_inputs(basis="model")). Added after the v1.0.0 manual reconciliation.
SUPPLEMENTAL_REGISTRY: dict[str, tuple[str, list[str]]] = {
    "restricted_cash": ("instant", ["RestrictedCashAndCashEquivalents", "RestrictedCashAndCashEquivalentsAtCarryingValue",
                                    "RestrictedCash", "RestrictedCashAndCashEquivalentsCurrent", "RestrictedCashCurrent"]),
    "cost_of_revenue_da": ("duration", ["CostOfGoodsAndServicesSoldDepreciationAndAmortization",
                                        "CostOfServicesDepreciationAndAmortization",
                                        "CostOfGoodsSoldDepreciationAndAmortization"]),
    "interest_net_pl": ("duration", ["InterestIncomeExpenseNonoperatingNet", "InterestIncomeExpenseNet"]),
    # v1.6 credit-only disclosures: the debt maturity schedule (principal of long-term debt by year) and retained
    # earnings for the Altman Z'' textbook score. Never model inputs.
    "debt_maturity_y1": ("instant", ["LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths"]),
    "debt_maturity_y2": ("instant", ["LongTermDebtMaturitiesRepaymentsOfPrincipalInYearTwo"]),
    "debt_maturity_y3": ("instant", ["LongTermDebtMaturitiesRepaymentsOfPrincipalInYearThree"]),
    "debt_maturity_y4": ("instant", ["LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFour"]),
    "debt_maturity_y5": ("instant", ["LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFive"]),
    "debt_maturity_after5": ("instant", ["LongTermDebtMaturitiesRepaymentsOfPrincipalAfterYearFive"]),
    "retained_earnings": ("instant", ["RetainedEarningsAccumulatedDeficit"]),
}


@dataclass
class SourcedFact:
    field: str
    value: float
    tag: str
    period_end: str
    period_start: Optional[str]
    accession: str
    form: str
    filed: str
    unit: str = "USD"
    extraction_method: str = "XBRL"
    page: Optional[int] = None          # set for facts extracted from an uploaded PDF


@dataclass
class CompanyYear:
    cik: str
    company_name: str
    fiscal_year_end: str
    available_as_of: Optional[str] = None           # latest filing date among chosen facts
    facts: dict[str, Optional[SourcedFact]] = field(default_factory=dict)
    restatements: dict[str, list[SourcedFact]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    hard_failures: list[str] = field(default_factory=list)
    derived: dict[str, tuple[float, str]] = field(default_factory=dict)   # field -> (value, rule)   [model + credit]
    supplemental: dict[str, SourcedFact] = field(default_factory=dict)    # SUPPLEMENTAL_REGISTRY facts [credit only]
    credit: dict[str, tuple[float, str]] = field(default_factory=dict)    # field -> (value, rule) R5-R7 [credit only]
    cash_basis: str = "unrestricted"   # unrestricted | unrestricted_derived | combined_not_separable | missing

    def values(self) -> dict[str, Optional[float]]:
        """Values as the stress model v1 saw them (reported facts + derivation rules R1-R4)."""
        out = {k: (v.value if v else None) for k, v in self.facts.items()}
        for k, (val, _) in self.derived.items():
            out[k] = val
        return out

    def credit_values(self) -> dict[str, Optional[float]]:
        """Values for credit analysis: model values plus the credit-basis corrections R5-R7."""
        out = self.values()
        for k, (val, _) in self.credit.items():
            out[k] = val
        return out

    @property
    def scorable(self) -> bool:
        return not self.hard_failures


def _d(s: str) -> date:
    return date.fromisoformat(s)


def is_annual(entry: dict, period_type: str) -> bool:
    if entry.get("form") not in ANNUAL_FORMS:
        return False
    if period_type == "instant":
        return "start" not in entry or not entry.get("start")
    if not entry.get("start"):
        return False
    days = (_d(entry["end"]) - _d(entry["start"])).days
    return MIN_DAYS <= days <= MAX_DAYS


def _entries(companyfacts: dict, tag: str) -> Iterable[dict]:
    units = companyfacts.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {})
    return units.get("USD", [])


def build_company_years(companyfacts: dict, as_of: Optional[str] = None,
                        vintage: str = "original") -> list[CompanyYear]:
    """Return one CompanyYear per fiscal-year end visible at `as_of`."""
    assert vintage in ("original", "latest")
    cik = str(companyfacts.get("cik", "")).zfill(10)
    name = companyfacts.get("entityName", "")
    cutoff = _d(as_of) if as_of else None

    # field -> period_end -> list[SourcedFact] (first-matching tag in priority order wins per period)
    per_field: dict[str, dict[str, list[SourcedFact]]] = {}
    for fld, (ptype, tags) in {**TAG_REGISTRY, **SUPPLEMENTAL_REGISTRY}.items():
        found: dict[str, list[SourcedFact]] = {}
        for tag in tags:
            for e in _entries(companyfacts, tag):
                if not is_annual(e, ptype):
                    continue
                if cutoff and _d(e["filed"]) > cutoff:
                    continue                   # not yet public at prediction date
                end = e["end"]
                if end in found and found[end][0].tag != tag:
                    continue                   # a higher-priority tag already covers this period
                found.setdefault(end, []).append(SourcedFact(
                    fld, float(e["val"]), tag, end, e.get("start"), e["accn"], e["form"], e["filed"],
                    extraction_method=e.get("extraction_method", "XBRL"), page=e.get("page")))
        per_field[fld] = found

    # Fiscal-year ends are defined by duration facts from income statement (revenue or operating income)
    fy_ends = sorted(set(per_field["revenue"]) | set(per_field["operating_income"]))
    years: list[CompanyYear] = []
    for end in fy_ends:
        cy = CompanyYear(cik=cik, company_name=name, fiscal_year_end=end)
        for fld, by_end in per_field.items():
            cands = by_end.get(end, [])
            if fld in SUPPLEMENTAL_REGISTRY:          # credit-only inputs: never in facts / model values
                uniq = sorted({(c.accession, c.value): c for c in cands}.values(), key=lambda c: (c.filed, c.accession))
                if uniq:
                    cy.supplemental[fld] = uniq[0] if vintage == "original" else uniq[-1]
                continue
            # dedupe identical (accession, value) repeats — the same fact appears in several later 10-Ks
            uniq = {(c.accession, c.value): c for c in cands}.values()
            ordered = sorted(uniq, key=lambda c: (c.filed, c.accession))
            if not ordered:
                if fld in ZERO_IF_ABSENT:
                    cy.facts[fld] = None
                    cy.warnings.append(f"{fld}: no tag reported; treated as 0 for debt sum (verify in 10-K)")
                else:
                    cy.facts[fld] = None
                continue
            chosen = ordered[0] if vintage == "original" else ordered[-1]
            cy.facts[fld] = chosen
            distinct_vals = {round(c.value, 2) for c in ordered}
            if len(distinct_vals) > 1:
                cy.restatements[fld] = [c for c in ordered if c is not chosen]
                cy.warnings.append(f"{fld}: restated in later filing(s); using {vintage} vintage")
            if chosen.tag in LEASE_BUNDLED_TAGS:
                cy.warnings.append(f"{fld}: tag {chosen.tag} bundles finance leases into debt")
            if chosen.tag in CASH_INTEREST_TAGS:
                cy.warnings.append(f"{fld}: no P&L interest tag; using cash interest paid ({chosen.tag})")
        filed_dates = [f.filed for f in cy.facts.values() if f]
        cy.available_as_of = max(filed_dates) if filed_dates else None
        derive(cy)
        credit_adjustments(cy)
        run_quality_checks(cy)
        years.append(cy)
    return years


def _val(cy: CompanyYear, fld: str) -> Optional[float]:
    f = cy.facts.get(fld)
    return f.value if f else None


def derive(cy: CompanyYear) -> None:
    """Fill canonical gaps from reported totals using explicit, logged rules (no estimation).

    Debt — gross debt must equal STB + current LTD + noncurrent LTD without double counting:
      R1  noncurrent LTD reported, current pieces absent, DebtCurrent reported
          -> current_maturities_ltd := DebtCurrent, short_term_borrowings := 0 (DebtCurrent covers both)
      R2  noncurrent LTD absent, LongTermDebt/DebtAndCapitalLeaseObligations (total incl. current) reported
          -> long_term_debt := total - current_maturities_ltd (if reported) so the sum is unchanged
      R3  as R2 but the total is DebtLongtermAndShorttermCombinedAmount (includes short-term borrowings)
          -> long_term_debt := total, short_term & current := 0
    Liabilities — Liabilities tag absent:
      R4  total_liabilities := LiabilitiesAndStockholdersEquity - equity (incl. NCI when available)
    """
    stb, cur, ltd = _val(cy, "short_term_borrowings"), _val(cy, "current_maturities_ltd"), _val(cy, "long_term_debt")
    total_f, dcur = cy.facts.get("long_term_debt_total"), _val(cy, "debt_current_total")
    if ltd is not None and stb is None and cur is None and dcur is not None:
        cy.derived["current_maturities_ltd"] = (dcur, "R1:DebtCurrent")
        cy.derived["short_term_borrowings"] = (0.0, "R1:included_in_DebtCurrent")
        cy.warnings.append("debt: current debt taken from DebtCurrent (R1)")
    elif ltd is None and total_f is not None:
        if total_f.tag == "DebtLongtermAndShorttermCombinedAmount":
            cy.derived.update(long_term_debt=(total_f.value, "R3:combined_total"),
                              short_term_borrowings=(0.0, "R3:in_total"), current_maturities_ltd=(0.0, "R3:in_total"))
        else:
            cur_in = cur if cur is not None else 0.0
            cy.derived["long_term_debt"] = (max(total_f.value - cur_in, 0.0), f"R2:{total_f.tag}-current")
            if cur is None:
                cy.derived["current_maturities_ltd"] = (0.0, "R2:in_total")
        cy.warnings.append(f"debt: gross debt resolved from total tag {total_f.tag} ({'R3' if 'Combined' in total_f.tag else 'R2'})")
    # a derived value supersedes the generic "treated as 0" warning for that field
    cy.warnings = [w for w in cy.warnings if not (w.split(":")[0] in cy.derived and "treated as 0" in w)]
    if _val(cy, "total_liabilities") is None:
        le, eq = _val(cy, "liabilities_and_equity"), _val(cy, "stockholders_equity")
        if le is not None and eq is not None:
            cy.derived["total_liabilities"] = (le - eq, "R4:L&E-equity")
            cy.warnings.append("total_liabilities derived as liabilities&equity minus equity (R4)")


def credit_adjustments(cy: CompanyYear) -> None:
    """Credit-basis corrections found in the v1.0.0 reconciliation against original 10-Ks (docs/manual_cross_check.md).

      R5  Cash: net debt is defined on UNRESTRICTED cash. When only the combined cash + restricted cash tag exists:
          subtract a tagged restricted-cash amount; if none is tagged, keep the figure but mark it as not separable
          (net debt and net leverage are then qualified, never silently presented as unrestricted).
      R6  D&A: some filers tag depreciation inside cost of revenue separately (e.g. United Rentals' rental fleet).
          When the chosen D&A tag is smaller than that component, the cash-flow total = component + other D&A.
          If the chosen tag is already at least as large, it may include the component: keep it and warn.
      R7  Interest: when the only interest tag is CASH interest paid, prefer the income-statement net interest
          expense (negative InterestIncomeExpense...Net), flagged as net of interest income.
    """
    sup = cy.supplemental
    cash = cy.facts.get("cash")
    if cash is None:
        cy.cash_basis = "missing"
    elif cash.tag == COMBINED_CASH_TAG:
        rc = sup.get("restricted_cash")
        if rc is not None and 0 <= rc.value <= cash.value:
            cy.credit["cash"] = (cash.value - rc.value, f"R5: combined cash {cash.value / 1e6:,.1f}m less restricted "
                                                       f"cash {rc.value / 1e6:,.1f}m ({rc.tag})")
            cy.cash_basis = "unrestricted_derived"
        else:
            cy.cash_basis = "combined_not_separable"
            cy.warnings.append("cash: only cash including restricted cash is tagged and no restricted amount is "
                               "reported, so it cannot be separated; net debt is qualified (R5)")

    da, cogs = cy.facts.get("depreciation_amortization"), sup.get("cost_of_revenue_da")
    if cogs is not None and cogs.value > 0:
        if da is None:
            cy.warnings.append(f"depreciation_amortization: only D&A within cost of revenue ({cogs.value / 1e6:,.1f}m) "
                               "is tagged; total D&A not available")
        elif da.value < cogs.value:
            cy.credit["depreciation_amortization"] = (
                da.value + cogs.value, f"R6: D&A in cost of revenue {cogs.value / 1e6:,.1f}m ({cogs.tag}) + "
                                       f"other D&A {da.value / 1e6:,.1f}m ({da.tag})")
        else:
            cy.warnings.append(f"depreciation_amortization: a separate cost-of-revenue D&A of {cogs.value / 1e6:,.1f}m "
                               f"is tagged; check whether {da.tag} already includes it")

    intr, net = cy.facts.get("interest_expense"), sup.get("interest_net_pl")
    if net is not None and net.value < 0 and (intr is None or intr.tag in CASH_INTEREST_TAGS):
        cy.credit["interest_expense"] = (-net.value, f"R7: income-statement interest expense, net of interest income "
                                                     f"({net.tag})" + (f"; replaces cash interest paid "
                                                                       f"{intr.value / 1e6:,.1f}m" if intr else ""))
        # the earlier model-basis warning stays true for the neural screen; say so instead of contradicting R7
        cy.warnings = [w.replace("using cash interest paid", "the neural screen uses cash interest paid")
                       if w.startswith("interest_expense: no P&L interest tag") else w for w in cy.warnings]
    for k, (_, rule) in cy.credit.items():
        cy.warnings.append(f"{k}: credit basis uses {rule}")


def run_quality_checks(cy: CompanyYear, tolerance: float = 0.01) -> None:
    """Hard checks block inference; soft checks become visible warnings (p.06)."""
    v = cy.values()
    a, l, eq = v.get("total_assets"), v.get("total_liabilities"), v.get("stockholders_equity")
    le = v.get("liabilities_and_equity")
    if a is not None and le is not None and a > 0 and abs(a - le) / a > tolerance:
        cy.hard_failures.append(f"balance_sheet_identity: assets {a:,.0f} != liabilities&equity {le:,.0f}")
    elif a is not None and l is not None and eq is not None and a > 0 and "total_liabilities" not in cy.derived:
        if abs(a - (l + eq)) / a > tolerance:
            cy.hard_failures.append(f"balance_sheet_identity: assets {a:,.0f} != liabilities+equity {l + eq:,.0f}")
    for fld in ("total_assets", "revenue"):
        if v.get(fld) is not None and v[fld] < 0:
            cy.hard_failures.append(f"{fld}_negative")
    for fld in ("short_term_borrowings", "current_maturities_ltd", "long_term_debt", "cash"):
        if v.get(fld) is not None and v[fld] < 0:
            cy.hard_failures.append(f"{fld}_negative")
    if v.get("capital_expenditures") is not None and v["capital_expenditures"] < 0:
        cy.warnings.append("capital_expenditures reported negative; engine will flip sign")
    if v.get("depreciation_amortization") is None:
        cy.warnings.append("depreciation_amortization missing: EBITDA not available")
    if v.get("interest_expense") is None:
        cy.warnings.append("interest_expense missing: coverage not available (not invented)")


def engine_inputs(cy: CompanyYear, basis: str = "credit") -> dict[str, Optional[float]]:
    """Canonical values ready for finance.metrics.compute_all (zero-fill only the flagged debt buckets).

    basis="credit" (ratios, scenarios, memo) applies R5-R7; basis="model" reproduces exactly the inputs the
    stress model v1 was trained on, so serving never drifts from training.
    """
    assert basis in ("credit", "model")
    v = cy.credit_values() if basis == "credit" else cy.values()
    for fld in ZERO_IF_ABSENT:
        if v.get(fld) is None and v.get("long_term_debt") is not None:
            v[fld] = 0.0
    for fld in HELPER_FIELDS:
        v.pop(fld, None)
    return v
