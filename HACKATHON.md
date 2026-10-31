# Hackathon Submission

## Problem Statement
Problem 5: Automated Documentation Drift Detection

## Project Name
DocDrift

## Proposed Solution
DocDrift is an AI-assisted tool that detects outdated
documentation caused by changes in source code.

It analyses Git changes, extracts modified Python
functions, parameters and default values, scans Markdown
documentation, and identifies possible inconsistencies.

It combines deterministic Python analysis with a
locally running open-weight AI model for semantic
matching and explanations.

## Models and Why
Model: qwen3.5:4b, run locally through Ollama

Why:
Our tool will use Qwen to compare changed code with related documentation, identify sentences that may now be outdated, and explain its findings using evidence from the code and documentation. We chose it because it is an open-weight model that can run locally.

Python AST and Git diff will provide verifiable evidence.

## Team
Team Name: Baddies

Members:
1. Manvi Chaudhary
2. Anubhuti Jain
3. Henal Katyal