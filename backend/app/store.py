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


@contextmanager
def conn() -> Iterator[sqlite3.Connection]:
    with _lock:
        c = sqlite3.connect(DB_PATH)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        try:
            c.executescript(SCHEMA)
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


def purge_expired() -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=RETENTION_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with conn() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM documents WHERE created_at < ?", (cutoff,))]
        for i in ids:
            c.execute("DELETE FROM facts WHERE document_id = ?", (i,))
            c.execute("DELETE FROM documents WHERE id = ?", (i,))
    for i in ids:
        audit("document_expired", i)
    return len(ids)


# ------------------------------------------------------------------ documents
def create_document(*, filename: str, sha256: str, extraction: dict, company_name: str) -> str:
    doc_id = uuid.uuid4().hex
    company_id = f"doc{doc_id[:7]}"
    with conn() as c:
        c.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (doc_id, company_id, filename[:200], sha256, extraction["pages"], company_name[:120],
                   extraction["currency"], extraction["scale_label"], extraction["fiscal_year_end"],
                   int(extraction["fiscal_year_end_inferred"]), json.dumps(extraction["statement_pages"]),
                   json.dumps(extraction["issues"]), "in_review", now(), None))
        for cand in extraction["candidates"]:
            status = "needs_review" if cand["needs_review"] else "auto_accepted"
            c.execute("INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (uuid.uuid4().hex, doc_id, cand["field"], cand["period"], cand["value"], cand["page"],
                       cand["label"][:200], cand["snippet"][:300], cand["statement"], cand["confidence"],
                       json.dumps(cand["reasons"]), status, None, None, now()))
    return doc_id


def get_document(doc_id: str) -> Optional[dict]:
    with conn() as c:
        d = c.execute("SELECT * FROM documents WHERE id = ? OR company_id = ?", (doc_id, doc_id)).fetchone()
        if not d:
            return None
        facts = c.execute("SELECT * FROM facts WHERE document_id = ? ORDER BY period, field", (d["id"],)).fetchall()
    out = dict(d)
    out["statement_pages"] = json.loads(out["statement_pages"])
    out["issues"] = json.loads(out["issues"])
    out["fye_inferred"] = bool(out["fye_inferred"])
    out["facts"] = [{**dict(f), "reasons": json.loads(f["reasons"])} for f in facts]
    return out


def list_finalized() -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT id FROM documents WHERE status = 'finalized'")]


def review_fact(fact_id: str, decision: str, value: Optional[float], note: Optional[str]) -> dict:
    status = {"accept": "accepted", "correct": "corrected", "reject": "rejected"}[decision]
    with conn() as c:
        f = c.execute("SELECT * FROM facts WHERE id = ?", (fact_id,)).fetchone()
        if not f:
            raise KeyError(fact_id)
        d = c.execute("SELECT status FROM documents WHERE id = ?", (f["document_id"],)).fetchone()
        if d["status"] == "finalized":
            raise PermissionError("Document already finalized; delete and re-upload to change figures")
        c.execute("UPDATE facts SET status = ?, reviewed_value = ?, reviewer_note = ?, updated_at = ? WHERE id = ?",
                  (status, value if decision == "correct" else None, (note or "")[:500], now(), fact_id))
    audit("fact_reviewed", f["document_id"], fact=f["field"], period=f["period"], decision=decision,
          old=f["value"], new=value, note=note)
    return {"id": fact_id, "status": status}


def set_document_meta(doc_id: str, fiscal_year_end: Optional[str], company_name: Optional[str]) -> None:
    with conn() as c:
        if fiscal_year_end:
            c.execute("UPDATE documents SET fiscal_year_end = ?, fye_inferred = 0 WHERE id = ?", (fiscal_year_end, doc_id))
        if company_name:
            c.execute("UPDATE documents SET company_name = ? WHERE id = ?", (company_name[:120], doc_id))
    audit("document_meta_updated", doc_id, fiscal_year_end=fiscal_year_end, company_name=company_name)


def finalize(doc_id: str) -> None:
    with conn() as c:
        c.execute("UPDATE documents SET status = 'finalized', finalized_at = ? WHERE id = ?", (now(), doc_id))
    audit("document_finalized", doc_id)


def delete_document(doc_id: str) -> bool:
    with conn() as c:
        d = c.execute("SELECT id FROM documents WHERE id = ? OR company_id = ?", (doc_id, doc_id)).fetchone()
        if not d:
            return False
        c.execute("DELETE FROM facts WHERE document_id = ?", (d["id"],))
        c.execute("DELETE FROM documents WHERE id = ?", (d["id"],))
    audit("document_deleted", d["id"])
    return True


# ------------------------------------------------------------------ memos
def save_memo(memo: dict) -> None:
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO memos VALUES (?,?,?,?,?)",
                  (memo["id"], memo["company_id"], memo["fiscal_year_end"], memo["created_at"], json.dumps(memo)))


def get_memo(memo_id: str) -> Optional[dict]:
    with conn() as c:
        r = c.execute("SELECT body FROM memos WHERE id = ?", (memo_id,)).fetchone()
    return json.loads(r["body"]) if r else None
