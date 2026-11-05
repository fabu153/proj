"""Memo verification layer (Blueprint p.14 'generation contract'; tests G01/G02).

A sentence is accepted only if:
  * every {{ref}} exists in the package,
  * every number written directly (outside placeholders) matches a package value within formatting
    tolerance — matched numbers are linked to that item, others are flagged as unsupported,
  * it uses none of the restricted credit terms (rating / PD / approval language),
  * claim sentences cite at least one package item,
  * it passes the semantic checks (v1.3): stated direction matches the sign of the change, negative covenant
    headroom is described as a breach and positive headroom is not, undefined ratios are not cited, and one
    sentence does not mix the assumptions of one stress case with the results of another.
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


UP = r"\b(rises?|rose|increas(?:e|es|ed)|grew|grows|up|higher|improv(?:e|es|ed))\b"
DOWN = r"\b(falls?|fell|drops?|dropped|declin(?:e|es|ed)|decreas(?:e|es|ed)|down|lower|weaken(?:s|ed)?)\b"
BREACH = r"(breach\w*|short(?:fall)?|fails?|below the minimum|above the maximum|violat\w*)"
# signed source for items that are shown as magnitudes or changes
SIGNED = {"metric.revenue_growth.abs": "metric.revenue_growth.t", "metric.revenue_growth.t": "metric.revenue_growth.t",
          "metric.ebitda_margin.change": "metric.ebitda_margin.change"}
# a scenario result is compared with the pre-loan figure when a sentence says it rises or falls "to" it
BASELINE = {"gross_debt": "metric.gross_debt.t", "net_debt": "metric.net_debt.t", "ebitda": "metric.ebitda.t",
            "net_leverage": "metric.net_leverage.t", "ebitda_interest_cover": "metric.ebitda_interest_cover.t",
            "interest_expense": "fact.interest_expense.t"}
CASE_WORDS = {"base": r"\bbase case\b", "downside": r"\bdownside\b", "severe": r"\bsevere\b",
              "custom": r"\b(own|your) case\b"}


def _val(pk: Package, ref: str):
    it = pk.items.get(ref)
    return None if it is None else it["value"]


def semantic_issues(text: str, pk: Package) -> list[str]:
    """Checks that a sentence whose numbers all reconcile still says something true about them."""
    refs = PLACEHOLDER.findall(text)
    plain = PLACEHOLDER.sub(lambda m: f"<{m.group(1)}>", text).lower()      # keeps where each value sits
    bare = PLACEHOLDER.sub(" ", text).lower()                               # words only, never the item ids
    issues = []
    # 1. direction words agree with the sign of the change they describe
    for r in refs:
        if r in SIGNED and isinstance(_val(pk, SIGNED[r]), (int, float)):
            sign = _val(pk, SIGNED[r])
            window = re.sub(r"<[^>]*>", " ", plain[max(0, plain.find(f"<{r}>") - 40): plain.find(f"<{r}>")])
            if sign < 0 and re.search(UP, window) and not re.search(DOWN, window):
                issues.append(f"direction: says an increase, but {pk.items[SIGNED[r]]['label']} is negative")
            if sign > 0 and re.search(DOWN, window) and not re.search(UP, window):
                issues.append(f"direction: says a decrease, but {pk.items[SIGNED[r]]['label']} is positive")
    for m in re.finditer(UP + r" to <(scen\.[a-z_]+\.([a-z_]+))>|" + DOWN + r" to <(scen\.[a-z_]+\.([a-z_]+))>", plain):
        up = m.group(1) is not None
        ref, field = (m.group(2), m.group(3)) if up else (m.group(5), m.group(6))
        new, old = _val(pk, ref), _val(pk, BASELINE.get(field, ""))
        if isinstance(new, (int, float)) and isinstance(old, (int, float)) and new != old:
            if up and new < old:
                issues.append(f"direction: says {field.replace('_', ' ')} rises, but it falls ({old:,.2f} to {new:,.2f})")
            if not up and new > old:
                issues.append(f"direction: says {field.replace('_', ' ')} falls, but it rises ({old:,.2f} to {new:,.2f})")
    # 2. signed covenant headroom
    for r in refs:
        if re.search(r"\.headroom_(lev|cov)$", r) and isinstance(_val(pk, r), (int, float)) and _val(pk, r) < 0:
            issues.append("covenant: negative headroom must be stated as a breach (cite the shortfall item)")
        if r.endswith("_shortfall") and not re.search(BREACH, bare):
            issues.append("covenant: a shortfall is cited but the sentence does not say the covenant is breached")
    if re.search(r"\bbreach", bare) and not any(r.endswith("_shortfall") for r in refs):
        positive = [r for r in refs if re.search(r"\.headroom_(lev|cov)$", r) and (_val(pk, r) or 0) >= 0]
        if positive and not re.search(r"\b(but|while|whereas)\b", bare):
            issues.append("covenant: describes a breach, but the cited headroom is positive")
    # 3. undefined ratios
    for r in refs:
        src = (pk.items.get(r) or {}).get("source", {})
        if src.get("status") in ("undefined", "not_available"):
            note = (src.get("note") or "").replace("_", " ")
            issues.append(f"undefined ratio cited: {pk.items[r]['label']}" + (f" ({note})" if note else ""))
    # 4. one stress case per claim: assumptions and results must belong to the same case
    cases = {r.split(".")[1] for r in refs if r.startswith("scen.") and r.split(".")[1] != "unavailable"}
    named = {k for k, pat in CASE_WORDS.items() if re.search(pat, bare)}
    if len(named) == 1 and cases and not cases <= named:
        issues.append(f"scenario: the sentence names the {next(iter(named))} case but cites "
                      f"{', '.join(sorted(cases - named))} results")
    assumption_cases = {r.split(".")[1] for r in refs if r.startswith("scen.") and r.endswith(".assumptions")}
    if assumption_cases and cases - assumption_cases and len(named) <= 1:
        issues.append(f"scenario: the assumptions of the {', '.join(sorted(assumption_cases))} case are paired with "
                      f"{', '.join(sorted(cases - assumption_cases))} results")
    return issues


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
    if not unknown:
        issues += semantic_issues(text, pk)
    all_refs = list(dict.fromkeys([r for r in refs if r in pk.items] + linked))
    if kind == "claim" and not all_refs:
        issues.append("claim cites no evidence")
    return {"template": text, "text": rendered, "refs": all_refs, "kind": kind,
            "status": "flagged" if issues else "ok", "issues": issues}


def render(text: str, pk: Package) -> str:
    return PLACEHOLDER.sub(lambda m: pk.items[m.group(1)]["display"] if m.group(1) in pk.items else m.group(0), text)
