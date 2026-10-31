"""The built-in example: an option renamed from --timeout to --deadline.

The README still says --timeout, so this is the case DocDrift should flag.
"""

from __future__ import annotations

SAMPLE_DIFF = """\
diff --git a/jobrunner/cli.py b/jobrunner/cli.py
index 3f2a1c7..9b8d4e2 100644
--- a/jobrunner/cli.py
+++ b/jobrunner/cli.py
@@ -10,7 +10,7 @@ def build_parser():
     parser = argparse.ArgumentParser(prog="jobrunner")
     parser.add_argument("script", help="script to run")
-    parser.add_argument("--timeout", type=int, default=30, help="seconds before a job is stopped")
+    parser.add_argument("--deadline", type=int, default=30, help="seconds before a job is stopped")
     return parser
"""

SAMPLE_README = """\
# jobrunner

Run scripts from the command line.

## Usage

    jobrunner backup.py

Use --timeout to stop slow jobs.

## Installing

Install with `pip install jobrunner`.
"""

SAMPLE_DOCUMENTS = [{"name": "README.md", "text": SAMPLE_README}]
