"""RAHBAR indexer pipeline package.

Stages (assignment sec. 3.1): extract -> clean -> chunk -> embed -> store.
Entry point: ``python -m pipeline`` (see ``__main__.py``).
"""

from . import chunk, clean, embed, extract, store

__all__ = ["chunk", "clean", "embed", "extract", "store"]
