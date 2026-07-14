"""
Local conftest for safety tests.

Adds backend/ and backend/tests/ to sys.path so imports work
from the shared venv without needing a local .venv.
"""
import sys
from pathlib import Path

# conftest is at backend/tests/safety/conftest.py
# backend/ is at the repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_BACKEND = _REPO_ROOT / "backend"
_BACKEND_TESTS = _REPO_ROOT / "backend" / "tests"

for p in (_BACKEND, _BACKEND_TESTS):
    if p.exists() and str(p) not in sys.path:
        sys.path.insert(0, str(p))
