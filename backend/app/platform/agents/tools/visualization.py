"""Compatibility shim: visualization port now lives in providers/experiment/visualization."""

from __future__ import annotations

from ..providers.experiment.visualization import (
    make_session_scoped_visualization_port,
)
