# DocDrift

### AI-Assisted Documentation Drift Detection

DocDrift is an open-source tool designed to identify potentially outdated documentation when source code changes.

Documentation often becomes inaccurate when developers modify functions, parameters, command-line options, or default values without updating the README or other documentation files.

DocDrift aims to identify these inconsistencies using Python-based code analysis and a locally running open-weight AI model.

## Problem Statement

**Problem 5: Automated Documentation Drift Detection**

Keeping technical documentation synchronised with continuously changing source code is a common software development challenge.

DocDrift aims to reduce this problem by detecting possible differences between source-code changes and existing documentation.

## Our Example

Consider this situation:

**Old command-line option:**
`--timeout`

**Updated command-line option:**
`--deadline`

However, the README still refers to `--timeout`.

DocDrift identifies this potential mismatch and presents the relevant code and documentation evidence.

## Proposed Solution

The planned workflow consists of:

1. Detecting source-code changes using Git.
2. Extracting relevant Python code information.
3. Scanning Markdown documentation.
4. Identifying potentially inconsistent references.
5. Using a local AI model to assist with semantic matching and explanations.
6. Generating a report containing file names, line numbers, and supporting evidence.

## Technology Stack

- Python
- Git
- Python AST
- Ollama
- Qwen (planned local model integration)
- Markdown
- Pytest
- GitHub Actions

The exact Qwen model variant will be documented after verifying the installed model.

## Project Structure

```text
docdrift/
├── HACKATHON.md
├── LICENSE
├── README.md
├── analyzer/
├── tests/
├── examples/
└── .github/
    ├── pull_request_template.md
    └── workflows/
```

## Project Status

Currently under development as part of Hacktoberfest HackDay Sonipat 2026.

## Team

- Manvi — Project and GitHub Lead
- Anubhuti — AI and Qwen Integration
- Henal — Testing, Examples and Demo

## Licence

This project is licensed under the MIT Licence. See the LICENSE file for details.