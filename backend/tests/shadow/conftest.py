"""Local conftest for shadow tests (P1-09 G3B owned)."""
import sys
from pathlib import Path

_BACKEND = str(Path(__file__).resolve().parents[2])
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
