from __future__ import annotations

import asyncio
import sqlite3

from sqlalchemy.exc import OperationalError

from app.models.database import _build_connect_args
from app.platform.agents.providers.persistence.agent_run import (
    SqlAgentLLMDiagnosticStore,
)


class _Session:
    def __init__(self, *, failures: list[BaseException]) -> None:
        self._failures = failures
        self.added = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def add(self, value):
        self.added.append(value)

    def commit(self):
        if self._failures:
            raise self._failures.pop(0)


def _locked_error() -> OperationalError:
    return OperationalError(
        "INSERT diagnostic",
        {},
        sqlite3.OperationalError("database is locked"),
    )


def test_sqlite_connect_args_use_bounded_wait():
    args = _build_connect_args("sqlite:///tmp/test.db")
    assert args["check_same_thread"] is False
    assert args["timeout"] == 30.0
    assert _build_connect_args("postgresql://localhost/test") == {}


def test_diagnostic_sink_retries_transient_sqlite_lock():
    failures = [_locked_error()]
    sessions = []

    def factory():
        session = _Session(failures=failures)
        sessions.append(session)
        return session

    asyncio.run(SqlAgentLLMDiagnosticStore(factory).record(
        run_id="run_test",
        trace_id="trace_test",
        agent_type="prep",
        purpose="test",
    ))

    assert len(sessions) == 2
    assert len(sessions[-1].added) == 1


def test_diagnostic_sink_is_best_effort_after_retries_exhausted():
    failures = [_locked_error(), _locked_error(), _locked_error(), _locked_error()]

    def factory():
        return _Session(failures=failures)

    # A diagnostic failure must not escape into the mapping/prep workflow.
    asyncio.run(SqlAgentLLMDiagnosticStore(factory).record(
        run_id="run_test",
        trace_id="trace_test",
        agent_type="prep",
    ))
    assert failures == []
