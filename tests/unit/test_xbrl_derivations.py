"""Debt and liabilities derivation rules R1-R4 — gross debt never double counts current debt."""
from backend.app.documents.xbrl import CompanyYear, SourcedFact, derive, engine_inputs, run_quality_checks


def _cy(**vals) -> CompanyYear:
    tags = {"long_term_debt_total": "LongTermDebt"}
    cy = CompanyYear("0000000009", "T", "2025-12-31")
    for k, v in vals.items():
        tag = tags.get(k, k) if not isinstance(v, tuple) else v[1]
        val = v if not isinstance(v, tuple) else v[0]
        cy.facts[k] = SourcedFact(k, float(val), tag, "2025-12-31", None, "a", "10-K", "2026-02-01")
    derive(cy)
    run_quality_checks(cy)
    return cy


def _gross(v):
    return v["short_term_borrowings"] + v["current_maturities_ltd"] + v["long_term_debt"]


def test_r1_debt_current_fills_current_bucket():
    cy = _cy(long_term_debt=200, debt_current_total=30)
    assert _gross(engine_inputs(cy)) == 230


def test_real_issuer_r1_supersedes_zero_fill_warning():
    import gzip, json
    from pathlib import Path
    from backend.app.documents.xbrl import build_company_years
    p = Path(__file__).parents[2] / "backend" / "data" / "curated" / "companyfacts_0001067701.json.gz"
    with gzip.open(p, "rt") as fh:
        y = build_company_years(json.load(fh))[-1]
    assert "current_maturities_ltd" in y.derived
    assert not any(w.startswith("current_maturities_ltd") and "treated as 0" in w for w in y.warnings)


def test_r2_total_ltd_net_of_reported_current_portion():
    v = engine_inputs(_cy(long_term_debt_total=250, current_maturities_ltd=50))
    assert v["long_term_debt"] == 200 and _gross(v) == 250


def test_r2_total_ltd_without_current_tag_not_double_counted():
    v = engine_inputs(_cy(long_term_debt_total=250, short_term_borrowings=10))
    assert _gross(v) == 260


def test_r3_combined_total_includes_short_term():
    v = engine_inputs(_cy(long_term_debt_total=(300, "DebtLongtermAndShorttermCombinedAmount"),
                          short_term_borrowings=40))
    assert _gross(v) == 300


def test_r4_liabilities_derived_and_helpers_hidden_from_engine():
    cy = _cy(total_assets=1000, liabilities_and_equity=1000, stockholders_equity=400)
    v = engine_inputs(cy)
    assert v["total_liabilities"] == 600 and "liabilities_and_equity" not in v and cy.scorable


def test_assets_vs_liabilities_and_equity_mismatch_is_hard_failure():
    assert not _cy(total_assets=1000, liabilities_and_equity=900, stockholders_equity=400).scorable


def test_cash_interest_fallback_is_flagged():
    cy = CompanyYear("1", "T", "2025-12-31")
    from backend.app.documents.xbrl import build_company_years
    cf = {"cik": 1, "entityName": "T", "facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [{"start": "2025-01-01", "end": "2025-12-31", "val": 100, "accn": "a",
                                        "form": "10-K", "filed": "2026-02-01"}]}},
        "InterestPaidNet": {"units": {"USD": [{"start": "2025-01-01", "end": "2025-12-31", "val": 5, "accn": "a",
                                               "form": "10-K", "filed": "2026-02-01"}]}}}}}
    y = build_company_years(cf)[0]
    assert y.values()["interest_expense"] == 5 and any("cash interest" in w for w in y.warnings)
