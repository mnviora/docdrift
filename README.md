# DocDrift

### AI-Assisted Documentation Drift Detection

DocDrift is an open-source tool designed to identify potentially outdated documentation when source code changes.

Documentation often becomes inaccurate when developers modify functions, parameters, command-line options, or default values without updating the README or other documentation files.

DocDrift compares a code diff with your Markdown documentation using a **locally running open-weight AI model** (`qwen3.5:4b` through Ollama) and shows the sentences that may now be wrong, together with the changed code that supports each warning.

Nothing leaves your computer: no cloud AI APIs and no API keys.

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

However, the README still says "Use `--timeout` to stop slow jobs."

DocDrift flags that sentence and shows the changed code that supports the warning. You can try exactly this case with the **Try sample** button on the website.

## Setup

You need Python 3.10 or newer, Git, and Ollama.

1. Install **Ollama** from https://ollama.com and start it (open the app, or run `ollama serve`).
2. Download the model once (it is a large download):

   ```bash
   ollama pull qwen3.5:4b
   ```

3. Clone this repository, `cd` into it, and install the one dependency (Flask, used only for the website):

   ```bash
   python -m pip install -r requirements.txt
   ```

DocDrift only works with a local Ollama that has `qwen3.5:4b` installed. It never calls another model or a cloud service.

## Use the website

Start it:

```bash
python -m docdrift serve
```

Then open **http://localhost:8000** in your browser. (Use `--port 8001` if port 8000 is busy.) The server listens only on your own computer unless you pass `--host`.

1. The chip at the top shows whether Ollama is reachable and `qwen3.5:4b` is installed. If not, the page tells you what to run.
2. Click **Try sample**. It fills in a diff that renames `--timeout` to `--deadline` and a README that still says `--timeout`.
3. Click **Check documentation**. A small local model can take a minute or two, especially on the first run.
4. Read the results. Each finding is labelled **Possible documentation drift** or **Uncertain** and shows the file and line, the exact documentation sentence, the changed code, and a short explanation. If nothing is found, the page says **No likely drift found in the supplied files**. That only covers the files you supplied; it does not prove the rest of your documentation is up to date.
5. Use **Download Markdown** or **Download JSON** to keep the report.

To check your own change, paste the output of `git diff` (or upload a `.diff` / `.patch` file) and paste or upload one or more `.md` files.

The model does not report a confidence score, so none is shown.

### Privacy and limits

- Your text is only read as text. Nothing you submit is executed, saved to disk, or sent anywhere except the local Ollama service.
- The page loads no external fonts, scripts or images.
- Limits: 100,000 characters for the diff, 100,000 per document, up to 10 documents, about 1 MB in total. The model itself reads roughly the first 20,000 characters of the diff and of the documentation; the page warns you when something was cut off.
- One check runs at a time.

## Use the command line

From inside the Git repository you want to check:

```bash
python -m docdrift check --base origin/main
```

`--base` is the branch or commit to compare with (default: `origin/main`). Run `git fetch` first if `origin/main` is out of date, or pass another branch, e.g. `--base main`.

The tool compares your current working tree (committed, staged and unstaged changes to tracked files) with the point where your branch left the base. New files not yet tracked by Git are not included. Markdown files are the documentation that gets checked; they are not part of the code diff.

Findings are labelled `possible_drift` or `uncertain`. If nothing is found, the output says that no likely drift was found in the scanned files.

## Troubleshooting

- **Ollama not reachable / "Ollama is not running"**: install and start Ollama (https://ollama.com), then run `ollama pull qwen3.5:4b`.
- **Model not installed**: run `ollama pull qwen3.5:4b`, then click **Check again** on the page.
- **The check times out**: the first request loads the model into memory and can be slow. Wait and try again, or raise `DOCDRIFT_OLLAMA_TIMEOUT` (seconds, default 300).
- **Ollama on another address**: set the `OLLAMA_HOST` environment variable (for example `127.0.0.1:11434`).
- **"Could not find the base ref"** (command line): run `git fetch`, or use `--base main`.
- **Port already in use**: `python -m docdrift serve --port 8001`.

## Tests

```bash
python -m pip install -r requirements.txt pytest
python -m pytest
```

The tests mock the model, so they need neither Ollama nor the downloaded model. GitHub Actions runs them on every pull request.

### Manually checking the real Qwen flow

The automated tests cannot prove that the real model behaves well, so check it by hand on a computer that has Ollama and `qwen3.5:4b`:

1. Run `ollama list` and confirm `qwen3.5:4b` is listed.
2. Run `python -m docdrift serve` and open http://localhost:8000. The top chip should say Ollama is running and the model is installed.
3. Click **Try sample**, then **Check documentation**.
4. Expect a finding for `README.md`, line 9, quoting "Use --timeout to stop slow jobs.", with the `--timeout` / `--deadline` lines from the diff as evidence.
5. Stop Ollama and run the check again. You should see "Ollama is not running" with instructions.

A 4B model is not deterministic or perfect. If the sample comes back as **Uncertain** or empty, run it again and note it.

## Project Structure

```text
docdrift/
├── HACKATHON.md
├── LICENSE
├── README.md
├── requirements.txt
├── docdrift/
│   ├── cli.py            command line (check, serve)
│   ├── git_input.py      reads the Git diff and Markdown files
│   ├── ollama_client.py  talks to local Ollama / qwen3.5:4b
│   ├── prompts.py        prompt and output schema for the model
│   ├── report.py         terminal and Markdown formatting
│   ├── web.py            the website's Flask app
│   ├── sample.py         the --timeout / --deadline example
│   └── static/           the website's HTML, CSS and JavaScript
├── tests/
├── examples/
└── .github/
    ├── pull_request_template.md
    └── workflows/
```

## Current Limitations

- Evidence comes from the text of the Git diff and your Markdown files, and is checked against them. The Python AST analysis mentioned in `HACKATHON.md` is **not implemented yet**.
- The model can miss real drift or flag sentences that are fine. Treat findings as prompts to review, not verdicts.
- The website does not read your repository; you paste or upload the diff and the documents.

## Technology Stack

- Python and Flask
- Git
- Ollama with the open-weight `qwen3.5:4b` model, run locally
- Markdown
- Pytest
- GitHub Actions

## Project Status

Developed as part of Hacktoberfest HackDay Sonipat 2026.

## Team

- Manvi: Project and GitHub Lead
- Anubhuti: AI and Qwen Integration
- Henal: Testing, Examples and Demo

## Licence

This project is licensed under the MIT Licence. See the LICENSE file for details.
