"""
Product 1 test configuration.

Re-exports shared fixtures from the parent conftest and adds P1-specific
fixtures as needed.
"""

from __future__ import annotations

import pytest

# Re-export shared fixtures so product1/ tests can use them.
# These fixtures are defined in backend/tests/conftest.py.
pytest_plugins = [
    "backend.tests.conftest",
]
