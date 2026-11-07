"""Memo writers. Both produce the same structure: sections of sentences that cite package items
with {{id}} placeholders. Neither writes numbers itself; the validator enforces that.

* TemplateWriter — deterministic, always available, used when no LLM key is configured.
* LLMWriter      — Anthropic or OpenAI chat API via httpx; output must be JSON in the same shape.
  Only the package (labels, formatted values, sources) is sent — never the uploaded PDF.
"""
from __future__ import annotations

import json
import os
import re

import httpx

from .package import Package

SECTIONS = [
    ("executive", "Executive assessment"),
    ("profile", "Financial profile"),
    ("strengths", "Key strengths"),
    ("risks", "Key risks"),
    ("model", "Neural stress screen"),
    ("stress", "Stress cases"),
    ("covenants", "Covenant headroom"),
    ("considerations", "Diligence questions"),
]


def S(text: str, kind: str = "claim") -> dict:
    return {"text": text, "kind": kind}


class TemplateWriter:
    name = "template"

    def write(self, pk: Package) -> list[dict]:
        h, v = pk.has, pk.val
        out: dict[str, list[dict]] = {k: [] for k, _ in SECTIONS}

        # executive: the assessment in four sentences; facility terms are in the PDF header block
        if h("scen.base.net_leverage") and h("metric.net_leverage.t"):
            out["executive"].append(S("After the facility, net debt / EBITDA would be {{scen.base.net_leverage}}, against "
                                      "{{metric.net_leverage.t}} before it, with EBITDA / interest at "
                                      "{{scen.base.ebitda_interest_cover}}."))
        elif h("metric.net_leverage.t"):
            out["executive"].append(S("Net debt / EBITDA is {{metric.net_leverage.t}} for the fiscal year ending {{meta.fye}}."))
        if v("risk.status") == "scored":
            out["executive"].append(S("The next-FY accounting-stress screen is {{risk.probability}}, in the {{risk.band}} band."))
        elif h("risk.gate"):
            out["executive"].append(S("The next-FY accounting-stress screen was withheld: {{risk.gate}}."))
        if h("covenant.max_net_leverage"):
            st = v("scen.downside.headroom_lev_state")
            if st == "breach":
                out["executive"].append(S("The downside case breaches the maximum net debt / EBITDA covenant of "
                                          "{{covenant.max_net_leverage}} by {{scen.downside.headroom_lev_shortfall}}."))
            elif st == "pass":
                out["executive"].append(S("The maximum net debt / EBITDA covenant of {{covenant.max_net_leverage}} holds in "
                                          "the downside case, with headroom of {{scen.downside.headroom_lev}}."))
            elif st == "not testable":
                out["executive"].append(S("The maximum net debt / EBITDA covenant of {{covenant.max_net_leverage}} cannot "
                                          "be tested in the downside case: {{scen.downside.headroom_lev_reason}}."))
        out["executive"].append(S("Figures come from {{meta.source}}; the memo supports analyst judgement and makes no "
                                  "lending decision.", "claim"))

        # profile
        if h("fact.revenue.t"):
            g = ""
            if h("metric.revenue_growth.t"):
                g = (", up {{metric.revenue_growth.abs}} year on year" if v("metric.revenue_growth.t") >= 0
                     else ", down {{metric.revenue_growth.abs}} year on year")
            out["profile"].append(S("Revenue was {{fact.revenue.t}}" + g + "."))
        if h("metric.ebitda.t"):
            m = (", against {{metric.ebitda_margin.t1}} a year earlier" if h("metric.ebitda_margin.t1") else "")
            out["profile"].append(S("EBITDA, approximated as operating income plus depreciation and amortization, was "
                                    "{{metric.ebitda.t}}, a margin of {{metric.ebitda_margin.t}}" + m + "."))
        if h("fact.operating_cash_flow.t") and h("fact.capital_expenditures.t") and h("metric.fcf_simple.t"):
            out["profile"].append(S("Operating cash flow of {{fact.operating_cash_flow.t}} covered capital expenditure "
                                    "of {{fact.capital_expenditures.t}}, leaving simple free cash flow of "
                                    "{{metric.fcf_simple.t}}." if v("metric.fcf_simple.t") >= 0 else
                                    "Operating cash flow of {{fact.operating_cash_flow.t}} did not cover capital "
                                    "expenditure of {{fact.capital_expenditures.t}}; simple free cash flow was "
                                    "{{metric.fcf_simple.t}}."))
        if h("metric.gross_debt.t") and h("fact.cash.t"):
            out["profile"].append(S("Gross debt stood at {{metric.gross_debt.t}} and cash at {{fact.cash.t}}, "
                                    "for net debt of {{metric.net_debt.t}}."))
        if h("metric.net_leverage.t") and h("metric.ebitda_interest_cover.t"):
            out["profile"].append(S("Net debt / EBITDA was {{metric.net_leverage.t}} and EBITDA / interest "
                                    "{{metric.ebitda_interest_cover.t}}."))
        if h("data.credit_rules"):
            out["profile"].append(S("For the credit ratios the filing figures were adjusted to {{data.credit_rules}}; "
                                    "the appendix gives each rule."))

        # strengths / risks (thresholds are presentation rules, not credit policy)
        lev, cov = v("metric.net_leverage.t"), v("metric.ebitda_interest_cover.t")
        fcf, cr = v("metric.fcf_simple.t"), v("metric.current_ratio.t")
        if lev is not None and lev <= 2.5:
            out["strengths"].append(S("Leverage is moderate, with net debt / EBITDA of {{metric.net_leverage.t}}."))
        if cov is not None and cov >= 5:
            out["strengths"].append(S("Interest is comfortably covered, with EBITDA / interest of {{metric.ebitda_interest_cover.t}}."))
        if fcf is not None and fcf > 0:
            out["strengths"].append(S("The business generated positive free cash flow of {{metric.fcf_simple.t}}."))
        if cr is not None and cr >= 1.5:
            out["strengths"].append(S("Liquidity is solid, with a current ratio of {{metric.current_ratio.t}}."))
        if not out["strengths"]:
            out["strengths"].append(S("No clear quantitative strengths stand out on the metrics reviewed.", "framing"))

        if lev is not None and lev > 3.5:
            out["risks"].append(S("Leverage is high, with net debt / EBITDA of {{metric.net_leverage.t}}."))
        if h("metric.ebitda.t") and v("metric.ebitda.t") <= 0:
            out["risks"].append(S("EBITDA is not positive ({{metric.ebitda.t}}), so leverage ratios are undefined."))
        if cov is not None and cov < 3:
            out["risks"].append(S("Interest cover is thin, with EBITDA / interest of {{metric.ebitda_interest_cover.t}}."))
        if h("metric.ebitda_margin.change") and v("metric.ebitda_margin.change") <= -0.02:
            out["risks"].append(S("The EBITDA margin moved by {{metric.ebitda_margin.change}} year on year."))
        if h("metric.revenue_growth.t") and v("metric.revenue_growth.t") < 0:
            out["risks"].append(S("Revenue fell {{metric.revenue_growth.abs}} year on year."))
        if fcf is not None and fcf < 0:
            out["risks"].append(S("Free cash flow was negative at {{metric.fcf_simple.t}}."))
        if cr is not None and cr < 1:
            out["risks"].append(S("The current ratio of {{metric.current_ratio.t}} is below one, so current "
                                  "liabilities exceed current assets."))
        if h("data.cash_basis"):
            out["risks"].append(S("Reported cash {{data.cash_basis}}, so net debt and net debt / EBITDA may be understated."))
        if h("data.unavailable"):
            out["risks"].append(S("These figures were marked unavailable in the document review and are not used: "
                                  "{{data.unavailable}}."))
        if v("data.warning_count"):
            out["risks"].append(S("Some inputs were derived or approximated ({{data.warning_count}} data warnings); "
                                  "see the evidence appendix."))
        if not out["risks"]:
            out["risks"].append(S("No metric breaches the memo's risk thresholds; stress cases below remain relevant.",
                                  "framing"))

        # model
        if v("risk.status") == "scored":
            out["model"].append(S("The neural stress screen puts the chance that next year's accounts show financial "
                                  "stress at {{risk.probability}}, in the {{risk.band}} screening band."))
            if h("risk.driver.1") and h("risk.driver.2"):
                out["model"].append(S("The largest contributions came from {{risk.driver.1}} and {{risk.driver.2}}."))
            out["model"].append(S("On held-out years the model reached a precision-recall AUC of {{model.test_pr_auc}}, "
                                  "against {{model.xgb_pr_auc}} for an XGBoost benchmark."))
            out["model"].append(S("The screen is an indicator of accounting stress, not of default, and is one input to "
                                  "analyst judgement.", "framing"))
        elif h("risk.gate"):
            out["model"].append(S("The stress screen was withheld: {{risk.gate}}."))
        else:
            out["model"].append(S("No stress screen is available for this company-year.", "framing"))

        # stress cases (net debt / EBITDA is undefined when stressed EBITDA is not positive: say so, never a number)
        if h("scen.base.ebitda"):
            gd_new, gd_old = v("scen.base.gross_debt"), v("metric.gross_debt.t")
            verb = "rises to" if gd_old is None or gd_new > gd_old else "stays at" if gd_new == gd_old else "falls to"
            lev = lambda c: ("net debt / EBITDA is {{scen." + c + ".net_leverage}}" if h(f"scen.{c}.net_leverage")  # noqa: E731
                             else "EBITDA is {{scen." + c + ".ebitda}}, so net debt / EBITDA is undefined")
            cov = lambda c: (" and EBITDA / interest is {{scen." + c + ".ebitda_interest_cover}}"  # noqa: E731
                             if h(f"scen.{c}.ebitda_interest_cover") else "")
            out["stress"].append(S("In the base case gross debt " + verb + " {{scen.base.gross_debt}}; " + lev("base")
                                   + cov("base") + "."))
            for c, name in (("downside", "the downside case"), ("severe", "the severe case"),
                            ("custom", "the analyst's own case")):
                if h(f"scen.{c}.ebitda"):
                    out["stress"].append(S("In " + name + " ({{scen." + c + ".assumptions}}) " + lev(c) + cov(c) + "."))
            if v("scen.base.ebitda") is not None and v("scen.base.ebitda") < 0:
                out["stress"].append(S("EBITDA is negative, so each downside deepens the loss by that share of its size.",
                                       "framing"))
            out["stress"].append(S("Proceeds spent on capex or acquisitions are assumed to add no EBITDA.", "framing"))
        elif h("scen.unavailable"):
            out["stress"].append(S("Stress cases could not be run because these inputs are missing: {{scen.unavailable}}."))

        # covenant headroom: base, downside and the analyst's own case, one sentence each, by the engine's state
        any_cov = False
        names = {"base": "the base case", "downside": "the downside case", "custom": "the analyst's own case"}
        for cov, item, what in (("covenant.max_net_leverage", "headroom_lev", "a maximum net debt / EBITDA"),
                                ("covenant.min_cover", "headroom_cov", "a minimum EBITDA / interest")):
            if not h(cov):
                continue
            first = True
            for case in ("base", "downside", "custom"):
                st = v(f"scen.{case}.{item}_state")
                if st is None:
                    continue
                any_cov = True
                lead = ("Against " + what + " of {{" + cov + "}}, in " + names[case]) if first else "In " + names[case]
                first = False
                if st == "breach":
                    out["covenants"].append(S(lead + " the covenant is breached by {{scen." + case + "." + item + "_shortfall}}."))
                elif st == "pass":
                    out["covenants"].append(S(lead + " headroom is {{scen." + case + "." + item + "}}."))
                else:
                    out["covenants"].append(S(lead + " the covenant cannot be tested: {{scen." + case + "." + item +
                                              "_reason}}."))
        if any(v(f"scen.{c}.{i}_state") == "not testable" for c in ("base", "downside", "custom")
               for i in ("headroom_lev", "headroom_cov")):
            out["covenants"].append(S("A covenant that cannot be tested is not counted as a breach; check how the loan "
                                      "agreement defines it.", "framing"))
        if not any_cov and h("scen.base.ebitda"):
            out["covenants"].append(S("No covenants were set in the loan lab, so headroom was not tested.", "framing"))

        # considerations
        if h("covenant.max_net_leverage"):
            out["considerations"].append(S("Is a maximum net debt / EBITDA covenant of {{covenant.max_net_leverage}} "
                                           "appropriate given the downside headroom?", "question"))
        out["considerations"].append(S("How much of the existing debt is floating-rate, and is it hedged?", "question"))
        out["considerations"].append(S("Does operating income include one-off items that an adjusted EBITDA would "
                                       "remove?", "question"))
        if v("data.warning_count"):
            out["considerations"].append(S("Close the data gaps listed in the appendix before committee.", "framing"))
        return [{"key": k, "title": t, "sentences": out[k]} for k, t in SECTIONS]


# ---------------------------------------------------------------------------- LLM
PROMPT = """You draft sections of a corporate credit memo for a bank credit committee.

Rules — they are checked automatically and violations are rejected:
1. Never type a number. Every figure must be a placeholder {{item_id}} copied exactly from the ITEMS list; the system
   inserts the formatted value. Years inside words like "fiscal year" are fine only via {{meta.fye}}.
2. Use only facts present in ITEMS. If something is not available, do not mention it.
3. Never use rating or decision language: no "investment grade", letter ratings, "probability of default",
   "guarantee", "approve". The model output is an "accounting-stress screen", not a default probability.
4. Plain, precise analyst prose. Each sentence is one claim. No adjectives without a cited number.
5. Return ONLY JSON: {"sections":[{"key":"...","sentences":[{"text":"...","kind":"claim|framing|question"}]}]}
   using exactly these section keys in order: executive, profile, strengths, risks, model, stress, covenants,
   considerations.
6. Describe changes in the direction the numbers show; a negative covenant headroom is a breach (cite the
   *_shortfall item); a covenant whose *_state is "not testable" is not a breach (cite its *_reason item);
   never describe one stress case with another case's assumptions.
   kind "claim" sentences must contain at least one placeholder.

ITEMS (id | label | formatted value | source kind):
"""


class LLMWriter:
    def __init__(self, provider: str, model: str, api_key: str):
        self.provider, self.model, self.api_key = provider, model, api_key
        self.name = f"{provider}:{model}"

    def _items(self, pk: Package) -> str:
        return "\n".join(f"{i} | {it['label']} | {it['display']} | {it['source'].get('kind')}"
                         for i, it in pk.items.items() if it["value"] is not None)

    def write(self, pk: Package) -> list[dict]:
        prompt = PROMPT + self._items(pk)
        if self.provider == "anthropic":
            r = httpx.post("https://api.anthropic.com/v1/messages", timeout=90,
                           headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                                    "content-type": "application/json"},
                           json={"model": self.model, "max_tokens": 4000,
                                 "messages": [{"role": "user", "content": prompt}]})
            r.raise_for_status()
            text = "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")
        else:  # openai-compatible chat completions
            r = httpx.post("https://api.openai.com/v1/chat/completions", timeout=90,
                           headers={"authorization": f"Bearer {self.api_key}"},
                           json={"model": self.model, "messages": [{"role": "user", "content": prompt}],
                                 "response_format": {"type": "json_object"}})
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", text, re.S)
        data = json.loads(m.group(0) if m else text)
        titles = dict(SECTIONS)
        by_key = {s.get("key"): s for s in data.get("sections", [])}
        return [{"key": k, "title": titles[k],
                 "sentences": [S(str(x.get("text", "")), x.get("kind", "claim")) for x in by_key.get(k, {}).get("sentences", [])]}
                for k, _ in SECTIONS]


def get_writer(prefer_llm: bool = True):
    provider = os.environ.get("CREDITLENS_LLM_PROVIDER", "anthropic").lower()
    key = os.environ.get("ANTHROPIC_API_KEY") if provider == "anthropic" else os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("CREDITLENS_LLM_MODEL") or ("claude-sonnet-5-5" if provider == "anthropic" else None)
    if prefer_llm and key and model and provider in ("anthropic", "openai"):
        return LLMWriter(provider, model, key)
    return TemplateWriter()


def llm_status() -> dict:
    w = get_writer()
    return {"writer": w.name, "llm_configured": isinstance(w, LLMWriter)}
