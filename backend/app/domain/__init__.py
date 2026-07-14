"""Product 1 domain layer.

This package groups domain modules owned by individual agents:
``learning`` (P1-07) and ``safety`` (P1-08).  Submodules are imported
lazily by their owners; this top-level package intentionally does not
import them to avoid cross-agent coupling at import time.
"""
