"""LLM path with a mocked provider: output is validated exactly like the template writer, and failures fall back."""
import gzip
import json
from pathlib import Path

import httpx
import pytest

from backend.app.memos import service, writer
from backend.app.scenarios.loan import Covenants, Facility

CURATED = Path(__file__).parents[2] / "backend" / "data" / "curated"


def _cf():
    with gzip.open(CURATED / "companyfacts_0000080424.json.gz", "rt") as fh:
        return json.load(fh)


class FakeResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def _llm(monkeypatch, text):
    monkeypatch.setenv("CREDITLENS_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    calls = []

    def fake_post(url, **kw):
        calls.append((url, kw))
        return FakeResp({"content": [{"type": "text", "text": text}]})
    monkeypatch.setattr(writer.httpx, "post", fake_post)
    return calls


def test_llm_output_is_validated_and_unsupported_numbers_flagged(monkeypatch):
    out = {"sections": [
        {"key": "executive", "sentences": [{"text": "{{meta.company}} reported revenue of {{fact.revenue.t}}.", "kind": "claim"}]},
        {"key": "risks", "sentences": [{"text": "Leverage could rise to 4.9x next year.", "kind": "claim"},
                                      {"text": "The borrower is investment grade.", "kind": "framing"}]}]}
    calls = _llm(monkeypatch, "Here you go:\n" + json.dumps(out))
    memo = service.generate(_cf(), "0000080424", None, Facility(amount=100, currency="USD"), Covenants(max_net_leverage=3.5))
    assert memo["writer"] == "anthropic:claude-sonnet-5-5"
    sents = {s["text"]: s for sec in memo["sections"] for s in sec["sentences"]}
    assert any(s["status"] == "ok" and "PROCTER" in t for t, s in sents.items())
    assert sents["Leverage could rise to 4.9x next year."]["status"] == "flagged"
    assert any("restricted" in i for i in sents["The borrower is investment grade."]["issues"])
    # only the package is sent: labels and formatted values, no raw filings
    prompt = calls[0][1]["json"]["messages"][0]["content"]
    assert "fact.revenue.t" in prompt and "%PDF" not in prompt and calls[0][1]["headers"]["x-api-key"] == "test-key"


def test_provider_failure_falls_back_to_template(monkeypatch):
    monkeypatch.setenv("CREDITLENS_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def boom(url, **kw):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(writer.httpx, "post", boom)
    memo = service.generate(_cf(), "0000080424", None, Facility(amount=100, currency="USD"), None)
    assert memo["writer"] == "template" and "failed" in memo["writer_note"]
    assert memo["summary"]["flagged"] == 0


def test_no_key_means_template(monkeypatch):
    monkeypatch.setenv("CREDITLENS_LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert writer.llm_status() == {"writer": "template", "llm_configured": False}


def test_openai_requires_explicit_model(monkeypatch):
    monkeypatch.setenv("CREDITLENS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.delenv("CREDITLENS_LLM_MODEL", raising=False)
    assert writer.get_writer().name == "template"
    monkeypatch.setenv("CREDITLENS_LLM_MODEL", "some-model")
    assert writer.get_writer().name == "openai:some-model"
