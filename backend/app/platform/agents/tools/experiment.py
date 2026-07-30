"""Compatibility shim: experiment port now lives in providers/experiment/experiment."""

from __future__ import annotations

from ..providers.experiment.experiment import (
    make_session_scoped_experiment_port,
)
