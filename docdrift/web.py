"""Local website for DocDrift.

Flow: browser form -> this Flask app -> ``ollama_client.analyze`` -> local
Ollama (qwen3.5:4b) -> findings shown in the browser.

Safety notes:
* Submitted text is only analysed as text. Nothing is executed, nothing is
  written to disk, and nothing is sent anywhere except the local Ollama
  service.
* The server binds to 127.0.0.1 by default and rejects cross-site POSTs.
"""

from __future__ import annotations

import re
import sys
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from docdrift import ollama_client, prompts, report
from docdrift.git_input import _number_lines
from docdrift.sample import SAMPLE_DIFF, SAMPLE_DOCUMENTS

try:  # Flask is only needed for the website, not for the command-line tool.
    from flask import Flask, jsonify, request, send_from_directory
except ImportError:  # pragma: no cover - exercised only without Flask installed
    Flask = None  # type: ignore[assignment,misc]

STATIC_DIR = Path(__file__).resolve().parent / "static"

MAX_REQUEST_BYTES = 1_000_000
MAX_DIFF_CHARS = 100_000
MAX_DOC_CHARS = 100_000
MAX_DOCUMENTS = 10
MARKDOWN_EXTENSIONS = (".md", ".markdown")
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}

CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


class WebInputError(Exception):
    """A problem with what the user submitted. The message is shown to them."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


# --------------------------------------------------------------------------
# Input validation (pure functions, easy to test)
# --------------------------------------------------------------------------

def _clean_text(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise WebInputError("invalid_request", f"{label} must be text.")
    if "\x00" in value:
        raise WebInputError(
            "invalid_file", f"{label} looks like a binary file. Use plain text."
        )
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _clean_name(raw: Any, fallback: str) -> str:
    name = str(raw or "").strip().replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(" .")[:100] or fallback
    if not name.lower().endswith(MARKDOWN_EXTENSIONS):
        raise WebInputError(
            "invalid_file",
            f"'{name}' is not a Markdown file. Documentation files must end in .md or .markdown.",
        )
    return name


def _looks_like_diff(text: str) -> bool:
    return re.search(r"^(@@|diff |\+|-)", text, re.MULTILINE) is not None


def validate_payload(payload: Any) -> tuple[str, dict[str, str]]:
    """Check the submitted JSON and return (diff_text, {file name: raw text})."""
    if not isinstance(payload, dict):
        raise WebInputError("invalid_request", "The request was not valid JSON.")

    diff = _clean_text(payload.get("diff", ""), "The code diff")
    if not diff.strip():
        raise WebInputError(
            "missing_diff",
            "Add a code diff first: paste the output of `git diff`, upload a .diff or "
            ".patch file, or load the sample.",
        )
    if len(diff) > MAX_DIFF_CHARS:
        raise WebInputError(
            "too_large",
            f"The diff is too large ({len(diff):,} characters). The limit is "
            f"{MAX_DIFF_CHARS:,}. Try a smaller change.",
            413,
        )
    if not _looks_like_diff(diff):
        raise WebInputError(
            "invalid_diff",
            "That does not look like a diff. Paste the output of `git diff` or a .patch file.",
        )

    raw_documents = payload.get("documents")
    if not isinstance(raw_documents, list):
        raise WebInputError("invalid_request", "The request had no list of documents.")
    if len(raw_documents) > MAX_DOCUMENTS:
        raise WebInputError(
            "too_large", f"Too many documents. The limit is {MAX_DOCUMENTS}.", 413
        )

    documents: dict[str, str] = {}
    for index, item in enumerate(raw_documents, start=1):
        if not isinstance(item, dict):
            raise WebInputError("invalid_request", "A document was not in the expected format.")
        text = _clean_text(item.get("text", ""), "The documentation")
        if not text.strip():
            continue  # an empty card is ignored as long as another has text
        name = _clean_name(item.get("name"), "README.md" if index == 1 else f"doc-{index}.md")
        if len(text) > MAX_DOC_CHARS:
            raise WebInputError(
                "too_large",
                f"'{name}' is too large ({len(text):,} characters). The limit per "
                f"document is {MAX_DOC_CHARS:,}.",
                413,
            )
        unique, counter = name, 2
        while unique in documents:
            stem, dot, ext = name.rpartition(".")
            unique = f"{stem}-{counter}.{ext}" if dot else f"{name}-{counter}"
            counter += 1
        documents[unique] = text

    if not documents:
        raise WebInputError(
            "missing_docs",
            "Add documentation to check: paste Markdown, upload .md files, or load the sample.",
        )
    return diff, documents


def build_warnings(diff: str, numbered_documents: dict[str, str]) -> list[str]:
    """Tell the user when the model only saw part of what they sent."""
    warnings: list[str] = []
    if len(diff) > prompts.MAX_DIFF_CHARS:
        warnings.append(
            f"The model only read the first {prompts.MAX_DIFF_CHARS:,} characters of the diff. "
            "Changes after that point were not checked."
        )
    if sum(len(text) for text in numbered_documents.values()) > prompts.MAX_DOCS_CHARS:
        warnings.append(
            f"The model only read about {prompts.MAX_DOCS_CHARS:,} characters of documentation. "
            "Later text or files were not checked."
        )
    return warnings


_LABELS = {"possible_drift": "Possible documentation drift", "uncertain": "Uncertain"}
_NO_DRIFT_HEADLINE = "No likely drift found in the supplied files"


def build_markdown(findings: list[dict], warnings: list[str]) -> str:
    """The downloadable report. Keeps the full code evidence in a fenced block."""
    counts = report.summarize(findings)
    lines = ["# DocDrift report", ""]
    if not findings:
        lines += [
            f"**{_NO_DRIFT_HEADLINE}.**",
            "",
            "Only the diff and documentation that were supplied were checked. "
            "This does not prove other documentation is up to date.",
            "",
        ]
    else:
        lines += [
            f"{counts['total']} finding(s): {counts['possible_drift']} possible drift, "
            f"{counts['uncertain']} uncertain.",
            "",
        ]
    for index, finding in enumerate(findings, start=1):
        where = finding.get("document_file") or "unknown file"
        if isinstance(finding.get("line_number"), int):
            where += f", line {finding['line_number']}"
        lines += [f"## {index}. {_LABELS.get(finding.get('status'), 'Uncertain')} ({where})", ""]
        quote = (finding.get("quoted_text") or "").strip()
        if quote:
            lines += ["The documentation says:", "", f"> {quote}", ""]
        evidence = (finding.get("code_evidence") or "").strip()
        if evidence:
            lines += ["Changed code that supports this:", "", "```diff", evidence, "```", ""]
        explanation = (finding.get("explanation") or "").strip()
        if explanation:
            lines += [f"Why it may be outdated: {explanation}", ""]
    if warnings:
        lines += ["## Notes", ""] + [f"- {w}" for w in warnings] + [""]
    lines += ["---", f"Checked locally with {ollama_client.MODEL} through Ollama.", ""]
    return "\n".join(lines)


def build_result(findings: list[dict], warnings: list[str]) -> dict[str, Any]:
    clean, _problems = report.sanitize_findings(findings)
    ordered = report._ordered(clean)
    summary = report.summarize(ordered)
    if summary["possible_drift"]:
        verdict = "possible_drift"
    elif summary["total"]:
        verdict = "uncertain"
    else:
        verdict = "none"
    markdown = build_markdown(ordered, warnings)
    return {
        "ok": True,
        "model": ollama_client.MODEL,
        "verdict": verdict,
        "summary": summary,
        "findings": ordered,
        "warnings": warnings,
        "markdown": markdown,
    }


# --------------------------------------------------------------------------
# The Flask app
# --------------------------------------------------------------------------

def create_app(allowed_hosts: set[str] | None = None) -> "Flask":
    """Build the app. ``allowed_hosts`` (host names) enables a Host header check."""
    if Flask is None:
        raise RuntimeError("Flask is not installed. Run: pip install -r requirements.txt")

    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
    app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
    app.json.sort_keys = False
    busy = threading.Lock()  # one check at a time: a 4B model on a laptop is slow

    def error(code: str, message: str, status: int, **extra: Any):
        body = {"ok": False, "error": {"code": code, "message": message, **extra}}
        return jsonify(body), status

    @app.before_request
    def guard_request():
        if allowed_hosts is not None:
            host = urlparse("//" + request.host).hostname or ""
            if host.lower() not in allowed_hosts:
                return error("bad_host", "This address is not allowed.", 400)
        if request.method == "POST":
            origin = request.headers.get("Origin")
            if origin and urlparse(origin).netloc != request.host:
                return error("bad_origin", "Cross-site requests are not allowed.", 403)

    @app.after_request
    def add_headers(response):
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(413)
    def too_large(_exc):
        return error(
            "too_large",
            "That is too much text to send at once. The limit is about 1 MB in total.",
            413,
        )

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/api/status")
    def status():
        return jsonify(ollama_client.check_status())

    @app.get("/api/sample")
    def sample():
        return jsonify({"diff": SAMPLE_DIFF, "documents": SAMPLE_DOCUMENTS})

    @app.post("/api/analyze")
    def analyze():
        try:
            diff, documents = validate_payload(request.get_json(silent=True))
        except WebInputError as exc:
            return error(exc.code, exc.message, exc.status)

        numbered = {name: _number_lines(text) for name, text in documents.items()}
        warnings = build_warnings(diff, numbered)

        if not busy.acquire(blocking=False):
            return error(
                "busy",
                "Another check is still running. Wait for it to finish, then try again.",
                429,
            )
        try:
            findings = ollama_client.analyze(diff, numbered)
        except ollama_client.OllamaModelMissingError as exc:
            return error(
                "model_missing", str(exc), 503, fix=f"Run `ollama pull {ollama_client.MODEL}`."
            )
        except ollama_client.OllamaUnavailableError as exc:
            return error(
                "ollama_unavailable", str(exc), 503, fix=ollama_client.INSTALL_HELP
            )
        except ollama_client.OllamaError as exc:
            return error(
                "model_error",
                f"{exc} Try again; small local models sometimes give an unusable answer.",
                502,
            )
        except Exception:  # noqa: BLE001 - never leak internals to the browser
            app.logger.exception("Unexpected error while analysing")
            return error(
                "unexpected",
                "The check failed unexpectedly. Details are in the terminal running DocDrift.",
                500,
            )
        finally:
            busy.release()

        return jsonify(build_result(findings, warnings))

    return app


def run(host: str = "127.0.0.1", port: int = 8000) -> int:
    """Start the website. Returns a process exit code."""
    if Flask is None:
        print(
            "Error: Flask is not installed. Run: python -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1
    allowed = LOOPBACK_HOSTS if host in LOOPBACK_HOSTS else None
    app = create_app(allowed_hosts=allowed)
    shown = "localhost" if host in LOOPBACK_HOSTS else host
    print(f"DocDrift is running at http://{shown}:{port}  (press Ctrl+C to stop)")
    if allowed is None:
        print("Warning: listening beyond this computer. Anyone on your network can reach it.")
    try:
        app.run(host=host, port=port, threaded=True, debug=False)
    except OSError as exc:
        print(f"Error: could not start on {host}:{port} ({exc}). Try --port 8001.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
