## docdrift: documentation drift detection

`docdrift` checks whether a code change made your Markdown documentation outdated.
It reads the Git diff and your Markdown files, asks a **local** model
(`qwen3.5:4b` through [Ollama](https://ollama.com)) to compare them, and prints
the sentences that may now be wrong together with the code evidence.
Nothing leaves your computer: no cloud AI APIs and no API keys.

### Setup

1. Install Python 3.10 or newer and Git.
2. Install Ollama from https://ollama.com and start it.
3. Download the model once:

   ```bash
   ollama pull qwen3.5:4b
   ```

4. Clone this repository and `cd` into it. If the repository lists
   dependencies in `requirements.txt` or `pyproject.toml`, install them
   (for example `pip install -r requirements.txt`).

### Run

From inside the Git repository you want to check:

```bash
python -m docdrift check --base origin/main
```

`--base` is the branch or commit to compare with (default: `origin/main`).
Run `git fetch` first if `origin/main` is out of date. If your base branch has
another name, pass it, e.g. `--base main`.

The tool compares your current working tree (committed, staged and unstaged
changes to tracked files) with the point where your branch left the base.
New files that are not yet tracked by Git are not included. Markdown files are
the documentation that gets checked; they are not part of the code diff.

### Example

If a change renames `--timeout` to `--deadline` in the code but the README
still says `--timeout`, docdrift reports the README sentence as possible drift
and shows the changed code line it is based on.

Findings are labelled `possible_drift` or `uncertain`. If nothing is found,
the output says that no likely drift was found in the scanned files. That does
not prove the rest of the project is up to date.

### Troubleshooting

- **Could not find the base ref**: run `git fetch`, or use `--base main`.
- **Could not connect to Ollama / model not found**: start Ollama and run
  `ollama pull qwen3.5:4b`.
- **No code changes found**: there is no difference from the base, so nothing
  is sent to the model.

### Tests

```bash
python -m pip install pytest
python -m pytest
```

The tests mock the Ollama client, so they do not need Ollama or the model.
GitHub Actions runs them on every pull request.
