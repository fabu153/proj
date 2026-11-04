"""Generate, validate, edit and export credit memos."""
from __future__ import annotations

import uuid
from typing import Optional

from .. import store
from ..scenarios.loan import Covenants, Facility
from .package import Package, build_package
from .validator import validate_sentence
from .writer import TemplateWriter, get_writer


def _validated_sections(raw: list[dict], pk: Package) -> list[dict]:
    out = []
    for sec in raw:
        sents = []
        for i, s in enumerate(sec["sentences"]):
            v = validate_sentence(s["text"], s.get("kind", "claim"), pk)
            sents.append({"id": f"{sec['key']}-{i + 1}", "edited": False, **v})
        out.append({"key": sec["key"], "title": sec["title"], "sentences": sents})
    return out


def generate(companyfacts: dict, company_id: str, fiscal_year_end: Optional[str], facility: Optional[Facility],
             covenants: Optional[Covenants], existing_floating_share: float = 0.0, prefer_llm: bool = True) -> dict:
    pk = build_package(companyfacts, company_id, fiscal_year_end, facility, covenants, existing_floating_share)
    writer, error = get_writer(prefer_llm), None
    try:
        raw = writer.write(pk)
    except Exception as e:  # noqa: BLE001 — provider down, bad JSON: fall back, record why
        error = f"{writer.name} failed ({type(e).__name__}); used the template writer"
        writer = TemplateWriter()
        raw = writer.write(pk)
    sections = _validated_sections(raw, pk)
    memo = {"id": uuid.uuid4().hex, "company_id": company_id, "fiscal_year_end": pk.val("meta.fye"),
            "created_at": store.now(), "writer": writer.name, "writer_note": error,
            "package_sha256": pk.sha256(), "currency": pk.ccy, "package": pk.items, "sections": sections}
    memo["summary"] = summarize(memo)
    store.save_memo(memo)
    store.audit("memo_generated", memo["id"], company_id=company_id, writer=writer.name,
                flagged=memo["summary"]["flagged"], package_sha256=memo["package_sha256"])
    return memo


def summarize(memo: dict) -> dict:
    s = [x for sec in memo["sections"] for x in sec["sentences"]]
    return {"sentences": len(s), "flagged": sum(x["status"] == "flagged" for x in s),
            "cited_items": len({r for x in s for r in x["refs"]})}


def _package(memo: dict) -> Package:
    pk = Package(memo["currency"])
    pk.items = memo["package"]
    return pk


def edit_sentence(memo: dict, sentence_id: str, text: str) -> dict:
    pk = _package(memo)
    for sec in memo["sections"]:
        for i, s in enumerate(sec["sentences"]):
            if s["id"] == sentence_id:
                if not text.strip():                      # empty edit = remove the sentence
                    sec["sentences"].pop(i)
                    store.audit("memo_sentence_removed", memo["id"], sentence=sentence_id, before=s["text"])
                else:
                    v = validate_sentence(text.strip()[:1000], s["kind"], pk)
                    store.audit("memo_sentence_edited", memo["id"], sentence=sentence_id, before=s["text"],
                                after=v["text"], status=v["status"])
                    sec["sentences"][i] = {"id": sentence_id, "edited": True, **v}
                memo["summary"] = summarize(memo)
                store.save_memo(memo)
                return memo
    raise KeyError(sentence_id)
