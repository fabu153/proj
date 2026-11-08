"""Search any U.S. public company and load its SEC filings into the same pipeline as the curated samples.

* The search index is SEC's own company/ticker list (company_tickers_exchange.json), fetched server side through
  SECClient and kept for a day. The browser only ever talks to this API (through the site's /api proxy).
* A selected company's companyfacts and identity record are fetched through SECClient (throttled, cached for 12
  hours on local disk and in memory) and normalised by the unchanged XBRL pipeline: original vintages, point-in-time
  availability dates, accession numbers and derivation rules all apply exactly as for the curated issuers.
* Nothing is invented: a company without supported us-gaap annual statements is reported as such, not filled in.
"""
from __future__ import annotations

import os
import re
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .sec_client import SECClient, SECError

CACHE_DIR = Path(os.environ.get("CREDITLENS_SEC_CACHE", "/tmp/creditlens-sec"))
INDEX_TTL_S = 24 * 3600
FACTS_TTL_S = 12 * 3600
MAX_LOADED = 32                      # companies kept in memory; each compact companyfacts is a few hundred kB
MAX_QUERY = 80

_client: Optional[SECClient] = None
_client_lock = threading.Lock()


def client() -> SECClient:
    """One shared, throttled client for the live app: short retries so a user is never kept waiting a minute."""
    global _client
    with _client_lock:
        if _client is None:
            fx = os.environ.get("CREDITLENS_SEC_FIXTURES")
            if fx:                                     # tests / offline browser runs only
                from .sec_fixtures import transport
                _client = SECClient(cache_dir=CACHE_DIR / "fixtures", retries=2, backoff_s=0.01, timeout_s=5,
                                    transport=transport(fx))
            else:
                _client = SECClient(cache_dir=CACHE_DIR, retries=2, backoff_s=1.0, timeout_s=20)
        return _client


def set_client(c: Optional[SECClient]) -> None:
    """Tests inject a client whose HTTP transport is mocked; no test talks to SEC."""
    global _client, _index
    with _client_lock:
        _client = c
    _index = None
    _loaded.clear()


# ------------------------------------------------------------------ search index
_NORM = re.compile(r"[^A-Z0-9 ]+")


def _norm(s: str) -> str:
    return " ".join(_NORM.sub(" ", s.upper().replace("&", " AND ")).split())


def _ticker(s: str) -> str:
    return s.strip().upper().replace(".", "-").replace("/", "-")


class CompanyIndex:
    def __init__(self, raw: dict, source: str, retrieved_at: Optional[str]):
        fields = raw.get("fields") or ["cik", "name", "ticker", "exchange"]
        pos = {f: i for i, f in enumerate(fields)}
        by_cik: "OrderedDict[str, dict]" = OrderedDict()
        for rank, row in enumerate(raw.get("data", [])):
            try:
                cik = str(int(row[pos["cik"]])).zfill(10)
            except (TypeError, ValueError, KeyError, IndexError):
                continue
            name = str(row[pos["name"]] or "").strip()
            if not name:
                continue
            e = by_cik.setdefault(cik, {"cik": cik, "name": name, "tickers": [], "exchanges": [], "rank": rank,
                                        "_n": _norm(name)})
            t, x = row[pos["ticker"]], row[pos["exchange"]] if "exchange" in pos else None
            if t and t not in e["tickers"]:
                e["tickers"].append(str(t))
            if x and x not in e["exchanges"]:
                e["exchanges"].append(str(x))
        self.entries = list(by_cik.values())
        self.by_cik = by_cik
        self.by_ticker = {_ticker(t): e for e in self.entries for t in e["tickers"]}
        self.source, self.retrieved_at = source, retrieved_at

    def search(self, q: str, limit: int = 10) -> list[dict]:
        q = q.strip()
        cikq = re.fullmatch(r"(?:CIK)?\s*0*(\d{1,10})", q, flags=re.I)
        scored: dict[str, tuple[int, dict, str]] = {}

        def add(e: dict, score: int, how: str):
            if e["cik"] not in scored or scored[e["cik"]][0] < score:
                scored[e["cik"]] = (score, e, how)

        if cikq:
            e = self.by_cik.get(cikq.group(1).zfill(10))
            if e:
                add(e, 100, "cik")
        t = _ticker(q)
        if t in self.by_ticker:
            add(self.by_ticker[t], 95, "ticker")
        nq = _norm(q)
        if nq:
            words = nq.split()
            for e in self.entries:
                n = e["_n"]
                if n == nq:
                    add(e, 90, "name")
                elif n.startswith(nq):
                    add(e, 80, "name")
                elif len(t) >= 2 and any(_ticker(x).startswith(t) for x in e["tickers"]):
                    add(e, 70, "ticker")
                else:
                    nw = n.split()
                    if all(any(w2.startswith(w) for w2 in nw) for w in words):
                        add(e, 60, "name")
                    elif len(nq) >= 3 and nq in n:
                        add(e, 50, "name")
        ranked = sorted(scored.values(), key=lambda r: (-r[0], r[1]["rank"], r[1]["name"]))
        return [{"company_id": e["cik"], "cik": e["cik"], "name": e["name"], "tickers": e["tickers"],
                 "exchanges": e["exchanges"], "match": how} for _, e, how in ranked[:limit]]


_index: Optional[CompanyIndex] = None
_index_at = 0.0
_index_lock = threading.Lock()


def index() -> CompanyIndex:
    """SEC's list, refreshed daily. If SEC cannot be reached, a list fetched earlier is used and labelled as such."""
    global _index, _index_at
    with _index_lock:
        if _index is not None and time.time() - _index_at < INDEX_TTL_S:
            return _index
        c = client()
        try:
            raw = c.company_tickers(max_age_s=INDEX_TTL_S)
            _index = CompanyIndex(raw, "SEC EDGAR company list", _mtime(c, "company_tickers_exchange"))
        except SECError:
            if _index is not None:               # serve yesterday's list rather than nothing; retry next call
                return _index
            stale = c.cache_dir / "company_tickers_exchange.json.gz"
            if not stale.exists():
                raise
            import gzip
            import json
            with gzip.open(stale, "rt") as fh:
                _index = CompanyIndex(json.load(fh), "SEC EDGAR company list (cached copy; SEC unreachable)",
                                      _mtime(c, "company_tickers_exchange"))
            return _index
        _index_at = time.time()
        return _index


def _mtime(c: SECClient, name: str) -> Optional[str]:
    p = c.cache_dir / f"{name}.json.gz"
    return datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if p.exists() else None


def search(q: str, limit: int = 10) -> dict:
    ix = index()
    return {"query": q, "results": ix.search(q, limit), "index": {"source": ix.source, "retrieved_at": ix.retrieved_at,
                                                                   "companies": len(ix.entries)}}


# ------------------------------------------------------------------ live company load
_loaded: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()
_load_lock = threading.Lock()


def is_cik(company_id: str) -> bool:
    return bool(re.fullmatch(r"\d{10}", company_id or ""))


def loaded() -> dict[str, dict]:
    """Companies already fetched in this process (newest last), without touching SEC."""
    now = time.time()
    return {k: cf for k, (t, cf) in list(_loaded.items()) if now - t < FACTS_TTL_S}


def load(cik: str) -> dict:
    """companyfacts for one filer, tagged with its SEC identity record. Raises SECError."""
    cik10 = str(int(cik)).zfill(10)
    with _load_lock:
        hit = _loaded.get(cik10)
        if hit and time.time() - hit[0] < FACTS_TTL_S:
            _loaded.move_to_end(cik10)
            return hit[1]
    c = client()
    meta = c.submissions_meta(cik10, max_age_s=FACTS_TTL_S)
    if str(meta.get("cik") or "").lstrip("0") not in ("", cik10.lstrip("0")):
        raise SECError("unavailable", f"SEC returned the record of CIK {meta.get('cik')} for CIK {cik10}.")
    try:
        cf = dict(c.company_facts(cik10, max_age_s=FACTS_TTL_S))
    except SECError as e:
        if e.kind != "not_found":
            raise
        # SEC has the filer but no XBRL financial data (e.g. an older filer or a fund): an honest empty record
        cf = {"cik": int(cik10), "entityName": meta.get("name"), "facts": {}}
    if cf.get("cik") not in (None, "") and str(cf["cik"]).lstrip("0") != cik10.lstrip("0"):
        raise SECError("unavailable", f"SEC returned the facts of CIK {cf.get('cik')} for CIK {cik10}.")
    cf["cik"] = int(cik10)
    cf["entityName"] = cf.get("entityName") or meta.get("name") or cik10
    cf["source"] = "SEC XBRL companyfacts (loaded on request)"
    cf["sec_meta"] = {k: meta.get(k) for k in ("name", "sic", "sicDescription", "tickers", "exchanges",
                                               "fiscalYearEnd", "category", "stateOfIncorporation")}
    cf["sic"] = meta.get("sic")
    cf["retrieved_at"] = _mtime(c, f"companyfacts_{cik10}") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    with _load_lock:
        _loaded[cik10] = (time.time(), cf)
        _loaded.move_to_end(cik10)
        while len(_loaded) > MAX_LOADED:
            _loaded.popitem(last=False)
    return cf
