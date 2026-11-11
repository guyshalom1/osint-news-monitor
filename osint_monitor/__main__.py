"""Run the command-line interface with `python -m osint_monitor`."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
