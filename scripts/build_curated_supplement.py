"""Build backend/data/curated/supplement/: v1.6 credit-only XBRL tags for the three curated issuers.

    SEC_USER_AGENT="Name email" python -m scripts.build_curated_supplement

The curated companyfacts files are frozen by the release manifest (v1.2.0), so they are not rewritten. The new
credit-only tags (debt maturity schedule, retained earnings) are fetched from SEC and stored next to them; the API
merges them at load time. Supplemental tags never reach the model basis (xbrl.SUPPLEMENTAL_REGISTRY).
"""
import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

from backend.app.documents.sec_client import SECClient
from backend.app.documents.xbrl import SUPPLEMENTAL_REGISTRY

CURATED = Path("backend/data/curated")
NEW = ["debt_maturity_y1", "debt_maturity_y2", "debt_maturity_y3", "debt_maturity_y4", "debt_maturity_y5",
       "debt_maturity_after5", "retained_earnings"]


def main():
    tags = {t for f in NEW for t in SUPPLEMENTAL_REGISTRY[f][1]}
    client = SECClient(cache_dir=Path("/tmp/creditlens-supplement"))
    out = CURATED / "supplement"
    out.mkdir(exist_ok=True)
    for p in sorted(CURATED.glob("companyfacts_*.json.gz")):
        cik = p.stem.split("_")[1].split(".")[0]
        raw, sha = client._fetch(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
        ug = raw["facts"]["us-gaap"]
        sup = {"cik": int(cik), "entityName": raw.get("entityName"), "source_sha256": sha,
               "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
               "facts": {"us-gaap": {t: {"units": {"USD": ug[t]["units"].get("USD", [])}} for t in sorted(tags) if t in ug}}}
        with gzip.open(out / f"supplement_{cik}.json.gz", "wt") as fh:
            json.dump(sup, fh)
        print(cik, raw.get("entityName"), sorted(sup["facts"]["us-gaap"]))


if __name__ == "__main__":
    main()
