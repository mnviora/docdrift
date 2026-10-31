"""Local Qwen connection through Ollama.

Owned by Anubhuti. Public interface (shared contract):

    analyze(diff_text: str, documents: dict[str, str]) -> list[dict]

Each finding has the keys status, document_file, line_number, quoted_text,
code_evidence and explanation. Only the Python standard library is used, and
only a local Ollama server is contacted (default http://localhost:11434).
No cloud AI service or API key is involved.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from .prompts import FINDING_FIELDS, FINDING_STATUSES, FINDINGS_SCHEMA, build_messages

MODEL = "qwen3.5:4b"
DEFAULT_HOST = "http://localhost:11434"
DEFAULT_TIMEOUT_SECONDS = 300  # a 4B model on a laptop can be slow
NUM_CTX = 16384


class OllamaError(RuntimeError):
    """Base class. The message is written to be shown directly to the user."""


class OllamaUnavailableError(OllamaError):
    """Ollama is not running / not reachable."""


class OllamaModelMissingError(OllamaError):
    """Ollama is running but qwen3.5:4b is not downloaded."""


class OllamaResponseError(OllamaError):
    """Ollama answered, but not with usable findings."""


# --------------------------------------------------------------------------
# Talking to Ollama
# --------------------------------------------------------------------------

def _host() -> str:
    host = os.environ.get("OLLAMA_HOST", "").strip() or DEFAULT_HOST
    if "://" not in host:
        host = "http://" + host
    return host.rstrip("/")


def _timeout() -> float:
    raw = os.environ.get("DOCDRIFT_OLLAMA_TIMEOUT", "").strip()
    try:
        return float(raw) if raw else DEFAULT_TIMEOUT_SECONDS
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def _chat(messages: list[dict[str, str]]) -> str:
    host = _host()
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "think": False,
        "format": FINDINGS_SCHEMA,
        "options": {"temperature": 0, "num_ctx": NUM_CTX},
    }
    request = urllib.request.Request(
        f"{host}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_timeout()) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read().decode("utf-8", "replace")).get("error", "")
        except Exception:  # noqa: BLE001 - best effort only
            pass
        if exc.code == 404 or "not found" in detail.lower():
            raise OllamaModelMissingError(
                f"Ollama is running but the model '{MODEL}' is not installed. "
                f"Run:  ollama pull {MODEL}"
            ) from exc
        raise OllamaError(
            f"Ollama returned HTTP {exc.code}" + (f": {detail}" if detail else ".")
        ) from exc
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, TimeoutError) or isinstance(exc, TimeoutError):
            raise OllamaUnavailableError(
                f"Ollama at {host} did not answer in time. The model may still be "
                "loading; try again, or raise DOCDRIFT_OLLAMA_TIMEOUT (seconds)."
            ) from exc
        raise OllamaUnavailableError(
            f"Could not reach Ollama at {host} ({reason}). Install Ollama, start it "
            f"(run `ollama serve` or open the Ollama app), then run `ollama pull {MODEL}`."
        ) from exc

    try:
        data = json.loads(body)
        content = data["message"]["content"]
    except (ValueError, KeyError, TypeError) as exc:
        raise OllamaResponseError("Ollama returned an unexpected response format.") from exc
    if not isinstance(content, str) or not content.strip():
        raise OllamaResponseError("The model returned an empty answer.")
    return content


# --------------------------------------------------------------------------
# Parsing the model output
# --------------------------------------------------------------------------

def _parse_json(content: str) -> Any:
    text = content.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        return json.loads(text)
    except ValueError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except ValueError:
            pass
    raise OllamaResponseError("The model did not return valid JSON.")


def _raw_findings(content: str) -> list[Any]:
    parsed = _parse_json(content)
    if isinstance(parsed, dict):
        parsed = parsed.get("findings")
    if not isinstance(parsed, list):
        raise OllamaResponseError("The model's JSON did not contain a 'findings' list.")
    return parsed


# --------------------------------------------------------------------------
# Checking findings against the real inputs
# --------------------------------------------------------------------------

# Documents arrive "with line numbers"; tolerate "12: text", "12 | text",
# "12<TAB>text" and "L12: text".
_LINE_PREFIX = re.compile(r"^\s*L?(\d+)\s*(?:[:|]|\t)\s?")


def _norm(text: str) -> str:
    return " ".join(text.replace("`", "").split())


def _split_document(text: str) -> list[tuple[int, str]]:
    lines = []
    for index, raw in enumerate(text.splitlines(), start=1):
        match = _LINE_PREFIX.match(raw)
        if match:
            lines.append((int(match.group(1)), raw[match.end():]))
        else:
            lines.append((index, raw))
    return lines


def _strip_prefixes(text: str) -> str:
    return "\n".join(_LINE_PREFIX.sub("", line, count=1) for line in text.splitlines())


def _locate(doc_lines: list[tuple[int, str]], quote: str) -> int | None:
    """Return the document line number where ``quote`` starts, or None."""
    needle = _norm(_strip_prefixes(quote))
    if not needle:
        return None
    joined = ""
    starts: list[tuple[int, int]] = []
    for number, text in doc_lines:
        starts.append((len(joined), number))
        joined += _norm(text) + " "
    index = joined.find(needle)
    if index == -1:
        return None
    line = starts[0][1]
    for offset, number in starts:
        if offset <= index:
            line = number
        else:
            break
    return line


def _norm_diff(text: str) -> str:
    lines = []
    for line in text.splitlines():
        lines.append(line[1:] if line[:1] in ("+", "-", " ") else line)
    return _norm("\n".join(lines))


def _resolve_document(name: Any, documents: dict[str, str]) -> str | None:
    if not isinstance(name, str):
        return None
    if name in documents:
        return name
    cleaned = name.strip().lstrip("./")
    for path in documents:
        if path == cleaned or path.endswith("/" + cleaned) or cleaned.endswith("/" + path):
            return path
    return None


def _validate(
    raw: list[Any], diff_text: str, documents: dict[str, str]
) -> list[dict[str, Any]]:
    doc_lines = {path: _split_document(text) for path, text in documents.items()}
    diff_norm = _norm_diff(diff_text)
    findings: list[dict[str, Any]] = []
    seen: set[tuple[str, int | None, str]] = set()

    for item in raw:
        if not isinstance(item, dict):
            continue
        path = _resolve_document(item.get("document_file"), documents)
        quote = item.get("quoted_text")
        if path is None or not isinstance(quote, str):
            continue  # cannot be tied to a supplied document: drop it
        line = _locate(doc_lines[path], quote)
        if line is None:
            continue  # quote is not in the document: model invented it

        status = item.get("status")
        if status not in FINDING_STATUSES:
            status = "uncertain"
        explanation = str(item.get("explanation") or "").strip()
        evidence = item.get("code_evidence")
        evidence = evidence.strip() if isinstance(evidence, str) else ""

        evidence_ok = bool(evidence) and _norm_diff(evidence) in diff_norm
        if not evidence_ok:
            # No verifiable support in the diff: never present it as drift.
            status = "uncertain"
            evidence = ""
            note = "No matching code evidence was found in the diff."
            explanation = f"{explanation} {note}".strip()

        key = (path, line, _norm(quote))
        if key in seen:
            continue
        seen.add(key)
        findings.append(
            {
                "status": status,
                "document_file": path,
                "line_number": line,
                "quoted_text": _strip_prefixes(quote).strip(),
                "code_evidence": evidence,
                "explanation": explanation or "The documentation may no longer match the change.",
            }
        )
    assert all(set(f) == set(FINDING_FIELDS) for f in findings)
    return findings


# --------------------------------------------------------------------------
# Public interface
# --------------------------------------------------------------------------

def analyze(diff_text: str, documents: dict[str, str]) -> list[dict[str, Any]]:
    """Ask local qwen3.5:4b which documentation sentences the diff made outdated.

    Returns a list of finding dictionaries (possibly empty). Raises
    ``OllamaError`` subclasses with a user-friendly message if Ollama or the
    model is unavailable or answers badly.
    """
    if not diff_text or not diff_text.strip() or not documents:
        return []

    messages = build_messages(diff_text, documents)
    try:
        raw = _raw_findings(_chat(messages))
    except OllamaResponseError:
        # Small models occasionally slip; one retry is cheap.
        raw = _raw_findings(_chat(messages))
    return _validate(raw, diff_text, documents)
