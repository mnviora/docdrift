"""report.py

Owned by Henal.

Implements the shared contract:

    report.format_findings(findings) -> str

Turns a list of finding dicts (produced by ``ollama_client.analyze``) into a
readable string for the terminal. This module has no dependency on Ollama,
the model, or the network, so it can be unit tested in isolation.

Finding shape (shared contract, see HACKATHON spec):

    {
        "status": "possible_drift" | "uncertain",
        "document_file": str,
        "line_number": int | None,
        "quoted_text": str,
        "code_evidence": str,
        "explanation": str,
    }

Beyond the required ``format_findings``, this module offers:

    report.sanitize_findings(raw_findings)   -> (clean_findings, warnings)
        Defensively clean up whatever a (possibly imperfect) LLM response
        hands back before it's formatted or acted on.

    report.format_findings_markdown(findings) -> str
        A Markdown rendering, e.g. for pasting into a PR description.

    report.format_findings_compact(findings)  -> str
        One line per finding, for CI logs / grepping.

    report.summarize(findings)                -> {"total", "possible_drift", "uncertain"}
    report.summarize_by_file(findings)         -> {document_file: {same counts}}
    report.filter_findings(findings, ...)      -> list[dict]
    report.has_possible_drift(findings)        -> bool
    report.exit_code(findings)                 -> int  (0 clean, 1 drift found)
"""

from __future__ import annotations

import os
import sys

VALID_STATUSES = {"possible_drift", "uncertain"}

NO_DRIFT_MESSAGE = (
    "No likely documentation drift was found in the scanned files."
)

# Keep a single very long doc sentence or diff hunk from blowing up the
# terminal. format_findings(..., max_field_len=...) can override this.
DEFAULT_MAX_FIELD_LEN = 160

# Suggested process exit codes for a caller (e.g. cli.py) that wants CI to
# fail the build when drift is found.
EXIT_OK = 0
EXIT_DRIFT_FOUND = 1

_COLOR_CODES = {
    "possible_drift": "\033[31m",  # red
    "uncertain": "\033[33m",  # yellow
    "footer": "\033[1m",  # bold
    "reset": "\033[0m",
}

_MARKDOWN_EMOJI = {
    "possible_drift": "\U0001F534",  # red circle
    "uncertain": "\U0001F7E1",  # yellow circle
}


# ---------------------------------------------------------------------------
# Validation / sanitization
# ---------------------------------------------------------------------------


def validate_finding(finding) -> list[str]:
    """Return human-readable problems with a single finding.

    An empty list means the finding is well-formed enough to display (it
    may still be missing optional detail). This is deliberately lenient
    about anything format_findings already tolerates (missing/invalid
    status defaults to "uncertain"; a missing line_number is fine) and
    strict about what it can't recover from (no document location at all).
    """
    if not isinstance(finding, dict):
        return [f"finding is not a dict (got {type(finding).__name__})"]

    problems = []
    if not finding.get("document_file"):
        problems.append("missing or empty 'document_file'")

    status = finding.get("status")
    if status is not None and status not in VALID_STATUSES:
        problems.append(
            f"unrecognized status {status!r} "
            "(expected 'possible_drift' or 'uncertain')"
        )

    line_number = finding.get("line_number")
    if line_number is not None and not isinstance(line_number, int):
        problems.append(
            f"line_number should be an int or null, got {type(line_number).__name__}"
        )

    if not finding.get("quoted_text") and not finding.get("code_evidence"):
        problems.append("has neither quoted_text nor code_evidence")

    return problems


def sanitize_findings(raw_findings) -> tuple[list[dict], list[str]]:
    """Clean up a findings list that may have come straight out of a
    (possibly imperfect) LLM response, before it's formatted.

    A finding that isn't a dict, or has no 'document_file', is dropped
    entirely -- there's nowhere to point the reader. Anything else is kept
    (format_findings's own defaulting handles a bad/missing status), but
    noted in the returned warnings so a caller can log or display them.

    Returns (clean_findings, warnings).
    """
    if not isinstance(raw_findings, list):
        return (
            [],
            [
                f"expected a list of findings, got {type(raw_findings).__name__}; "
                "treating as no findings"
            ],
        )

    clean: list[dict] = []
    warnings: list[str] = []
    for i, finding in enumerate(raw_findings, start=1):
        problems = validate_finding(finding)
        is_dict = isinstance(finding, dict)
        dropped = (not is_dict) or (not finding.get("document_file"))
        if dropped:
            warnings.append(f"finding #{i} dropped: {'; '.join(problems)}")
            continue
        if problems:
            warnings.append(f"finding #{i} kept with issues: {'; '.join(problems)}")
        clean.append(finding)

    return clean, warnings


# ---------------------------------------------------------------------------
# Counting / filtering
# ---------------------------------------------------------------------------


def summarize(findings: list[dict]) -> dict:
    """Return counts: {'total', 'possible_drift', 'uncertain'}."""
    possible = sum(1 for f in findings if f.get("status") == "possible_drift")
    return {
        "total": len(findings),
        "possible_drift": possible,
        "uncertain": len(findings) - possible,
    }


def summarize_by_file(findings: list[dict]) -> dict:
    """Return {document_file: {'total', 'possible_drift', 'uncertain'}},
    for callers that want to see which docs need the most attention.
    Findings with no document_file are grouped under "<unknown file>".
    """
    by_file: dict[str, list[dict]] = {}
    for finding in findings:
        doc_file = finding.get("document_file") or "<unknown file>"
        by_file.setdefault(doc_file, []).append(finding)
    return {doc_file: summarize(items) for doc_file, items in by_file.items()}


def filter_findings(
    findings: list[dict],
    *,
    status: str | None = None,
    document_file: str | None = None,
) -> list[dict]:
    """Return the subset of findings matching the given status and/or
    document_file (both optional; combining them is an AND). Useful for a
    caller that wants to support e.g. "--only drift" or "--file README.md"
    without re-implementing the filtering logic.
    """
    result = findings
    if status is not None:
        result = [f for f in result if f.get("status") == status]
    if document_file is not None:
        result = [f for f in result if f.get("document_file") == document_file]
    return result


def has_possible_drift(findings: list[dict]) -> bool:
    """True if any finding is status == 'possible_drift'."""
    return any(f.get("status") == "possible_drift" for f in findings)


def exit_code(findings: list[dict]) -> int:
    """EXIT_DRIFT_FOUND (1) if any possible_drift finding is present, else
    EXIT_OK (0). For a caller (cli.py) deciding the process exit status."""
    return EXIT_DRIFT_FOUND if has_possible_drift(findings) else EXIT_OK


# ---------------------------------------------------------------------------
# Terminal formatting (the required contract function)
# ---------------------------------------------------------------------------


def format_findings(
    findings: list[dict],
    *,
    color: bool | None = None,
    max_field_len: int = DEFAULT_MAX_FIELD_LEN,
) -> str:
    """Format findings into a readable string for the terminal.

    - If ``findings`` is empty, report that no likely drift was found in the
      scanned files. This is deliberately scoped ("in the scanned files")
      rather than a blanket "the project is safe" claim.
    - possible_drift findings are listed before uncertain ones, so the
      highest-priority items are at the top; within a status, findings are
      grouped by document file and then by line number.
    - Each finding is rendered as a numbered block showing its status,
      location, the doc sentence in question, the code evidence behind the
      claim, and a short explanation. Overly long doc/code text is
      truncated to ``max_field_len`` characters so one finding can't
      swallow the terminal.
    - Findings with a missing/invalid status are treated as "uncertain"
      rather than dropped, since we'd rather over-report than silently hide
      something the model flagged.
    - ``color``: None (default) auto-detects an interactive terminal
      (honoring the NO_COLOR / FORCE_COLOR environment variables); True/False
      force it on or off, e.g. for tests or when piping to a file.
    """
    if not findings:
        return NO_DRIFT_MESSAGE

    use_color = _supports_color() if color is None else color
    counts = summarize(findings)
    ordered = _ordered(findings)

    lines = [
        f"Scanned files: {counts['total']} finding(s) "
        f"({counts['possible_drift']} possible drift, {counts['uncertain']} uncertain)",
        "",
    ]

    for index, finding in enumerate(ordered, start=1):
        lines.append(_format_single(index, finding, use_color, max_field_len))
        lines.append("")

    if counts["possible_drift"]:
        footer = (
            f"Review the {counts['possible_drift']} possible-drift "
            "item(s) above before merging."
        )
        if use_color:
            footer = f"{_COLOR_CODES['footer']}{footer}{_COLOR_CODES['reset']}"
        lines.append(footer)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _ordered(findings: list[dict]) -> list[dict]:
    """possible_drift first, then grouped by (document_file, line_number)."""

    def sort_key(finding: dict):
        status_rank = 0 if finding.get("status") == "possible_drift" else 1
        doc_file = finding.get("document_file") or ""
        line_number = finding.get("line_number")
        # A missing or non-int line_number sorts after any real one within
        # the same file (a malformed model response shouldn't crash sorting).
        line_rank = (0, line_number) if isinstance(line_number, int) else (1, 0)
        return (status_rank, doc_file, line_rank)

    return sorted(findings, key=sort_key)


def _supports_color(stream=None) -> bool:
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("FORCE_COLOR") is not None:
        return True
    return hasattr(stream, "isatty") and stream.isatty()


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "…"


def _status_and_label(finding: dict) -> tuple[str, str]:
    status = finding.get("status")
    if status not in VALID_STATUSES:
        status = "uncertain"
    label = "POSSIBLE DRIFT" if status == "possible_drift" else "UNCERTAIN"
    return status, label


def _location(finding: dict, *, quote_file: bool = False) -> str:
    """'file:line' when line_number is a real int, else just 'file'.

    A non-int line_number (e.g. a malformed model response that sent back
    a string) is treated the same as a missing one, rather than printed
    verbatim as "file:not-a-number".
    """
    doc_file = finding.get("document_file") or "<unknown file>"
    if quote_file:
        doc_file = f"`{doc_file}`"
    line_number = finding.get("line_number")
    if isinstance(line_number, int):
        return f"{doc_file}:{line_number}"
    return doc_file


def _format_single(
    index: int, finding: dict, use_color: bool, max_field_len: int
) -> str:
    status, label = _status_and_label(finding)
    if use_color:
        label = f"{_COLOR_CODES[status]}{label}{_COLOR_CODES['reset']}"

    location = _location(finding)

    quoted = _truncate(finding.get("quoted_text") or "", max_field_len)
    code = _truncate(finding.get("code_evidence") or "", max_field_len)
    explanation = (finding.get("explanation") or "").strip()

    block = [
        f"[{index}] {label} — {location}",
        f'    Doc says:   "{quoted}"' if quoted else "    Doc says:   (not provided)",
        f"    Code shows: {code}" if code else "    Code shows: (not provided)",
    ]
    if explanation:
        block.append(f"    Why:        {explanation}")

    return "\n".join(block)


# ---------------------------------------------------------------------------
# Alternate renderings
# ---------------------------------------------------------------------------


def format_findings_compact(
    findings: list[dict], *, max_field_len: int = DEFAULT_MAX_FIELD_LEN
) -> str:
    """One line per finding: 'file:line [status] explanation'.

    No color, no footer, no blank-line padding -- meant for CI logs or
    piping through grep, not for a human reading the terminal directly.
    Empty input still returns NO_DRIFT_MESSAGE for consistency with
    format_findings.
    """
    if not findings:
        return NO_DRIFT_MESSAGE

    rows = []
    for finding in _ordered(findings):
        status, _ = _status_and_label(finding)
        location = _location(finding)
        detail = (finding.get("explanation") or finding.get("quoted_text") or "").strip()
        detail = _truncate(detail, max_field_len)
        rows.append(f"{location} [{status}] {detail}".rstrip())

    return "\n".join(rows) + "\n"


def format_findings_markdown(
    findings: list[dict], *, max_field_len: int = DEFAULT_MAX_FIELD_LEN
) -> str:
    """Render findings as a Markdown document, e.g. to paste into a PR
    description by hand. This module never posts anything anywhere itself
    -- it only produces text.
    """
    if not findings:
        return f"## Documentation drift\n\n{NO_DRIFT_MESSAGE}\n"

    counts = summarize(findings)
    ordered = _ordered(findings)

    lines = [
        "## Documentation drift",
        "",
        f"**{counts['total']} finding(s)** — "
        f"{counts['possible_drift']} possible drift, {counts['uncertain']} uncertain",
        "",
    ]

    for index, finding in enumerate(ordered, start=1):
        status, label = _status_and_label(finding)
        emoji = _MARKDOWN_EMOJI[status]
        location = f"`{_location(finding)}`"

        quoted = _truncate(finding.get("quoted_text") or "", max_field_len)
        code = _truncate(finding.get("code_evidence") or "", max_field_len)
        explanation = (finding.get("explanation") or "").strip()

        lines.append(f"### {index}. {emoji} {label.title()} — {location}")
        lines.append("")
        if quoted:
            lines.append(f"- **Doc says:** {quoted}")
        if code:
            lines.append(f"- **Code shows:** `{code}`")
        if explanation:
            lines.append(f"- **Why:** {explanation}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
