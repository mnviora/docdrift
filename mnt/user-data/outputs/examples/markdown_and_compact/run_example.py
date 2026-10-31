"""Demo: the two alternate renderings alongside the default terminal one.

- format_findings_markdown(): for pasting into a PR description by hand.
- format_findings_compact(): one line per finding, meant for CI logs or
  piping through grep rather than for a human reading the terminal.

Run from the repo root:
    python examples/markdown_and_compact/run_example.py
"""

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from docdrift.report import (  # noqa: E402
    format_findings_compact,
    format_findings_markdown,
)


def main() -> None:
    findings = json.loads((HERE / "findings.json").read_text())

    print("=== Markdown ===")
    print(format_findings_markdown(findings))
    print("=== Compact ===")
    print(format_findings_compact(findings))


if __name__ == "__main__":
    main()
