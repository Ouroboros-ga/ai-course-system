"""Pytest fixtures for education_graph tests.

IMPORTANT: Run with PYTHONPATH set to backend/ (NOT backend/app/).
Adding backend/app to sys.path or PYTHONPATH shadows the stdlib 'platform'
module (because backend/app/platform/ exists), which breaks faker and
other dependencies that do 'import platform'.
"""
import pytest


@pytest.fixture
def store():
    """Provide a fresh InMemoryGraphStore for each test."""
    from app.platform.graph.fakes import InMemoryGraphStore
    return InMemoryGraphStore()
