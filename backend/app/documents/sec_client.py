"""Polite SEC EDGAR client with on-disk cache (Blueprint p.05: fair-access guidance).

* SEC asks automated clients to identify themselves. Set SEC_USER_AGENT to your app name
  and contact email (e.g. "CreditLens-Capstone you@school.edu"); a generic name is used otherwise.
* Throttled to <= 4 requests/second (SEC limit is 10).
* companyfacts are cached in COMPACT form: only the us-gaap tags in TAG_REGISTRY are kept,
  which shrinks each file ~20-50x while preserving every field the pipeline uses. The raw
  response hash is logged so the compaction is auditable, and the tag list is saved in the file:
  a file cut with fewer tags than the code now reads is reported, never silently used as complete.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

BASE = "https://data.sec.gov"
WWW = "https://www.sec.gov"
DEFAULT_CACHE = Path(os.environ.get("CREDITLENS_DATA", "training/data")) / "raw" / "sec"
MIN_INTERVAL_S = 0.25
MAX_RETRY_AFTER_S = 10           # SEC asking for a longer pause is answered at once, not waited out
DEFAULT_UA = "CreditLens-Capstone academic research project"
TAGS_KEY = "cached_tags"          # the XBRL tag list a compact companyfacts file was cut with

log = logging.getLogger("creditlens")
_warned: set = set()


class SECError(Exception):
    """kind: "not_found" (no such filer / file), "throttled" (SEC asked us to slow down), "unavailable" (network,
    SEC error, or a request SEC refused, e.g. a User-Agent without contact details)."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def _check_tags(cached: list | None, needed: set, name: str) -> None:
    """A cached file keeps only the tags read when it was saved. If the code now reads more, those figures would be
    silently unavailable for the company; say so loudly (once per run for each kind) and leave the re-download to
    the operator: refresh=True, e.g. `build_panel --refresh`. Nothing is fetched automatically, because a new
    download brings the filings made since and can change a frozen panel."""
    if cached is None:
        key = "untracked"
        msg = (f"{name}.json.gz (and possibly other cached companyfacts files) was saved before cache files recorded "
               "their XBRL tag list, so it may lack tags added to TAG_REGISTRY or SUPPLEMENTAL_REGISTRY since; their "
               "figures would read as unavailable. If tags were added, re-download with refresh=True "
               "(build_panel --refresh).")
    else:
        missing = needed - set(cached)
        if not missing:
            return
        key = frozenset(missing)
        msg = (f"{name}.json.gz (and possibly other cached companyfacts files) was saved before these XBRL tags were "
               f"read: {', '.join(sorted(missing))}. Their figures read as unavailable until the file is downloaded "
               "again with refresh=True (build_panel --refresh).")
    if key not in _warned:
        _warned.add(key)
        log.warning(msg)


def _retry_after(r: httpx.Response, default: float) -> float:
    """Seconds SEC asks us to wait (Retry-After, in seconds or as an HTTP date), or our own backoff when it does not
    say."""
    value = r.headers.get("retry-after")
    if value is None:
        return default
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return default
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


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
            for attempt in range(max(1, self.retries)):        # retries=0 still makes the request
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
                    pause = _retry_after(r, self.backoff_s * 2 ** attempt)
                    if attempt + 1 < self.retries and pause <= MAX_RETRY_AFTER_S:
                        time.sleep(pause)
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
        # abs(): a file stamped in the future (clock change) is not fresh forever
        fresh = path.exists() and (max_age_s is None or abs(time.time() - path.stat().st_mtime) < max_age_s)
        if fresh and not refresh:
            try:
                with gzip.open(path, "rt") as fh:
                    return json.load(fh)
            except (OSError, EOFError, ValueError):     # damaged file (e.g. a write cut short): fetch it again
                pass
        data, sha = self._fetch(url)
        if transform:
            data = transform(data)
        # written next to the target and renamed into place, so a reader never sees a half-written file
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            with gzip.open(tmp, "wt") as fh:
                json.dump(data, fh)
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)           # gone after the rename; removed if writing failed
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
                                          for t, v in ug.items() if t in keep}},
                    TAGS_KEY: sorted(keep)}
        cik10 = str(cik).zfill(10)
        name = f"companyfacts_{cik10}"
        data = self._cached(f"{BASE}/api/xbrl/companyfacts/CIK{cik10}.json", name, refresh, compact, max_age_s)
        _check_tags(data.get(TAGS_KEY), keep, name)
        return {k: v for k, v in data.items() if k != TAGS_KEY}

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
