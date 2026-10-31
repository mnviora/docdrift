"""Reads the Git changes and Markdown documentation that docdrift analyzes.

Public interface (shared contract):

    collect_inputs(base: str) -> (diff_text: str, documents: dict[str, str])

* ``diff_text`` is the code diff between the merge-base of ``base`` and HEAD
  and the current working tree (so committed, staged and unstaged changes to
  tracked files are included). Markdown files are left out of the diff because
  they are sent separately as ``documents``.
* ``documents`` maps each tracked Markdown file path (relative to the
  repository root, always with "/" separators) to its full text, where every
  line is prefixed with its 1-based line number like ``"12: some text"``.
"""

from __future__ import annotations

import subprocess

# A 4B local model has a small context window, so keep the diff bounded.
MAX_DIFF_CHARS = 30_000

MARKDOWN_PATTERNS = ("*.md", "*.markdown")


class GitInputError(RuntimeError):
    """Raised with a user-friendly message when Git input cannot be read."""


def _git(args: list[str], cwd: str | None = None) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise GitInputError("Git was not found. Please install Git and try again.") from exc
    if result.returncode != 0:
        raise GitInputError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def _repo_root() -> str:
    try:
        return _git(["rev-parse", "--show-toplevel"]).strip()
    except GitInputError as exc:
        raise GitInputError(
            "This is not a Git repository. Run docdrift from inside your project."
        ) from exc


def _resolve_base(base: str, root: str) -> str:
    """Return the commit to diff against: the merge-base of `base` and HEAD."""
    try:
        _git(["rev-parse", "--verify", "--quiet", f"{base}^{{commit}}"], cwd=root)
    except GitInputError as exc:
        raise GitInputError(
            f"Could not find the base ref '{base}'. "
            f"Try 'git fetch' first, or pass another ref, e.g. --base main."
        ) from exc
    try:
        return _git(["merge-base", base, "HEAD"], cwd=root).strip()
    except GitInputError:
        # No common ancestor (unrelated histories): compare with base directly.
        return base


def _number_lines(text: str) -> str:
    return "\n".join(f"{n}: {line}" for n, line in enumerate(text.splitlines(), start=1))


def _read_diff(merge_base: str, root: str) -> str:
    excludes = [f":(exclude){pattern}" for pattern in MARKDOWN_PATTERNS]
    diff = _git(
        ["diff", "--no-color", "--unified=3", merge_base, "--", ".", *excludes],
        cwd=root,
    )
    if len(diff) > MAX_DIFF_CHARS:
        diff = (
            diff[:MAX_DIFF_CHARS]
            + f"\n[diff truncated: only the first {MAX_DIFF_CHARS} characters are shown]\n"
        )
    return diff


def _read_documents(root: str) -> dict[str, str]:
    listing = _git(["ls-files", "-z", "--", *MARKDOWN_PATTERNS], cwd=root)
    documents: dict[str, str] = {}
    for path in sorted(filter(None, listing.split("\0"))):
        try:
            with open(f"{root}/{path}", encoding="utf-8", errors="replace") as handle:
                documents[path] = _number_lines(handle.read())
        except OSError:
            continue  # e.g. file deleted in the working tree but still tracked
    return documents


def collect_inputs(base: str) -> tuple[str, dict[str, str]]:
    """Collect the code diff against `base` and the Markdown docs with line numbers."""
    root = _repo_root()
    merge_base = _resolve_base(base, root)
    return _read_diff(merge_base, root), _read_documents(root)
