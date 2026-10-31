"""Tests for docdrift.ollama_client with the HTTP layer mocked.

No Ollama and no model are needed.
"""

import json

import pytest

from docdrift import ollama_client as oc

DIFF = (
    "@@ -1,3 +1,3 @@\n"
    '-    parser.add_argument("--timeout", type=int)\n'
    '+    parser.add_argument("--deadline", type=int)\n'
)
DOCS = {"README.md": "1: # Tool\n2: Use --timeout to set the limit.\n3: Other text."}
EVIDENCE = '-    parser.add_argument("--timeout", type=int)\n+    parser.add_argument("--deadline", type=int)'


def model_says(monkeypatch, findings):
    monkeypatch.setattr(oc, "_chat", lambda messages: json.dumps({"findings": findings}))


def good(**overrides):
    finding = {
        "status": "possible_drift",
        "document_file": "README.md",
        "line_number": 99,
        "quoted_text": "Use --timeout to set the limit.",
        "code_evidence": EVIDENCE,
        "explanation": "Option renamed.",
    }
    finding.update(overrides)
    return finding


def test_valid_finding_is_kept_and_line_number_comes_from_the_document(monkeypatch):
    model_says(monkeypatch, [good()])
    [finding] = oc.analyze(DIFF, DOCS)
    assert finding["status"] == "possible_drift"
    assert finding["line_number"] == 2  # not the model's guess of 99
    assert set(finding) == {
        "status", "document_file", "line_number", "quoted_text", "code_evidence", "explanation",
    }


def test_invented_quote_is_dropped(monkeypatch):
    model_says(monkeypatch, [good(quoted_text="This sentence is not in the README.")])
    assert oc.analyze(DIFF, DOCS) == []


def test_unknown_file_is_dropped(monkeypatch):
    model_says(monkeypatch, [good(document_file="MISSING.md")])
    assert oc.analyze(DIFF, DOCS) == []


def test_unsupported_code_evidence_downgrades_to_uncertain(monkeypatch):
    model_says(monkeypatch, [good(code_evidence="made up code")])
    [finding] = oc.analyze(DIFF, DOCS)
    assert finding["status"] == "uncertain"
    assert finding["code_evidence"] == ""


def test_invalid_status_becomes_uncertain(monkeypatch):
    model_says(monkeypatch, [good(status="definitely")])
    assert oc.analyze(DIFF, DOCS)[0]["status"] == "uncertain"


def test_duplicates_are_removed(monkeypatch):
    model_says(monkeypatch, [good(), good()])
    assert len(oc.analyze(DIFF, DOCS)) == 1


def test_empty_inputs_do_not_call_the_model(monkeypatch):
    def must_not_run(_messages):
        raise AssertionError("model called")

    monkeypatch.setattr(oc, "_chat", must_not_run)
    assert oc.analyze("", DOCS) == []
    assert oc.analyze(DIFF, {}) == []


def test_code_fenced_json_is_accepted(monkeypatch):
    payload = "```json\n" + json.dumps({"findings": [good()]}) + "\n```"
    monkeypatch.setattr(oc, "_chat", lambda messages: payload)
    assert len(oc.analyze(DIFF, DOCS)) == 1


def test_bad_json_is_retried_once_then_reported(monkeypatch):
    calls = []

    def garbage(messages):
        calls.append(1)
        return "not json"

    monkeypatch.setattr(oc, "_chat", garbage)
    with pytest.raises(oc.OllamaResponseError):
        oc.analyze(DIFF, DOCS)
    assert len(calls) == 2


def test_request_goes_to_local_ollama_with_the_right_model(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps({"message": {"content": json.dumps({"findings": []})}}).encode()

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        return FakeResponse()

    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setattr(oc.urllib.request, "urlopen", fake_urlopen)
    assert oc.analyze(DIFF, DOCS) == []
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["body"]["model"] == "qwen3.5:4b"
    assert captured["body"]["stream"] is False
    assert captured["body"]["think"] is False


def test_unreachable_ollama_raises_helpful_error(monkeypatch):
    def refuse(request, timeout):
        raise oc.urllib.error.URLError(ConnectionRefusedError("refused"))

    monkeypatch.setattr(oc.urllib.request, "urlopen", refuse)
    with pytest.raises(oc.OllamaUnavailableError) as info:
        oc.analyze(DIFF, DOCS)
    assert "ollama pull qwen3.5:4b" in str(info.value)


# ---------------------------------------------------------------- check_status


class FakeTags:
    def __init__(self, names):
        self.names = names

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps({"models": [{"name": n, "model": n} for n in self.names]}).encode()


def test_status_ready_when_model_installed(monkeypatch):
    monkeypatch.setattr(oc.urllib.request, "urlopen", lambda r, timeout: FakeTags(["qwen3.5:4b", "x:1b"]))
    status = oc.check_status()
    assert status["ready"] and status["ollama_reachable"] and status["model_installed"]


def test_status_model_missing(monkeypatch):
    monkeypatch.setattr(oc.urllib.request, "urlopen", lambda r, timeout: FakeTags(["llama3:8b"]))
    status = oc.check_status()
    assert status["ollama_reachable"] and not status["model_installed"] and not status["ready"]
    assert "ollama pull qwen3.5:4b" in status["fix"]


def test_status_ollama_off(monkeypatch):
    def refuse(request, timeout):
        raise oc.urllib.error.URLError(ConnectionRefusedError("refused"))

    monkeypatch.setattr(oc.urllib.request, "urlopen", refuse)
    status = oc.check_status()
    assert not status["ollama_reachable"] and not status["ready"]
    assert "ollama.com" in status["fix"]
