"""Polite SEC EDGAR client with on-disk cache (Blueprint p.05: fair-access guidance).

* SEC asks automated clients to identify themselves. Set SEC_USER_AGENT to your app name
  and contact email (e.g. "CreditLens-Capstone you@school.edu"); a generic name is used otherwise.
* Throttled to <= 4 requests/second (SEC limit is 10).
* companyfacts are cached in COMPACT form: only the us-gaap tags in TAG_REGISTRY are kept,
  which shrinks each file ~20-50x while preserving every field the pipeline uses. The raw
  response hash is logged so the compaction is auditable.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE = "https://data.sec.gov"
DEFAULT_CACHE = Path(os.environ.get("CREDITLENS_DATA", "training/data")) / "raw" / "sec"
MIN_INTERVAL_S = 0.25
DEFAULT_UA = "CreditLens-Capstone academic research project"


class SECClient:
    def __init__(self, user_agent: str | None = None, cache_dir: Path = DEFAULT_CACHE):
        ua = user_agent or os.environ.get("SEC_USER_AGENT") or DEFAULT_UA
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._http = httpx.Client(headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}, timeout=60)
        self._last = 0.0

    # ------------------------------------------------------------------ low level
    def _fetch(self, url: str) -> tuple[dict, str]:
        for attempt in range(4):
            wait = MIN_INTERVAL_S - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            r = self._http.get(url)
            self._last = time.monotonic()
            if r.status_code in (429, 503):
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r.json(), hashlib.sha256(r.content).hexdigest()
        r.raise_for_status()
        raise RuntimeError(f"SEC throttled {url}")

    def _cached(self, url: str, name: str, refresh: bool, transform=None) -> dict:
        path = self.cache_dir / f"{name}.json.gz"
        if path.exists() and not refresh:
            with gzip.open(path, "rt") as fh:
                return json.load(fh)
        data, sha = self._fetch(url)
        if transform:
            data = transform(data)
        with gzip.open(path, "wt") as fh:
            json.dump(data, fh)
        with (self.cache_dir / "access_log.jsonl").open("a") as log:
            log.write(json.dumps({"url": url, "file": path.name, "raw_sha256": sha,
                                  "retrieved_at": datetime.now(timezone.utc).isoformat()}) + "\n")
        return data

    # ------------------------------------------------------------------ endpoints
    def company_facts(self, cik: str | int, refresh: bool = False) -> dict:
        from .xbrl import SUPPLEMENTAL_REGISTRY, TAG_REGISTRY
        keep = {t for _, tags in {**TAG_REGISTRY, **SUPPLEMENTAL_REGISTRY}.values() for t in tags}

        def compact(d: dict) -> dict:
            ug = d.get("facts", {}).get("us-gaap", {})
            return {"cik": d.get("cik"), "entityName": d.get("entityName"),
                    "facts": {"us-gaap": {t: {"units": {"USD": v.get("units", {}).get("USD", [])}}
                                          for t, v in ug.items() if t in keep}}}
        cik10 = str(cik).zfill(10)
        return self._cached(f"{BASE}/api/xbrl/companyfacts/CIK{cik10}.json", f"companyfacts_{cik10}", refresh, compact)

    def submissions_meta(self, cik: str | int, refresh: bool = False) -> dict:
        """Only the identity fields (SIC, name, tickers, state) — filing lists are dropped."""
        def compact(d: dict) -> dict:
            return {k: d.get(k) for k in ("cik", "name", "sic", "sicDescription", "tickers", "exchanges",
                                          "stateOfIncorporation", "fiscalYearEnd", "category")}
        cik10 = str(cik).zfill(10)
        return self._cached(f"{BASE}/submissions/CIK{cik10}.json", f"submissions_{cik10}", refresh, compact)

    def frame(self, tag: str, period: str, refresh: bool = False) -> dict:
        """e.g. frame('Assets', 'CY2016Q4I') — one value per filer for that period."""
        return self._cached(f"{BASE}/api/xbrl/frames/us-gaap/{tag}/USD/{period}.json", f"frame_{tag}_{period}", refresh)
