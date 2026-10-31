"""Tests for the DocDrift website (docdrift.web).

The model is mocked: no Ollama, no downloaded model and no network are needed.
"""

import json

import pytest

pytest.importorskip("flask")

from docdrift import cli, ollama_client, web  # noqa: E402
from docdrift.sample import SAMPLE_DIFF, SAMPLE_README  # noqa: E402

FINDING = {
    "status": "possible_drift",
    "document_file": "README.md",
    "line_number": 9,
    "quoted_text": "Use --timeout to stop slow jobs.",
    "code_evidence": '-    parser.add_argument("--timeout", type=int, default=30)\n'
    '+    parser.add_argument("--deadline", type=int, default=30)',
    "explanation": "The option was renamed in the diff.",
}


@pytest.fixture()
def client():
    return web.create_app().test_client()


def post(client, payload, **kwargs):
    return client.post("/api/analyze", json=payload, **kwargs)


def sample_payload(**overrides):
    payload = {
        "diff": SAMPLE_DIFF,
        "documents": [{"name": "README.md", "text": SAMPLE_README}],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------- pages


def test_home_page_is_served_with_security_headers(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"DocDrift" in response.data
    assert b"Try sample" in response.data
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_static_assets_are_served(client):
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/app.css").status_code == 200


def test_page_makes_no_external_requests(client):
    html = client.get("/").get_data(as_text=True)
    css = client.get("/static/app.css").get_data(as_text=True)
    js = client.get("/static/app.js").get_data(as_text=True)
    for text in (html, css, js):
        assert "http://" not in text.replace("http://www.w3.org", "")
        assert "https://" not in text.replace("https://ollama.com", "")


def test_sample_endpoint_contains_the_timeout_example(client):
    data = client.get("/api/sample").get_json()
    assert '"--deadline"' in data["diff"]
    assert data["documents"][0]["name"] == "README.md"
    assert "Use --timeout to stop slow jobs." in data["documents"][0]["text"]


def test_status_endpoint_reports_ollama_state(client, monkeypatch):
    fake = {"ready": False, "ollama_reachable": False, "message": "off", "fix": "start it"}
    monkeypatch.setattr(ollama_client, "check_status", lambda: fake)
    assert client.get("/api/status").get_json() == fake


# ---------------------------------------------------------------- analysis


def test_analyze_returns_findings_and_downloads(client, monkeypatch):
    seen = {}

    def fake_analyze(diff_text, documents):
        seen["diff"], seen["documents"] = diff_text, documents
        return [FINDING]

    monkeypatch.setattr(ollama_client, "analyze", fake_analyze)
    response = post(client, sample_payload())
    body = response.get_json()

    assert response.status_code == 200
    assert body["ok"] is True
    assert body["model"] == "qwen3.5:4b"
    assert body["verdict"] == "possible_drift"
    assert body["summary"] == {"total": 1, "possible_drift": 1, "uncertain": 0}
    assert body["findings"][0]["document_file"] == "README.md"
    md = body["markdown"]
    assert "Possible documentation drift (README.md, line 9)" in md
    assert "> Use --timeout to stop slow jobs." in md
    assert "```diff" in md and '+    parser.add_argument("--deadline", type=int, default=30)' in md
    assert "Checked locally with qwen3.5:4b" in md
    # The analyzer must receive documents with line numbers, like git_input produces.
    assert seen["documents"]["README.md"].splitlines()[0] == "1: # jobrunner"
    assert "--deadline" in seen["diff"]


def test_analyze_with_no_findings_says_none_found(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "analyze", lambda d, docs: [])
    body = post(client, sample_payload()).get_json()
    assert body["verdict"] == "none"
    assert body["findings"] == []


def test_analyze_uncertain_only(client, monkeypatch):
    uncertain = dict(FINDING, status="uncertain")
    monkeypatch.setattr(ollama_client, "analyze", lambda d, docs: [uncertain])
    assert post(client, sample_payload()).get_json()["verdict"] == "uncertain"


def test_findings_are_sorted_with_drift_first(client, monkeypatch):
    uncertain = dict(FINDING, status="uncertain", line_number=2)
    monkeypatch.setattr(ollama_client, "analyze", lambda d, docs: [uncertain, FINDING])
    statuses = [f["status"] for f in post(client, sample_payload()).get_json()["findings"]]
    assert statuses == ["possible_drift", "uncertain"]


def test_blank_document_cards_are_ignored(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "analyze", lambda d, docs: [])
    payload = sample_payload()
    payload["documents"].append({"name": "empty.md", "text": "   "})
    assert post(client, payload).status_code == 200


def test_duplicate_and_unsafe_file_names_are_cleaned(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(ollama_client, "analyze", lambda d, docs: seen.update(docs=docs) or [])
    payload = sample_payload(
        documents=[
            {"name": "../../etc/README.md", "text": "a"},
            {"name": "docs\\README.md", "text": "b"},
        ]
    )
    assert post(client, payload).status_code == 200
    assert list(seen["docs"]) == ["README.md", "README-2.md"]


def test_large_input_adds_a_truncation_warning(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "analyze", lambda d, docs: [])
    big_diff = "@@ -1 +1 @@\n" + "+x = 1\n" * 4000  # over the 20,000 character prompt budget
    body = post(client, sample_payload(diff=big_diff)).get_json()
    assert any("first 20,000 characters of the diff" in w for w in body["warnings"])


# ---------------------------------------------------------------- bad input


@pytest.mark.parametrize(
    "payload, code, status",
    [
        (sample_payload(diff="   "), "missing_diff", 400),
        (sample_payload(documents=[{"name": "README.md", "text": ""}]), "missing_docs", 400),
        (sample_payload(documents=[]), "missing_docs", 400),
        (sample_payload(diff="just some words, not a diff"), "invalid_diff", 400),
        (sample_payload(diff="+a\n\x00"), "invalid_file", 400),
        (sample_payload(documents=[{"name": "notes.txt", "text": "hi"}]), "invalid_file", 400),
        (sample_payload(documents=[{"name": "a.md", "text": "x" * 100_001}]), "too_large", 413),
        (sample_payload(diff="+" + "x" * 100_001), "too_large", 413),
        (sample_payload(documents=[{"name": f"{i}.md", "text": "x"} for i in range(11)]), "too_large", 413),
        (sample_payload(documents="not a list"), "invalid_request", 400),
        (["not", "an", "object"], "invalid_request", 400),
    ],
)
def test_bad_input_gets_a_clear_error(client, monkeypatch, payload, code, status):
    def must_not_run(*_args):
        raise AssertionError("the model must not be called for invalid input")

    monkeypatch.setattr(ollama_client, "analyze", must_not_run)
    response = post(client, payload)
    assert response.status_code == status
    body = response.get_json()
    assert body["ok"] is False
    assert body["error"]["code"] == code
    assert body["error"]["message"]


def test_non_json_body_is_rejected(client):
    response = client.post("/api/analyze", data="hello", content_type="text/plain")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_request"


def test_request_over_total_limit_is_rejected(client):
    body = json.dumps({"diff": "+" + "x" * 1_200_000, "documents": []})
    response = client.post("/api/analyze", data=body, content_type="application/json")
    assert response.status_code == 413
    assert response.get_json()["error"]["code"] == "too_large"


# ---------------------------------------------------------------- Ollama problems


def test_ollama_off_gives_instructions(client, monkeypatch):
    def boom(*_args):
        raise ollama_client.OllamaUnavailableError("Could not reach Ollama at http://localhost:11434.")

    monkeypatch.setattr(ollama_client, "analyze", boom)
    response = post(client, sample_payload())
    error = response.get_json()["error"]
    assert response.status_code == 503
    assert error["code"] == "ollama_unavailable"
    assert "ollama pull qwen3.5:4b" in error["fix"]


def test_missing_model_gives_pull_command(client, monkeypatch):
    def boom(*_args):
        raise ollama_client.OllamaModelMissingError("model not installed")

    monkeypatch.setattr(ollama_client, "analyze", boom)
    response = post(client, sample_payload())
    assert response.status_code == 503
    assert response.get_json()["error"]["fix"] == "Run `ollama pull qwen3.5:4b`."


def test_unusable_model_answer_is_a_502(client, monkeypatch):
    def boom(*_args):
        raise ollama_client.OllamaResponseError("The model did not return valid JSON.")

    monkeypatch.setattr(ollama_client, "analyze", boom)
    response = post(client, sample_payload())
    assert response.status_code == 502
    assert response.get_json()["error"]["code"] == "model_error"


def test_unexpected_errors_do_not_leak_details(client, monkeypatch):
    def boom(*_args):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(ollama_client, "analyze", boom)
    response = post(client, sample_payload())
    assert response.status_code == 500
    assert "secret internal detail" not in response.get_data(as_text=True)


def test_only_one_check_runs_at_a_time(client, monkeypatch):
    started = {}

    def slow(_diff, _docs):
        # While the first check runs, a second request must be told to wait.
        started["second"] = post(client, sample_payload()).status_code
        return []

    monkeypatch.setattr(ollama_client, "analyze", slow)
    assert post(client, sample_payload()).status_code == 200
    assert started["second"] == 429


# ---------------------------------------------------------------- request guards


def test_cross_site_post_is_rejected(client):
    response = post(client, sample_payload(), headers={"Origin": "https://evil.example"})
    assert response.status_code == 403


def test_same_origin_post_is_allowed(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "analyze", lambda d, docs: [])
    response = post(client, sample_payload(), headers={"Origin": "http://localhost"})
    assert response.status_code == 200


def test_unknown_host_header_is_rejected_when_bound_to_loopback():
    app = web.create_app(allowed_hosts=web.LOOPBACK_HOSTS)
    client = app.test_client()
    assert client.get("/api/sample", headers={"Host": "localhost:8000"}).status_code == 200
    assert client.get("/api/sample", headers={"Host": "attacker.example"}).status_code == 400


# ---------------------------------------------------------------- command line


def test_serve_subcommand_is_registered():
    args = cli.build_parser().parse_args(["serve", "--port", "9001"])
    assert (args.command, args.host, args.port) == ("serve", "127.0.0.1", 9001)


def test_check_subcommand_still_works():
    args = cli.build_parser().parse_args(["check", "--base", "main"])
    assert (args.command, args.base) == ("check", "main")
