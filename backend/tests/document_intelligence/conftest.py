"""Local conftest: ensure ``app`` and ``fakes`` are importable from the
document_intelligence test subdirectory.

This is needed because pytest's ``--rootdir`` is the repo root, and
``backend/`` and ``backend/tests/`` are not on sys.path by default.
"""

import sys
from pathlib import Path


_THIS_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _THIS_DIR.parent.parent  # backend/
_TESTS_DIR = _BACKEND_DIR / "tests"      # backend/tests/

for p in (_BACKEND_DIR, _TESTS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
