"""Allows `python -m docdrift check --base origin/main`."""

import sys

from docdrift.cli import main

if __name__ == "__main__":
    sys.exit(main())
