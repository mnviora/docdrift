"""End-to-end-ish test of the report stage with a *mocked* Ollama client.

This does not import docdrift.ollama_client directly (that module belongs
to Anubhuti and may not exist on this branch yet). Instead it stands in a
fake client with the same shape as the shared contract --
``analyze(diff_text, documents) -> list[finding]`` -- to prove report.py
works correctly when fed whatever a (mocked) model call would return.

No network access, no Ollama process, and no downloaded model are needed
to run this test.
"""

from unittest.mock import MagicMock

from docdrift.report import format_findings


def test_report_renders_mocked_ollama_client_output():
    # Stand-in for ollama_client.analyze(diff_text, documents)
    fake_analyze = MagicMock(
        return_value=[
            {
                "status": "possible_drift",
                "document_file": "README.md",
                "line_number": 42,
                "quoted_text": "Use --timeout to set how long the command waits before giving up.",
                "code_evidence": (
                    "argparse: parser.add_argument('--deadline', ...)  "
                    "# replaces removed '--timeout' option"
                ),
                "explanation": (
                    "The code diff renames the CLI option from --timeout to "
                    "--deadline, but README.md still documents --timeout."
                ),
            }
        ]
    )

    diff_text = "- '--timeout'\n+ '--deadline'\n"
    documents = {"README.md": "42: Use --timeout to set how long..."}

    findings = fake_analyze(diff_text, documents)
    output = format_findings(findings, color=False)

    fake_analyze.assert_called_once_with(diff_text, documents)
    assert "POSSIBLE DRIFT" in output
    assert "README.md:42" in output
    assert "--deadline" in output


def test_report_handles_empty_mocked_response():
    fake_analyze = MagicMock(return_value=[])

    findings = fake_analyze("some diff", {"README.md": "no relevant lines"})
    output = format_findings(findings, color=False)

    assert output == "No likely documentation drift was found in the scanned files."
