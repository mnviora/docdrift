"""Tests for docdrift.report.

These use hand-built "fake" finding dicts -- no Ollama call, no model, no
network. They should pass in CI with nothing installed but the project
itself and pytest.

Every call pins color=False unless a test is specifically about color, so
results are deterministic whether or not the test runner's stdout is a tty.
"""

import json
import pathlib

from docdrift.report import (
    NO_DRIFT_MESSAGE,
    format_findings,
    has_possible_drift,
    summarize,
)

EXAMPLES_DIR = pathlib.Path(__file__).resolve().parent.parent / "examples"


def _load_example(name):
    d = EXAMPLES_DIR / name
    findings = json.loads((d / "finding.json").read_text())
    expected = (d / "expected_output.txt").read_text()
    return findings, expected


# ---------------------------------------------------------------------------
# Core formatting
# ---------------------------------------------------------------------------


def test_no_findings_reports_scoped_message():
    output = format_findings([], color=False)
    assert output == NO_DRIFT_MESSAGE
    # Must not claim the whole project is safe.
    assert "safe" not in output.lower()
    assert "scanned files" in output.lower()


def test_single_possible_drift_finding_includes_all_fields():
    finding = {
        "status": "possible_drift",
        "document_file": "README.md",
        "line_number": 42,
        "quoted_text": "Use --timeout to set how long the command waits.",
        "code_evidence": "argparse: add_argument('--deadline', ...)",
        "explanation": "--timeout was renamed to --deadline in the diff.",
    }

    output = format_findings([finding], color=False)

    assert "POSSIBLE DRIFT" in output
    assert "README.md:42" in output
    assert "--timeout to set how long the command waits" in output
    assert "add_argument('--deadline'" in output
    assert "renamed to --deadline" in output
    assert "1 finding(s)" in output
    assert "1 possible drift, 0 uncertain" in output


def test_uncertain_finding_is_labelled_uncertain():
    finding = {
        "status": "uncertain",
        "document_file": "docs/usage.md",
        "line_number": None,
        "quoted_text": "The tool retries failed requests automatically.",
        "code_evidence": "No retry logic found in the diff.",
        "explanation": "Can't confirm whether retry behavior changed from the diff alone.",
    }

    output = format_findings([finding], color=False)

    assert "UNCERTAIN" in output
    assert "POSSIBLE DRIFT" not in output
    # No line number given -> file path only, no trailing ":None".
    assert "docs/usage.md:" not in output
    assert "docs/usage.md" in output


def test_missing_or_invalid_status_defaults_to_uncertain_not_dropped():
    finding = {
        "document_file": "README.md",
        "quoted_text": "Some sentence.",
        "code_evidence": "Some code.",
        "explanation": "No status field at all.",
    }

    output = format_findings([finding], color=False)

    assert "UNCERTAIN" in output
    assert "1 finding(s)" in output


def test_multiple_findings_are_numbered_and_counted():
    findings = [
        {
            "status": "possible_drift",
            "document_file": "README.md",
            "line_number": 10,
            "quoted_text": "doc sentence one",
            "code_evidence": "code evidence one",
            "explanation": "reason one",
        },
        {
            "status": "uncertain",
            "document_file": "docs/setup.md",
            "line_number": 5,
            "quoted_text": "doc sentence two",
            "code_evidence": "code evidence two",
            "explanation": "reason two",
        },
    ]

    output = format_findings(findings, color=False)

    assert "[1]" in output
    assert "[2]" in output
    assert "2 finding(s) (1 possible drift, 1 uncertain)" in output


def test_missing_optional_text_fields_do_not_crash():
    finding = {
        "status": "possible_drift",
        "document_file": "README.md",
        "line_number": None,
        "quoted_text": "",
        "code_evidence": "",
        "explanation": "",
    }

    output = format_findings([finding], color=False)

    assert "(not provided)" in output
    assert "README.md" in output


# ---------------------------------------------------------------------------
# Ordering: possible_drift first, then grouped by file/line
# ---------------------------------------------------------------------------


def test_possible_drift_findings_are_listed_before_uncertain():
    findings = [
        {
            "status": "uncertain",
            "document_file": "a.md",
            "line_number": 1,
            "quoted_text": "x",
            "code_evidence": "x",
            "explanation": "x",
        },
        {
            "status": "possible_drift",
            "document_file": "z.md",
            "line_number": 99,
            "quoted_text": "y",
            "code_evidence": "y",
            "explanation": "y",
        },
    ]

    output = format_findings(findings, color=False)

    # The possible_drift finding (z.md) should be rendered as item [1]
    # even though it came second in the input list.
    first_block_end = output.index("[2]")
    assert "z.md:99" in output[:first_block_end]
    assert "POSSIBLE DRIFT" in output[:first_block_end]


def test_same_status_findings_grouped_by_file_then_line():
    findings = [
        {
            "status": "possible_drift",
            "document_file": "b.md",
            "line_number": 1,
            "quoted_text": "x",
            "code_evidence": "x",
            "explanation": "x",
        },
        {
            "status": "possible_drift",
            "document_file": "a.md",
            "line_number": 20,
            "quoted_text": "y",
            "code_evidence": "y",
            "explanation": "y",
        },
        {
            "status": "possible_drift",
            "document_file": "a.md",
            "line_number": 5,
            "quoted_text": "z",
            "code_evidence": "z",
            "explanation": "z",
        },
    ]

    output = format_findings(findings, color=False)

    pos_a5 = output.index("a.md:5")
    pos_a20 = output.index("a.md:20")
    pos_b1 = output.index("b.md:1")
    assert pos_a5 < pos_a20 < pos_b1


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------


def test_overly_long_fields_are_truncated():
    long_text = "x" * 500
    finding = {
        "status": "possible_drift",
        "document_file": "README.md",
        "line_number": 1,
        "quoted_text": long_text,
        "code_evidence": long_text,
        "explanation": "short",
    }

    output = format_findings([finding], color=False, max_field_len=50)

    assert long_text not in output
    assert "…" in output


def test_max_field_len_zero_or_negative_disables_truncation():
    long_text = "x" * 300
    finding = {
        "status": "possible_drift",
        "document_file": "README.md",
        "line_number": 1,
        "quoted_text": long_text,
        "code_evidence": "short",
        "explanation": "short",
    }

    output = format_findings([finding], color=False, max_field_len=0)

    assert long_text in output


# ---------------------------------------------------------------------------
# Color
# ---------------------------------------------------------------------------


def test_color_true_wraps_label_in_ansi_codes():
    finding = {
        "status": "possible_drift",
        "document_file": "README.md",
        "line_number": 1,
        "quoted_text": "x",
        "code_evidence": "x",
        "explanation": "x",
    }

    output = format_findings([finding], color=True)

    assert "\033[31m" in output  # red
    assert "\033[0m" in output
    assert "POSSIBLE DRIFT" in output  # still present as plain text inside the codes


def test_color_false_has_no_ansi_codes():
    finding = {
        "status": "possible_drift",
        "document_file": "README.md",
        "line_number": 1,
        "quoted_text": "x",
        "code_evidence": "x",
        "explanation": "x",
    }

    output = format_findings([finding], color=False)

    assert "\033[" not in output


# ---------------------------------------------------------------------------
# Review-nudge footer
# ---------------------------------------------------------------------------


def test_footer_appears_only_when_possible_drift_present():
    drift_finding = {
        "status": "possible_drift",
        "document_file": "README.md",
        "line_number": 1,
        "quoted_text": "x",
        "code_evidence": "x",
        "explanation": "x",
    }
    uncertain_finding = {**drift_finding, "status": "uncertain"}

    with_drift = format_findings([drift_finding], color=False)
    without_drift = format_findings([uncertain_finding], color=False)

    assert "Review the 1 possible-drift item(s)" in with_drift
    assert "Review the" not in without_drift


# ---------------------------------------------------------------------------
# Helpers: summarize / has_possible_drift
# ---------------------------------------------------------------------------


def test_summarize_counts():
    findings = [
        {"status": "possible_drift"},
        {"status": "possible_drift"},
        {"status": "uncertain"},
        {},  # missing status counts as uncertain for display, but summarize
             # only counts exact "possible_drift" matches as drift
    ]

    counts = summarize(findings)

    assert counts == {"total": 4, "possible_drift": 2, "uncertain": 2}


def test_has_possible_drift_true_and_false():
    assert has_possible_drift([{"status": "possible_drift"}]) is True
    assert has_possible_drift([{"status": "uncertain"}]) is False
    assert has_possible_drift([]) is False


# ---------------------------------------------------------------------------
# Regression against saved example fixtures
# ---------------------------------------------------------------------------


def test_matches_timeout_to_deadline_example():
    findings, expected = _load_example("timeout_to_deadline")
    assert format_findings(findings, color=False) == expected


def test_matches_no_drift_found_example():
    findings, expected = _load_example("no_drift_found")
    assert format_findings(findings, color=False) == expected


def test_matches_uncertain_only_example():
    findings, expected = _load_example("uncertain_only")
    assert format_findings(findings, color=False) == expected


def test_matches_malformed_model_output_example():
    """The example script prints sanitize_findings()'s warnings followed by
    format_findings() on the cleaned list -- reproduce both steps here."""
    from docdrift.report import sanitize_findings

    d = EXAMPLES_DIR / "malformed_model_output"
    raw = json.loads((d / "raw_model_response.json").read_text())
    expected = (d / "expected_output.txt").read_text()

    clean, warnings = sanitize_findings(raw)
    lines = [f"{len(warnings)} issue(s) while reading the model's response:"]
    lines += [f"  - {w}" for w in warnings]
    lines.append("")
    rendered = "\n".join(lines) + "\n" + format_findings(clean, color=False) + "\n"

    assert rendered == expected


def test_matches_markdown_and_compact_example():
    from docdrift.report import format_findings_compact, format_findings_markdown

    d = EXAMPLES_DIR / "markdown_and_compact"
    findings = json.loads((d / "findings.json").read_text())
    expected = (d / "expected_output.txt").read_text()

    rendered = (
        "=== Markdown ===\n"
        + format_findings_markdown(findings)
        + "\n=== Compact ===\n"
        + format_findings_compact(findings)
        + "\n"
    )

    assert rendered == expected
