"""Demo: sanitize_findings() cleaning up an imperfect raw model response.

Real LLM output won't always match the shared contract exactly -- a field
might be missing, a status might be misspelled, or the model might return
something that isn't even a well-formed object. This shows sanitize_findings
catching that before it ever reaches format_findings, instead of the CLI
crashing on a KeyError or TypeError.

raw_model_response.json intentionally contains:
  1. a well-formed possible_drift finding (kept)
  2. a finding missing 'document_file' (dropped -- nowhere to point the reader)
  3. a bare string instead of an object (dropped)
  4. a finding with a bad 'status' and non-int 'line_number', but a real
     document_file (kept, with a warning; format_findings still displays it
     sensibly by treating the bad status as "uncertain")

Run from the repo root:
    python examples/malformed_model_output/run_example.py
"""

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from docdrift.report import format_findings, sanitize_findings  # noqa: E402


def main() -> None:
    raw = json.loads((HERE / "raw_model_response.json").read_text())
    clean, warnings = sanitize_findings(raw)

    if warnings:
        print(f"{len(warnings)} issue(s) while reading the model's response:")
        for warning in warnings:
            print(f"  - {warning}")
        print()

    print(format_findings(clean, color=False))


if __name__ == "__main__":
    main()
