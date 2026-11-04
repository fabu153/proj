"""Memo verification layer (Blueprint p.14 'generation contract'; tests G01/G02).

A sentence is accepted only if:
  * every {{ref}} exists in the package,
  * every number written directly (outside placeholders) matches a package value within formatting
    tolerance — matched numbers are linked to that item, others are flagged as unsupported,
  * it uses none of the restricted credit terms (rating / PD / approval language),
  * claim sentences cite at least one package item.
Flagged sentences are shown to the analyst and excluded from the exported PDF until fixed.
"""
from __future__ import annotations

import re

from .package import Package

PLACEHOLDER = re.compile(r"\{\{\s*([a-z0-9_.]+)\s*\}\}")
NUMBER = re.compile(r"(?<![\w.])(-?\d[\d,]*(?:\.\d+)?)\s*(%|x\b|bp\b|m\b|bn\b|million\b|billion\b)?", re.I)
YEAR = re.compile(r"^(19|20)\d\d$")
RESTRICTED = [r"\binvestment[- ]grade\b", r"\b(aaa|aa|a|bbb|bb)[-+]?[- ]rated\b", r"\bprobability of default\b",
              r"\bdefault probability\b", r"\bguarantee[ds]?\b", r"\bwe (recommend|approve)\b", r"\bapproved?\b",
              r"\bwill default\b", r"\bjunk\b", r"\bpd of\b"]
SAFE_WORDS = {"10-k", "10-q"}


def _candidates(pk: Package) -> list[tuple[str, float, str]]:
    out = []
    for i, it in pk.items.items():
        v = it["value"]
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append((i, float(v), it["unit"]))
    return out


def _matches(num: float, suffix: str, value: float, unit: str) -> bool:
    s = (suffix or "").lower()
    # signs are often carried by words ("down 5.4%", "falls short by 2.17x"), so magnitudes also match
    if unit in ("pct", "prob"):
        return s == "%" and abs(abs(num) - abs(value * 100)) <= 0.051
    if unit == "pp":
        return abs(abs(num) - abs(value * 100)) <= 0.051
    if unit == "x":
        return s in ("x", "") and abs(abs(num) - abs(value)) <= 0.0051
    if unit == "amount":
        scale = 1000 if s in ("bn", "billion") else 1
        n = num * scale
        return abs(abs(n) - abs(value)) <= max(0.005 * abs(value), 0.51)
    if unit == "ratio":
        return abs(num - value) <= 0.0006
    return False


def unlinked_numbers(text: str, pk: Package) -> tuple[list[str], list[str]]:
    """Return (refs auto-linked from typed numbers, unsupported number strings)."""
    stripped = PLACEHOLDER.sub(" ", text)
    for w in SAFE_WORDS:
        stripped = re.sub(re.escape(w), " ", stripped, flags=re.I)
    cands = _candidates(pk)
    linked, bad = [], []
    for m in NUMBER.finditer(stripped):
        raw, suffix = m.group(1), m.group(2)
        clean = raw.replace(",", "")
        if YEAR.match(clean) and not suffix:
            continue
        num = float(clean)
        hit = next((i for i, v, u in cands if _matches(num, suffix, v, u)), None)
        if hit:
            linked.append(hit)
        else:
            bad.append(m.group(0).strip())
    return linked, bad


def validate_sentence(text: str, kind: str, pk: Package) -> dict:
    refs = PLACEHOLDER.findall(text)
    issues = []
    unknown = [r for r in refs if r not in pk.items]
    if unknown:
        issues.append(f"unknown reference: {', '.join(unknown)}")
    missing = [r for r in refs if r in pk.items and pk.items[r]["value"] is None]
    if missing:
        issues.append(f"value not available: {', '.join(missing)}")
    linked, bad = unlinked_numbers(text, pk)
    if bad:
        issues.append(f"number not found in the analysis: {', '.join(bad)}")
    rendered = render(text, pk)
    for pat in RESTRICTED:
        if re.search(pat, rendered, re.I):
            issues.append(f"restricted credit language: '{re.search(pat, rendered, re.I).group(0)}'")
    all_refs = list(dict.fromkeys([r for r in refs if r in pk.items] + linked))
    if kind == "claim" and not all_refs:
        issues.append("claim cites no evidence")
    return {"template": text, "text": rendered, "refs": all_refs, "kind": kind,
            "status": "flagged" if issues else "ok", "issues": issues}


def render(text: str, pk: Package) -> str:
    return PLACEHOLDER.sub(lambda m: pk.items[m.group(1)]["display"] if m.group(1) in pk.items else m.group(0), text)
