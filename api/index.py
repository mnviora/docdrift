"""Vercel serverless entrypoint. All routes are rewritten here by vercel.json."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docdrift.web import create_app  # noqa: E402

app = create_app()
