"""Regenerate docs/samples/*.pdf: one committee memo per sample issuer, with the loan lab's default inputs.

    python scripts/make_samples.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
os.environ["CREDITLENS_DB"] = os.path.join(tempfile.mkdtemp(), "samples.db")
os.environ["CREDITLENS_CURATED"] = "backend/data/curated"
os.environ["CREDITLENS_LLM_PROVIDER"] = "none"

from fastapi.testclient import TestClient  # noqa: E402

from backend.app.api.main import app  # noqa: E402

LAB_DEFAULTS = {  # same as the loan lab on first load (frontend/components/LoanLab.tsx)
    "facility": {"amount": 100, "currency": "USD", "coupon": 0.06, "floating": True, "tenor_years": 5,
                 "annual_amortization": 0, "use_of_proceeds": "capex"},
    "covenants": {"max_net_leverage": 3.5, "min_ebitda_interest_cover": 3.0},
    "existing_floating_share": 0.0,
    "shocks": [{"name": "Base", "ebitda_shock": 0, "rate_shock_bps": 0},
               {"name": "Downside", "ebitda_shock": -0.2, "rate_shock_bps": 200},
               {"name": "Severe", "ebitda_shock": -0.35, "rate_shock_bps": 400},
               {"name": "Your case", "ebitda_shock": -0.1, "rate_shock_bps": 100}],
}

c = TestClient(app)
for cid, slug in (("0000080424", "procter_gamble"), ("0001067701", "united_rentals"), ("0001278027", "bg_foods")):
    m = c.post("/memos", json={"company_id": cid, **LAB_DEFAULTS}).json()
    pdf = c.get(f"/memos/{m['id']}/pdf").content
    Path(f"docs/samples/credit_memo_{slug}.pdf").write_bytes(pdf)
    print(slug, "snapshot", m["snapshot"]["id"], m["summary"], f"{len(pdf):,} bytes")
