"""Offline SEC for tests and local browser runs: CREDITLENS_SEC_FIXTURES=<dir> serves SEC URLs from files.

Never set in production. Files: company_tickers_exchange.json, submissions_<cik10>.json,
companyfacts_<cik10>.json(.gz); anything missing answers 404, as SEC does for an unknown record.
"""
from __future__ import annotations

import gzip
import re
from pathlib import Path

import httpx


def transport(folder: str | Path) -> httpx.MockTransport:
    root = Path(folder)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        name = None
        if path.endswith("/files/company_tickers_exchange.json"):
            name = "company_tickers_exchange.json"
        elif m := re.search(r"/submissions/CIK(\d{10})\.json$", path):
            name = f"submissions_{m.group(1)}.json"
        elif m := re.search(r"/companyfacts/CIK(\d{10})\.json$", path):
            name = f"companyfacts_{m.group(1)}.json"
        if name:
            for p in (root / name, root / f"{name}.gz"):
                if p.exists():
                    body = gzip.decompress(p.read_bytes()) if p.suffix == ".gz" else p.read_bytes()
                    return httpx.Response(200, content=body, headers={"content-type": "application/json"})
        return httpx.Response(404, text="Not Found")

    return httpx.MockTransport(handler)
