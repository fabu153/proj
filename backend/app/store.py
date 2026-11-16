"""Small SQLite store for uploaded documents, reviewed facts, memos and the audit trail.

Data minimization: the uploaded PDF itself is NEVER written to disk or the database. It is parsed
in memory during the upload request; only its SHA-256, page citations, short line snippets and the
extracted numbers are kept, and DELETE /documents/{id} removes those too. Rows are purged
automatically after RETENTION_HOURS. On Render's free plan the database lives on ephemeral disk.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, Optional

DB_PATH = os.environ.get("CREDITLENS_DB", "/tmp/creditlens.db")
RETENTION_HOURS = int(os.environ.get("CREDITLENS_RETENTION_HOURS", "24"))
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY, company_id TEXT UNIQUE, filename TEXT, sha256 TEXT, pages INTEGER,
  company_name TEXT, currency TEXT, scale_label TEXT, fiscal_year_end TEXT, fye_inferred INTEGER,
  statement_pages TEXT, issues TEXT, status TEXT, created_at TEXT, finalized_at TEXT);
CREATE TABLE IF NOT EXISTS facts (
  id TEXT PRIMARY KEY, document_id TEXT REFERENCES documents(id) ON DELETE CASCADE, field TEXT, period TEXT,
  value REAL, page INTEGER, label TEXT, snippet TEXT, statement TEXT, confidence TEXT, reasons TEXT,
  status TEXT, reviewed_value REAL, reviewer_note TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS memos (
  id TEXT PRIMARY KEY, company_id TEXT, fiscal_year_end TEXT, created_at TEXT, body TEXT);
CREATE TABLE IF NOT EXISTS audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, subject TEXT, detail TEXT);
"""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


MIGRATIONS = ["ALTER TABLE documents ADD COLUMN sec_check TEXT"]
_migrated: set[str] = set()


@contextmanager
def conn() -> Iterator[sqlite3.Connection]:
    with _lock:
        c = sqlite3.connect(DB_PATH)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        try:
            c.executescript(SCHEMA)
            if DB_PATH not in _migrated:          # additive column migrations for databases created by v1.0
                for m in MIGRATIONS:
                    try:
                        c.execute(m)
                    except sqlite3.OperationalError:
                        pass                      # column already exists
                _migrated.add(DB_PATH)
            yield c
            c.commit()
        finally:
            c.close()


def audit(kind: str, subject: str, **detail: Any) -> None:
    with conn() as c:
        c.execute("INSERT INTO audit_events(ts, kind, subject, detail) VALUES (?,?,?,?)",
                  (now(), kind, subject, json.dumps(detail, default=str)))


def audit_log(subject: Optional[str] = None, limit: int = 200) -> list[dict]:
    with conn() as c:
        q = "SELECT * FROM audit_events" + (" WHERE subject = ?" if subject else "") + " ORDER BY id DESC LIMIT ?"
        rows = c.execute(q, ((subject, limit) if subject else (limit,))).fetchall()
    return [{**dict(r), "detail": json.loads(r["detail"])} for r in rows]


def _cutoff() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=RETENTION_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _delete_document_rows(c: sqlite3.Connection, doc_id: str, company_id: str) -> None:
    """An upload's figures live in its facts and in every memo written about it; all of them go together."""
    c.execute("DELETE FROM facts WHERE document_id = ?", (doc_id,))
    c.execute("DELETE FROM memos WHERE company_id = ?", (company_id,))
    c.execute("DELETE FROM documents WHERE id = ?", (doc_id,))


def purge_expired() -> int:
    with conn() as c:
        rows = c.execute("SELECT id, company_id FROM documents WHERE created_at < ?", (_cutoff(),)).fetchall()
        for r in rows:
            _delete_document_rows(c, r["id"], r["company_id"])
        c.execute("DELETE FROM memos WHERE company_id LIKE 'doc%' AND company_id NOT IN "
                  "(SELECT company_id FROM documents)")
    for r in rows:
        audit("document_expired", r["id"])
    return len(rows)


_last_purge = 0.0


def _purge_if_due() -> None:
    """Expired uploads are removed while the service runs, not only when it restarts (at most every 10 minutes)."""
    global _last_purge
    if time.monotonic() - _last_purge > 600:
        _last_purge = time.monotonic()
        purge_expired()


# ------------------------------------------------------------------ documents
def clean_name(name: str) -> str:
    """One line of printable text: a company name is shown, printed and quoted to a writer, never a block of text."""
    return " ".join("".join(ch if ch.isprintable() else " " for ch in name).split())[:120]


def create_document(*, filename: str, sha256: str, extraction: dict, company_name: str) -> str:
    doc_id = uuid.uuid4().hex
    company_id = f"doc{doc_id}"     # unguessable: an upload is reachable only by whoever holds its link
    with conn() as c:
        c.execute("INSERT INTO documents (id, company_id, filename, sha256, pages, company_name, currency, scale_label, "
                  "fiscal_year_end, fye_inferred, statement_pages, issues, status, created_at, finalized_at, sec_check) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (doc_id, company_id, filename[:200], sha256, extraction["pages"], clean_name(company_name),
                   extraction["currency"], extraction["scale_label"], extraction["fiscal_year_end"],
                   int(extraction["fiscal_year_end_inferred"]), json.dumps(extraction["statement_pages"]),
                   json.dumps(extraction["issues"]), "in_review", now(), None,
                   extraction.get("sec_check") or "Not checked against SEC"))
        for cand in extraction["candidates"]:
            status = "needs_review" if cand["needs_review"] else "auto_accepted"
            c.execute("INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (uuid.uuid4().hex, doc_id, cand["field"], cand["period"], cand["value"], cand["page"],
                       cand["label"][:200], cand["snippet"][:300], cand["statement"], cand["confidence"],
                       json.dumps(cand["reasons"]), status, None, None, now()))
    return doc_id


def get_document(doc_id: str) -> Optional[dict]:
    """By its private id only: the analysis link (company_id) may be shared, but it must not open or delete the
    upload's review. Past the retention window a document no longer exists, even before it is purged."""
    return _document("id", doc_id)


def get_finalized(company_id: str) -> Optional[dict]:
    """A finalized upload by the company id its analysis link uses."""
    d = _document("company_id", company_id)
    return d if d and d["status"] == "finalized" else None


def _document(key: str, value: str) -> Optional[dict]:
    _purge_if_due()
    with conn() as c:
        d = c.execute(f"SELECT * FROM documents WHERE {key} = ? AND created_at >= ?", (value, _cutoff())).fetchone()
        if not d:
            return None
        facts = c.execute("SELECT * FROM facts WHERE document_id = ? ORDER BY period, field", (d["id"],)).fetchall()
    out = dict(d)
    out["statement_pages"] = json.loads(out["statement_pages"])
    out["issues"] = json.loads(out["issues"])
    out["fye_inferred"] = bool(out["fye_inferred"])
    out["facts"] = [{**dict(f), "reasons": json.loads(f["reasons"])} for f in facts]
    return out


def review_fact(fact_id: str, decision: str, value: Optional[float], note: Optional[str]) -> dict:
    status = {"accept": "accepted", "correct": "corrected", "reject": "rejected"}[decision]
    with conn() as c:
        f = c.execute("SELECT * FROM facts WHERE id = ?", (fact_id,)).fetchone()
        if not f:
            raise KeyError(fact_id)
        d = c.execute("SELECT status FROM documents WHERE id = ? AND created_at >= ?",
                      (f["document_id"], _cutoff())).fetchone()
        if not d:
            raise KeyError(fact_id)                   # its document expired: it no longer exists
        if d["status"] == "finalized":
            raise PermissionError("Document already finalized; delete and re-upload to change figures")
        c.execute("UPDATE facts SET status = ?, reviewed_value = ?, reviewer_note = ?, updated_at = ? WHERE id = ?",
                  (status, value if decision == "correct" else None, (note or "")[:500], now(), fact_id))
    audit("fact_reviewed", f["document_id"], fact=f["field"], period=f["period"], decision=decision,
          old=f["value"], new=value, note=note)
    return {"id": fact_id, "status": status}


def set_document_meta(doc_id: str, fiscal_year_end: Optional[str], company_name: Optional[str],
                      currency: Optional[str] = None, scale_label: Optional[str] = None) -> None:
    from .documents.uploads import SCALES
    with conn() as c:
        d = c.execute("SELECT status, scale_label FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if d["status"] == "finalized":
            raise PermissionError("Document already finalized; delete and re-upload to change it")
        if fiscal_year_end:
            c.execute("UPDATE documents SET fiscal_year_end = ?, fye_inferred = 0 WHERE id = ?", (fiscal_year_end, doc_id))
        if company_name and clean_name(company_name):
            c.execute("UPDATE documents SET company_name = ? WHERE id = ?", (clean_name(company_name), doc_id))
        if currency:
            c.execute("UPDATE documents SET currency = ? WHERE id = ?", (currency, doc_id))
        if scale_label and scale_label != d["scale_label"]:
            # extracted values were stored at the previously assumed scale (unconfirmed = as printed); rescale them.
            # Analyst-entered and corrected values are already in currency units (the UI sends millions x 1e6).
            factor = SCALES[scale_label] / SCALES.get(d["scale_label"] or "units", 1.0)
            c.execute("UPDATE facts SET value = value * ? WHERE document_id = ? "
                      "AND status NOT IN ('manual', 'unavailable')", (factor, doc_id))
            c.execute("UPDATE documents SET scale_label = ? WHERE id = ?", (scale_label, doc_id))
    audit("document_meta_updated", doc_id, fiscal_year_end=fiscal_year_end, company_name=company_name,
          currency=currency, scale_label=scale_label)


def add_fact(doc_id: str, field: str, period: str, value: Optional[float], page: Optional[int],
             note: Optional[str]) -> str:
    """An analyst-entered figure (status manual) or an explicit 'not available' (status unavailable)."""
    fact_id = uuid.uuid4().hex
    status = "unavailable" if value is None else "manual"
    with conn() as c:
        d = c.execute("SELECT status FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if d["status"] == "finalized":
            raise PermissionError("Document already finalized; delete and re-upload to change figures")
        c.execute("DELETE FROM facts WHERE document_id = ? AND field = ? AND period = ? AND status IN "
                  "('manual', 'unavailable')", (doc_id, field, period))
        c.execute("INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (fact_id, doc_id, field, period, value, page or 0,
                   "Entered by analyst" if value is not None else "Marked unavailable by analyst",
                   (note or "")[:300], "manual", "manual", json.dumps([]), status, None, (note or "")[:500], now()))
    audit("fact_added", doc_id, fact=field, period=period, value=value, status=status, note=note)
    return fact_id


def finalize(doc_id: str) -> bool:
    """Finalizes once: finalized_at is the uploaded company's filing date, so a repeat (e.g. a retry after a lost
    response) changes nothing. Returns whether this call finalized it."""
    with conn() as c:
        done = c.execute("UPDATE documents SET status = 'finalized', finalized_at = ? "
                         "WHERE id = ? AND status != 'finalized'", (now(), doc_id)).rowcount
    if done:
        audit("document_finalized", doc_id)
    return bool(done)


def delete_document(doc_id: str) -> bool:
    with conn() as c:
        d = c.execute("SELECT id, company_id FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if not d:
            return False
        _delete_document_rows(c, d["id"], d["company_id"])
    audit("document_deleted", d["id"])
    return True


# ------------------------------------------------------------------ memos
class Gone(LookupError):
    """The uploaded report a memo is about was deleted or expired (e.g. while the memo was being written)."""


def save_memo(memo: dict) -> None:
    with conn() as c:
        if not _upload_alive(c, memo["company_id"]):
            raise Gone(memo["company_id"])
        c.execute("INSERT OR REPLACE INTO memos VALUES (?,?,?,?,?)",
                  (memo["id"], memo["company_id"], memo["fiscal_year_end"], memo["created_at"], json.dumps(memo)))


def get_memo(memo_id: str) -> Optional[dict]:
    _purge_if_due()
    with conn() as c:
        r = c.execute("SELECT company_id, body FROM memos WHERE id = ?", (memo_id,)).fetchone()
        if r and not _upload_alive(c, r["company_id"]):
            return None                                # about an upload past its retention window
    return json.loads(r["body"]) if r else None


def _upload_alive(c: sqlite3.Connection, company_id: str) -> bool:
    """True for every SEC company; for an uploaded report (doc...), only while its document exists."""
    if not company_id.startswith("doc"):
        return True
    live = "SELECT 1 FROM documents WHERE company_id = ? AND created_at >= ?"
    return c.execute(live, (company_id, _cutoff())).fetchone() is not None
