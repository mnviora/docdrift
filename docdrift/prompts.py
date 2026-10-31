"""Prompt text and output schema for the local Qwen documentation-drift check.

Owned by Anubhuti. Used only by ``docdrift.ollama_client``.
"""

from __future__ import annotations

FINDING_STATUSES = ("possible_drift", "uncertain")

FINDING_FIELDS = (
    "status",
    "document_file",
    "line_number",
    "quoted_text",
    "code_evidence",
    "explanation",
)

# JSON schema passed to Ollama's structured-output ``format`` option so the
# model is constrained to the shared finding shape.
FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": list(FINDING_STATUSES)},
                    "document_file": {"type": "string"},
                    "line_number": {"type": ["integer", "null"]},
                    "quoted_text": {"type": "string"},
                    "code_evidence": {"type": "string"},
                    "explanation": {"type": "string"},
                },
                "required": list(FINDING_FIELDS),
            },
        }
    },
    "required": ["findings"],
}

# Rough character budgets so a small local model is not overrun.
MAX_DIFF_CHARS = 20000
MAX_DOCS_CHARS = 20000

SYSTEM_PROMPT = """\
You check whether a code change made Markdown documentation outdated.

You are given a Git diff and one or more Markdown documents. Lines in the
documents start with their line number.

Rules:
1. Look for documentation sentences that describe something the diff removed,
   renamed or changed (command-line options, function names, defaults, file
   paths, environment variables, behaviour). Report a sentence only if the diff
   makes it likely to be wrong now.
2. Use ONLY the diff and the documents you were given. Never invent files,
   sentences, code or line numbers.
3. "quoted_text" must be copied word for word from one document line, without
   the line-number prefix.
4. "code_evidence" must be copied from the diff (the removed or added lines
   that show the change).
5. "document_file" must be exactly one of the file paths provided.
6. Use status "possible_drift" when the diff clearly contradicts the sentence.
   Use status "uncertain" when the sentence might be affected but the diff does
   not clearly show it. Do not guess.
7. "explanation" is one short sentence giving the reason.
8. If you find no likely problem, return {"findings": []}.
9. Reply with JSON only, matching the requested schema.
"""

# Shown to the model purely as a format illustration. It is not part of the
# user's repository and must never be reported as a finding.
_EXAMPLE = """\
Illustration of the expected format (NOT part of the real input):
{"findings": [{"status": "possible_drift", "document_file": "README.md",
"line_number": 12, "quoted_text": "Use --timeout to set the limit.",
"code_evidence": "-    parser.add_argument(\\"--timeout\\")\\n+    parser.add_argument(\\"--deadline\\")",
"explanation": "The diff renames --timeout to --deadline but the README still says --timeout."}]}
"""


def _truncate(text: str, limit: int, label: str) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[... {label} truncated after {limit} characters ...]\n"


def _format_documents(documents: dict[str, str]) -> str:
    parts: list[str] = []
    used = 0
    omitted: list[str] = []
    for path, text in documents.items():
        remaining = MAX_DOCS_CHARS - used
        if remaining <= 0:
            omitted.append(path)
            continue
        body = _truncate(text, remaining, f"document {path}")
        used += min(len(text), remaining)
        parts.append(f"=== DOCUMENT: {path} ===\n{body}\n")
    if omitted:
        parts.append(
            "[Documents not shown because of the size limit: " + ", ".join(omitted) + "]\n"
        )
    return "\n".join(parts)


def build_messages(diff_text: str, documents: dict[str, str]) -> list[dict[str, str]]:
    """Return the chat messages (system + user) for Ollama's /api/chat."""
    diff_part = _truncate(diff_text, MAX_DIFF_CHARS, "diff")
    user = (
        f"{_EXAMPLE}\n"
        "=== GIT DIFF ===\n"
        f"{diff_part}\n"
        "=== END GIT DIFF ===\n\n"
        f"{_format_documents(documents)}\n"
        "Now list documentation sentences that the diff may have made outdated. "
        "Reply with JSON only."
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
