"""Thin entrypoint alias: ``python indexer/main.py`` == ``python -m pipeline``.

The Docker ENTRYPOINT uses ``python -m pipeline``; this file exists
so the Job can also be run as ``python indexer/main.py`` from the
repo root during local development.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if __name__ == "__main__":
    from pipeline.__main__ import main

    sys.exit(main())
