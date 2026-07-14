"""
P1-06 Student memory test configuration.

Adds backend/ and backend/tests/ to sys.path so that imports work
when running pytest from the worktree root.
"""

import sys
from pathlib import Path

# Ensure backend/ and backend/tests/ are on sys.path
_backend_dir = Path(__file__).resolve().parent.parent.parent / "app"
_tests_dir = Path(__file__).resolve().parent.parent

if str(_backend_dir.parent) not in sys.path:
    sys.path.insert(0, str(_backend_dir.parent))

if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))
