"""Tests for the extra report.py features beyond the core format_findings
contract: validation/sanitization, alternate renderings (markdown/compact),
by-file summaries, filtering, and exit codes.

Still no Ollama, no model, no network.
"""

from docdrift.report import (
    EXIT_DRIFT_FOUND,
    EXIT_OK,
    NO_DRIFT_MESSAGE,
    exit_code,
    filter_findings,
    format_findings_compact,
    format_findings_markdown,
    sanitize_findings,
    summarize_by_file,
    validate_finding,
)

GOOD_DRIFT = {
    "status": "possible_drift",
    "document_file": "README.md",
    "line_number": 42,
    "quoted_text": "Use --timeout to set how long the command waits.",
    "code_evidence": "argparse: add_argument('--deadline', ...)",
    "explanation": "--timeout was renamed to --deadline in the diff.",
}

GOOD_UNCERTAIN = {
    "status": "uncertain",
    "document_file": "docs/usage.md",
    "line_number": 5,
    "quoted_text": "Retries happen automatically.",
    "code_evidence": "No retry logic visible in the diff.",
    "explanation": "Can't confirm from the diff alone.",
}


# ---------------------------------------------------------------------------
# validate_finding
# ---------------------------------------------------------------------------


def test_validate_finding_accepts_well_formed_finding():
    assert validate_finding(GOOD_DRIFT) == []


def test_validate_finding_flags_non_dict():
    problems = validate_finding("not a dict")
    assert len(problems) == 1
    assert "not a dict" in problems[0]


def test_validate_finding_flags_missing_document_file():
    bad = {**GOOD_DRIFT, "document_file": ""}
    problems = validate_finding(bad)
    assert any("document_file" in p for p in problems)


def test_validate_finding_flags_bad_status():
    bad = {**GOOD_DRIFT, "status": "definitely_drifted"}
    problems = validate_finding(bad)
    assert any("unrecognized status" in p for p in problems)


def test_validate_finding_flags_non_int_line_number():
    bad = {**GOOD_DRIFT, "line_number": "42"}
    problems = validate_finding(bad)
    assert any("line_number" in p for p in problems)


def test_validate_finding_allows_null_line_number():
    ok = {**GOOD_DRIFT, "line_number": None}
    assert validate_finding(ok) == []


def test_validate_finding_flags_no_evidence_at_all():
    bad = {**GOOD_DRIFT, "quoted_text": "", "code_evidence": ""}
    problems = validate_finding(bad)
    assert any("neither quoted_text nor code_evidence" in p for p in problems)


# ---------------------------------------------------------------------------
# sanitize_findings
# ---------------------------------------------------------------------------


def test_sanitize_findings_keeps_well_formed_findings_unchanged():
    clean, warnings = sanitize_findings([GOOD_DRIFT, GOOD_UNCERTAIN])
    assert clean == [GOOD_DRIFT, GOOD_UNCERTAIN]
    assert warnings == []


def test_sanitize_findings_drops_entries_with_no_document_file():
    raw = [GOOD_DRIFT, {"status": "possible_drift", "quoted_text": "x", "code_evidence": "y"}]
    clean, warnings = sanitize_findings(raw)
    assert clean == [GOOD_DRIFT]
    assert len(warnings) == 1
    assert "dropped" in warnings[0]


def test_sanitize_findings_drops_non_dict_entries():
    raw = [GOOD_DRIFT, "garbage", 42, None]
    clean, warnings = sanitize_findings(raw)
    assert clean == [GOOD_DRIFT]
    assert len(warnings) == 3


def test_sanitize_findings_keeps_bad_status_but_warns():
    bad_status = {**GOOD_DRIFT, "status": "maybe"}
    clean, warnings = sanitize_findings([bad_status])
    assert clean == [bad_status]
    assert len(warnings) == 1
    assert "kept with issues" in warnings[0]


def test_sanitize_findings_handles_non_list_input():
    clean, warnings = sanitize_findings({"not": "a list"})
    assert clean == []
    assert len(warnings) == 1
    assert "expected a list" in warnings[0]


def test_sanitize_findings_output_feeds_cleanly_into_format_findings():
    from docdrift.report import format_findings

    raw = [GOOD_DRIFT, {"document_file": "", "status": "possible_drift"}]
    clean, _ = sanitize_findings(raw)
    output = format_findings(clean, color=False)
    assert "README.md:42" in output
    assert "1 finding(s)" in output


# ---------------------------------------------------------------------------
# format_findings_compact
# ---------------------------------------------------------------------------


def test_compact_empty_returns_no_drift_message():
    assert format_findings_compact([]) == NO_DRIFT_MESSAGE


def test_compact_one_line_per_finding():
    output = format_findings_compact([GOOD_DRIFT, GOOD_UNCERTAIN])
    lines = [line for line in output.splitlines() if line.strip()]
    assert len(lines) == 2
    assert lines[0].startswith("README.md:42 [possible_drift]")
    assert lines[1].startswith("docs/usage.md:5 [uncertain]")


def test_compact_has_no_color_codes_or_footer():
    output = format_findings_compact([GOOD_DRIFT])
    assert "\033[" not in output
    assert "Review" not in output


# ---------------------------------------------------------------------------
# format_findings_markdown
# ---------------------------------------------------------------------------


def test_markdown_empty_still_names_no_drift():
    output = format_findings_markdown([])
    assert "## Documentation drift" in output
    assert NO_DRIFT_MESSAGE in output


def test_markdown_includes_heading_counts_and_fields():
    output = format_findings_markdown([GOOD_DRIFT])
    assert "## Documentation drift" in output
    assert "1 finding(s)" in output
    assert "README.md:42" in output
    assert "--timeout to set how long the command waits" in output
    assert "add_argument('--deadline'" in output
    assert "renamed to --deadline" in output


def test_markdown_uses_different_emoji_for_each_status():
    output = format_findings_markdown([GOOD_DRIFT, GOOD_UNCERTAIN])
    assert "\U0001F534" in output  # red circle for possible_drift
    assert "\U0001F7E1" in output  # yellow circle for uncertain


# ---------------------------------------------------------------------------
# summarize_by_file
# ---------------------------------------------------------------------------


def test_summarize_by_file_groups_correctly():
    second_drift_in_readme = {**GOOD_DRIFT, "line_number": 99}
    result = summarize_by_file([GOOD_DRIFT, second_drift_in_readme, GOOD_UNCERTAIN])

    assert result["README.md"] == {"total": 2, "possible_drift": 2, "uncertain": 0}
    assert result["docs/usage.md"] == {"total": 1, "possible_drift": 0, "uncertain": 1}


def test_summarize_by_file_groups_missing_file_as_unknown():
    no_file = {**GOOD_DRIFT}
    del no_file["document_file"]
    result = summarize_by_file([no_file])
    assert "<unknown file>" in result


# ---------------------------------------------------------------------------
# filter_findings
# ---------------------------------------------------------------------------


def test_filter_findings_by_status():
    result = filter_findings([GOOD_DRIFT, GOOD_UNCERTAIN], status="possible_drift")
    assert result == [GOOD_DRIFT]


def test_filter_findings_by_document_file():
    other_file = {**GOOD_UNCERTAIN, "document_file": "README.md"}
    result = filter_findings([GOOD_DRIFT, GOOD_UNCERTAIN, other_file], document_file="README.md")
    assert result == [GOOD_DRIFT, other_file]


def test_filter_findings_combines_both_filters():
    other_file = {**GOOD_UNCERTAIN, "document_file": "README.md"}
    result = filter_findings(
        [GOOD_DRIFT, GOOD_UNCERTAIN, other_file],
        status="uncertain",
        document_file="README.md",
    )
    assert result == [other_file]


def test_filter_findings_no_filters_returns_everything():
    findings = [GOOD_DRIFT, GOOD_UNCERTAIN]
    assert filter_findings(findings) == findings


# ---------------------------------------------------------------------------
# exit_code
# ---------------------------------------------------------------------------


def test_exit_code_ok_when_no_drift():
    assert exit_code([GOOD_UNCERTAIN]) == EXIT_OK
    assert exit_code([]) == EXIT_OK


def test_exit_code_nonzero_when_drift_present():
    assert exit_code([GOOD_DRIFT]) == EXIT_DRIFT_FOUND
    assert exit_code([GOOD_DRIFT, GOOD_UNCERTAIN]) == EXIT_DRIFT_FOUND
