"""Command-line entry point: python -m docdrift check --base origin/main"""

from __future__ import annotations

import argparse
import sys

from docdrift import git_input, ollama_client, report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docdrift",
        description="Check whether a code change made Markdown documentation outdated.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser(
        "check", help="compare the code changes against the Markdown documentation"
    )
    check.add_argument(
        "--base",
        default="origin/main",
        help="Git ref to compare against (default: origin/main)",
    )
    serve = subparsers.add_parser("serve", help="start the local website")
    serve.add_argument(
        "--host",
        default="127.0.0.1",
        help="address to listen on (default: 127.0.0.1, this computer only)",
    )
    serve.add_argument("--port", type=int, default=8000, help="port (default: 8000)")
    return parser


def _run_check(base: str) -> int:
    try:
        diff_text, documents = git_input.collect_inputs(base)
    except git_input.GitInputError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not diff_text.strip():
        print(f"No code changes found compared with '{base}', so there is nothing to check.")
        return 0
    if not documents:
        print("No Markdown documentation files were found in this repository.")
        return 0

    try:
        findings = ollama_client.analyze(diff_text, documents)
    except Exception as exc:  # the client reports Ollama/model problems here
        print(f"Error: the documentation check could not run: {exc}", file=sys.stderr)
        print(
            "Make sure Ollama is running locally and the model is installed:\n"
            "  ollama pull qwen3.5:4b",
            file=sys.stderr,
        )
        return 1

    print(report.format_findings(findings))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "check":
        return _run_check(args.base)
    if args.command == "serve":
        from docdrift import web  # imported here so `check` works without Flask

        return web.run(args.host, args.port)
    return 2  # unreachable: argparse requires a valid subcommand
