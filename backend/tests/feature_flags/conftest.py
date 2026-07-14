"""Local conftest for feature_flags tests (P1-09 G3A owned).

Ensures backend/ is on sys.path so `app.core.*` imports resolve when
running from the worktree root. Does NOT import the shared
backend/tests/conftest.py or fakes.py (P1-10 owned).
"""
import sys
from pathlib import Path

_BACKEND = str(Path(__file__).resolve().parents[2])
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
