"""v1.6: peer percentiles (backend/app/finance/peers.py)."""
import pytest

from backend.app.finance import peers


@pytest.fixture
def fake_table(monkeypatch):
    rows = []
    for i in range(30):                                       # 30 food companies in FY2024, one ratio each
        rows.append({"cik": f"{i:010d}", "fiscal_year_end": "2024-12-31", "sic": 2030, "net_leverage": float(i)})
    for i in range(10):                                       # 10 chemicals companies: too few on their own
        rows.append({"cik": f"9{i:09d}", "fiscal_year_end": "2024-12-31", "sic": 2800, "net_leverage": 100.0 + i})
    rows.append({"cik": "0000000005", "fiscal_year_end": "2023-12-31", "sic": 2030, "net_leverage": 999.0})  # older year
    for r in rows:
        r["_fy"], r["_major"] = peers.fiscal_year(r["fiscal_year_end"]), r["sic"] // 100
    t = {"metrics": {"net_leverage": {"label": "Net debt / EBITDA", "stronger": "lower"}}, "_rows": rows,
         "basis": "test", "population": "test"}
    monkeypatch.setattr(peers, "table", lambda: t)
    return t


def test_percentile_in_own_major_group_excluding_self(fake_table):
    b = peers.percentiles({"net_leverage": 10.0}, "0000000003", 2040, "2024-12-31")["bands"]["net_leverage"]
    assert b["group"].startswith("SIC 20") and b["years"] == "FY2024" and b["peers"] == 29   # itself excluded
    assert b["percentile"] == round(100 * (10 - 1 + 0.5) / 29)                            # 0..9 minus own 3, tie at 10
    assert b["stronger"] == "lower"


def test_small_group_widens_to_division(fake_table):
    b = peers.percentiles({"net_leverage": 105.0}, "0000000999", 2810, "2024-12-31")["bands"]["net_leverage"]
    assert b["group"] == "SIC division: manufacturing" and b["peers"] == 40


def test_unknown_sic_uses_all_companies_and_missing_value_has_no_band(fake_table):
    out = peers.percentiles({"net_leverage": 1.0, "current_ratio": None}, "x", None, "2024-12-31")["bands"]
    assert out["net_leverage"]["group"] == "all non-financial companies" and "current_ratio" not in out


def test_each_peer_counts_once_with_its_latest_year(fake_table):
    b = peers.percentiles({"net_leverage": 10.0}, "x", 2040, "2025-12-31")["bands"]["net_leverage"]
    assert b["years"] == "FY2023-2025" and b["peers"] == 30           # company 5 counted once, with FY2024


def test_52_53_week_year_label():
    assert peers.fiscal_year("2026-01-03") == 2025 and peers.fiscal_year("2025-12-27") == 2025
    assert peers.fiscal_year("2025-01-31") == 2025


def test_real_peer_table_is_the_lending_population():
    t = peers.table()
    assert len(t["_rows"]) == 4435 and not any(60 <= r["_major"] <= 67 for r in t["_rows"])   # no financials
    assert set(t["metrics"]) >= {"net_leverage", "ebitda_interest_cover", "altman_z2", "ohlson_o"}
