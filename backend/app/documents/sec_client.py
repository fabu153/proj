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
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE = "https://data.sec.gov"
WWW = "https://www.sec.gov"
DEFAULT_CACHE = Path(os.environ.get("CREDITLENS_DATA", "training/data")) / "raw" / "sec"
MIN_INTERVAL_S = 0.25
DEFAULT_UA = "CreditLens-Capstone academic research project"


class SECError(Exception):
    """kind: "not_found" (no such filer / file), "throttled" (SEC asked us to slow down), "unavailable" (network,
    SEC error, or a request SEC refused, e.g. a User-Agent without contact details)."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


class SECClient:
    def __init__(self, user_agent: str | None = None, cache_dir: Path = DEFAULT_CACHE, *, retries: int = 4,
                 backoff_s: float = 1.0, timeout_s: float = 60, transport: httpx.BaseTransport | None = None):
        ua = user_agent or os.environ.get("SEC_USER_AGENT") or DEFAULT_UA
        self.user_agent = ua
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._http = httpx.Client(headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}, timeout=timeout_s,
                                  transport=transport)
        self._last = 0.0
        self._lock = threading.Lock()          # the API serves requests on several threads: one SEC call at a time
        self.retries, self.backoff_s = retries, backoff_s

    # ------------------------------------------------------------------ low level
    def _fetch(self, url: str) -> tuple[dict, str]:
        with self._lock:
            for attempt in range(self.retries):
                wait = MIN_INTERVAL_S - (time.monotonic() - self._last)
                if wait > 0:
                    time.sleep(wait)
                try:
                    r = self._http.get(url)
                except httpx.HTTPError as e:
                    self._last = time.monotonic()
                    if attempt + 1 < self.retries:
                        time.sleep(self.backoff_s * 2 ** attempt)
                        continue
                    raise SECError("unavailable", f"SEC EDGAR could not be reached ({type(e).__name__}).") from e
                self._last = time.monotonic()
                if r.status_code in (429, 503):
                    if attempt + 1 < self.retries:
                        time.sleep(self.backoff_s * 2 ** attempt)
                        continue
                    raise SECError("throttled", "SEC EDGAR is limiting requests right now; try again in a minute.")
                if r.status_code == 404:
                    raise SECError("not_found", f"SEC EDGAR has no such record ({url.rsplit('/', 1)[-1]}).")
                if r.status_code == 403:
                    raise SECError("unavailable", "SEC EDGAR refused the request (it requires a User-Agent with a "
                                                  "contact email: set SEC_USER_AGENT).")
                if r.status_code >= 400:
                    raise SECError("unavailable", f"SEC EDGAR answered {r.status_code}.")
                try:
                    return r.json(), hashlib.sha256(r.content).hexdigest()
                except ValueError as e:
                    raise SECError("unavailable", "SEC EDGAR returned a response that is not JSON.") from e
        raise SECError("throttled", "SEC EDGAR is limiting requests right now; try again in a minute.")

    def _cached(self, url: str, name: str, refresh: bool, transform=None, max_age_s: float | None = None) -> dict:
        """On-disk cache. max_age_s=None keeps a file forever (training snapshots); the live app passes a TTL."""
        path = self.cache_dir / f"{name}.json.gz"
        fresh = path.exists() and (max_age_s is None or time.time() - path.stat().st_mtime < max_age_s)
        if fresh and not refresh:
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
    def company_facts(self, cik: str | int, refresh: bool = False, max_age_s: float | None = None) -> dict:
        from .xbrl import SUPPLEMENTAL_REGISTRY, TAG_REGISTRY
        keep = {t for _, tags in {**TAG_REGISTRY, **SUPPLEMENTAL_REGISTRY}.values() for t in tags}

        def compact(d: dict) -> dict:
            ug = d.get("facts", {}).get("us-gaap", {})
            return {"cik": d.get("cik"), "entityName": d.get("entityName"),
                    "facts": {"us-gaap": {t: {"units": {"USD": v.get("units", {}).get("USD", [])}}
                                          for t, v in ug.items() if t in keep}}}
        cik10 = str(cik).zfill(10)
        return self._cached(f"{BASE}/api/xbrl/companyfacts/CIK{cik10}.json", f"companyfacts_{cik10}", refresh, compact,
                            max_age_s)

    def submissions_meta(self, cik: str | int, refresh: bool = False, max_age_s: float | None = None) -> dict:
        """Only the identity fields (SIC, name, tickers, state) — filing lists are dropped."""
        def compact(d: dict) -> dict:
            return {k: d.get(k) for k in ("cik", "name", "sic", "sicDescription", "tickers", "exchanges",
                                          "stateOfIncorporation", "fiscalYearEnd", "category")}
        cik10 = str(cik).zfill(10)
        return self._cached(f"{BASE}/submissions/CIK{cik10}.json", f"submissions_{cik10}", refresh, compact, max_age_s)

    def company_tickers(self, refresh: bool = False, max_age_s: float | None = None) -> dict:
        """SEC's list of operating companies with a ticker: {"fields": [cik, name, ticker, exchange], "data": [...]}."""
        return self._cached(f"{WWW}/files/company_tickers_exchange.json", "company_tickers_exchange", refresh,
                            max_age_s=max_age_s)

    def frame(self, tag: str, period: str, refresh: bool = False) -> dict:
        """e.g. frame('Assets', 'CY2016Q4I') — one value per filer for that period."""
        return self._cached(f"{BASE}/api/xbrl/frames/us-gaap/{tag}/USD/{period}.json", f"frame_{tag}_{period}", refresh)
